"""End-to-end tests for light_defaults against a real Home Assistant core."""

from unittest.mock import patch

import pytest

from homeassistant.components.light import Profile
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, entity_registry as er
from homeassistant.helpers.service import _load_services_file
from homeassistant.loader import async_get_integration
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import setup_test_component_platform

from .recording_light import make_lights

CONFIG = {
    "light": [
        {"platform": "test"},
        {
            "platform": "group",
            "name": "Both",
            "entities": ["light.ct_lamp", "light.dimmer"],
        },
    ],
    "light_defaults": {
        "light.ct_lamp": {"brightness": 100, "temperature": 6500},
        "light.dimmer": {"brightness": 80, "temperature": 2700},
        "light.color_bulb": {"temperature": 3000},
    },
}


@pytest.fixture
async def lights(hass: HomeAssistant):
    entities = make_lights()
    setup_test_component_platform(hass, "light", entities)
    assert await async_setup_component(hass, "light_defaults", CONFIG)
    await hass.async_block_till_done()
    return {light.entity_id: light for light in entities}


async def call(hass: HomeAssistant, service: str, **data) -> None:
    await hass.services.async_call("light", service, data, blocking=True)
    await hass.async_block_till_done()


def last(lights, entity_id):
    return lights[entity_id].calls[-1]


async def test_bare_turn_on_gets_defaults(hass, lights):
    await call(hass, "turn_on", entity_id="light.ct_lamp")
    assert last(lights, "light.ct_lamp") == {"brightness": 255, "color_temp_kelvin": 6500}
    state = hass.states.get("light.ct_lamp")
    assert state.attributes["brightness"] == 255
    assert state.attributes["color_temp_kelvin"] == 6500
    assert state.attributes["color_mode"] == "color_temp"


async def test_brightness_override_keeps_default_temperature(hass, lights):
    await call(hass, "turn_on", entity_id="light.ct_lamp", brightness_pct=40)
    assert last(lights, "light.ct_lamp") == {"brightness": 102, "color_temp_kelvin": 6500}


async def test_temperature_override_keeps_default_brightness(hass, lights):
    await call(hass, "turn_on", entity_id="light.ct_lamp", color_temp_kelvin=2700)
    assert last(lights, "light.ct_lamp") == {"brightness": 255, "color_temp_kelvin": 2700}


async def test_full_override_wins(hass, lights):
    await call(
        hass, "turn_on", entity_id="light.ct_lamp", brightness_pct=30, color_temp_kelvin=2200
    )
    assert last(lights, "light.ct_lamp") == {"brightness": 76, "color_temp_kelvin": 2200}


async def test_brightness_step_from_off_counts_as_explicit(hass, lights):
    await call(hass, "turn_on", entity_id="light.ct_lamp", brightness_step_pct=10)
    assert last(lights, "light.ct_lamp") == {"brightness": 26, "color_temp_kelvin": 6500}


async def test_already_on_light_is_left_alone(hass, lights):
    await call(hass, "turn_on", entity_id="light.ct_lamp")
    await call(hass, "turn_on", entity_id="light.ct_lamp", brightness_pct=50)
    assert last(lights, "light.ct_lamp") == {"brightness": 128}
    # e.g. a motion automation re-firing light.turn_on on a light that's already on
    await call(hass, "turn_on", entity_id="light.ct_lamp")
    assert last(lights, "light.ct_lamp") == {}
    assert hass.states.get("light.ct_lamp").attributes["brightness"] == 128


async def reload(hass: HomeAssistant, yaml_map: dict) -> None:
    with patch(
        "homeassistant.config.async_hass_config_yaml",
        return_value={"light_defaults": yaml_map},
    ):
        await hass.services.async_call("light_defaults", "reload", blocking=True)


async def test_reset_when_on_resets_a_plain_turn_on(hass, lights):
    await reload(
        hass, {"light.ct_lamp": {"brightness": 100, "temperature": 6500, "reset_when_on": True}}
    )
    await call(
        hass, "turn_on", entity_id="light.ct_lamp", brightness_pct=50, color_temp_kelvin=2700
    )
    # A light that's on still keeps whatever the call doesn't set...
    await call(hass, "turn_on", entity_id="light.ct_lamp", brightness_pct=40)
    assert last(lights, "light.ct_lamp") == {"brightness": 102}
    await call(hass, "turn_on", entity_id="light.ct_lamp", color_temp_kelvin=3000)
    assert last(lights, "light.ct_lamp") == {"color_temp_kelvin": 3000}
    # ...but a plain turn-on puts it back to its defaults.
    await call(hass, "turn_on", entity_id="light.ct_lamp")
    assert last(lights, "light.ct_lamp") == {"brightness": 255, "color_temp_kelvin": 6500}
    assert hass.states.get("light.ct_lamp").attributes["color_temp_kelvin"] == 6500

    # HA skips the defaults step for a light that's on when the call has a transition.
    await call(hass, "turn_on", entity_id="light.ct_lamp", transition=1)
    assert last(lights, "light.ct_lamp") == {"transition": 1}


async def test_reset_when_on_never_reaches_turn_off(hass, lights):
    await reload(
        hass, {"light.ct_lamp": {"brightness": 100, "temperature": 6500, "reset_when_on": True}}
    )
    # Turning off reaches the defaults step just like a plain turn-on of a light
    # that's on, so this relies on HA dropping what we add.
    await call(hass, "turn_on", entity_id="light.ct_lamp")
    await call(hass, "turn_off", entity_id="light.ct_lamp")
    await call(hass, "turn_on", entity_id="light.ct_lamp")
    await call(hass, "toggle", entity_id="light.ct_lamp")
    assert lights["light.ct_lamp"].off_calls == [{}, {}]
    assert hass.states.get("light.ct_lamp").state == "off"


async def test_reset_when_on_comes_with_a_groups_defaults(hass, lights):
    await reload(hass, {"light.both": {"brightness": 50, "reset_when_on": True}})
    await call(hass, "turn_on", entity_id="light.dimmer", brightness_pct=20)
    await call(hass, "turn_on", entity_id="light.dimmer")
    assert last(lights, "light.dimmer") == {"brightness": 128}

    # Turning on the group while it's on resets each light in it.
    await call(hass, "turn_on", entity_id="light.ct_lamp", brightness_pct=20)
    await call(hass, "turn_on", entity_id="light.both")
    assert last(lights, "light.ct_lamp") == {"brightness": 128}
    assert last(lights, "light.dimmer") == {"brightness": 128}


async def test_defaults_return_after_turning_off(hass, lights):
    await call(
        hass, "turn_on", entity_id="light.ct_lamp", brightness_pct=50, color_temp_kelvin=2700
    )
    await call(hass, "turn_off", entity_id="light.ct_lamp")
    await call(hass, "turn_on", entity_id="light.ct_lamp")
    assert last(lights, "light.ct_lamp") == {"brightness": 255, "color_temp_kelvin": 6500}


async def test_toggle_from_off_gets_defaults(hass, lights):
    await call(hass, "toggle", entity_id="light.ct_lamp")
    assert last(lights, "light.ct_lamp") == {"brightness": 255, "color_temp_kelvin": 6500}


async def test_effect_call_is_left_alone(hass, lights):
    await call(hass, "turn_on", entity_id="light.ct_lamp", effect="candle")
    assert last(lights, "light.ct_lamp") == {"effect": "candle"}


async def test_brightness_only_light_drops_temperature(hass, lights):
    await call(hass, "turn_on", entity_id="light.dimmer")
    assert last(lights, "light.dimmer") == {"brightness": 204}


async def test_temperature_only_entry_leaves_brightness(hass, lights):
    await call(hass, "turn_on", entity_id="light.color_bulb")
    assert last(lights, "light.color_bulb") == {"color_temp_kelvin": 3000}


async def test_explicit_color_skips_default_temperature(hass, lights):
    await call(hass, "turn_on", entity_id="light.color_bulb", rgb_color=[255, 0, 0])
    kwargs = last(lights, "light.color_bulb")
    assert "color_temp_kelvin" not in kwargs
    assert "hs_color" in kwargs


async def test_unconfigured_light_is_untouched(hass, lights):
    await call(hass, "turn_on", entity_id="light.unconfigured")
    assert last(lights, "light.unconfigured") == {}


async def test_multi_target_call_applies_each_lights_defaults(hass, lights):
    await call(
        hass,
        "turn_on",
        entity_id=["light.ct_lamp", "light.dimmer", "light.unconfigured"],
    )
    assert last(lights, "light.ct_lamp") == {"brightness": 255, "color_temp_kelvin": 6500}
    assert last(lights, "light.dimmer") == {"brightness": 204}
    assert last(lights, "light.unconfigured") == {}


async def test_area_target(hass, lights):
    area = ar.async_get(hass).async_create("Office")
    er.async_get(hass).async_update_entity("light.ct_lamp", area_id=area.id)
    await call(hass, "turn_on", area_id=area.id)
    assert last(lights, "light.ct_lamp") == {"brightness": 255, "color_temp_kelvin": 6500}


async def test_light_group_members_get_their_own_defaults(hass, lights):
    await call(hass, "turn_on", entity_id="light.both")
    assert last(lights, "light.ct_lamp") == {"brightness": 255, "color_temp_kelvin": 6500}
    assert last(lights, "light.dimmer") == {"brightness": 204}


async def test_lights_get_the_smallest_configured_group_they_are_in(hass: HomeAssistant):
    entities = make_lights()
    setup_test_component_platform(hass, "light", entities)
    lamps = {"platform": "group", "name": "Lamps", "entities": ["light.ct_lamp", "light.color_bulb"]}
    downstairs = {"platform": "group", "name": "Downstairs", "entities": ["light.lamps", "light.dimmer"]}
    yaml_map = {"light.downstairs": {"brightness": 80}, "light.lamps": {"brightness": 50}}
    config = {"light": [{"platform": "test"}, lamps, downstairs], "light_defaults": yaml_map}
    assert await async_setup_component(hass, "light_defaults", config)
    await hass.async_block_till_done()
    lights = {light.entity_id: light for light in entities}

    await call(hass, "turn_on", entity_id="light.dimmer")
    assert last(lights, "light.dimmer") == {"brightness": 204}
    await call(hass, "turn_on", entity_id="light.ct_lamp")
    assert last(lights, "light.ct_lamp") == {"brightness": 128}
    await call(hass, "turn_on", entity_id="light.unconfigured")
    assert last(lights, "light.unconfigured") == {}

    # Without its own group's entry, a light goes by the group that group is in.
    del yaml_map["light.lamps"]
    with patch("homeassistant.config.async_hass_config_yaml", return_value=config):
        await hass.services.async_call("light_defaults", "reload", blocking=True)
    await call(hass, "turn_off", entity_id="light.ct_lamp")
    await call(hass, "turn_on", entity_id="light.ct_lamp")
    assert last(lights, "light.ct_lamp") == {"brightness": 204}


async def test_light_profiles_csv_still_fills_the_rest(hass, lights):
    profiles = hass.data["light_profiles"]
    profiles.data["light.ct_lamp.default"] = Profile("light.ct_lamp.default", None, None, 10, 2)
    profiles.data["light.unconfigured.default"] = Profile(
        "light.unconfigured.default", None, None, 50, None
    )
    await call(hass, "turn_on", entity_id="light.ct_lamp")
    assert last(lights, "light.ct_lamp") == {
        "brightness": 255,
        "color_temp_kelvin": 6500,
        "transition": 2,
    }
    await call(hass, "turn_on", entity_id="light.unconfigured")
    assert last(lights, "light.unconfigured") == {"brightness": 50}


async def test_reload_picks_up_changes(hass, lights):
    new = {"light_defaults": {"light.ct_lamp": {"brightness": 50, "temperature": 2700}}}
    with patch("homeassistant.config.async_hass_config_yaml", return_value=new):
        await hass.services.async_call("light_defaults", "reload", blocking=True)
    await call(hass, "turn_on", entity_id="light.ct_lamp")
    assert last(lights, "light.ct_lamp") == {"brightness": 128, "color_temp_kelvin": 2700}
    await call(hass, "turn_on", entity_id="light.dimmer")
    assert last(lights, "light.dimmer") == {}


async def test_reload_reads_map_from_included_file(hass, lights, tmp_path, monkeypatch):
    monkeypatch.setattr(hass.config, "config_dir", str(tmp_path))
    (tmp_path / "configuration.yaml").write_text(
        "light_defaults: !include light_defaults.yaml\n"
    )
    (tmp_path / "light_defaults.yaml").write_text(
        "light.ct_lamp:\n  brightness: 50\n  temperature: 2700\n"
    )
    await hass.services.async_call("light_defaults", "reload", blocking=True)
    await call(hass, "turn_on", entity_id="light.ct_lamp")
    assert last(lights, "light.ct_lamp") == {"brightness": 128, "color_temp_kelvin": 2700}

    # Edits to the included file show up on the next reload.
    await call(hass, "turn_off", entity_id="light.ct_lamp")
    (tmp_path / "light_defaults.yaml").write_text("light.ct_lamp:\n  brightness: 20\n")
    await hass.services.async_call("light_defaults", "reload", blocking=True)
    await call(hass, "turn_on", entity_id="light.ct_lamp")
    assert last(lights, "light.ct_lamp") == {"brightness": 51}


async def test_reload_with_bad_config_keeps_current_map(hass, lights):
    bad = {"light_defaults": {"light.ct_lamp": {"brightness": 150}}}
    with patch("homeassistant.config.async_hass_config_yaml", return_value=bad):
        await hass.services.async_call("light_defaults", "reload", blocking=True)
    await call(hass, "turn_on", entity_id="light.ct_lamp")
    assert last(lights, "light.ct_lamp") == {"brightness": 255, "color_temp_kelvin": 6500}


@pytest.mark.parametrize(
    "bad_map",
    [
        {"switch.not_a_light": {"brightness": 50}},
        {"light.ct_lamp": {"temp": 3000}},
        {"light.ct_lamp": {"brightness": 0}},
        {"light.ct_lamp": {"temperature": 500}},
        {"light.ct_lamp": {"brightness": 50, "reset_when_on": "sometimes"}},
    ],
)
async def test_rejects_bad_config(hass, bad_map):
    setup_test_component_platform(hass, "light", make_lights())
    config = {"light": [{"platform": "test"}], "light_defaults": bad_map}
    assert not await async_setup_component(hass, "light_defaults", config)


async def test_missing_hook_fails_cleanly(hass, caplog):
    setup_test_component_platform(hass, "light", make_lights())
    assert await async_setup_component(hass, "light", {"light": [{"platform": "test"}]})
    await hass.async_block_till_done()
    hass.data.pop("light_profiles")
    assert not await async_setup_component(hass, "light_defaults", {"light_defaults": {}})
    assert "light_defaults is inactive" in caplog.text


async def test_a_failure_never_breaks_turn_on(hass, lights, caplog):
    with patch(
        "custom_components.light_defaults._fill_defaults", side_effect=RuntimeError("boom")
    ):
        await call(hass, "turn_on", entity_id="light.ct_lamp")
    assert last(lights, "light.ct_lamp") == {}
    assert hass.states.get("light.ct_lamp").state == "on"
    assert "Couldn't apply defaults to light.ct_lamp" in caplog.text


async def test_reload_action_is_described(hass, lights):
    # Same loader HA uses to build action descriptions for the UI.
    integration = await async_get_integration(hass, "light_defaults")
    services = await hass.async_add_executor_job(_load_services_file, integration)
    assert services["reload"]["name"] == "Reload"
    assert hass.services.has_service("light_defaults", "reload")


async def test_brand_icon_is_picked_up(hass, lights):
    integration = await async_get_integration(hass, "light_defaults")
    assert integration.has_branding
