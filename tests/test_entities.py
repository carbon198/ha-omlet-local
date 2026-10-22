"""Tests for MQTT-backed Omlet entities."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import Platform
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations
from homeassistant.loader import async_get_integration
from homeassistant.components.light import ColorMode

from custom_components.omlet_coop.const import ACTION_ROOT, DOMAIN, TOPIC_ROOT
from custom_components.omlet_coop.light import OmletLight
from custom_components.omlet_coop.select import OmletDoorModeSelect

from .conftest import DEVICE_ID


def _entity_id(hass, platform, key):
    """Look up an Omlet entity by its unique ID suffix."""
    registry = er.async_get(hass)
    return registry.async_get_entity_id(
        platform, DOMAIN, f"{DEVICE_ID}_{key}"
    )


def _status_topic(suffix):
    return f"{TOPIC_ROOT.format(device_id=DEVICE_ID)}/{suffix}"


def _action_topic(suffix):
    return f"{ACTION_ROOT.format(device_id=DEVICE_ID)}/{suffix}"


def _door_config_topic(setting):
    return f"device/{DEVICE_ID}/configuration/door/{setting}"


async def _send(hass, mqtt_messages, topic, payload):
    mqtt_messages(topic, payload)
    await hass.async_block_till_done()


async def test_setup_registers_entities_and_unloads(
    hass, omlet_entry, mqtt_messages
):
    """Entry setup creates platform entities and unload cleans runtime data."""
    assert hass.data[DOMAIN][omlet_entry.entry_id].device_id == DEVICE_ID
    assert _entity_id(hass, Platform.COVER, "door") is not None
    assert _entity_id(hass, Platform.LIGHT, "light") is not None
    assert _entity_id(hass, Platform.SENSOR, "battery") is not None

    assert await hass.config_entries.async_unload(omlet_entry.entry_id)
    assert omlet_entry.entry_id not in hass.data[DOMAIN]


async def test_entity_translations_icons_and_private_ssid_default(
    hass, omlet_entry
):
    """Entities use localized names, semantic icons, and opt-in SSID exposure."""
    registry = er.async_get(hass)
    cover_id = _entity_id(hass, Platform.COVER, "door")
    light_id = _entity_id(hass, Platform.LIGHT, "light")
    battery_id = _entity_id(hass, Platform.SENSOR, "battery")
    ssid_id = _entity_id(hass, Platform.SENSOR, "wifi_ssid")
    integration = await async_get_integration(hass, DOMAIN)
    assert integration.has_translations
    translations = await async_get_translations(
        hass, "en", "entity", {DOMAIN}
    )

    expected_translation_keys = {
        (
            f"component.{DOMAIN}.entity.{entity.domain}."
            f"{entity.translation_key}.name"
        )
        for entity in registry.entities.values()
        if entity.platform == DOMAIN and entity.translation_key is not None
    }
    assert (
        translations.get("component.omlet_coop.entity.cover.door.name")
        == "Door"
    ), (integration.file_path, integration._top_level_files, translations)
    assert expected_translation_keys <= translations.keys()
    assert registry.async_get(cover_id).translation_key == "door"
    assert registry.async_get(light_id).translation_key == "light"
    assert "Door" in hass.states.get(cover_id).attributes["friendly_name"]
    assert hass.states.get(light_id).attributes["icon"] == "mdi:lightbulb"
    assert hass.states.get(battery_id) is not None
    assert hass.states.get(ssid_id) is None
    assert (
        registry.async_get(ssid_id).disabled_by
        is er.RegistryEntryDisabler.INTEGRATION
    )


async def test_unload_failure_preserves_runtime_data(
    hass, omlet_entry, mqtt_messages
):
    """Failed platform unload leaves the config entry runtime data intact."""
    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        new_callable=AsyncMock,
        return_value=False,
    ):
        assert not await hass.config_entries.async_unload(omlet_entry.entry_id)
    assert omlet_entry.entry_id in hass.data[DOMAIN]
    hass.data[DOMAIN][omlet_entry.entry_id].async_unload()


async def test_cover_states_and_pending_actions(hass, omlet_entry, mqtt_messages):
    """Cover state follows device reports and pending follows action clearing."""
    cover_id = _entity_id(hass, Platform.COVER, "door")

    await _send(hass, mqtt_messages, _status_topic("door/state"), "opening")
    assert hass.states.get(cover_id).state == "opening"
    await _send(hass, mqtt_messages, _status_topic("door/state"), "closing")
    assert hass.states.get(cover_id).state == "closing"
    await _send(hass, mqtt_messages, _status_topic("door/state"), "open")
    assert hass.states.get(cover_id).state == "open"
    await _send(hass, mqtt_messages, _status_topic("door/state"), "closed")
    assert hass.states.get(cover_id).state == "closed"
    await _send(hass, mqtt_messages, _status_topic("door/state"), "unexpected")
    assert hass.states.get(cover_id).state == "closed"
    await _send(hass, mqtt_messages, _status_topic("door/state"), "")
    assert hass.states.get(cover_id).state == "closed"

    await _send(hass, mqtt_messages, _action_topic("door/state"), "open")
    assert hass.states.get(cover_id).attributes["open_pending"] is True
    assert hass.states.get(cover_id).attributes["close_pending"] is False
    await _send(hass, mqtt_messages, _action_topic("door/state"), "close")
    assert hass.states.get(cover_id).attributes["close_pending"] is True
    await _send(hass, mqtt_messages, _action_topic("door/state"), "stop")
    assert hass.states.get(cover_id).attributes["stop_pending"] is True
    await _send(hass, mqtt_messages, _action_topic("door/state"), "unknown")
    assert hass.states.get(cover_id).attributes["stop_pending"] is True
    await _send(hass, mqtt_messages, _action_topic("door/state"), "")
    assert hass.states.get(cover_id).attributes["stop_pending"] is False


async def test_cover_commands_publish_stay_alive_and_retained_actions(
    hass, omlet_entry, mqtt_messages
):
    """Cover commands publish the configured wake time and retained action."""
    cover_id = _entity_id(hass, Platform.COVER, "door")
    with patch(
        "custom_components.omlet_coop.commands.mqtt.async_publish",
        new_callable=AsyncMock,
    ) as publish:
        for service in ("open_cover", "close_cover", "stop_cover"):
            await hass.services.async_call(
                Platform.COVER,
                service,
                {"entity_id": cover_id},
                blocking=True,
            )

    published = [
        (call.args[1], call.args[2], call.kwargs)
        for call in publish.await_args_list
    ]
    assert [item[:2] for item in published] == [
        (_action_topic("stayAlive"), "60"),
        (_action_topic("door/state"), "open"),
        (_action_topic("stayAlive"), "60"),
        (_action_topic("door/state"), "close"),
        (_action_topic("stayAlive"), "60"),
        (_action_topic("door/state"), "stop"),
    ]
    assert all(item[2] == {"qos": 2, "retain": True} for item in published)


async def test_cover_command_publish_failure_rolls_back_pending(
    hass, omlet_entry, mqtt_messages
):
    """A failed cover publish restores the prior pending state."""
    cover_id = _entity_id(hass, Platform.COVER, "door")
    with patch(
        "custom_components.omlet_coop.commands.mqtt.async_publish",
        new_callable=AsyncMock,
        side_effect=HomeAssistantError("publish failed"),
    ):
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                Platform.COVER,
                "open_cover",
                {"entity_id": cover_id},
                blocking=True,
            )

    assert hass.states.get(cover_id).attributes["open_pending"] is False


async def test_light_state_fault_and_pending(hass, omlet_entry, mqtt_messages):
    """Light feedback, action clearing, and fault reports are handled."""
    light_id = _entity_id(hass, Platform.LIGHT, "light")
    fault_id = _entity_id(hass, Platform.BINARY_SENSOR, "light_fault")

    await _send(hass, mqtt_messages, _status_topic("light/state"), "on")
    assert hass.states.get(light_id).state == "on"
    await _send(hass, mqtt_messages, _status_topic("light/state"), "off")
    assert hass.states.get(light_id).state == "off"
    await _send(hass, mqtt_messages, _status_topic("light/state"), "invalid")
    assert hass.states.get(light_id).state == "off"
    await _send(hass, mqtt_messages, _status_topic("light/state"), "")
    assert hass.states.get(light_id).state == "off"
    await _send(hass, mqtt_messages, _status_topic("light/fault"), "off")
    assert hass.states.get(fault_id).state == "off"
    await _send(hass, mqtt_messages, _status_topic("light/fault"), "overheat")
    assert hass.states.get(fault_id).state == "on"
    await _send(hass, mqtt_messages, _status_topic("light/fault"), "")
    assert hass.states.get(fault_id).state == "on"

    await _send(hass, mqtt_messages, _action_topic("light/state"), "on")
    assert hass.states.get(light_id).attributes["pending"] is True
    await _send(hass, mqtt_messages, _action_topic("light/state"), "")
    assert hass.states.get(light_id).attributes["pending"] is False
    await _send(hass, mqtt_messages, _action_topic("light/state"), "invalid")
    assert hass.states.get(light_id).attributes["pending"] is False

    device_data = hass.data[DOMAIN][omlet_entry.entry_id]
    light = OmletLight(device_data)
    assert light.color_mode is None
    light._attr_is_on = True
    assert light.color_mode is ColorMode.ONOFF


async def test_light_commands_and_publish_failure(hass, omlet_entry, mqtt_messages):
    """Light commands do not change reported state until feedback arrives."""
    light_id = _entity_id(hass, Platform.LIGHT, "light")
    with patch(
        "custom_components.omlet_coop.commands.mqtt.async_publish",
        new_callable=AsyncMock,
    ) as publish:
        await hass.services.async_call(
            Platform.LIGHT,
            "turn_on",
            {"entity_id": light_id},
            blocking=True,
        )

    assert hass.states.get(light_id).state == "unknown"
    assert hass.states.get(light_id).attributes["pending"] is True
    assert [call.args[1:3] for call in publish.await_args_list] == [
        (_action_topic("stayAlive"), "60"),
        (_action_topic("light/state"), "on"),
    ]

    with patch(
        "custom_components.omlet_coop.commands.mqtt.async_publish",
        new_callable=AsyncMock,
        side_effect=HomeAssistantError("publish failed"),
    ):
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                Platform.LIGHT,
                "turn_off",
                {"entity_id": light_id},
                blocking=True,
            )
    assert hass.states.get(light_id).attributes["pending"] is True


async def test_binary_sensor_values_and_door_fault(
    hass, omlet_entry, mqtt_messages
):
    """Connectivity, recovery, and fault sensors parse known payloads."""
    connected_id = _entity_id(hass, Platform.BINARY_SENSOR, "connected")
    recovery_id = _entity_id(
        hass, Platform.BINARY_SENSOR, "recovery_app_running"
    )
    door_fault_id = _entity_id(hass, Platform.BINARY_SENSOR, "door_fault")

    await _send(hass, mqtt_messages, _status_topic("connected"), "true")
    assert hass.states.get(connected_id).state == "on"
    await _send(hass, mqtt_messages, _status_topic("connected"), "0")
    assert hass.states.get(connected_id).state == "off"
    await _send(hass, mqtt_messages, _status_topic("connected"), "")
    assert hass.states.get(connected_id).state == "off"
    await _send(hass, mqtt_messages, _status_topic("connected"), "invalid")
    assert hass.states.get(connected_id).state == "off"
    await _send(
        hass, mqtt_messages, _status_topic("recoveryAppRunning"), "true"
    )
    assert hass.states.get(recovery_id).state == "on"
    await _send(
        hass, mqtt_messages, _status_topic("recoveryAppRunning"), "false"
    )
    assert hass.states.get(recovery_id).state == "off"
    await _send(hass, mqtt_messages, _status_topic("door/fault"), "none")
    assert hass.states.get(door_fault_id).state == "off"
    await _send(hass, mqtt_messages, _status_topic("door/fault"), "motor_stall")
    assert hass.states.get(door_fault_id).state == "on"
    await _send(hass, mqtt_messages, _status_topic("door/fault"), "")
    assert hass.states.get(door_fault_id).state == "on"


async def test_numeric_and_text_sensors(hass, omlet_entry, mqtt_messages):
    """Sensor entities parse valid values and retain state on invalid clears."""
    battery_id = _entity_id(hass, Platform.SENSOR, "battery")
    uptime_id = _entity_id(hass, Platform.SENSOR, "uptime")
    source_id = _entity_id(hass, Platform.SENSOR, "power_source")

    await _send(hass, mqtt_messages, _status_topic("batteryLevel"), "87.0")
    assert hass.states.get(battery_id).state == "87"
    await _send(hass, mqtt_messages, _status_topic("batteryLevel"), "73.5")
    assert hass.states.get(battery_id).state == "73.5"
    await _send(hass, mqtt_messages, _status_topic("batteryLevel"), "bad")
    assert hass.states.get(battery_id).state == "73.5"
    await _send(hass, mqtt_messages, _status_topic("batteryLevel"), "")
    assert hass.states.get(battery_id).state == "73.5"
    await _send(hass, mqtt_messages, _status_topic("uptime"), "bad")
    assert hass.states.get(uptime_id).state == "unknown"
    await _send(hass, mqtt_messages, _status_topic("uptime"), "12")
    assert hass.states.get(uptime_id).state == "12"
    await _send(hass, mqtt_messages, _status_topic("powerSource"), "battery")
    assert hass.states.get(source_id).state == "battery"
    await _send(hass, mqtt_messages, _status_topic("powerSource"), "")
    assert hass.states.get(source_id).state == "battery"


async def test_door_mode_select_tracks_both_reports(
    hass, omlet_entry, mqtt_messages
):
    """Door mode is unknown until both device settings agree."""
    select_id = _entity_id(hass, Platform.SELECT, "door_mode")
    await _send(
        hass, mqtt_messages, _door_config_topic("openMode"), "time"
    )
    assert hass.states.get(select_id).state == "unknown"
    await _send(
        hass, mqtt_messages, _door_config_topic("closeMode"), "time"
    )
    assert hass.states.get(select_id).state == "time"
    await _send(
        hass, mqtt_messages, _door_config_topic("openMode"), "manual"
    )
    assert hass.states.get(select_id).state == "unknown"
    await _send(
        hass, mqtt_messages, _door_config_topic("openMode"), "invalid"
    )
    assert hass.states.get(select_id).state == "unknown"


async def test_door_mode_select_writes_both_settings(
    hass, omlet_entry, mqtt_messages
):
    """Selecting a mode writes the same retained value to both topics."""
    select_id = _entity_id(hass, Platform.SELECT, "door_mode")
    with patch(
        "custom_components.omlet_coop.commands.mqtt.async_publish",
        new_callable=AsyncMock,
    ) as publish:
        await hass.services.async_call(
            Platform.SELECT,
            "select_option",
            {"entity_id": select_id, "option": "light"},
            blocking=True,
        )

    assert [call.args[1:3] for call in publish.await_args_list] == [
        (_action_topic("stayAlive"), "60"),
        (_door_config_topic("openMode"), "light"),
        (_door_config_topic("closeMode"), "light"),
    ]


async def test_door_mode_select_rejects_invalid_option_and_empty_report(
    hass, omlet_entry, mqtt_messages
):
    """Invalid selections fail and empty reports preserve the current value."""
    select_id = _entity_id(hass, Platform.SELECT, "door_mode")
    await _send(
        hass,
        mqtt_messages,
        _door_config_topic("openMode"),
        "manual",
    )
    await _send(
        hass,
        mqtt_messages,
        _door_config_topic("closeMode"),
        "manual",
    )
    await _send(
        hass,
        mqtt_messages,
        _door_config_topic("openMode"),
        "",
    )
    assert hass.states.get(select_id).state == "manual"

    device_data = hass.data[DOMAIN][omlet_entry.entry_id]
    config_root = f"device/{DEVICE_ID}/configuration/door"
    entity = OmletDoorModeSelect(device_data, config_root)
    with pytest.raises(ValueError, match="Unsupported door mode"):
        await entity.async_select_option("unsupported")
