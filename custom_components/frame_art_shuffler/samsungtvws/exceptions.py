"""
SamsungTVWS - Samsung Smart TV WS API wrapper

Copyright (C) 2019 DSR! <xchwarze@gmail.com>

SPDX-License-Identifier: LGPL-3.0
"""

import re

# frame-art-shuffler patch (docs/VENDORING.md): the TV's pairing token rides in its handshake messages
# (data.token in ms.channel.connect, attributes.token in another client's ms.channel.clientConnect) and
# in the connection URL; text built from them goes through redact_tokens before a log or an error.
_TOKEN_VALUE = re.compile(r"""(?P<key>["']token["']\s*:\s*)(?P<value>"[^"]*"|'[^']*'|\d+)|(?P<param>token=)[^&\s"']*""")


def redact_tokens(text: str) -> str:
    """The text with every token value replaced by <redacted>."""

    def _redacted(match: "re.Match[str]") -> str:
        if match.group("param"):
            return f"{match.group('param')}<redacted>"
        quote = match.group("value")[0] if match.group("value")[0] in "\"'" else ""
        return f"{match.group('key')}{quote}<redacted>{quote}"

    return _TOKEN_VALUE.sub(_redacted, text)


class ConnectionFailure(Exception):
    """Error during connection. Raised with the TV's reply, which callers keep; its text hides the token."""

    def __str__(self) -> str:
        return redact_tokens(super().__str__())


class UnauthorizedError(ConnectionFailure):
    """Error from ms.channel.unauthorized event."""

    pass


class ResponseError(Exception):
    """Error in response."""

    pass


class HttpApiError(Exception):
    """Error using HTTP API."""

    pass


class MessageError(Exception):
    """Error from ms.error event."""

    pass
    
class TimeoutError(Exception):
    """Websocket time out."""

    pass
