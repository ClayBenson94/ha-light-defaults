"""Light Defaults: per-light default brightness and color temperature.

When a light is turned on from off (light.turn_on or light.toggle) and the call
leaves out brightness and/or color, the configured defaults fill the gap:

    light_defaults:
      light.office_lamp:
        brightness: 100    # percent
        temperature: 6500  # Kelvin
      light.living_room_lamp:
        brightness: 80
        reset_when_on: true  # optional, see below

- Anything in the call wins, per attribute: `brightness_pct: 100` on its own
  still gets the default temperature, and an explicit color keeps the default
  brightness.
- Lights that are already on, and calls with an effect or flash, are left alone.
  With `reset_when_on`, a plain turn-on (no brightness, no color) applies the
  defaults to a light that's already on too.
- A light group's defaults also cover the lights in it that have none of their
  own; a light in more than one configured group gets the smallest one's.
- After editing the map, run the `light_defaults.reload` action. No restart needed.

Lights can also be set up in the UI (config_flow.py), where one config entry
gives one or more lights the same defaults. A light set up in the UI ignores
its YAML entry, and its entry follows the light when its entity ID changes.

How it works: Home Assistant's light integration already runs a per-light
"defaults" step on every turn-on and toggle (the hook behind light_profiles.csv).
This wraps that step, so it covers every path through HA: dashboards, voice,
HomeKit/Google, scenes, automations, areas and light groups. That step is
internal; if a future HA release changes it, setup fails with a logged error
and lights fall back to stock behavior.
"""

from dataclasses import dataclass, field
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_FLASH,
    ATTR_HS_COLOR,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_WHITE,
    ATTR_XY_COLOR,
    DOMAIN as LIGHT_DOMAIN,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, CONF_ENTITIES, SERVICE_RELOAD
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.reload import async_integration_yaml_config
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)

DOMAIN = "light_defaults"
CONF_BRIGHTNESS = "brightness"
CONF_TEMPERATURE = "temperature"
CONF_RESET_WHEN_ON = "reset_when_on"

# Where the light integration keeps its profiles object (light.const.DATA_PROFILES).
PROFILES_KEY = "light_profiles"

# Where ZHA, WLED and MQTT groups (Zigbee2MQTT 2.10+) list their members
# (const.ATTR_GROUP_ENTITIES, which older HA doesn't have). HA light groups
# use the entity_id attribute instead.
ATTR_GROUP_ENTITIES = "group_entities"

# Color attributes as they look at the defaults step: color_name has already
# become rgb_color and any `profile:` has already been applied.
COLOR_ATTRS = (
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ATTR_RGBWW_COLOR,
    ATTR_XY_COLOR,
    ATTR_WHITE,
)

LIGHT_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_BRIGHTNESS): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=100)
        ),
        vol.Optional(CONF_TEMPERATURE): vol.All(
            vol.Coerce(int), vol.Range(min=1000, max=10000)
        ),
        vol.Optional(CONF_RESET_WHEN_ON): cv.boolean,
    }
)

CONFIG_SCHEMA = vol.Schema(
    # Own Schema so ALLOW_EXTRA below doesn't let non-light keys through.
    {DOMAIN: vol.Schema({cv.entity_domain(LIGHT_DOMAIN): LIGHT_SCHEMA})},
    extra=vol.ALLOW_EXTRA,
)


@dataclass
class LightDefaults:
    """Defaults by entity ID, from the YAML map and from UI config entries."""

    yaml: dict[str, dict[str, Any]] = field(default_factory=dict)
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)

    def get(self, hass: HomeAssistant, entity_id: str) -> dict[str, Any] | None:
        """A light's own defaults (a UI entry replaces its YAML entry), or else
        those of a configured group it's in."""
        if entity_id in self.entries:
            return self.entries[entity_id]
        if entity_id in self.yaml:
            return self.yaml[entity_id]
        # Otherwise the smallest configured group the light is in.
        groups = [
            (len(lights), group_id)
            for group_id in self.entries.keys() | self.yaml.keys()
            if entity_id in (lights := _group_lights(hass, group_id))
        ]
        return self.get(hass, min(groups)[1]) if groups else None

    def warn_overlap(self) -> None:
        """Log lights set up in both places, since their YAML entry is ignored."""
        if both := sorted(self.yaml.keys() & self.entries.keys()):
            _LOGGER.warning(
                "Set up both in YAML and in the UI, using the UI values: %s",
                ", ".join(both),
            )


def _group_lights(hass: HomeAssistant, entity_id: str) -> set[str]:
    """The lights in a group, through nested groups; empty for a plain light."""
    found: set[str] = set()
    todo = [entity_id]
    while todo:
        if (state := hass.states.get(todo.pop())) is None:
            continue
        attrs = state.attributes
        members = attrs.get(ATTR_GROUP_ENTITIES) or attrs.get(ATTR_ENTITY_ID) or ()
        for member in members:
            if member != entity_id and member not in found:
                found.add(member)
                todo.append(member)
    return found


def _fill_defaults(
    light: dict[str, Any] | None, state_on: bool | None, params: dict[str, Any]
) -> None:
    """Fill in what the call left out, for a configured light turning on from off.

    With reset_when_on, a plain call (no brightness, no color) to a light that's
    already on gets them too. Turning a light off reaches here the same way
    (on, empty params); HA's filter_turn_off_params then drops what we add.
    """
    if not light or ATTR_EFFECT in params or ATTR_FLASH in params:
        return
    has_brightness = ATTR_BRIGHTNESS in params
    has_color = any(attr in params for attr in COLOR_ATTRS)
    plain = not has_brightness and not has_color
    if state_on and not (plain and light.get(CONF_RESET_WHEN_ON)):
        return
    if CONF_BRIGHTNESS in light and not has_brightness:
        params[ATTR_BRIGHTNESS] = round(255 * light[CONF_BRIGHTNESS] / 100)
    if CONF_TEMPERATURE in light and not has_color:
        params[ATTR_COLOR_TEMP_KELVIN] = light[CONF_TEMPERATURE]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Wrap the light integration's per-light defaults step."""
    profiles = hass.data.get(PROFILES_KEY)
    original = getattr(profiles, "apply_default", None)
    if original is None:
        _LOGGER.error(
            "This Home Assistant version doesn't have the light defaults step "
            "this integration hooks into; light_defaults is inactive"
        )
        return False

    defaults = hass.data[DOMAIN] = LightDefaults(yaml=dict(config.get(DOMAIN, {})))

    @callback
    def apply_default(
        entity_id: str,
        state_on: bool | None,
        params: dict[str, Any],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        try:
            _fill_defaults(defaults.get(hass, entity_id), state_on, params)
        except Exception:  # Never let this break light.turn_on.
            _LOGGER.exception("Couldn't apply defaults to %s", entity_id)
        # Any light_profiles.csv defaults still apply to whatever is left.
        original(entity_id, state_on, params, *args, **kwargs)

    profiles.apply_default = apply_default

    async def async_reload(call: ServiceCall) -> None:
        conf = await async_integration_yaml_config(hass, DOMAIN)
        if conf is None:  # Invalid config; HA has already logged why.
            return
        defaults.yaml = dict(conf.get(DOMAIN, {}))
        _LOGGER.info("Loaded YAML defaults for %d lights", len(defaults.yaml))
        defaults.warn_overlap()

    async_register_admin_service(hass, DOMAIN, SERVICE_RELOAD, async_reload)

    @callback
    def entity_id_changed(event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        """Rename a light in its UI entry; the update listener does the rest."""
        old, new = event.data["old_entity_id"], event.data["entity_id"]
        for entry in hass.config_entries.async_entries(DOMAIN):
            if old in (lights := entry.options[CONF_ENTITIES]):
                hass.config_entries.async_update_entry(
                    entry,
                    options={
                        **entry.options,
                        CONF_ENTITIES: [new if e == old else e for e in lights],
                    },
                )

    @callback
    def is_entity_id_change(data: er.EventEntityRegistryUpdatedData) -> bool:
        return "old_entity_id" in data

    hass.bus.async_listen(
        er.EVENT_ENTITY_REGISTRY_UPDATED, entity_id_changed, is_entity_id_change
    )
    return True


@callback
def _add_entry(defaults: LightDefaults, entry: ConfigEntry) -> None:
    """Give each of the entry's lights its defaults."""
    light = {
        key: entry.options[key]
        for key in (CONF_BRIGHTNESS, CONF_TEMPERATURE, CONF_RESET_WHEN_ON)
        if key in entry.options
    }
    # The lights to take out again when the entry changes or unloads.
    entry.runtime_data = list(entry.options[CONF_ENTITIES])
    for entity_id in entry.runtime_data:
        defaults.entries[entity_id] = light
    defaults.warn_overlap()


@callback
def _remove_entry(defaults: LightDefaults, entry: ConfigEntry) -> None:
    for entity_id in entry.runtime_data:
        defaults.entries.pop(entity_id, None)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Add lights set up in the UI; entry.options holds them and their defaults."""
    _add_entry(hass.data[DOMAIN], entry)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    _remove_entry(hass.data[DOMAIN], entry)
    _add_entry(hass.data[DOMAIN], entry)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _remove_entry(hass.data[DOMAIN], entry)
    return True
