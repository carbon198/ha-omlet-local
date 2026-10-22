"""Tests for device availability and privacy-preserving diagnostics."""

from datetime import timedelta
from types import SimpleNamespace

from homeassistant.const import Platform
from homeassistant.util import dt as dt_util

from custom_components.omlet_coop.const import (
    DEVICE_AVAILABILITY_TIMEOUT,
    DOMAIN,
)
from custom_components.omlet_coop.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.omlet_coop.models import message_payload

from .conftest import DEVICE_ID
from .test_entities import _entity_id


async def test_retained_messages_do_not_make_device_available(
    hass, omlet_entry, mqtt_messages
):
    """Only fresh non-retained device messages establish availability."""
    device_data = hass.data[DOMAIN][omlet_entry.entry_id]
    device_data._cancel_timeout()
    device_data._cancel_timeout = None
    device_data._last_check_in = None
    device_data._write_entity_states()

    cover_id = _entity_id(hass, Platform.COVER, "door")
    connected_id = _entity_id(hass, Platform.BINARY_SENSOR, "connected")
    assert hass.states.get(cover_id).state == "unavailable"

    mqtt_messages(
        f"device/{DEVICE_ID}/action/door/state",
        "open",
    )
    mqtt_messages(
        f"device/{DEVICE_ID}/configuration/door/openMode",
        "manual",
    )
    mqtt_messages(
        f"device/{DEVICE_ID}/configuration/general/datetime",
        "Thu Oct 22 07:21:12 2026",
    )
    await hass.async_block_till_done()
    assert hass.states.get(cover_id).state == "unavailable"

    mqtt_messages(
        f"device/{DEVICE_ID}/status/connected",
        "true",
        retain=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(cover_id).state == "unavailable"

    mqtt_messages(
        f"device/{DEVICE_ID}/status/connected",
        "false",
    )
    await hass.async_block_till_done()
    assert hass.states.get(cover_id).state == "unknown"
    assert hass.states.get(connected_id).state == "off"
    assert device_data.available


async def test_device_becomes_unavailable_after_timeout(
    hass, omlet_entry, mqtt_messages
):
    """A quiet device expires after 15 minutes and entities recover on check-in."""
    device_data = hass.data[DOMAIN][omlet_entry.entry_id]
    cover_id = _entity_id(hass, Platform.COVER, "door")
    assert hass.states.get(cover_id).state == "unknown"

    device_data._cancel_timeout()
    device_data._cancel_timeout = None
    device_data._last_check_in = dt_util.utcnow() - DEVICE_AVAILABILITY_TIMEOUT
    device_data._handle_timeout(dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get(cover_id).state == "unavailable"

    mqtt_messages(
        f"device/{DEVICE_ID}/status/door/state",
        "closed",
    )
    await hass.async_block_till_done()
    assert hass.states.get(cover_id).state == "closed"


async def test_other_device_topics_count_as_check_ins(
    hass, omlet_entry, mqtt_messages
):
    """Non-retained device topics outside local publish paths refresh liveness."""
    device_data = hass.data[DOMAIN][omlet_entry.entry_id]
    device_data._cancel_timeout()
    device_data._cancel_timeout = None
    device_data._last_check_in = None
    device_data._write_entity_states()

    mqtt_messages(
        f"device/{DEVICE_ID}/configuration/connectivity/wifi",
        "on",
    )
    await hass.async_block_till_done()
    assert device_data.available


async def test_timeout_reschedules_if_callback_runs_early(
    hass, omlet_entry, mqtt_messages
):
    """An early timeout callback is rescheduled for the remaining interval."""
    device_data = hass.data[DOMAIN][omlet_entry.entry_id]
    device_data._cancel_timeout()
    device_data._cancel_timeout = None

    device_data._handle_timeout(dt_util.utcnow())
    assert device_data._cancel_timeout is not None


async def test_diagnostics_redact_device_id_and_omit_private_state(
    hass, omlet_entry
):
    """Diagnostics expose liveness without device identifiers or entity values."""
    diagnostics = await async_get_config_entry_diagnostics(hass, omlet_entry)

    assert diagnostics["device_id"] == "[redacted]"
    assert diagnostics["available"] is True
    assert DEVICE_ID not in str(diagnostics)
    assert "wifi_ssid" not in diagnostics
    assert "ssid" not in str(diagnostics).lower()


def test_message_payload_decodes_bytes_and_text():
    """MQTT payload normalization handles the supported byte and text forms."""
    assert message_payload(SimpleNamespace(payload="open")) == "open"
    assert message_payload(SimpleNamespace(payload=b"open")) == "open"
    assert message_payload(SimpleNamespace(payload=bytearray(b"open"))) == "open"


async def test_device_data_unload_is_idempotent(
    hass, omlet_entry, mqtt_messages
):
    """Unloading twice safely handles already-cleared subscriptions and timers."""
    device_data = hass.data[DOMAIN][omlet_entry.entry_id]
    device_data.async_unload()
    device_data.async_unload()
