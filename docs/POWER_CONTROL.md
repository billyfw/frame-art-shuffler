# Power control: how the shuffler switches a TV's screen off and on (0.5.0)

## Operative summary

- **An explicit per-TV setting**, `power_control` in the TV's config (`entry.data["tvs"][tv_id]`), chosen in the
  integration's Configure > Add a new TV / Edit a TV or tablet > Power control. It is never inferred from the
  model or from a token on disk; a TV without the key uses `remote_keys` (`targets.power_control`). Wall tablets
  have none: they are never contacted.
- **`remote_keys`** (the default, and every TV set up before 0.5.0): off holds `KEY_POWER` for 3 s over the
  WebSocket, which older Frames treat as an Art Mode screen sleep; on sends two Wake-on-LAN packets 12 s apart
  (`docs/POWER_COMMANDS.md`), then `set_art_mode`. Unchanged by 0.5.0.
- **`ip_control`**: Samsung IP Control, JSON-RPC 2.0 over HTTPS on port 1516 (`ip_control.py`): off is
  `powerControl` `powerOff`, a real standby from Art Mode or TV mode; on is `powerOn`, then `set_art_mode` (the
  TV comes back in the mode it was switched off in).
- **Which to choose**: Frames from 2024 on ignore the power-key hold and flip between Art Mode and TV mode
  instead (reports below, and a 2026 Frame on the bench). A quick test: switch the TV off from Home Assistant on
  `remote_keys`; if the Samsung home screen appears instead of a dark panel, the TV needs `ip_control`.
- Every caller reads the TV's method when it acts: the Power switch, the On+Art Mode button, the motion-off
  button, the `turn_on_tv` and `turn_off_tv` services, and auto motion (off timer and wake). Changing the setting
  needs no reload (`power_control` is not structural config).

## Setting a TV to IP Control

At the TV, once:

1. Settings > All Settings > Connections > Network > Expert Settings: **Power On with Mobile** on (IP Remote needs
   it) and **IP Remote** on (Samsung's 2026 e-Manual, page 13).
2. Settings > All Settings > Connections > Device Connection Manager > **Access Notification**: Off (verified) or
   First Time Only (untested). On Always On, after every real off and on the TV asked again to allow the
   shuffler's WebSocket the first time it connected, and held the connection until someone answered (e-Manual
   page 193 has the setting; the behavior is the bench's). Nobody is at the TV for a morning power-on.
3. For a new pairing, take the TV out of Art Mode (a tap on the remote's power button) and stay at it to accept
   the prompt.

In Home Assistant: Configure > Edit a TV or tablet > the TV > Power control: Samsung IP Control > Submit.

- A key already stored for the TV's address is verified with a power read; if the TV accepts it, the setting is
  saved at once, with no prompt.
- Otherwise the `ip_control` step shows what to set at the TV; submitting it starts `ip_control_pair`, a progress
  step: `createAccessToken` shows a prompt on the TV and waits up to 120 s for someone to accept it. Then
  `ip_control_done` saves the setting. Nothing is saved until a pairing (or a stored key) works.
- Form errors: `ip_control_unreachable` (no answer: IP Remote off, or the TV off the network),
  `ip_control_timeout` (the prompt was not accepted, or not shown because the TV was in Art Mode),
  `ip_control_refused` (the TV refused to pair in its current state), `ip_control_failed` (an unexpected reply).
- The step runs again when the TV's address changes, when Re-pair is ticked, or when no key is stored; an edit of
  anything else on an IP Control TV saves without it.
- Adding a TV with IP Control runs the same step before the TV is added.

The key lives beside the WebSocket token: `tokens/<address with _>.ipcontrol.token` next to `<address>.token`,
mode 600, written atomically, deleted with the TV. It is a credential: never logged, never in an exception.

Over Home Assistant's REST API (a script driving the options flow):
`POST /api/config/config_entries/options/flow` with `{"handler": "<entry_id>"}`, then POST to
`/api/config/config_entries/options/flow/<flow_id>` in turn `{"action": "edit_tv"}`, `{"tv_id": "<tv_id>"}`,
`{"power_control": "ip_control"}` (fields left out keep the TV's values). The answer is `create_entry` when a
stored key is accepted. Otherwise it is the `ip_control` form: POST `{}` starts the pairing (`progress`); after the
prompt is accepted, advance with a GET of the flow (not a POST: a POST to the `ip_control` form after a failed
pairing is a new submit, and a new prompt).

## What the code does (frame_tv.py)

- Off: a TV whose REST power state is already off (or that does not answer) is left alone, as on `remote_keys`.
  Otherwise `powerOff`, then up to 10 s for REST to read standby (a warning if it does not). A failure raises
  `FrameArtConnectionError` saying what to check: not paired, key rejected, or IP Control not answering.
- On: a TV whose REST power state is already on is left alone. Otherwise `powerOn`, retried every 3 s for up to
  90 s while IP Control does not answer (a TV can refuse every port for a while right after a real off), then up
  to 15 s for REST to read on, then up to 20 s for the art channel to answer, so the caller's `set_art_mode` can
  read the mode.
- No Wake-on-LAN fallback: Wake-on-LAN did not wake the 2026 Frame from an IP Control standby.
- One request at a time per TV (observed TVs reset overlapping connections to port 1516).

## What a 2026 Frame did on the bench (2026-10-24 and 2026-10-25)

A 2026 Frame (LS03H, art API 6.0.0.0), watched by eye, its REST `PowerState` logged:

- The power-key hold over the WebSocket, 3 s or tapped, only toggles Art Mode and TV mode; `KEY_POWEROFF` is
  ignored in both (2026-10-24), as the 2026 Frame Pro report below says.
- Pairing with the TV in TV mode: the token came back 3 s after the request, once the prompt was accepted.
- `powerOff` from Art Mode (three times) and from TV mode (once): the panel went dark and REST read standby within
  3 s. `powerOn`: on within 2 s, in the mode it was switched off in (Art Mode back to art, TV mode back to the
  Samsung home screen).
- Port 1516 answered in standby in 3 of 4 cycles. Once, 25 s after the first off, the TV refused every port
  (ping still answered) and answered again within 2 min.
- Wake-on-LAN, the `remote_keys` on (two packets 12 s apart), did not wake it from that standby.
- Access Notification on Always On: after each real off and on, the first WebSocket connection made the TV ask
  to allow the shuffler (twice). With it Off: no prompt, and the art channel connected at once.
- Once, when that prompt appeared while Art Mode was starting after a power-on, the art screen stayed black (the
  TV reported Art Mode on and the picture shown) until Art Mode was switched off and on over the art channel. Not
  seen without the prompt.

## Known gaps

- The vendored art client's `open()` raises when `ms.channel.clientConnect` arrives before `ms.channel.ready`,
  seen only while an allow prompt was pending; `set_art_mode` then refuses to send `KEY_POWER`.
- No lower-security TLS retry for older TVs ("dh key too small"; TheFab21's client has one). Not needed on 2026
  firmware.
- Access Notification on First Time Only is untested.
- A Frame that dropped off the network after a mains loss (cold standby) answers neither IP Control nor
  Wake-on-LAN; only a local power-on helps, as on `remote_keys`.
- The black art screen above has no automatic recovery (an Art Mode toggle would flash the home screen).

## Sources

- 2026 Frame Pro measurements and the protocol summary:
  https://github.com/janstrm/Home-Assistant-Samsung-Frame-Art-Director-Integration/issues/24 and that
  repository's `docs/research/samsung-ip-control.md`
- The protocol, reverse-engineered on 2024 and 2025 Frames: TheFab21/ha-samsungtv-smart,
  `IP_Control_Protocol_Reference.md`
- A 2024 Frame's power command leaving Art Mode instead of powering down: https://github.com/home-assistant/core/issues/156635
- Samsung's 2026 TV e-Manual, pages 13 (Power On with Mobile, IP Remote) and 193 (Device Connection Manager,
  Access Notification)
- Samsung's 2020 IP command list (Power Off, Power On and Reboot exist; a token is required):
  https://image-us.samsung.com/SamsungUS/tv-ci-resources/2020-control-code/2020_IP_command_list.pdf
