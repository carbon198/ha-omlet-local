"""Cover platform for the Omlet smart coop autodoor."""

import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .commands import async_publish_commands
from .const import ACTION_ROOT, DOMAIN, TOPIC_ROOT
from .models import OmletDeviceData, message_payload

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Omlet cover."""
    device_data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([OmletCover(device_data)])


class OmletCover(CoverEntity, RestoreEntity):
    """Represent the coop door and publish its retained commands."""

    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )

    def __init__(self, device_data: OmletDeviceData) -> None:
        """Initialize the cover."""
        self._device_data = device_data
        device_id = device_data.device_id
        self._state_topic = (
            f"{TOPIC_ROOT.format(device_id=device_id)}/door/state"
        )
        self._action_topic = (
            f"{ACTION_ROOT.format(device_id=device_id)}/door/state"
        )
        self._attr_unique_id = f"{device_id}_door"
        self._attr_translation_key = "door"
        self._attr_device_class = CoverDeviceClass.DOOR
        self._attr_has_entity_name = True
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": f"Omlet Coop {device_id}",
            "manufacturer": "Omlet",
            "model": "Smart Coop Autodoor",
        }
        self._attr_is_closed = None
        self._attr_is_opening = False
        self._attr_is_closing = False
        self._pending_action: str | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last state and subscribe to door state updates."""
        await super().async_added_to_hass()
        self._device_data.register_entity(self)
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._set_state(last_state.state)

        self.async_on_remove(
            await mqtt.async_subscribe(
                self.hass, self._state_topic, self._handle_message
            )
        )
        self.async_on_remove(
            await mqtt.async_subscribe(
                self.hass, self._action_topic, self._handle_action_message
            )
        )

    @property
    def extra_state_attributes(self) -> dict[str, bool]:
        """Expose pending commands until the device clears its action topic."""
        return {
            "open_pending": self._pending_action == "open",
            "close_pending": self._pending_action == "close",
            "stop_pending": self._pending_action == "stop",
        }

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Publish a retained open command."""
        await self._publish_command("open")

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Publish a retained close command."""
        await self._publish_command("close")

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Publish a retained stop command."""
        await self._publish_command("stop")

    async def _publish_command(self, payload: str) -> None:
        """Publish a retained door action."""
        previous_action = self._pending_action
        self._pending_action = payload
        self.async_write_ha_state()
        try:
            await async_publish_commands(
                self.hass,
                self._device_data,
                [(self._action_topic, payload)],
            )
        except HomeAssistantError:
            self._pending_action = previous_action
            self.async_write_ha_state()
            raise

    @callback
    def _handle_action_message(self, message: mqtt.ReceiveMessage) -> None:
        """Track pending actions until the door publishes an empty payload."""
        payload = message_payload(message).strip().lower()
        if not payload:
            self._pending_action = None
            self.async_write_ha_state()
            return
        if payload not in ("open", "close", "stop"):
            _LOGGER.warning(
                "Unexpected door action %r received on %s",
                payload,
                self._action_topic,
            )
            return
        self._pending_action = payload
        self.async_write_ha_state()

    @callback
    def _handle_message(self, message: mqtt.ReceiveMessage) -> None:
        """Update the cover from a reported door state."""
        payload = message_payload(message).strip().lower()
        if not payload:
            return
        if not self._set_state(payload):
            _LOGGER.warning(
                "Unexpected door state %r received on %s",
                payload,
                self._state_topic,
            )
            return
        self.async_write_ha_state()

    def _set_state(self, state: str) -> bool:
        """Apply a known reported or restored door state."""
        if state not in ("open", "closed", "opening", "closing"):
            return False
        self._attr_is_closed = state == "closed"
        self._attr_is_opening = state == "opening"
        self._attr_is_closing = state == "closing"
        return True
