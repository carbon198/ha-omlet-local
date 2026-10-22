"""Tests for automatic MQTT device-clock correction."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.const import Platform

from custom_components.omlet_coop.const import ACTION_ROOT
from tests.test_entities import _entity_id
from tests.conftest import DEVICE_ID

DATETIME_TOPIC = f"device/{DEVICE_ID}/configuration/general/datetime"
TIMEZONE_TOPIC = f"device/{DEVICE_ID}/configuration/general/timeZone"
STAY_ALIVE_TOPIC = f"{ACTION_ROOT.format(device_id=DEVICE_ID)}/stayAlive"
DEVICE_TZ = "EST5EDT,M3.2.0,M11.1.0"


async def _send(hass, mqtt_messages, topic, payload):
    mqtt_messages(topic, payload)
    await hass.async_block_till_done()


async def test_clock_sync_corrects_drift_and_uses_retained_qos(
    hass, omlet_entry, mqtt_messages
):
    """Drift over one minute publishes local time after stay-alive."""
    now = datetime(2026, 10, 22, 11, 21, 12, tzinfo=timezone.utc)
    with (
        patch(
            "custom_components.omlet_coop.sensor.datetime"
        ) as datetime_mock,
        patch(
            "custom_components.omlet_coop.commands.mqtt.async_publish",
            new_callable=AsyncMock,
        ) as publish,
    ):
        datetime_mock.now.return_value = now
        await _send(
            hass, mqtt_messages, DATETIME_TOPIC, "Thu Oct 22 07:20:00 2026"
        )
        await _send(hass, mqtt_messages, TIMEZONE_TOPIC, DEVICE_TZ)

    assert [call.args[1:3] for call in publish.await_args_list] == [
        (STAY_ALIVE_TOPIC, "60"),
        (DATETIME_TOPIC, "Thu Oct 22 07:21:12 2026"),
    ]
    assert all(
        call.kwargs == {"qos": 2, "retain": True}
        for call in publish.await_args_list
    )
    assert hass.states.get(
        _entity_id(hass, Platform.SENSOR, "device_datetime")
    ).state == "Thu Oct 22 07:20:00 2026"


async def test_clock_waits_for_timezone_and_skips_small_drift(
    hass, omlet_entry, mqtt_messages
):
    """Datetime may arrive first; drift of exactly 60 seconds is ignored."""
    now = datetime(2026, 10, 22, 11, 21, 0, tzinfo=timezone.utc)
    with (
        patch("custom_components.omlet_coop.sensor.datetime") as datetime_mock,
        patch(
            "custom_components.omlet_coop.commands.mqtt.async_publish",
            new_callable=AsyncMock,
        ) as publish,
    ):
        datetime_mock.now.return_value = now
        await _send(hass, mqtt_messages, DATETIME_TOPIC, "")
        await _send(
            hass, mqtt_messages, DATETIME_TOPIC, "Thu Oct 22 07:20:00 2026"
        )
        assert publish.await_count == 0
        await _send(hass, mqtt_messages, TIMEZONE_TOPIC, "")
        await _send(hass, mqtt_messages, TIMEZONE_TOPIC, DEVICE_TZ)

    assert publish.await_count == 0


async def test_clock_corrects_device_time_that_is_ahead(
    hass, omlet_entry, mqtt_messages
):
    """Clock correction also handles negative drift."""
    now = datetime(2026, 10, 22, 11, 21, 12, tzinfo=timezone.utc)
    with (
        patch("custom_components.omlet_coop.sensor.datetime") as datetime_mock,
        patch(
            "custom_components.omlet_coop.commands.mqtt.async_publish",
            new_callable=AsyncMock,
        ) as publish,
    ):
        datetime_mock.now.return_value = now
        await _send(hass, mqtt_messages, TIMEZONE_TOPIC, DEVICE_TZ)
        await _send(
            hass, mqtt_messages, DATETIME_TOPIC, "Thu Oct 22 07:24:00 2026"
        )

    assert publish.await_args_list[-1].args[1:3] == (
        DATETIME_TOPIC,
        "Thu Oct 22 07:21:12 2026",
    )


@pytest.mark.parametrize(
    ("datetime_value", "timezone_value"),
    [
        ("not-a-date", DEVICE_TZ),
        ("Thu Oct 22 07:20:00 2026", "not-a-timezone"),
    ],
)
async def test_clock_does_not_publish_for_invalid_reports(
    hass, omlet_entry, mqtt_messages, datetime_value, timezone_value, caplog
):
    """Invalid datetime and time-zone data are logged and not guessed."""
    now = datetime(2026, 10, 22, 11, 21, 12, tzinfo=timezone.utc)
    with (
        patch("custom_components.omlet_coop.sensor.datetime") as datetime_mock,
        patch(
            "custom_components.omlet_coop.commands.mqtt.async_publish",
            new_callable=AsyncMock,
        ) as publish,
    ):
        datetime_mock.now.return_value = now
        await _send(hass, mqtt_messages, DATETIME_TOPIC, datetime_value)
        await _send(hass, mqtt_messages, TIMEZONE_TOPIC, timezone_value)

    assert publish.await_count == 0
    assert "Could not evaluate device clock drift" in caplog.text


async def test_clock_publish_failure_is_logged(
    hass, omlet_entry, mqtt_messages, caplog
):
    """MQTT failures are reported without crashing the message callback."""
    now = datetime(2026, 10, 22, 11, 21, 12, tzinfo=timezone.utc)
    with (
        patch("custom_components.omlet_coop.sensor.datetime") as datetime_mock,
        patch(
            "custom_components.omlet_coop.commands.mqtt.async_publish",
            new_callable=AsyncMock,
            side_effect=HomeAssistantError("publish failed"),
        ),
    ):
        datetime_mock.now.return_value = now
        await _send(hass, mqtt_messages, TIMEZONE_TOPIC, DEVICE_TZ)
        await _send(
            hass, mqtt_messages, DATETIME_TOPIC, "Thu Oct 22 07:20:00 2026"
        )

    assert "Could not publish device clock correction" in caplog.text
