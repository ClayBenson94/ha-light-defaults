"""Light Defaults: per-light default brightness and color temperature.

When a light is turned on from off (light.turn_on or light.toggle) and the call
leaves out brightness and/or color, the configured defaults fill the gap:

    light_defaults:
      light.office_lamp:
        brightness: 100    # percent
        temperature: 6500  # Kelvin
      light.living_room_lamp:
        brightness: 80

- Anything in the call wins, per attribute: `brightness_pct: 100` on its own
  still gets the default temperature, and an explicit color keeps the default
  brightness.
- Lights that are already on, and calls with an effect or flash, are left alone.
- After editing the map, run the `light_defaults.reload` action. No restart needed.

Lights can also be set up in the UI (config_flow.py), one config entry per
light. A light set up in the UI ignores its YAML entry, and its entry follows
the light when its entity ID changes.

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
from homeassistant.const import CONF_ENTITY_ID, SERVICE_RELOAD
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.reload import async_integration_yaml_config
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)

DOMAIN = "light_defaults"
CONF_BRIGHTNESS = "brightness"
CONF_TEMPERATURE = "temperature"

# Where the light integration keeps its profiles object (light.const.DATA_PROFILES).
PROFILES_KEY = "light_profiles"

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

    yaml: dict[str, dict[str, int]] = field(default_factory=dict)
    entries: dict[str, dict[str, int]] = field(default_factory=dict)

    def get(self, entity_id: str) -> dict[str, int] | None:
        """A light's defaults; a UI entry replaces its YAML entry."""
        if entity_id in self.entries:
            return self.entries[entity_id]
        return self.yaml.get(entity_id)

    def warn_overlap(self) -> None:
        """Log lights set up in both places, since their YAML entry is ignored."""
        if both := sorted(self.yaml.keys() & self.entries.keys()):
            _LOGGER.warning(
                "Set up both in YAML and in the UI, using the UI values: %s",
                ", ".join(both),
            )


def _fill_defaults(
    light: dict[str, int] | None, state_on: bool | None, params: dict[str, Any]
) -> None:
    """Fill in what the call left out, for a configured light turning on from off."""
    if not light or state_on or ATTR_EFFECT in params or ATTR_FLASH in params:
        return
    if CONF_BRIGHTNESS in light and ATTR_BRIGHTNESS not in params:
        params[ATTR_BRIGHTNESS] = round(255 * light[CONF_BRIGHTNESS] / 100)
    if CONF_TEMPERATURE in light and not any(attr in params for attr in COLOR_ATTRS):
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
            _fill_defaults(defaults.get(entity_id), state_on, params)
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
        """Move a light's UI entry to its new entity ID."""
        old, new = event.data["old_entity_id"], event.data["entity_id"]
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.data[CONF_ENTITY_ID] == old:
                if old in defaults.entries:
                    defaults.entries[new] = defaults.entries.pop(old)
                hass.config_entries.async_update_entry(
                    entry, data={CONF_ENTITY_ID: new}, unique_id=new
                )

    @callback
    def is_entity_id_change(data: er.EventEntityRegistryUpdatedData) -> bool:
        return "old_entity_id" in data

    hass.bus.async_listen(
        er.EVENT_ENTITY_REGISTRY_UPDATED, entity_id_changed, is_entity_id_change
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Add a light set up in the UI; entry.options holds its defaults."""
    defaults: LightDefaults = hass.data[DOMAIN]
    defaults.entries[entry.data[CONF_ENTITY_ID]] = dict(entry.options)
    defaults.warn_overlap()
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    hass.data[DOMAIN].entries[entry.data[CONF_ENTITY_ID]] = dict(entry.options)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data[DOMAIN].entries.pop(entry.data[CONF_ENTITY_ID], None)
    return True
