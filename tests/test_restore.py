"""Tests for restoring Omlet entity state after a Home Assistant restart."""

import pytest
from homeassistant.const import Platform

from tests.conftest import DEVICE_ID
from tests.test_entities import _entity_id


@pytest.fixture
def restored_states():
    """Seed prior states for every RestoreEntity platform."""
    prefix = "omlet_coop_" + DEVICE_ID + "_"
    return {
        f"cover.{prefix}door": "opening",
        f"light.{prefix}light": "on",
        f"binary_sensor.{prefix}reported_connected": "on",
        f"binary_sensor.{prefix}door_fault": "off",
        f"number.{prefix}open_delay": "25",
        f"number.{prefix}open_light_level": "invalid",
        f"select.{prefix}door_mode": "manual",
        f"time.{prefix}open_time": "06:30:00",
        f"time.{prefix}close_time": "invalid",
        f"sensor.{prefix}battery": "88.5",
        f"sensor.{prefix}uptime": "invalid",
        f"sensor.{prefix}wi_fi_power_level": "20.0",
        f"sensor.{prefix}power_source": "mains",
        f"sensor.{prefix}device_date_and_time": "Thu Oct 22 07:21:12 2026",
    }


async def test_entities_restore_last_valid_states(hass, omlet_entry):
    """Valid prior entity states are restored, invalid ones stay unknown."""
    assert hass.states.get(_entity_id(hass, Platform.COVER, "door")).state == "opening"
    assert hass.states.get(_entity_id(hass, Platform.LIGHT, "light")).state == "on"
    assert (
        hass.states.get(_entity_id(hass, Platform.BINARY_SENSOR, "connected")).state
        == "on"
    )
    assert hass.states.get(
        _entity_id(hass, Platform.BINARY_SENSOR, "door_fault")
    ).state == "off"
    assert hass.states.get(
        _entity_id(hass, Platform.NUMBER, "open_delay")
    ).state == "25"
    assert hass.states.get(
        _entity_id(hass, Platform.NUMBER, "open_light_level")
    ).state == "unknown"
    assert hass.states.get(
        _entity_id(hass, Platform.SELECT, "door_mode")
    ).state == "manual"
    assert hass.states.get(
        _entity_id(hass, Platform.TIME, "open_time")
    ).state == "06:30:00"
    assert hass.states.get(
        _entity_id(hass, Platform.TIME, "close_time")
    ).state == "unknown"
    assert hass.states.get(
        _entity_id(hass, Platform.SENSOR, "battery")
    ).state == "88.5"
    assert hass.states.get(
        _entity_id(hass, Platform.SENSOR, "uptime")
    ).state == "unknown"
    assert hass.states.get(
        _entity_id(hass, Platform.SENSOR, "wifi_power_level")
    ).state == "20"
    assert hass.states.get(
        _entity_id(hass, Platform.SENSOR, "power_source")
    ).state == "mains"
    assert hass.states.get(
        _entity_id(hass, Platform.SENSOR, "device_datetime")
    ).state == "Thu Oct 22 07:21:12 2026"
