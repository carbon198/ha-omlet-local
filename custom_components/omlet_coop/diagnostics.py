"""Diagnostics for the Omlet smart coop autodoor integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .models import OmletDeviceData


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, bool | str | None]:
    """Return privacy-preserving device availability diagnostics."""
    device_data: OmletDeviceData = hass.data[DOMAIN][entry.entry_id]
    last_check_in = device_data.last_check_in
    return {
        "device_id": "[redacted]",
        "available": device_data.available,
        "last_check_in": last_check_in.isoformat() if last_check_in else None,
    }
