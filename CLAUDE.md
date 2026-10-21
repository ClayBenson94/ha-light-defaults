# CLAUDE.md

Context for working on this repo. Read it before changing anything.

## What this is

`light_defaults` is a Home Assistant custom integration, installed through HACS
as a custom repository. When a light turns on from off and the `light.turn_on`
or `light.toggle` call leaves out brightness or color, it fills in per-light
defaults from a YAML map, or from config entries set up in the UI (each one
gives one or more lights the same values):

```yaml
light_defaults:
  light.office_lamp:
    brightness: 100    # percent, 1–100
    temperature: 6500  # Kelvin, 1000–10000
  light.living_room_lamp:
    brightness: 80
    reset_when_on: true  # optional
```

Built for color-temperature-only bulbs on Zigbee2MQTT (Hue White Ambiance
class). The flat entity → `brightness`/`temperature` map is the point of the
project; keep it that simple. The owner asked for the optional
`reset_when_on` flag; don't add more keys without asking. The owner asked for
UI setup too, which lives in `config_flow.py`; keep everything else in
`__init__.py` and keep the code small unless the owner asks for more.

## Behavior contract

Don't change these without asking the owner:

- Applies when the light is off and being turned on. Lights that are already
  on are left alone by default, so a motion automation re-firing `turn_on`
  doesn't reset a dimmed light.
- `reset_when_on` (per entry, off by default; a checkbox in both flows): a
  plain turn-on (no brightness, no color attribute) of a light that's already
  on gets both defaults, so a switch's "on" button doubles as a reset. Calls
  that set brightness or a color still get nothing for a light that's on. A
  light covered by a group follows the group's setting. The UI stores the key
  only when it's ticked.
- Explicit values win per attribute: a call with brightness still gets the
  default temperature, and a call with any color attribute still gets the
  default brightness.
- Calls with `effect` or `flash` are left alone.
- A light with no entry of its own (UI or YAML) uses the smallest configured
  group it's in, through nested groups. A light's own entry beats any group.
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
  attribute), and a warning names the overlap. A light can only be in one UI
  entry. Reload only touches the YAML
  side; UI changes apply as soon as the flow saves.

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
  For a light that's already on, it skips `apply_default` when the call has a
  `transition`, so a plain turn-on with a transition never resets.
- `process_turn_off_params()` calls `apply_default(entity_id, True, params)`,
  which looks exactly like a plain turn-on of a light that's on. So for a
  `reset_when_on` light we fill both defaults into turn-off params too;
  `filter_turn_off_params` keeps only `transition` and `flash`, so they're
  dropped (`test_reset_when_on_never_reaches_turn_off` checks this). HA's own
  `Profiles.apply_default` relies on the same thing: it applies the whole
  profile whenever `params` is empty.

HA light groups forward `light.turn_on` to their members along with whatever
the group's own defaults filled in, so members of a configured group that's
turned on from off get the group's values. `LightDefaults.get` covers the other
ways a member turns on (by itself, or through a group that's already on): a
light with no entry of its own gets the smallest configured group whose
members include it. `_group_lights` reads members from public state, recursing
into nested groups: `group_entities` (ZHA, WLED, and MQTT entities with the
`group` option, which Zigbee2MQTT sends from 2.10) or `entity_id` (HA light
groups, which don't use `group_entities` yet). A Z2M group is a single MQTT
light entity, so turning it on sends one command with the group's values. Adaptive Lighting, if it's ever added, intercepts at the service level
and writes its values before this hook runs, so lights it manages follow AL.

`hass.data["light_defaults"]` is a `LightDefaults` holding the YAML map
(`.yaml`) and the UI lights (`.entries`), both keyed by entity ID; the hook
reads it through `.get()`. `async_setup` installs the hook whether or not YAML
exists (HA calls it before setting up config entries). Each config entry keeps
everything in `options`: its lights under `entities` and their shared defaults
beside them, in the same shape as a YAML entry; `data` is empty and there's no
unique ID (the entry's title is the optional name, or its lights' names).
`async_setup_entry` and an update listener give each of the entry's lights its
defaults in `.entries` and remember that list in `entry.runtime_data`, so a
change or `async_unload_entry` can take the old lights out. A light can only be
in one entry: both flows leave lights in other entries out of the picker and
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
  `tests/recording_light.py` (which record turn-on and turn-off kwargs),
  including lights covered by nested groups and `reset_when_on`.
- `tests/test_config_flow.py`: UI setup (config and options flows, entries
  with several lights, a configured light group covering its lights, overlap
  with YAML, the `reset_when_on` checkbox).
- `tests/test_mqtt_z2m.py`: the MQTT payload a Zigbee2MQTT-style light
  receives, alone and as a member of a configured Z2M group. A bare turn-on is a single
  `{"state": "ON", "brightness": 254, "color_temp": 153}` command, and so is
  a plain turn-on of a `reset_when_on` light that's already on.

Gotchas:

- HA 2026.x validates with `probatio`; `import voluptuous` still works because
  HA aliases it at startup. Keep `import voluptuous as vol` so older HA works
  too.
- Nested dict schemas inherit `extra=ALLOW_EXTRA` from `CONFIG_SCHEMA`. The
  inner map is wrapped in its own `vol.Schema` so non-light keys are rejected;
  keep it that way.
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
