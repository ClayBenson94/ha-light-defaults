"""UI setup for Light Defaults: one config entry per set of lights, plus one for
all lights and one for excluded lights.

entry.options holds everything and entry.data is empty. Values are in the same
shape as a YAML entry, with None for `none`:
- A set of lights (no unique ID): {"entities": ["light.a", "light.b"],
  "brightness": 80, "temperature": None}.
- All lights (unique ID "all"): {"brightness": 100}.
- Excluded lights (unique ID "exclude"): {"entities": ["light.sunroom"]}.
"""

from collections.abc import Mapping
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

from . import CONF_ALL, CONF_BRIGHTNESS, CONF_EXCLUDE, CONF_TEMPERATURE, DOMAIN, VALUES

# Form only: the values a set of lights gets `none` for.
CONF_NO_DEFAULT = "no_default"

TITLES = {CONF_ALL: "All lights", CONF_EXCLUDE: "Excluded lights"}

# Optional, so either can be left out (or cleared later), like in YAML.
VALUE_FIELDS = {
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

NO_DEFAULT_FIELD = {
    vol.Optional(CONF_NO_DEFAULT): selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=list(VALUES),
            multiple=True,
            mode=selector.SelectSelectorMode.LIST,
            translation_key=CONF_NO_DEFAULT,
        )
    )
}


def _taken(hass: HomeAssistant, entry_id: str | None = None) -> set[str]:
    """Lights in entries other than entry_id; a light can only be in one,
    counting the excluded lights entry."""
    return {
        entity_id
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.entry_id != entry_id
        for entity_id in entry.options.get(CONF_ENTITIES, ())
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


def _fields(hass: HomeAssistant, kind: str | None, entry_id: str | None = None) -> dict:
    """The form fields for an entry; kind is its unique ID (None for lights)."""
    if kind == CONF_ALL:
        return VALUE_FIELDS
    if kind == CONF_EXCLUDE:
        return _lights_field(hass, entry_id)
    return {**_lights_field(hass, entry_id), **VALUE_FIELDS, **NO_DEFAULT_FIELD}


def _form_values(options: Mapping[str, Any]) -> dict[str, Any]:
    """An entry's options as form values: a `none` value is picked under No
    default for, with its own field left empty."""
    return {
        **{key: value for key, value in options.items() if value is not None},
        CONF_NO_DEFAULT: [key for key in VALUES if key in options and options[key] is None],
    }


def _options(
    hass: HomeAssistant,
    kind: str | None,
    user_input: dict[str, Any],
    errors: dict[str, str],
    entry_id: str | None = None,
) -> dict[str, Any] | None:
    """The form's lights and whole-number values (None for `none`), or None
    with errors set."""
    options: dict[str, Any] = {}
    if kind != CONF_ALL:
        lights = options[CONF_ENTITIES] = user_input[CONF_ENTITIES]
        if not lights:
            errors[CONF_ENTITIES] = "no_lights"
        elif _taken(hass, entry_id).intersection(lights):
            # Added in another form since this one opened.
            errors[CONF_ENTITIES] = "already_configured"
    if kind != CONF_EXCLUDE:
        values = {key: round(user_input[key]) for key in VALUES if key in user_input}
        # A value picked under No default for overrides its slider, since the
        # form can't disable the slider when the box is ticked.
        values |= dict.fromkeys(user_input.get(CONF_NO_DEFAULT, []))
        if not values:
            errors["base"] = "no_values" if kind == CONF_ALL else "no_defaults"
        options |= values
    return None if errors else options


class LightDefaultsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add defaults for some lights or for all lights, or lights to exclude."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="user", menu_options=["lights", CONF_ALL, CONF_EXCLUDE]
        )

    async def async_step_lights(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if options := _options(self.hass, None, user_input, errors):
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
                **VALUE_FIELDS,
                **NO_DEFAULT_FIELD,
            }
        )
        return self.async_show_form(
            step_id="lights",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_all(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_step_single(CONF_ALL, user_input)

    async def async_step_exclude(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_step_single(CONF_EXCLUDE, user_input)

    async def _async_step_single(
        self, kind: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """The one entry for all lights, or for excluded lights."""
        await self.async_set_unique_id(kind)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        if user_input is not None:
            if options := _options(self.hass, kind, user_input, errors):
                return self.async_create_entry(
                    title=TITLES[kind], data={}, options=options
                )

        return self.async_show_form(
            step_id=kind,
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(_fields(self.hass, kind)), user_input
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return LightDefaultsOptionsFlow()


class LightDefaultsOptionsFlow(OptionsFlow):
    """Change an entry's lights or values."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The form for the entry's kind; this step's own for a set of lights."""
        if self.config_entry.unique_id == CONF_ALL:
            return await self.async_step_all()
        if self.config_entry.unique_id == CONF_EXCLUDE:
            return await self.async_step_exclude()
        return self._async_form("init", user_input)

    async def async_step_all(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self._async_form(CONF_ALL, user_input)

    async def async_step_exclude(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self._async_form(CONF_EXCLUDE, user_input)

    @callback
    def _async_form(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        entry = self.config_entry
        errors: dict[str, str] = {}
        if user_input is not None:
            if options := _options(
                self.hass, entry.unique_id, user_input, errors, entry.entry_id
            ):
                return self.async_create_entry(data=options)

        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(_fields(self.hass, entry.unique_id, entry.entry_id)),
                _form_values(entry.options) if user_input is None else user_input,
            ),
            errors=errors,
            description_placeholders={"name": entry.title},
        )
