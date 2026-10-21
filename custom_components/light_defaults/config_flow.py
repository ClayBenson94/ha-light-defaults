"""UI setup for Light Defaults: one config entry per set of lights.

entry.options holds the lights and their defaults, the defaults in the same
shape as a YAML entry: {"entities": ["light.a", "light.b"], "brightness": 80,
"temperature": 2700}, plus "reset_when_on": True only when it's ticked.
entry.data is empty.
"""

from typing import Any

import voluptuous as vol

from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ENTITIES, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from . import CONF_BRIGHTNESS, CONF_RESET_WHEN_ON, CONF_TEMPERATURE, DOMAIN

# Optional, so either can be left out (or cleared later), like in YAML.
DEFAULTS_FIELDS = {
    vol.Optional(CONF_BRIGHTNESS): selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=1,
            max=100,
            step=1,
            unit_of_measurement="%",
            mode=selector.NumberSelectorMode.SLIDER,
        )
    ),
    vol.Optional(CONF_TEMPERATURE): selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=1000,
            max=10000,
            step=100,
            unit_of_measurement="K",
            mode=selector.NumberSelectorMode.SLIDER,
        )
    ),
    vol.Optional(CONF_RESET_WHEN_ON): selector.BooleanSelector(),
}


def _taken(hass: HomeAssistant, entry_id: str | None = None) -> set[str]:
    """Lights in entries other than entry_id; a light can only be in one."""
    return {
        entity_id
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.entry_id != entry_id
        for entity_id in entry.options[CONF_ENTITIES]
    }


def _lights_field(hass: HomeAssistant, entry_id: str | None = None) -> dict:
    return {
        vol.Required(CONF_ENTITIES): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=LIGHT_DOMAIN,
                multiple=True,
                exclude_entities=sorted(_taken(hass, entry_id)),
            )
        )
    }


def _options(
    hass: HomeAssistant,
    user_input: dict[str, Any],
    errors: dict[str, str],
    entry_id: str | None = None,
) -> dict[str, Any] | None:
    """The form's lights and whole-number defaults, or None with errors set."""
    lights = user_input[CONF_ENTITIES]
    defaults = {
        key: round(user_input[key])
        for key in (CONF_BRIGHTNESS, CONF_TEMPERATURE)
        if key in user_input
    }
    if not lights:
        errors[CONF_ENTITIES] = "no_lights"
    elif _taken(hass, entry_id).intersection(lights):
        # Added in another form since this one opened.
        errors[CONF_ENTITIES] = "already_configured"
    elif not defaults:
        errors["base"] = "no_defaults"
    else:
        if user_input.get(CONF_RESET_WHEN_ON):
            defaults[CONF_RESET_WHEN_ON] = True
        return {CONF_ENTITIES: lights, **defaults}
    return None


class LightDefaultsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add defaults for one or more lights."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if options := _options(self.hass, user_input, errors):
                names = []
                for entity_id in options[CONF_ENTITIES]:
                    state = self.hass.states.get(entity_id)
                    names.append(state.name if state else entity_id)
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, "").strip() or ", ".join(names),
                    data={},
                    options=options,
                )

        schema = vol.Schema(
            {
                **_lights_field(self.hass),
                vol.Optional(CONF_NAME): selector.TextSelector(),
                **DEFAULTS_FIELDS,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return LightDefaultsOptionsFlow()


class LightDefaultsOptionsFlow(OptionsFlow):
    """Change an entry's lights and defaults."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry_id = self.config_entry.entry_id
        errors: dict[str, str] = {}
        if user_input is not None:
            if options := _options(self.hass, user_input, errors, entry_id):
                return self.async_create_entry(data=options)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({**_lights_field(self.hass, entry_id), **DEFAULTS_FIELDS}),
                self.config_entry.options if user_input is None else user_input,
            ),
            errors=errors,
            description_placeholders={"name": self.config_entry.title},
        )
