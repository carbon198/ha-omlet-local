"""Tests for Omlet numeric and time configuration entities."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import Platform
from homeassistant.exceptions import HomeAssistantError

from custom_components.omlet_coop.const import ACTION_ROOT, CONFIG_ROOT, DOMAIN
from custom_components.omlet_coop.number import OmletConfigNumber
from custom_components.omlet_coop.time import OmletTimeEntity
from tests.conftest import DEVICE_ID
from tests.test_entities import _entity_id


def _config_topic(suffix):
    return f"{CONFIG_ROOT.format(device_id=DEVICE_ID)}/{suffix}"


def _stay_alive_topic():
    return f"{ACTION_ROOT.format(device_id=DEVICE_ID)}/stayAlive"


async def _send(hass, mqtt_messages, topic, payload):
    mqtt_messages(topic, payload)
    await hass.async_block_till_done()


async def test_numeric_configuration_reports_and_stay_alive(
    hass, omlet_entry, mqtt_messages
):
    """Valid MQTT numbers update state; invalid and empty messages are ignored."""
    delay_id = _entity_id(hass, Platform.NUMBER, "open_delay")
    stay_alive_id = _entity_id(hass, Platform.NUMBER, "stay_alive")

    await _send(hass, mqtt_messages, _config_topic("openDelay"), "42")
    assert hass.states.get(delay_id).state == "42"
    await _send(hass, mqtt_messages, _config_topic("openDelay"), "invalid")
    assert hass.states.get(delay_id).state == "42"
    await _send(hass, mqtt_messages, _config_topic("openDelay"), "61")
    assert hass.states.get(delay_id).state == "42"
    await _send(hass, mqtt_messages, _config_topic("openDelay"), "")
    assert hass.states.get(delay_id).state == "42"

    await _send(hass, mqtt_messages, _stay_alive_topic(), "120")
    assert hass.states.get(stay_alive_id).state == "120"
    assert hass.data[DOMAIN][omlet_entry.entry_id].stay_alive == 120
    await _send(hass, mqtt_messages, _stay_alive_topic(), "bad")
    assert hass.states.get(stay_alive_id).state == "120"


async def test_setting_number_commands_and_stay_alive(hass, omlet_entry):
    """Settings wake the device, while stay-alive publishes directly."""
    delay_id = _entity_id(hass, Platform.NUMBER, "open_delay")
    stay_alive_id = _entity_id(hass, Platform.NUMBER, "stay_alive")
    with patch(
        "custom_components.omlet_coop.commands.mqtt.async_publish",
        new_callable=AsyncMock,
    ) as publish:
        await hass.services.async_call(
            Platform.NUMBER,
            "set_value",
            {"entity_id": delay_id, "value": 20},
            blocking=True,
        )
        await hass.services.async_call(
            Platform.NUMBER,
            "set_value",
            {"entity_id": stay_alive_id, "value": 180},
            blocking=True,
        )

    assert [call.args[1:3] for call in publish.await_args_list] == [
        (_stay_alive_topic(), "60"),
        (_config_topic("openDelay"), "20"),
        (_stay_alive_topic(), "180"),
    ]
    assert hass.data[DOMAIN][omlet_entry.entry_id].stay_alive == 180
    assert hass.states.get(stay_alive_id).state == "180"


async def test_number_rejects_non_integer_and_out_of_range_values(
    hass, omlet_entry
):
    """Number entities reject values that do not fit their contract."""
    device_data = hass.data[DOMAIN][omlet_entry.entry_id]
    entity = OmletConfigNumber(
        device_data,
        _config_topic("openDelay"),
        "test_delay",
        0,
        60,
    )
    with pytest.raises(ValueError, match="integer"):
        await entity.async_set_native_value(1.5)
    with pytest.raises(ValueError, match="integer"):
        await entity.async_set_native_value(61)

    assert not entity._set_value("")
    assert not entity._set_value("not-a-number")
    assert not entity._set_value("61")
    assert entity._set_value("15")
    assert entity.native_value == 15


async def test_stay_alive_number_validates_and_publishes_directly(
    hass, omlet_entry
):
    """Direct stay-alive writes update runtime settings after publication."""
    device_data = hass.data[DOMAIN][omlet_entry.entry_id]
    entity = OmletConfigNumber(
        device_data,
        _stay_alive_topic(),
        "test_stay_alive",
        30,
        9000,
        is_stay_alive=True,
    )
    with patch(
        "custom_components.omlet_coop.commands.mqtt.async_publish",
        new_callable=AsyncMock,
    ) as publish, patch.object(entity, "async_write_ha_state"):
        await entity.async_set_native_value(240)
    assert device_data.stay_alive == 240
    assert publish.await_args_list[0].args[1:3] == (_stay_alive_topic(), "240")
    assert publish.await_args_list[0].kwargs == {"qos": 2, "retain": True}


async def test_time_reports_and_commands(hass, omlet_entry, mqtt_messages):
    """Local times parse strictly and writes use HH:MM with the wake value."""
    open_time_id = _entity_id(hass, Platform.TIME, "open_time")
    topic = _config_topic("openTime")

    await _send(hass, mqtt_messages, topic, "06:15")
    assert hass.states.get(open_time_id).state == "06:15:00"
    await _send(hass, mqtt_messages, topic, "")
    assert hass.states.get(open_time_id).state == "06:15:00"
    await _send(hass, mqtt_messages, topic, "invalid")
    assert hass.states.get(open_time_id).state == "06:15:00"
    await _send(hass, mqtt_messages, topic, "unknown")
    assert hass.states.get(open_time_id).state == "06:15:00"
    await _send(hass, mqtt_messages, topic, "unavailable")
    assert hass.states.get(open_time_id).state == "06:15:00"
    await _send(hass, mqtt_messages, topic, "06:15:00+01:00")
    assert hass.states.get(open_time_id).state == "06:15:00"

    with patch(
        "custom_components.omlet_coop.commands.mqtt.async_publish",
        new_callable=AsyncMock,
    ) as publish:
        await hass.services.async_call(
            Platform.TIME,
            "set_value",
            {"entity_id": open_time_id, "time": "07:45:00"},
            blocking=True,
        )
    assert [call.args[1:3] for call in publish.await_args_list] == [
        (_stay_alive_topic(), "60"),
        (topic, "07:45"),
    ]
    assert hass.states.get(open_time_id).state == "07:45:00"


async def test_time_publish_failure_does_not_advance_state(hass, omlet_entry):
    """A failed time write leaves the previous reported value visible."""
    open_time_id = _entity_id(hass, Platform.TIME, "open_time")
    topic = _config_topic("openTime")
    with patch(
        "custom_components.omlet_coop.commands.mqtt.async_publish",
        new_callable=AsyncMock,
        side_effect=HomeAssistantError("publish failed"),
    ):
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                Platform.TIME,
                "set_value",
                {"entity_id": open_time_id, "time": "07:45:00"},
                blocking=True,
            )
    assert hass.states.get(open_time_id).state == "unknown"
