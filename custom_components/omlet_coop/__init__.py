"""Omlet smart coop autodoor integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_DEVICE_ID, DOMAIN, PLATFORMS
from .models import OmletDeviceData


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Set up the Omlet device from a config entry."""
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = OmletDeviceData(
        device_id=entry.data[CONF_DEVICE_ID]
    )
    await hass.data[DOMAIN][entry.entry_id].async_setup(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an Omlet device config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    device_data = hass.data[DOMAIN].pop(entry.entry_id)
    device_data.async_unload()
    return True
