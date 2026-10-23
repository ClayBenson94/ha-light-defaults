# Light Defaults

Default brightness and color temperature for Home Assistant lights. When a
light turns on from off and the call leaves out brightness or color, the
defaults fill the gap instead of the light coming back at whatever it was last
set to.

## Install

1. In HACS, open the ⋮ menu → **Custom repositories**, add
   `https://github.com/ClayBenson94/ha-light-defaults` with type **Integration**.
2. Download **Light Defaults**.
3. Restart Home Assistant, then set up your lights in the UI or in YAML
   (below).

## Configure

There are three kinds of settings:

- **Defaults for all lights**: a brightness, a color temperature or both, for
  every light.
- **Defaults for some lights**: values for one or more lights or light groups.
  A value they leave out comes from a group they're in, or from the defaults
  for all lights. Setting it to `none` gives them no default for it instead.
- **Excluded lights**: lights that never get defaults.

Set them up in the UI, in YAML, or both.

### In the UI

Go to **Settings → Devices & services → Add integration**, choose **Light
Defaults**, then pick what to add:

- **Defaults for some lights**: pick one or more lights and set a brightness,
  a color temperature or both. Leave a value empty to use the one from a group
  or from the defaults for all lights, or pick it under **No default for** to
  keep the lights' usual behavior for it. A light group covers the lights in
  it, so picking the group is enough (see [Behavior](#behavior)). All the
  lights in an entry share its values, and you can give the entry a name
  (otherwise it's named after its lights).
- **Defaults for all lights**: a brightness, a color temperature or both.
- **Lights to exclude**: lights, or light groups, that never get defaults.

**Add entry** on the Light Defaults page adds another, **Configure** on an
entry changes it, and deleting the entry removes it. Changes apply right away.
There's one entry for all lights and one for excluded lights. A light can only
be in one entry, so lights that already have one, excluded lights included,
aren't offered again.

If you change a light's entity ID, its entry follows it. The YAML map can't,
so update the entity ID there yourself.

### In YAML

```yaml
light_defaults:
  all:
    brightness: 100    # percent, 1–100
  exclude:
    - light.sunroom
  light.office_lamp:
    temperature: 6500  # Kelvin, 1000–10000
  light.living_room_lamp:
    brightness: 80
    temperature: none
```

Every key can be left out. Here `light.office_lamp` comes on at 6500 K and
100% (from `all`), and `light.living_room_lamp` at 80% and whatever color
temperature it had. After editing the map, run the `light_defaults.reload`
action; no restart needed.

### Keeping the map in its own file

To keep `configuration.yaml` short, point `light_defaults` at a separate file
in the same folder:

```yaml
# configuration.yaml
light_defaults: !include light_defaults.yaml
```

```yaml
# light_defaults.yaml
all:
  brightness: 100
light.office_lamp:
  temperature: 6500
light.living_room_lamp:
  brightness: 80
```

The included file holds just the map: no `light_defaults:` line, and `all`,
`exclude` and the entity IDs start at the left margin. `light_defaults.reload`
re-reads it, so edits there don't need a restart either.

### Both

A light set up in the UI ignores its YAML entry, and Home Assistant logs a
warning naming it. The UI's defaults for all lights replace YAML's `all` the
same way. A light excluded in either place is excluded, even if it has an
entry in the other (that logs a warning too). Lights only in YAML keep working
as before.

## Behavior

- Applies only when a light turns on from off, through `light.turn_on` or
  `light.toggle`, from anything that goes through Home Assistant: dashboards,
  voice, HomeKit/Google, scenes, automations, areas and light groups.
- Anything the call specifies wins, per attribute: `brightness_pct: 100` on its
  own still gets the default temperature, and an explicit color keeps the
  default brightness.
- Lights that are already on, and calls with an effect or flash, are left alone.
- Each value comes from the most specific place that sets it: the light's own
  entry, then the configured groups it's in from smallest to largest, then the
  defaults for all lights. `none` counts as setting it, to nothing.
- A light group's values cover the lights in it, whether you turn on the group
  or a single light, so setting up the group is enough. This works for Home
  Assistant light groups, groups inside groups, and Zigbee2MQTT groups
  (Zigbee2MQTT 2.10 or later, which tells Home Assistant what's in each group).
- Turning on a Home Assistant light group gives each light in it the same
  defaults it would get turned on by itself. A Zigbee2MQTT group sends one
  command to all its bulbs, so they all get the group's values: from its own
  entry, a group it's in, or the defaults for all lights.
- Excluded lights never get defaults. Excluding a group excludes the lights in
  it, even ones with an entry of their own.
- Color lights switch to white when they get a color temperature, and lights
  with neither color nor color temperature ignore it. Lights without
  brightness support ignore brightness.
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

HACS offers each new GitHub release as an update, with its release notes.
Install it from HACS and restart Home Assistant.

## Development

Tests run against a real Home Assistant core and need Python 3.14+:

```sh
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements_test.txt
.venv/bin/pytest
```

See `CLAUDE.md` for how the integration hooks into Home Assistant.
