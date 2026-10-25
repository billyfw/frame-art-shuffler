"""Samsung IP Control: a real panel power-off and power-on (docs/POWER_CONTROL.md).

JSON-RPC 2.0 over HTTPS on port 1516, a channel separate from the 8001/8002 WebSockets, on Samsung TVs from
2020 on. The TV turns it on with IP Remote (Settings > All Settings > Connections > Network > Expert
Settings; it needs Power On with Mobile on as well) and presents a self-signed certificate. One pairing
(``createAccessToken``) shows a prompt on the TV and blocks until someone accepts it; every later request
carries the token it returns.

Used where the remote's power key cannot switch the panel off: 2024-and-later Frames treat the power-key
hold as an Art Mode / TV mode toggle. The protocol was worked out by TheFab21/ha-samsungtv-smart
(IP_Control_Protocol_Reference.md) and confirmed on a 2026 Frame Pro and a 2026 Frame (the doc has the
bench results).

Synchronous on purpose, like the rest of the TV code: callers run it in Home Assistant's executor. The
token is a credential: it is never logged and never part of an exception or a repr.
"""

from __future__ import annotations

import http.client
import json
import logging
import ssl
import threading
from typing import Any, Optional

_LOGGER = logging.getLogger(__name__)

PORT = 1516
PAIR_TIMEOUT = 120.0  # someone has to walk to the TV and accept the prompt
COMMAND_TIMEOUT = 6.0
MAX_RESPONSE_BYTES = 64 * 1024

POWER_ON = "powerOn"
POWER_OFF = "powerOff"

# JSON-RPC error codes as Samsung firmware uses them (observed, not published for consumer TVs).
ERROR_PARSE = -32700  # also this firmware's answer to a missing or stale AccessToken
ERROR_METHOD_NOT_FOUND = -32601  # also "not available in the TV's current state"
ERROR_UNAVAILABLE = -32002  # command refused in the current state
ERROR_UNAUTHORIZED = -32010  # token rejected

# Observed TVs reset overlapping connections to port 1516: one request at a time per TV.
_HOST_LOCKS: dict[str, threading.Lock] = {}
_HOST_LOCKS_GUARD = threading.Lock()


class IPControlError(Exception):
    """An IP Control request failed."""


class IPControlAuthError(IPControlError):
    """No token, or the TV rejected it: pair again."""


class IPControlUnavailableError(IPControlError):
    """The TV refused the method in its current state (or does not have it)."""


class IPControlTransportError(IPControlError):
    """The TV did not answer: off the network, IP Remote off, a timeout, or a TLS failure."""


class IPControlProtocolError(IPControlError):
    """The TV answered with something that is not the expected JSON-RPC reply."""


def _host_lock(host: str) -> threading.Lock:
    with _HOST_LOCKS_GUARD:
        return _HOST_LOCKS.setdefault(host, threading.Lock())


class IPControlClient:
    """One TV's IP Control channel. Short-lived HTTPS connections, one per request."""

    def __init__(
        self,
        host: str,
        token: Optional[str] = None,
        *,
        port: int = PORT,
        timeout: float = COMMAND_TIMEOUT,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._token = token

    def __repr__(self) -> str:
        return f"IPControlClient(host={self.host!r}, port={self.port}, paired={bool(self._token)})"

    def pair(self, timeout: float = PAIR_TIMEOUT) -> str:
        """Ask the TV for an access token; blocks until someone accepts the prompt on screen.

        The TV has to be out of Art Mode for the prompt to appear (reported on 2024 to 2026 Frames). A
        timeout means nobody accepted in time; the TV answered nothing.
        """
        result = self._request("createAccessToken", with_token=False, timeout=timeout)
        token = result.get("AccessToken")
        if not isinstance(token, str) or not token:
            raise IPControlProtocolError("IP Control pairing returned no access token")
        self._token = token
        return token

    def power_state(self) -> str:
        """``powerOn`` or ``powerOff``, as the TV reports it (a read: ``powerControl`` with no ``power``)."""
        result = self._request("powerControl")
        state = result.get("power")
        if state not in (POWER_ON, POWER_OFF):
            raise IPControlProtocolError(f"IP Control reported an unknown power state {state!r}")
        return state

    def power_on(self) -> None:
        self._request("powerControl", {"power": POWER_ON})

    def power_off(self) -> None:
        self._request("powerControl", {"power": POWER_OFF})

    def _request(
        self,
        method: str,
        params: Optional[dict[str, Any]] = None,
        *,
        with_token: bool = True,
        timeout: Optional[float] = None,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
        if with_token:
            if not self._token:
                raise IPControlAuthError("IP Control is not paired")
            request["params"] = {"AccessToken": self._token, **(params or {})}
        elif params:
            request["params"] = params

        body = json.dumps(request, separators=(",", ":")).encode("utf-8")
        with _host_lock(self.host):
            raw = self._post(body, self.timeout if timeout is None else timeout)

        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            raise IPControlProtocolError(f"IP Control {method}: the reply is not JSON") from err
        if not isinstance(decoded, dict):
            raise IPControlProtocolError(f"IP Control {method}: the reply is not a JSON object")

        error = decoded.get("error")
        if error is None and "code" in decoded and "result" not in decoded:
            # Flat envelope, seen on 2026 firmware: {"code": -32700, "message": "Parse error"}
            error = {"code": decoded.get("code"), "message": decoded.get("message")}
        if error is not None:
            code = error.get("code") if isinstance(error, dict) else None
            if code == ERROR_UNAUTHORIZED or (code == ERROR_PARSE and with_token):
                raise IPControlAuthError(f"IP Control {method}: the TV rejected the access token (code {code})")
            if code in (ERROR_METHOD_NOT_FOUND, ERROR_UNAVAILABLE):
                raise IPControlUnavailableError(f"IP Control {method}: not available on the TV now (code {code})")
            raise IPControlProtocolError(f"IP Control {method}: the TV answered error code {code!r}")

        result = decoded.get("result")
        if not isinstance(result, dict):
            raise IPControlProtocolError(f"IP Control {method}: the reply has no result")
        return result

    def _post(self, body: bytes, timeout: float) -> bytes:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE  # the TV's certificate is self-signed: trusted LAN only
        connection: Optional[http.client.HTTPSConnection] = None
        try:
            connection = http.client.HTTPSConnection(self.host, self.port, timeout=timeout, context=context)
            connection.request(
                "POST",
                "/",
                body=body,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
            response = connection.getresponse()
            if not 200 <= response.status < 300:
                raise IPControlProtocolError(f"IP Control answered HTTP {response.status}")
            data = response.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                raise IPControlProtocolError("IP Control reply is larger than expected")
            return data
        except IPControlError:
            raise
        except (OSError, http.client.HTTPException) as err:  # timeouts, refusals and TLS errors are OSErrors
            raise IPControlTransportError(
                f"IP Control on {self.host}:{self.port} did not answer ({type(err).__name__})"
            ) from err
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:  # pragma: no cover - best effort
                    pass
