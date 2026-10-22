"""Time entities for Omlet door configuration."""

import logging
from datetime import time

from homeassistant.components import mqtt
from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .commands import async_publish_commands
from .const import CONFIG_ROOT, DOMAIN
from .models import OmletDeviceData, message_payload

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Omlet door schedule time entities."""
    device_data = hass.data[DOMAIN][entry.entry_id]
    device_id = device_data.device_id
    config_root = CONFIG_ROOT.format(device_id=device_id)
    async_add_entities(
        [
            OmletTimeEntity(
                device_data,
                f"{config_root}/openTime",
                "open_time",
            ),
            OmletTimeEntity(
                device_data,
                f"{config_root}/closeTime",
                "close_time",
            ),
        ]
    )


class OmletTimeEntity(TimeEntity, RestoreEntity):
    """Represent a local wall-clock time published by the device."""

    def __init__(
        self, device_data: OmletDeviceData, topic: str, key: str
    ) -> None:
        """Initialize the time entity."""
        self._device_data = device_data
        device_id = device_data.device_id
        self._topic = topic
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_translation_key = key
        self._attr_icon = "mdi:clock-outline"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_has_entity_name = True
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": f"Omlet Coop {device_id}",
            "manufacturer": "Omlet",
            "model": "Smart Coop Autodoor",
        }
        self._attr_native_value = None

    async def async_added_to_hass(self) -> None:
        """Restore the time and subscribe to its MQTT topic."""
        await super().async_added_to_hass()
        self._device_data.register_entity(self)
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._set_value(last_state.state)
        self.async_on_remove(
            await mqtt.async_subscribe(
                self.hass, self._topic, self._handle_message
            )
        )

    async def async_set_value(self, value: time) -> None:
        """Publish a local wall-clock time in HH:MM format."""
        await async_publish_commands(
            self.hass,
            self._device_data,
            [(self._topic, value.strftime("%H:%M"))],
        )
        self._attr_native_value = value
        self.async_write_ha_state()

    @callback
    def _handle_message(self, message: mqtt.ReceiveMessage) -> None:
        """Update the entity from a device-published time."""
        payload = message_payload(message)
        if not payload.strip():
            return
        if not self._set_value(payload):
            _LOGGER.warning(
                "Unexpected time %r received on %s",
                payload,
                self._topic,
            )
            return
        self.async_write_ha_state()

    def _set_value(self, value: str) -> bool:
        """Parse an MQTT time without converting its local wall-clock value."""
        payload = value.strip()
        if not payload or payload in ("unknown", "unavailable"):
            return False
        try:
            parsed = time.fromisoformat(payload)
        except ValueError:
            return False
        if parsed.tzinfo is not None:
            return False
        self._attr_native_value = parsed
        return True
