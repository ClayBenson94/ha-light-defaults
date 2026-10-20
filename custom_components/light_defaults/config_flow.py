"""UI setup for Light Defaults: one config entry per light.

entry.data holds the light's entity ID, entry.options its defaults in the same
shape as a YAML entry ({"brightness": 80, "temperature": 2700}).
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
from homeassistant.const import CONF_ENTITY_ID
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import CONF_BRIGHTNESS, CONF_TEMPERATURE, DOMAIN

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
}


def _defaults(user_input: dict[str, Any]) -> dict[str, int]:
    """The defaults the form returned, as whole numbers."""
    return {
        key: round(user_input[key])
        for key in (CONF_BRIGHTNESS, CONF_TEMPERATURE)
        if key in user_input
    }


class LightDefaultsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add defaults for one light."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            entity_id = user_input[CONF_ENTITY_ID]
            await self.async_set_unique_id(entity_id)
            self._abort_if_unique_id_configured()
            if defaults := _defaults(user_input):
                state = self.hass.states.get(entity_id)
                return self.async_create_entry(
                    title=state.name if state else entity_id,
                    data={CONF_ENTITY_ID: entity_id},
                    options=defaults,
                )
            errors["base"] = "no_defaults"

        schema = vol.Schema(
            {
                vol.Required(CONF_ENTITY_ID): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=LIGHT_DOMAIN,
                        # Lights that already have an entry.
                        exclude_entities=list(self._async_current_ids()),
                    )
                ),
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
    """Change a light's defaults."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if defaults := _defaults(user_input):
                return self.async_create_entry(data=defaults)
            errors["base"] = "no_defaults"

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(DEFAULTS_FIELDS),
                self.config_entry.options if user_input is None else user_input,
            ),
            errors=errors,
            description_placeholders={"light": self.config_entry.title},
        )
