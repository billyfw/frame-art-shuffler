# Motion control: a TV's screen from the room's sensors (presence sensors since 0.6.0)

## Operative summary

- **Per TV**: `enable_motion_control`, `motion_sensors` (binary sensors) and `motion_off_delay` (minutes, 1 to
  120) in the TV's config, set in Configure > Edit a TV or tablet; the Auto-Motion Enable switch and the
  Auto-Motion Off Delay number change the toggle and the delay at runtime without a reload. Changing the sensor
  list is structural: the save reloads the entry.
- **Wake**: any listed sensor turning on wakes a dark screen through the TV's power control method
  (`docs/POWER_CONTROL.md`) and starts the off countdown; with the screen already lit it restarts the countdown.
- **Off**: the screen turns off `motion_off_delay` minutes after **every** listed sensor reads clear. While any
  sensor reads on, the countdown never ends in an off: when it comes due it starts over, and a sensor clearing
  (on to off or unavailable) restarts a pending countdown from that moment, once every sensor reads clear.
  While the room is in use, the Auto-Motion Off At sensor shows a time that moves forward each delay. Last
  Motion is the last time a sensor was seen on: a wake, or the clear that started the final countdown.
- **Which sensors**: the forms list binary sensors of device class `motion`, `occupancy` and `presence`. A motion
  sensor (a PIR) reads on for a moment after each movement; an occupancy or presence sensor (an mmWave radar, a
  ceiling occupancy sensor with its own hold time) reads on for as long as someone is in the room, sitting still
  included. All of them read on while the room is in use, which is all motion control reads, so they mix freely
  (OR logic).
- **Unchanged**: TV mode (the Auto-Shuffle switch off to watch TV) cancels the countdown and starts none until it
  ends, while a sensor still wakes a dark screen; an upload in progress delays an off by 30 s at a time (up to 5
  min); a wake nobody answers cancels the countdown (`Wake sent, no answer from TV`).

## Why 0.6.0 changed the off

Until 0.6.0 the countdown started at each sensor's turn to on and nothing else touched it, so the off came
`motion_off_delay` minutes after the last turn to on. That works for a PIR, which turns on again with every
movement and clears within seconds. An occupancy sensor turns on once when someone walks in and stays on while
they sit: the screen went dark one delay after they sat down, and stayed dark while they were there, since their
sensor never turned on again. The forms also listed only `motion` sensors, so an occupancy or presence sensor
could not be chosen at all. For a PIR the off now comes one delay after its clear instead of after its turn to
on, later by its hold time (seconds on most).

## A gap that went with it

Pending countdowns were not cancelled when the entry unloaded, so after a reload (any structural edit, such as
the sensor list) the old setup's countdown still fired once on its old schedule, and could darken a screen the
new setup had just woken or was holding on. Since 0.6.0 unloading cancels them; the new setup starts its own.

## What is not covered

- A sensor stuck on keeps the screen lit until something else turns it off (a house rule, a person, the power
  switch); before 0.6.0 the countdown ended in an off regardless. An mmWave sensor can read a moving fan or
  curtain as presence: set its detection zone and height limits before listing it.
- Presence of a pet counts like a person's. A house that wants no wake at night can switch Auto-Motion Enable off
  for the night from an automation (a runtime change, no reload).

Tests: `tests/test_motion_presence.py` (inside Home Assistant 2026.9, the clock moved with the freezer).
