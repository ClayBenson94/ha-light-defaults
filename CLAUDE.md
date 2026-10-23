# CLAUDE.md

Context for working on this repo. Read it before changing anything.

## What this is

`light_defaults` is a Home Assistant custom integration, installed through HACS
as a custom repository. When a light turns on from off and the `light.turn_on`
or `light.toggle` call leaves out brightness or color, it fills in defaults
from a YAML map, or from config entries set up in the UI (one per set of
lights, plus one each for all lights and excluded lights):

```yaml
light_defaults:
  all:                 # every light
    brightness: 100    # percent, 1–100
  exclude:             # lights that never get defaults
    - light.sunroom
  light.office_lamp:
    temperature: 6500  # Kelvin, 1000–10000
  light.living_room_lamp:
    brightness: 80
    temperature: none  # no default, whatever `all` or a group says
```

Built for color-temperature-only bulbs on Zigbee2MQTT (Hue White Ambiance
class). The flat entity → `brightness`/`temperature` map is the point of the
project; keep it that simple. `all` and `exclude` are the only other keys (the
owner asked for them in 1.3.0), and they can't clash with entity IDs. The
owner asked for UI setup too, which lives in `config_flow.py`; keep everything
else in `__init__.py` and keep the code small unless the owner asks for more.

## Behavior contract

Don't change these without asking the owner:

- Applies only when the light is off and being turned on. Lights that are
  already on are never touched, so a motion automation re-firing `turn_on`
  doesn't reset a dimmed light.
- Explicit values win per attribute: a call with brightness still gets the
  default temperature, and a call with any color attribute still gets the
  default brightness.
- Calls with `effect` or `flash` are left alone.
- Each value comes from the most specific place that sets it: the light's own
  entry, then the configured groups it's in (through nested groups) from
  smallest to largest, then `all`. Each value is looked up on its own, so a
  light's own temperature can go with its group's brightness. `none` (None in
  config entries, **No default for** in the UI) counts as setting it, so the
  light gets no default for it.
- Excluded lights, and the lights in excluded groups, get nothing, even with
  entries of their own. Excluded in YAML or in the UI counts, and an exclusion
  beats an entry in either place, with a warning.
- HA light groups (the ones with an `entity_id` attribute) get nothing
  themselves, so turning one on gives each light in it the same values as
  turning that light on by itself. Native groups (`group_entities`) send one
  command, so they get values like any light, and their members all get those.
- `brightness` is percent, converted with `round(255 * pct / 100)` (same as
  HA's `brightness_pct`). `temperature` is injected as `color_temp_kelvin`; HA
  converts or drops it per light.
- `light_profiles.csv` defaults still apply after ours (we fill first, then
  call the original).
- Fail open: errors in our code are logged and the turn-on goes through
  untouched. If the hook is missing, `async_setup` logs an error and returns
  False.
- `light_defaults.reload` (admin-only) re-reads the YAML; invalid YAML keeps
  the current map. The README offers `light_defaults: !include
  light_defaults.yaml` as a way to keep the map in its own file; HA resolves
  the include, and reload picks up edits to it because
  `async_integration_yaml_config` re-reads `configuration.yaml` and its
  includes. Keep reload on that helper.
- A light set up in the UI replaces its YAML entry as a whole (not per
  attribute), and a warning names the overlap; the UI's all lights entry
  replaces YAML's `all` the same way. A light can only be in one UI entry, the
  excluded lights entry included, and there's one entry each for all lights
  and excluded lights. Reload only touches the YAML side; UI changes apply as
  soon as the flow saves.

## How it works

`custom_components/light_defaults/__init__.py` replaces `apply_default` on the
light integration's `Profiles` object at `hass.data["light_profiles"]`
(`homeassistant.components.light.const.DATA_PROFILES`). HA calls it from
`homeassistant/components/light/helper.py`:

- `process_turn_on_params()` calls `apply_default(entity_id, light.is_on,
  params)` once per entity, for `light.turn_on` and for `light.toggle` from off
  (`LightEntity.async_toggle`). By then `brightness_pct`, `brightness_step*`,
  `color_name` and `profile:` have been normalized into `brightness`,
  `rgb_color` or `hs_color`. Color-mode conversion and `filter_turn_on_params`
  run after it, which is why we only set `brightness` and `color_temp_kelvin`.
- `process_turn_off_params()` calls `apply_default(entity_id, True, params)`;
  `state_on` is True, so we do nothing.

HA light groups forward `light.turn_on` to their members with everything the
call ended up with (`LightGroup.async_turn_on`, `FORWARDED_ATTRIBUTES`), so
anything we filled in for the group would reach its members as explicit values
and beat their own entries and exclusions. So `LightDefaults.get` returns
nothing for an HA light group, and each member goes through `get` itself; a
configured HA group's values reach its members through the group lookup in
`get`, which also covers a member turning on by itself or through a group
that's already on. `_group_lights` reads members from public state, recursing
into nested groups: `group_entities` (ZHA, WLED, and MQTT entities with the
`group` option, which Zigbee2MQTT sends from 2.10) or `entity_id` (HA light
groups, which don't use `group_entities` yet; if they switch, `_is_light_group`
has to follow, or every HA group would hand `all` to its members). A Z2M group
is a single MQTT light entity, so turning it on sends one command with the
group's values. Adaptive Lighting, if it's ever added, intercepts at the
service level and writes its values before this hook runs, so lights it
manages follow AL.

`hass.data["light_defaults"]` is a `LightDefaults` holding values (None for
`none`) by entity ID, and `all` under `CONF_ALL`, from YAML (`.yaml`) and from
the UI (`.entries`), plus each side's excluded lights (`.yaml_excluded`,
`.entries_excluded`); the hook reads it through `.get()`, and only for a light
turning on from off. `async_setup` installs the hook whether or not YAML
exists (HA calls it before setting up config entries). Each config entry keeps
everything in `options`, in the same shape as a YAML entry, and `data` is
empty:

- A set of lights has no unique ID: its lights under `entities` and their
  shared values beside them. Its title is the optional name, or its lights'
  names.
- The all lights entry has unique ID `all` and just the values.
- The excluded lights entry has unique ID `exclude` and just `entities`.

The unique IDs keep those two to one entry each. `async_setup_entry` and an
update listener add what the entry holds and remember the keys it added (its
lights, or `all`) in `entry.runtime_data`, so a change or `async_unload_entry`
can take them out. A light can only be in one entry, the excluded lights entry
included: the flows leave lights in other entries out of the picker and
re-check on submit, for two forms open at once. A listener on
`entity_registry_updated` (filtered to events with `old_entity_id`) renames the
light in its entry's `options`, and the update listener does the rest. The
YAML map isn't touched on renames.

The hook is internal API. HA marks light profiles as frozen, so it rarely
changes, but it's the first thing to check if an HA update breaks the tests.

## Repo rules (HACS)

- Exactly one folder under `custom_components/`. Test helpers live in `tests/`.
- `manifest.json` must keep `domain`, `name`, `version`, `documentation`,
  `issue_tracker` and `codeowners`, plus `dependencies: ["light"]` and
  `config_flow: true`.
- UI strings live in `custom_components/light_defaults/translations/en.json`.
  Custom integrations don't get `strings.json` compiled, so edit `en.json`
  directly.
- `hacs.json` (just `name`) and `README.md` stay at the root. Brand icons live
  in `custom_components/light_defaults/brand/` (`icon.png` 256 px,
  `icon@2x.png` 512 px); HA serves these for custom integrations.
- The repo must stay public; HACS can't read private repos.
- Changes go through pull requests against `main`; don't push to `main`
  directly. No CI runs on pull requests, so run the tests before merging.
- HACS installs GitHub releases (since v1.1.0) and ignores plain tags, so a
  merge to `main` doesn't reach HACS until the next release. To ship, bump
  `version` in `manifest.json` in the pull request, merge it, then publish a
  release from the merged commit on `main` with a tag that matches the
  version: `gh release create vX.Y.Z --target <main sha> --title vX.Y.Z
  --notes-file <notes>`. HACS shows the notes in its update dialog, so write
  them for the owner (what changed, and whether to restart).

## Development

Needs Python 3.14+ (HA 2026.10 requires 3.14.2 or later).

```sh
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements_test.txt
.venv/bin/pytest
```

The tests run against a real HA core, pinned through
`pytest-homeassistant-custom-component` in `requirements_test.txt`
(0.13.373 = HA 2026.10.2). To check a new HA release, bump that pin to the
matching version and rerun. `.github/workflows/latest-ha.yml` does this every
Monday against the newest release (or on demand from the Actions tab) and
records the HA version it tested in the run summary; a red run means an HA
change to check before updating HA.

- `tests/test_light_defaults.py`: behavior, using recording test lights from
  `tests/recording_light.py`: `all`, `none`, exclusions, values from nested
  groups, and HA light groups passing the turn-on through.
- `tests/test_config_flow.py`: UI setup (the Add entry menu, config and
  options flows for each kind of entry, **No default for**, a configured light
  group covering its lights, overlap with YAML, and `en.json` labeling every
  form field).
- `tests/test_mqtt_z2m.py`: the MQTT payload a Zigbee2MQTT-style light
  receives, alone and as a member of a configured Z2M group, and a Z2M group
  filling in `all` itself. A bare turn-on is a single `{"state": "ON",
  "brightness": 254, "color_temp": 153}` command.

Gotchas:

- HA 2026.x validates with `probatio`; `import voluptuous` still works because
  HA aliases it at startup. Keep `import voluptuous as vol` so older HA works
  too.
- Nested dict schemas inherit `extra=ALLOW_EXTRA` from `CONFIG_SCHEMA`. The
  inner map is wrapped in its own `vol.Schema` so non-light keys are rejected;
  keep it that way.
- HA's entity ID validators (`cv.entity_ids`, `cv.entity_domain`) take a
  dict's keys as entity IDs, so `exclude` checks `[cv.string]` first.
  Otherwise a mis-indented light entry under `exclude` would quietly exclude
  that light.
- The config flow's `user` step is a menu (`lights`, `all`, `exclude`), each
  its own form step. The options flow's `init` is the lights form and hands
  the other two kinds to its `all` and `exclude` steps, which have their own
  strings in `en.json`.
- `light.turn_on` no longer accepts mired `color_temp` or `kelvin`; only
  `color_temp_kelvin`.
- `tests/conftest.py` imports `custom_components` at collection time. Without
  that, the harness binds `custom_components` to its own testing config and HA
  reports "Integration not found".
- The options flow is created as `LightDefaultsOptionsFlow()` and reads
  `self.config_entry`; passing the entry in or assigning it is deprecated. Don't
  switch to `OptionsFlowWithReload`: HA forbids it alongside the update
  listener, and it needs HA 2025.8+.
- The MQTT tests set `expected_lingering_timers` because the mocked client
  leaves a timer behind.
- Don't use `async_get_all_descriptions` in tests; it imports every loaded
  integration, and conversation needs extra deps. `_load_services_file` checks
  `services.yaml` directly.

## Alternatives already ruled out

- `light_profiles.csv`: color as xy and brightness as 0–255, a restart for
  every edit, and it re-applies to lights that are already on.
- Adaptive Lighting with min = max: one AL instance (and four switches) per
  distinct value pair, so no flat map. Fine to add later for rooms that should
  follow the time of day; it coexists with this.
- Automations on off → on: a second command after the light is already on, and
  no way to tell explicit values from defaults.
- Wrapper or template lights: duplicate every entity.
