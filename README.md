# Light Defaults

Per-light default brightness and color temperature for Home Assistant. When a
light turns on from off and the call leaves out brightness or color, the
defaults fill the gap instead of the light coming back at whatever it was last
set to.

## Install

1. In HACS, open the ⋮ menu → **Custom repositories**, add
   `https://github.com/ClayBenson94/ha-light-defaults` with type **Integration**.
2. Download **Light Defaults**.
3. Add your map to `configuration.yaml` (below) and restart Home Assistant.

## Configure

```yaml
light_defaults:
  light.office_lamp:
    brightness: 100    # percent, 1–100
    temperature: 6500  # Kelvin, 1000–10000
  light.living_room_lamp:
    brightness: 80
```

Either key can be left out. After editing the map, run the
`light_defaults.reload` action; no restart needed.

### Keeping the map in its own file

To keep `configuration.yaml` short, point `light_defaults` at a separate file
in the same folder:

```yaml
# configuration.yaml
light_defaults: !include light_defaults.yaml
```

```yaml
# light_defaults.yaml
light.office_lamp:
  brightness: 100
  temperature: 6500
light.living_room_lamp:
  brightness: 80
```

The included file holds just the map: no `light_defaults:` line, and the entity
IDs start at the left margin. `light_defaults.reload` re-reads it, so edits
there don't need a restart either.

## Behavior

- Applies only when a light turns on from off, through `light.turn_on` or
  `light.toggle`, from anything that goes through Home Assistant: dashboards,
  voice, HomeKit/Google, scenes, automations, areas and light groups.
- Anything the call specifies wins, per attribute: `brightness_pct: 100` on its
  own still gets the default temperature, and an explicit color keeps the
  default brightness.
- Lights that are already on, and calls with an effect or flash, are left alone.
- Lights without color temperature support ignore `temperature`.
- Turn-ons that bypass Home Assistant (Zigbee-bound remotes, power at the wall)
  aren't affected.

## How it works

Home Assistant's light integration runs a per-light defaults step on every
turn-on (the step behind `light_profiles.csv`). This integration wraps that
step, so Home Assistant still handles unit conversion and drops anything a
light doesn't support. It's an internal hook: if a future Home Assistant
release changes it, setup fails with a logged error and lights behave as
stock. Errors while it runs are caught, so it can't break `light.turn_on`.

Tested on Home Assistant 2026.10.2.

## Updating

HACS tracks the default branch, so every push to `main` shows up in HACS as an
update. Install it from HACS and restart Home Assistant.

## Development

Tests run against a real Home Assistant core and need Python 3.14+:

```sh
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements_test.txt
.venv/bin/pytest
```

See `CLAUDE.md` for how the integration hooks into Home Assistant.
