"""Light platform for the Omlet smart coop autodoor."""

import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.light import LightEntity
from homeassistant.components.light.const import ColorMode
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
    """Set up the Omlet light."""
    device_data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([OmletLight(device_data)])


class OmletLight(LightEntity, RestoreEntity):
    """Control the device light using its retained action topic."""

    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(self, device_data: OmletDeviceData):
        """Initialize the device-reported light."""
        self._device_data = device_data
        self._action_topic = (
            f"{ACTION_ROOT.format(device_id=device_data.device_id)}/light/state"
        )
        self._state_topic = (
            f"{TOPIC_ROOT.format(device_id=device_data.device_id)}/light/state"
        )
        self._attr_unique_id = f"{device_data.device_id}_light"
        self._attr_translation_key = "light"
        self._attr_icon = "mdi:lightbulb"
        self._attr_has_entity_name = True
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_data.device_id)},
            "name": f"Omlet Coop {device_data.device_id}",
            "manufacturer": "Omlet",
            "model": "Smart Coop Autodoor",
        }
        self._attr_is_on = None
        self._pending = False

    @property
    def color_mode(self) -> ColorMode | None:
        """Report the on/off color mode while the light is on."""
        if self._attr_is_on:
            return ColorMode.ONOFF
        return None

    async def async_added_to_hass(self) -> None:
        """Restore the last state and subscribe to both light topics."""
        await super().async_added_to_hass()
        self._device_data.register_entity(self)
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in ("on", "off"):
            self._attr_is_on = last_state.state == "on"

        self.async_on_remove(
            await mqtt.async_subscribe(
                self.hass, self._action_topic, self._handle_action_message
            )
        )
        self.async_on_remove(
            await mqtt.async_subscribe(
                self.hass, self._state_topic, self._handle_state_message
            )
        )

    @property
    def extra_state_attributes(self) -> dict[str, bool]:
        """Expose whether the device has cleared the light action."""
        return {"pending": self._pending}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Publish the retained on command."""
        await self._publish_command("on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Publish the retained off command."""
        await self._publish_command("off")

    async def _publish_command(self, payload: str) -> None:
        """Publish the requested state and mark the command pending."""
        previous_pending = self._pending
        self._pending = True
        self.async_write_ha_state()
        try:
            await async_publish_commands(
                self.hass,
                self._device_data,
                [(self._action_topic, payload)],
            )
        except HomeAssistantError:
            self._pending = previous_pending
            self.async_write_ha_state()
            raise

    @callback
    def _handle_action_message(self, message: mqtt.ReceiveMessage) -> None:
        """Update pending status from the action topic."""
        payload = message_payload(message).strip().lower()
        if not payload:
            self._pending = False
            self.async_write_ha_state()
            return
        if payload not in ("on", "off"):
            _LOGGER.warning(
                "Unexpected light action %r received on %s",
                payload,
                self._action_topic,
            )
            return
        self._pending = True
        self.async_write_ha_state()

    @callback
    def _handle_state_message(self, message: mqtt.ReceiveMessage) -> None:
        """Update the light from its reported state topic."""
        payload = message_payload(message).strip().lower()
        if not payload:
            return
        if payload not in ("on", "off"):
            _LOGGER.warning(
                "Unexpected light state %r received on %s",
                payload,
                self._state_topic,
            )
            return
        self._attr_is_on = payload == "on"
        self.async_write_ha_state()
