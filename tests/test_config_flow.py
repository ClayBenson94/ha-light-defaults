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


async def add_entry(
    hass: HomeAssistant, *entity_ids: str, unique_id: str | None = None, **values
) -> MockConfigEntry:
    """An entry for a set of lights, or with unique_id "all" or "exclude", that one."""
    options = dict(values)
    if unique_id != "all":
        options["entities"] = list(entity_ids)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=", ".join(entity_ids) or unique_id,
        data={},
        options=options,
        unique_id=unique_id,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def start_flow(hass: HomeAssistant, step: str = "lights"):
    """Open the Add entry menu and pick one of its forms."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": step}
    )


async def turn_on(hass: HomeAssistant, lights, entity_id: str):
    """Turn a light on from off and return what it received."""
    await hass.services.async_call("light", "turn_off", {"entity_id": entity_id}, blocking=True)
    await hass.services.async_call("light", "turn_on", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done()
    return lights[entity_id].calls[-1]


def not_offered(result) -> list[str]:
    """The lights a form's picker leaves out."""
    schema = result["data_schema"].schema
    picker = next(value for key, value in schema.items() if key == "entities")
    return picker.config.get("exclude_entities", [])


def suggested(result) -> dict:
    """The values a form opens with."""
    return {
        str(key): key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key.description and "suggested_value" in key.description
    }


async def test_add_entry_offers_three_kinds(hass, lights):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["lights", "all", "exclude"]


async def test_add_lights_in_the_ui(hass, lights):
    result = await start_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "lights"
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


async def test_add_needs_a_value_or_no_default(hass, lights):
    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"entities": ["light.ct_lamp"], "no_default": []}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_defaults"}


async def test_no_default_for_sets_none(hass, lights):
    await add_entry(hass, unique_id="all", brightness=50, temperature=4000)
    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"entities": ["light.ct_lamp"], "temperature": 2700.0, "no_default": ["brightness"]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {
        "entities": ["light.ct_lamp"],
        "temperature": 2700,
        "brightness": None,
    }
    await hass.async_block_till_done()
    assert await turn_on(hass, lights, "light.ct_lamp") == {"color_temp_kelvin": 2700}
    assert await turn_on(hass, lights, "light.color_bulb") == {
        "brightness": 128,
        "color_temp_kelvin": 4000,
    }

    # No default for anything is a set of lights left alone.
    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"entities": ["light.color_bulb"], "no_default": ["brightness", "temperature"]},
    )
    assert result["options"] == {
        "entities": ["light.color_bulb"],
        "brightness": None,
        "temperature": None,
    }
    await hass.async_block_till_done()
    assert await turn_on(hass, lights, "light.color_bulb") == {}


async def test_no_default_for_overrides_the_value(hass, lights):
    await add_entry(hass, unique_id="all", brightness=50)
    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"entities": ["light.ct_lamp"], "brightness": 80.0, "no_default": ["brightness"]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {"entities": ["light.ct_lamp"], "brightness": None}
    await hass.async_block_till_done()
    assert await turn_on(hass, lights, "light.ct_lamp") == {}


async def test_light_with_an_entry_is_not_offered_again(hass, lights):
    await add_entry(hass, "light.ct_lamp", brightness=50)
    result = await start_flow(hass)
    assert not_offered(result) == ["light.ct_lamp"]
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
    assert not_offered(result) == ["light.ct_lamp"]


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
    assert not_offered(result) == ["light.ct_lamp"]


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


async def test_options_show_none_under_no_default(hass, lights):
    entry = await add_entry(hass, "light.ct_lamp", brightness=None, temperature=2700)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert suggested(result) == {
        "entities": ["light.ct_lamp"],
        "temperature": 2700,
        "no_default": ["brightness"],
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"entities": ["light.ct_lamp"], "brightness": 40.0, "no_default": []}
    )
    await hass.async_block_till_done()
    assert entry.options == {"entities": ["light.ct_lamp"], "brightness": 40}

    # Ticking the box again is enough; the slider can keep its value.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"entities": ["light.ct_lamp"], "brightness": 40.0, "no_default": ["brightness"]},
    )
    await hass.async_block_till_done()
    assert entry.options == {"entities": ["light.ct_lamp"], "brightness": None}


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


async def test_add_defaults_for_all_lights(hass, lights):
    await add_entry(hass, "light.ct_lamp", temperature=6500)
    result = await start_flow(hass, "all")
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"brightness": 50.0})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "All lights"
    assert result["result"].unique_id == "all"
    assert result["options"] == {"brightness": 50}
    await hass.async_block_till_done()
    assert await turn_on(hass, lights, "light.unconfigured") == {"brightness": 128}
    assert await turn_on(hass, lights, "light.ct_lamp") == {
        "brightness": 128,
        "color_temp_kelvin": 6500,
    }

    # There's only one.
    result = await start_flow(hass, "all")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_all_lights_needs_a_value(hass, lights):
    result = await start_flow(hass, "all")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_values"}


async def test_change_the_defaults_for_all_lights(hass, lights):
    entry = await add_entry(hass, unique_id="all", brightness=50)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "all"
    assert suggested(result) == {"brightness": 50}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"temperature": 3000.0}
    )
    await hass.async_block_till_done()
    assert entry.options == {"temperature": 3000}
    assert await turn_on(hass, lights, "light.unconfigured") == {"color_temp_kelvin": 3000}

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert await turn_on(hass, lights, "light.unconfigured") == {}
    assert hass.data[DOMAIN].entries == {}


async def test_add_lights_to_exclude(hass, lights):
    await add_entry(hass, unique_id="all", brightness=50)
    await add_entry(hass, "light.dimmer", brightness=80)
    result = await start_flow(hass, "exclude")
    assert not_offered(result) == ["light.dimmer"]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"entities": ["light.overhead"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Excluded lights"
    assert result["result"].unique_id == "exclude"
    assert result["options"] == {"entities": ["light.overhead"]}
    await hass.async_block_till_done()
    # Excluding a group excludes the lights in it.
    assert await turn_on(hass, lights, "light.ct_lamp") == {}
    assert await turn_on(hass, lights, "light.color_bulb") == {}
    assert await turn_on(hass, lights, "light.unconfigured") == {"brightness": 128}

    # Excluded lights aren't offered for defaults, and there's one exclude entry.
    result = await start_flow(hass)
    assert not_offered(result) == ["light.dimmer", "light.overhead"]
    result = await start_flow(hass, "exclude")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_exclude_needs_a_light(hass, lights):
    result = await start_flow(hass, "exclude")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"entities": []})
    assert result["errors"] == {"entities": "no_lights"}


async def test_change_the_excluded_lights(hass, lights):
    await add_entry(hass, unique_id="all", brightness=50)
    entry = await add_entry(hass, "light.ct_lamp", unique_id="exclude")
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "exclude"
    assert suggested(result) == {"entities": ["light.ct_lamp"]}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"entities": ["light.dimmer"]}
    )
    await hass.async_block_till_done()
    assert entry.options == {"entities": ["light.dimmer"]}
    assert await turn_on(hass, lights, "light.ct_lamp") == {"brightness": 128}
    assert await turn_on(hass, lights, "light.dimmer") == {}

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert await turn_on(hass, lights, "light.dimmer") == {"brightness": 128}


async def test_excluded_lights_follow_an_entity_id_change(hass, lights):
    await add_entry(hass, unique_id="all", brightness=50)
    entry = await add_entry(hass, "light.ct_lamp", unique_id="exclude")
    er.async_get(hass).async_update_entity("light.ct_lamp", new_entity_id="light.desk_lamp")
    await hass.async_block_till_done()
    assert entry.options == {"entities": ["light.desk_lamp"]}
    lights["light.desk_lamp"] = lights.pop("light.ct_lamp")
    assert await turn_on(hass, lights, "light.desk_lamp") == {}


async def group_on(hass: HomeAssistant) -> None:
    await hass.services.async_call("light", "turn_on", {"entity_id": "light.overhead"}, blocking=True)
    await hass.async_block_till_done()


async def test_a_group_covers_its_lights(hass, lights):
    await add_entry(hass, "light.overhead", brightness=50, temperature=2700)
    expected = {"brightness": 128, "color_temp_kelvin": 2700}
    # From off, the group passes the turn-on on, and each light that's off
    # gets the group's defaults.
    await group_on(hass)
    assert lights["light.ct_lamp"].calls[-1] == expected
    assert lights["light.color_bulb"].calls[-1] == expected

    # Same with one light on, which makes the group on.
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

    # Also when the group is turned on.
    await hass.services.async_call("light", "turn_off", {"entity_id": "light.overhead"}, blocking=True)
    await group_on(hass)
    assert lights["light.ct_lamp"].calls[-1] == {"brightness": 51}
    assert lights["light.color_bulb"].calls[-1] == {"brightness": 128}

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


async def test_ui_all_lights_replace_the_yaml_ones(hass, lights, caplog):
    yaml_map = {"all": {"brightness": 80, "temperature": 3000}}
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: yaml_map})
    assert await turn_on(hass, lights, "light.unconfigured") == {
        "brightness": 204,
        "color_temp_kelvin": 3000,
    }
    await add_entry(hass, unique_id="all", brightness=50)
    assert "using the UI values: all" in caplog.text
    # As a whole, like a light's entry: no temperature from YAML.
    assert await turn_on(hass, lights, "light.unconfigured") == {"brightness": 128}


async def test_an_exclusion_in_either_place_beats_an_entry(hass, lights, caplog):
    yaml_map = {"light.ct_lamp": {"brightness": 80}, "exclude": ["light.dimmer"]}
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: yaml_map})
    await add_entry(hass, "light.ct_lamp", unique_id="exclude")
    await add_entry(hass, "light.dimmer", brightness=50)
    assert "Excluded, so their defaults are ignored: light.ct_lamp" in caplog.text
    assert "Excluded, so their defaults are ignored: light.dimmer" in caplog.text
    assert await turn_on(hass, lights, "light.ct_lamp") == {}
    assert await turn_on(hass, lights, "light.dimmer") == {}


async def test_translations_cover_the_flows(hass, lights):
    strings = json.loads(TRANSLATIONS.read_text())

    def labels(flow: str, result) -> set[str]:
        step = strings[flow]["step"][result["step_id"]]
        assert set(step.get("data_description", {})) <= set(step["data"])
        return set(step["data"])

    def fields(result) -> set[str]:
        return {str(key) for key in result["data_schema"].schema}

    menu = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert list(strings["config"]["step"]["user"]["menu_options"]) == menu["menu_options"]
    for step in menu["menu_options"]:
        result = await start_flow(hass, step)
        assert labels("config", result) == fields(result)
        hass.config_entries.flow.async_abort(result["flow_id"])

    for entry in (
        await add_entry(hass, "light.ct_lamp", brightness=50),
        await add_entry(hass, unique_id="all", brightness=50),
        await add_entry(hass, "light.dimmer", unique_id="exclude"),
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert labels("options", result) == fields(result)

    errors = {"no_lights", "already_configured", "no_defaults", "no_values"}
    for flow in ("config", "options"):
        assert set(strings[flow]["error"]) == errors
    assert set(strings["config"]["abort"]) == {"already_configured", "already_in_progress"}
    assert set(strings["selector"]["no_default"]["options"]) == {"brightness", "temperature"}
