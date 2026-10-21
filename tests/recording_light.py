"""Test light entities that record exactly what Home Assistant sends them."""

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)


class RecordingLight(LightEntity):
    """Light that records the kwargs of every async_turn_on call in `calls`, and
    of every async_turn_off call in `off_calls`."""

    _attr_should_poll = False

    def __init__(
        self, name: str, modes: list[ColorMode], effects: list[str] | None = None
    ) -> None:
        self._attr_name = name
        self._attr_unique_id = name.lower().replace(" ", "_")
        self._attr_supported_color_modes = set(modes)
        self._attr_color_mode = modes[0]
        self._attr_is_on = False
        self._attr_brightness = 128
        self._attr_min_color_temp_kelvin = 2200
        self._attr_max_color_temp_kelvin = 6500
        self._attr_color_temp_kelvin = 4000
        self._attr_hs_color = None
        if effects:
            self._attr_supported_features = (
                LightEntityFeature.EFFECT | LightEntityFeature.TRANSITION
            )
            self._attr_effect_list = effects
            self._attr_effect = None
        self.calls: list[dict[str, Any]] = []
        self.off_calls: list[dict[str, Any]] = []

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        self._attr_is_on = True
        if ATTR_BRIGHTNESS in kwargs:
            self._attr_brightness = kwargs[ATTR_BRIGHTNESS]
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            self._attr_color_temp_kelvin = kwargs[ATTR_COLOR_TEMP_KELVIN]
            self._attr_color_mode = ColorMode.COLOR_TEMP
        if ATTR_HS_COLOR in kwargs:
            self._attr_hs_color = kwargs[ATTR_HS_COLOR]
            self._attr_color_mode = ColorMode.HS
        if ATTR_EFFECT in kwargs:
            self._attr_effect = kwargs[ATTR_EFFECT]
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.off_calls.append(kwargs)
        self._attr_is_on = False
        self.async_write_ha_state()


def make_lights() -> list[RecordingLight]:
    """One light per capability the integration has to handle."""
    return [
        # Like a Hue White Ambiance bulb: color temperature only, has effects.
        RecordingLight("CT Lamp", [ColorMode.COLOR_TEMP], effects=["candle"]),
        RecordingLight("Dimmer", [ColorMode.BRIGHTNESS]),
        RecordingLight("Color Bulb", [ColorMode.COLOR_TEMP, ColorMode.HS]),
        RecordingLight("Unconfigured", [ColorMode.COLOR_TEMP]),
    ]
