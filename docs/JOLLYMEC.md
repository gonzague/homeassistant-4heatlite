# Jolly Mec profile

Select **Jolly Mec (whole-degree temperatures)** in the device setup or integration
options. Existing entries default to the Lasian profile; changing a profile does
not send any commands. Save and reopen options after changing profiles.

For account-free setup, choose **Direct local connection (no cloud account)**,
select the discovered module or enter its IP address, and choose the Jolly Mec
profile. The device ID is optional for manual setup. No cloud login or device
key is requested; this entry stays in Direct mode. This does not change the
module's own cloud connection or the mobile app.

This profile implements the differences reported in [issue #2](https://github.com/pafernanr/homeassistant-4heatlite/issues/2)
and reproduced on a second Jolly Mec installation with a 4HEAT Lite module.
The exact model reference of the second installation is still unverified; do not
infer compatibility with every stove sold under the Synthesis name.

## Readings

| Reading | Register | Jolly Mec interpretation |
|---|---|---|
| State / error / on-off | `0310` | Bytes 5 / 1 / 2; state 7 is final cleaning |
| Room temperature | `0310` bytes 10–11 or `12fff7` | Whole degrees, not tenths |
| Exhaust temperature | `12ffff` bytes 3–4 | Whole degrees; do not use byte 4 of `0310` |
| Target temperature | `12005a` bytes 3–4 | Whole degrees, range 10–40 |
| Combustion power | `0e016c` bytes 3–4 | Raw 1 = Silent; raw 2–6 = levels 1–5 |
| Ducted fan 1 | `0e0266` bytes 3–4 | Same level as the controller; zero means off |

Alarm values in `0310` are kept raw: they are not assumed to be the alarm
numbers in the remote-control manual. Raw `32` (`0x20`) was observed with state
9 (Block) while the physical remote displayed **ManqueDépr Blocage**. The Jolly
Mec error sensor labels that value **Lack of depression**, exposes
`error_code_raw`, and leaves other unverified nonzero values unknown instead of
reusing Lasian alarm descriptions. This observation is not a general decoding
rule. The [manufacturer's SM208 manual, page 22](https://jm-poeles.com/Allegati/RadioCommande/2_sm208_fr.pdf)
describes the lack-of-depression alarm as a safety-pressure-switch trip.

After the user acknowledged that alarm on the remote, the remote displayed OFF
and three consecutive network samples reported state 0, while the raw alarm byte
remained 32 and the legacy `on_off` byte remained 1. These bytes must not be used
alone to infer current heating or an active alarm. The climate entity uses the
operating state for its OFF status. The error sensor reports the received value;
it does not claim to distinguish an active alarm from a retained one.

The combustion raw value is also kept as `power_raw` in coordinator data. Raw 7
has no verified user-facing meaning, so it is not offered as a preset. Negative
or high-bit room-temperature words are not published as unsigned temperatures:
`fff6`, observed at startup, is reported as unavailable. Its precise meaning is
not established.

The handheld remote's own temperature is a separate measurement; this profile
does not claim that the room-temperature register is the remote's decimal reading.

Direct mode polls the exhaust and ducted-fan registers in addition to the main
block. Matching is by register prefix across the entire response, since a single
read can return a cache of several registers. An omitted register retains its
last valid sample; this does not imply that the retained sample is fresh. An
explicit invalid temperature clears the value. TCP replies may span multiple
packets and more than one receive buffer.

## Controls

- ON/OFF uses the existing commands. One ON command was tested on the second
  installation: the module transitioned OFF → Check Up → Ignition, and the
  physical remote confirmed ignition. One OFF command was subsequently
  acknowledged and state 7 (final cleaning) was observed. During cooldown the
  stove entered state 9 with raw error 32, confirmed on the remote as lack of
  depression. After the user acknowledged the alarm on the physical remote,
  OFF was confirmed on the remote and by three consecutive state-0 reads. An
  uninterrupted automatic shutdown without that alarm has not been validated.
- Target temperatures use a step of 1 °C and the whole-degree wire format from
  issue #2. Values outside 10–40 or with fractional degrees are rejected.
- Presets are Silent and Power 1–5. They use the offset wire value from issue #2.
- Temperature and power write payloads are tested against the examples reported
  in issue #2; they were **not sent** to the second installation during validation.
- Ducted-fan control is not added; its level is exposed as a sensor.

## CCG schedules

`4heatlite.get_schedule` returns the observed CCG format as seven named day groups,
each with three start/end/flag slots. It includes `format: CCG`, `read_only: true`,
`mode_raw`, and per-slot `flag_raw`. These codes are deliberately not interpreted
as enable flags until verified.

The CCG format is different from H24 temperature-band schedules. The schedule
editor is hidden for this profile, and H24 writes are rejected by the service,
TCP client and proxy queue. Read support does not enable schedule editing.

## Validation

Offline tests use captured protocol payloads without module IDs, MACs, IPs or
account data. Schedule times in the fixture are synthetic. Test sockets cannot
connect to a real device. Legacy behavior is covered separately.

```sh
python -m pip install -r requirements-test.txt
python -m pytest -q
```

Python 3.14 is required by the pinned Home Assistant test runtime. These tests
exercise the real Home Assistant classes but do not replace an installed-instance
test of discovery, setup, proxy routing or the dashboard.
