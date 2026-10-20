# CLAUDE.md

Context for working on this repo. Read it before changing anything.

## What this is

`light_defaults` is a Home Assistant custom integration, installed through HACS
as a custom repository. When a light turns on from off and the `light.turn_on`
or `light.toggle` call leaves out brightness or color, it fills in per-light
defaults from a YAML map:

```yaml
light_defaults:
  light.office_lamp:
    brightness: 100    # percent, 1–100
    temperature: 6500  # Kelvin, 1000–10000
  light.living_room_lamp:
    brightness: 80
```

Built for color-temperature-only bulbs on Zigbee2MQTT (Hue White Ambiance
class). The flat entity → `brightness`/`temperature` map is the point of the
project; keep it that simple, and keep the code small (YAML-only, one module)
unless the owner asks for more.

## Behavior contract

Don't change these without asking the owner:

- Applies only when the light is off and being turned on. Lights that are
  already on are never touched, so a motion automation re-firing `turn_on`
  doesn't reset a dimmed light.
- Explicit values win per attribute: a call with brightness still gets the
  default temperature, and a call with any color attribute still gets the
  default brightness.
- Calls with `effect` or `flash` are left alone.
- `brightness` is percent, converted with `round(255 * pct / 100)` (same as
  HA's `brightness_pct`). `temperature` is injected as `color_temp_kelvin`; HA
  converts or drops it per light.
- `light_profiles.csv` defaults still apply after ours (we fill first, then
  call the original).
- Fail open: errors in our code are logged and the turn-on goes through
  untouched. If the hook is missing, `async_setup` logs an error and returns
  False.
- `light_defaults.reload` (admin-only) re-reads the YAML; invalid YAML keeps
  the current map.

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

HA light groups forward `light.turn_on` to their members, so each member gets
its own defaults. A Z2M group is a single MQTT light entity and works like any
light. Adaptive Lighting, if it's ever added, intercepts at the service level
and writes its values before this hook runs, so lights it manages follow AL.

The hook is internal API. HA marks light profiles as frozen, so it rarely
changes, but it's the first thing to check if an HA update breaks the tests.

## Repo rules (HACS)

- Exactly one folder under `custom_components/`. Test helpers live in `tests/`.
- `manifest.json` must keep `domain`, `name`, `version`, `documentation`,
  `issue_tracker` and `codeowners`, plus `dependencies: ["light"]`.
- `hacs.json` (just `name`) and `README.md` stay at the root. Brand icons live
  in `custom_components/light_defaults/brand/` (`icon.png` 256 px,
  `icon@2x.png` 512 px); HA serves these for custom integrations.
- The repo must stay public; HACS can't read private repos.
- No GitHub releases: HACS tracks `main`, so every push to `main` shows up as
  an update. Don't publish a release or tag casually; once releases exist, HACS
  follows releases instead of commits. Bump `version` in `manifest.json` for
  notable changes (HA logs it).

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
  `tests/recording_light.py`.
- `tests/test_mqtt_z2m.py`: the MQTT payload a Zigbee2MQTT-style light
  receives. A bare turn-on is a single
  `{"state": "ON", "brightness": 254, "color_temp": 153}` command.

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

## Open items

Delete each line once it's done.

- [ ] Owner adds the repo in HACS (⋮ → Custom repositories, type
  Integration), downloads Light Defaults, adds the YAML map and restarts HA.
  If a copy was placed in `config/custom_components/light_defaults` by hand
  earlier, delete it first so HACS owns that folder.
