"""Lights set up in the UI: config flow, options flow and config entries."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    setup_test_component_platform,
)

from .recording_light import make_lights

DOMAIN = "light_defaults"
TRANSLATIONS = Path(__file__).parents[1] / "custom_components/light_defaults/translations/en.json"


@pytest.fixture
async def lights(hass: HomeAssistant):
    entities = make_lights()
    setup_test_component_platform(hass, "light", entities)
    config = {
        "light": [
            {"platform": "test"},
            {
                "platform": "group",
                "name": "Overhead",
                "entities": ["light.ct_lamp", "light.color_bulb"],
            },
        ]
    }
    assert await async_setup_component(hass, "light", config)
    await hass.async_block_till_done()
    return {light.entity_id: light for light in entities}


async def add_entry(hass: HomeAssistant, *entity_ids: str, **defaults) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=", ".join(entity_ids),
        data={},
        options={"entities": list(entity_ids), **defaults},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def start_flow(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})


async def turn_on(hass: HomeAssistant, lights, entity_id: str):
    """Turn a light on from off and return what it received."""
    await hass.services.async_call("light", "turn_off", {"entity_id": entity_id}, blocking=True)
    await hass.services.async_call("light", "turn_on", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done()
    return lights[entity_id].calls[-1]


def excluded(result) -> list[str]:
    """The lights a form's picker leaves out."""
    schema = result["data_schema"].schema
    picker = next(value for key, value in schema.items() if key == "entities")
    return picker.config.get("exclude_entities", [])


async def test_add_lights_in_the_ui(hass, lights):
    result = await start_flow(hass)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "entities": ["light.ct_lamp", "light.dimmer"],
            "brightness": 50.0,
            "temperature": 2700.0,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "CT Lamp, Dimmer"
    assert result["data"] == {}
    assert result["options"] == {
        "entities": ["light.ct_lamp", "light.dimmer"],
        "brightness": 50,
        "temperature": 2700,
    }
    assert type(result["options"]["brightness"]) is int
    assert type(result["options"]["temperature"]) is int
    await hass.async_block_till_done()
    assert await turn_on(hass, lights, "light.ct_lamp") == {
        "brightness": 128,
        "color_temp_kelvin": 2700,
    }
    # Dimmer has no color temperature, so HA drops it.
    assert await turn_on(hass, lights, "light.dimmer") == {"brightness": 128}
    assert await turn_on(hass, lights, "light.unconfigured") == {}


async def test_name_becomes_the_title(hass, lights):
    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"entities": ["light.ct_lamp"], "name": " Office ", "brightness": 50},
    )
    assert result["title"] == "Office"


async def test_add_needs_a_light(hass, lights):
    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"entities": [], "brightness": 50}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"entities": "no_lights"}


async def test_add_needs_brightness_or_temperature(hass, lights):
    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"entities": ["light.ct_lamp"]}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_defaults"}


async def test_light_with_an_entry_is_not_offered_again(hass, lights):
    await add_entry(hass, "light.ct_lamp", brightness=50)
    result = await start_flow(hass)
    assert excluded(result) == ["light.ct_lamp"]
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"entities": ["light.dimmer", "light.ct_lamp"], "brightness": 80},
        )


async def test_same_light_from_two_open_forms_is_refused(hass, lights):
    first = await start_flow(hass)
    second = await start_flow(hass)
    await hass.config_entries.flow.async_configure(
        first["flow_id"], {"entities": ["light.ct_lamp"], "brightness": 50}
    )
    result = await hass.config_entries.flow.async_configure(
        second["flow_id"],
        {"entities": ["light.dimmer", "light.ct_lamp"], "brightness": 80},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"entities": "already_configured"}
    assert excluded(result) == ["light.ct_lamp"]


async def test_options_change_applies_right_away(hass, lights):
    entry = await add_entry(hass, "light.ct_lamp", brightness=50, temperature=2700)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    # Clearing the temperature field leaves it out of the input.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"entities": ["light.ct_lamp"], "brightness": 20.0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {"entities": ["light.ct_lamp"], "brightness": 20}
    assert await turn_on(hass, lights, "light.ct_lamp") == {"brightness": 51}


async def test_options_change_the_lights(hass, lights):
    entry = await add_entry(hass, "light.ct_lamp", "light.dimmer", brightness=50)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"entities": ["light.dimmer", "light.color_bulb"], "brightness": 50}
    )
    await hass.async_block_till_done()
    assert await turn_on(hass, lights, "light.ct_lamp") == {}
    assert await turn_on(hass, lights, "light.dimmer") == {"brightness": 128}
    assert await turn_on(hass, lights, "light.color_bulb") == {"brightness": 128}


async def test_options_offer_only_the_entrys_own_and_free_lights(hass, lights):
    await add_entry(hass, "light.ct_lamp", brightness=50)
    entry = await add_entry(hass, "light.dimmer", brightness=50)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert excluded(result) == ["light.ct_lamp"]


async def test_options_need_a_light_and_brightness_or_temperature(hass, lights):
    entry = await add_entry(hass, "light.ct_lamp", brightness=50)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"entities": [], "brightness": 50}
    )
    assert result["errors"] == {"entities": "no_lights"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"entities": ["light.ct_lamp"]}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_defaults"}
    assert entry.options == {"entities": ["light.ct_lamp"], "brightness": 50}


async def test_deleting_an_entry_stops_its_defaults(hass, lights):
    entry = await add_entry(hass, "light.ct_lamp", "light.dimmer", brightness=50)
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert await turn_on(hass, lights, "light.ct_lamp") == {}
    assert await turn_on(hass, lights, "light.dimmer") == {}
    assert hass.data[DOMAIN].entries == {}


async def test_entry_follows_an_entity_id_change(hass, lights):
    entry = await add_entry(hass, "light.ct_lamp", "light.dimmer", brightness=50)
    er.async_get(hass).async_update_entity("light.ct_lamp", new_entity_id="light.desk_lamp")
    await hass.async_block_till_done()
    assert entry.options == {"entities": ["light.desk_lamp", "light.dimmer"], "brightness": 50}
    lights["light.desk_lamp"] = lights.pop("light.ct_lamp")
    assert await turn_on(hass, lights, "light.desk_lamp") == {"brightness": 128}
    assert sorted(hass.data[DOMAIN].entries) == ["light.desk_lamp", "light.dimmer"]


async def group_on(hass: HomeAssistant) -> None:
    await hass.services.async_call("light", "turn_on", {"entity_id": "light.overhead"}, blocking=True)
    await hass.async_block_till_done()


async def test_a_group_covers_its_lights(hass, lights):
    await add_entry(hass, "light.overhead", brightness=50, temperature=2700)
    expected = {"brightness": 128, "color_temp_kelvin": 2700}
    # From off, the group fills in its defaults and passes them on.
    await group_on(hass)
    assert lights["light.ct_lamp"].calls[-1] == expected
    assert lights["light.color_bulb"].calls[-1] == expected

    # With one light on the group is on and fills in nothing, so the light
    # that's off gets the group's defaults itself.
    await hass.services.async_call("light", "turn_off", {"entity_id": "light.ct_lamp"}, blocking=True)
    await group_on(hass)
    assert lights["light.ct_lamp"].calls[-1] == expected
    assert lights["light.color_bulb"].calls[-1] == {}

    # So does a light turned on by itself.
    assert await turn_on(hass, lights, "light.color_bulb") == expected
    assert await turn_on(hass, lights, "light.dimmer") == {}


async def test_a_lights_own_entry_beats_its_group(hass, lights):
    await add_entry(hass, "light.overhead", brightness=50)
    entry = await add_entry(hass, "light.ct_lamp", brightness=20)
    assert await turn_on(hass, lights, "light.ct_lamp") == {"brightness": 51}
    assert await turn_on(hass, lights, "light.color_bulb") == {"brightness": 128}

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert await turn_on(hass, lights, "light.ct_lamp") == {"brightness": 128}


async def test_ui_entry_replaces_the_yaml_entry(hass, lights, caplog):
    yaml_map = {
        "light.ct_lamp": {"brightness": 100, "temperature": 6500},
        "light.dimmer": {"brightness": 80},
    }
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: yaml_map})
    await add_entry(hass, "light.ct_lamp", brightness=50)
    assert "using the UI values: light.ct_lamp" in caplog.text
    assert await turn_on(hass, lights, "light.ct_lamp") == {"brightness": 128}
    assert await turn_on(hass, lights, "light.dimmer") == {"brightness": 204}

    # Reloading the YAML leaves UI entries alone.
    with patch("homeassistant.config.async_hass_config_yaml", return_value={DOMAIN: yaml_map}):
        await hass.services.async_call(DOMAIN, "reload", blocking=True)
    assert await turn_on(hass, lights, "light.ct_lamp") == {"brightness": 128}


def test_translations_cover_the_flows():
    strings = json.loads(TRANSLATIONS.read_text())
    config, options = strings["config"], strings["options"]
    assert set(config["step"]["user"]["data"]) == {
        "entities",
        "name",
        "brightness",
        "temperature",
    }
    assert set(options["step"]["init"]["data"]) == {"entities", "brightness", "temperature"}
    for flow in (config, options):
        assert set(flow["error"]) == {"no_lights", "already_configured", "no_defaults"}
