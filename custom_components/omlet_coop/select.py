"""Select entities for Omlet door configuration."""

import logging

from homeassistant.components import mqtt
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .commands import async_publish_commands
from .const import CONFIG_ROOT, DOMAIN
from .models import OmletDeviceData, message_payload

_LOGGER = logging.getLogger(__name__)
_MODES = ["time", "manual", "light"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Omlet configuration selectors."""
    device_data = hass.data[DOMAIN][entry.entry_id]
    device_id = device_data.device_id
    config_root = CONFIG_ROOT.format(device_id=device_id)
    async_add_entities([OmletDoorModeSelect(device_data, config_root)])


class OmletDoorModeSelect(SelectEntity, RestoreEntity):
    """Keep opening and closing modes in sync with one selector."""

    def __init__(self, device_data: OmletDeviceData, config_root: str) -> None:
        """Initialize the combined door mode selector."""
        self._device_data = device_data
        device_id = device_data.device_id
        self._open_mode_topic = f"{config_root}/openMode"
        self._close_mode_topic = f"{config_root}/closeMode"
        self._open_mode: str | None = None
        self._close_mode: str | None = None
        self._attr_unique_id = f"{device_id}_door_mode"
        self._attr_translation_key = "door_mode"
        self._attr_icon = "mdi:door"
        self._attr_options = _MODES
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_has_entity_name = True
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": f"Omlet Coop {device_id}",
            "manufacturer": "Omlet",
            "model": "Smart Coop Autodoor",
        }
        self._attr_current_option: str | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last mode and subscribe to both configuration topics."""
        await super().async_added_to_hass()
        self._device_data.register_entity(self)
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in _MODES:
            self._open_mode = self._close_mode = last_state.state
            self._attr_current_option = last_state.state

        for topic in (self._open_mode_topic, self._close_mode_topic):
            self.async_on_remove(
                await mqtt.async_subscribe(
                    self.hass, topic, self._handle_message
                )
            )

    async def async_select_option(self, option: str) -> None:
        """Publish the selected mode to both door mode topics."""
        if option not in _MODES:
            raise ValueError(f"Unsupported door mode: {option}")

        await async_publish_commands(
            self.hass,
            self._device_data,
            [
                (self._open_mode_topic, option),
                (self._close_mode_topic, option),
            ],
        )
        self._open_mode = self._close_mode = option
        self._attr_current_option = option
        self.async_write_ha_state()

    @callback
    def _handle_message(self, message: mqtt.ReceiveMessage) -> None:
        """Update one side of the paired mode configuration."""
        mode = message_payload(message).strip().lower()
        if not mode:
            return
        if mode not in _MODES:
            _LOGGER.warning(
                "Unexpected door mode %r received on %s", mode, message.topic
            )
            return

        if message.topic == self._open_mode_topic:
            self._open_mode = mode
        else:
            self._close_mode = mode
        self._attr_current_option = (
            self._open_mode
            if self._open_mode is not None and self._open_mode == self._close_mode
            else None
        )
        self.async_write_ha_state()
