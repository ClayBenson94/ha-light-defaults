"""Check the actual payload sent to a Zigbee2MQTT-style MQTT light."""

import json

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_fire_mqtt_message

# Roughly what Zigbee2MQTT publishes for a Hue White Ambiance bulb.
DISCOVERY = {
    "schema": "json",
    "name": "Office Lamp",
    "unique_id": "0x0017880102abcdef_light_zigbee2mqtt",
    "command_topic": "zigbee2mqtt/Office Lamp/set",
    "state_topic": "zigbee2mqtt/Office Lamp",
    "brightness": True,
    "brightness_scale": 254,
    "supported_color_modes": ["color_temp"],
    "min_mireds": 153,
    "max_mireds": 454,
    "effect": True,
    "effect_list": ["candle", "fireplace"],
}

# A Zigbee2MQTT 2.10+ group with that bulb in it; `group` lists its members.
GROUP_DISCOVERY = {
    "schema": "json",
    "name": "Overhead",
    "unique_id": "1_light_zigbee2mqtt",
    "command_topic": "zigbee2mqtt/Overhead/set",
    "state_topic": "zigbee2mqtt/Overhead",
    "brightness": True,
    "brightness_scale": 254,
    "supported_color_modes": ["color_temp"],
    "min_mireds": 153,
    "max_mireds": 454,
    "group": [DISCOVERY["unique_id"]],
}


@pytest.fixture
def expected_lingering_timers() -> bool:
    """The mocked MQTT client leaves its housekeeping timer behind at teardown."""
    return True


async def _setup(hass: HomeAssistant, mqtt_mock, yaml_map=None) -> None:
    if yaml_map is None:
        yaml_map = {"light.office_lamp": {"brightness": 100, "temperature": 6500}}
    assert await async_setup_component(hass, "light_defaults", {"light_defaults": yaml_map})
    async_fire_mqtt_message(
        hass,
        "homeassistant/light/0x0017880102abcdef/light/config",
        json.dumps(DISCOVERY),
    )
    async_fire_mqtt_message(hass, "homeassistant/light/1/light/config", json.dumps(GROUP_DISCOVERY))
    await hass.async_block_till_done()
    report(hass, {"state": "OFF", "brightness": 80, "color_temp": 370, "color_mode": "color_temp"})
    mqtt_mock.async_publish.reset_mock()


def report(hass: HomeAssistant, state: dict) -> None:
    async_fire_mqtt_message(hass, "zigbee2mqtt/Office Lamp", json.dumps(state))


async def sent(hass: HomeAssistant, mqtt_mock, **data) -> dict:
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": "light.office_lamp", **data}, blocking=True
    )
    topic, payload = mqtt_mock.async_publish.call_args[0][:2]
    assert topic == "zigbee2mqtt/Office Lamp/set"
    mqtt_mock.async_publish.reset_mock()
    return json.loads(payload)


async def test_bare_turn_on_sends_defaults_in_one_command(hass, mqtt_mock):
    await _setup(hass, mqtt_mock)
    assert hass.states.get("light.office_lamp").state == "off"
    assert await sent(hass, mqtt_mock) == {"state": "ON", "brightness": 254, "color_temp": 153}


async def test_partial_override_and_already_on(hass, mqtt_mock):
    await _setup(hass, mqtt_mock)
    payload = await sent(hass, mqtt_mock, brightness_pct=40)
    assert payload["color_temp"] == 153 and abs(payload["brightness"] - 102) <= 1

    # Bulb reports on; a repeat bare turn_on must not reset it.
    report(hass, {"state": "ON", "brightness": 102, "color_temp": 153, "color_mode": "color_temp"})
    await hass.async_block_till_done()
    assert await sent(hass, mqtt_mock) == {"state": "ON"}


async def test_effect_passthrough(hass, mqtt_mock):
    await _setup(hass, mqtt_mock)
    assert await sent(hass, mqtt_mock, effect="candle") == {"state": "ON", "effect": "candle"}


async def test_zigbee2mqtt_group_covers_its_lights(hass, mqtt_mock):
    await _setup(hass, mqtt_mock, {"light.overhead": {"brightness": 50, "temperature": 2700}})
    assert hass.states.get("light.overhead").attributes["group_entities"] == ["light.office_lamp"]
    payload = await sent(hass, mqtt_mock)
    assert payload["state"] == "ON" and payload["color_temp"] == 370
    assert abs(payload["brightness"] - 127) <= 1


async def test_zigbee2mqtt_group_gets_the_defaults_for_all_lights(hass, mqtt_mock):
    # Unlike an HA light group it sends one command, so it fills them in itself.
    await _setup(hass, mqtt_mock, {"all": {"brightness": 50}})
    async_fire_mqtt_message(hass, "zigbee2mqtt/Overhead", json.dumps({"state": "OFF"}))
    await hass.async_block_till_done()
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": "light.overhead"}, blocking=True
    )
    topic, payload = mqtt_mock.async_publish.call_args[0][:2]
    assert topic == "zigbee2mqtt/Overhead/set"
    payload = json.loads(payload)
    assert payload["state"] == "ON" and abs(payload["brightness"] - 127) <= 1
    assert "color_temp" not in payload
