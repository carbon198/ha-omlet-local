"""Tests for the Omlet integration config flow."""

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.omlet_coop.const import CONF_DEVICE_ID, DOMAIN

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def test_user_flow_shows_form(hass):
    """The user flow asks for a device ID."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert CONF_DEVICE_ID in result["data_schema"].schema


@pytest.mark.parametrize("device_id", ["", "device/id", "device+", "device#"])
async def test_user_flow_rejects_invalid_device_id(hass, device_id):
    """Topic separators and wildcards are rejected."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={CONF_DEVICE_ID: device_id},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_DEVICE_ID: "invalid_device_id"}


async def test_user_flow_creates_entry(hass):
    """A valid device ID creates a uniquely identified config entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={CONF_DEVICE_ID: " coop-device "},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Omlet Coop coop-device"
    assert result["data"] == {CONF_DEVICE_ID: "coop-device"}
    assert result["result"].unique_id == "coop-device"


async def test_user_flow_aborts_for_duplicate_device(hass):
    """A configured device cannot be added a second time."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="coop-device",
        data={CONF_DEVICE_ID: "coop-device"},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={CONF_DEVICE_ID: "coop-device"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
