"""Number entities for Omlet door configuration."""

import logging

from homeassistant.components import mqtt
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .commands import async_publish_commands, async_publish_retained
from .const import (
    ACTION_ROOT,
    CONFIG_ROOT,
    DOMAIN,
    MAX_STAY_ALIVE,
    MIN_STAY_ALIVE,
)
from .models import OmletDeviceData, message_payload

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Omlet door configuration number entities."""
    device_data = hass.data[DOMAIN][entry.entry_id]
    device_id = device_data.device_id
    config_root = CONFIG_ROOT.format(device_id=device_id)
    async_add_entities(
        [
            OmletConfigNumber(
                device_data,
                f"{config_root}/openLightLevel",
                "open_light_level",
                0,
                100,
                PERCENTAGE,
                icon="mdi:brightness-6",
            ),
            OmletConfigNumber(
                device_data,
                f"{config_root}/closeLightLevel",
                "close_light_level",
                0,
                100,
                PERCENTAGE,
                icon="mdi:brightness-6",
            ),
            OmletConfigNumber(
                device_data,
                f"{config_root}/openDelay",
                "open_delay",
                0,
                60,
                icon="mdi:timer-outline",
            ),
            OmletConfigNumber(
                device_data,
                f"{config_root}/closeDelay",
                "close_delay",
                0,
                60,
                icon="mdi:timer-outline",
            ),
            OmletConfigNumber(
                device_data,
                f"{ACTION_ROOT.format(device_id=device_id)}/stayAlive",
                "stay_alive",
                MIN_STAY_ALIVE,
                MAX_STAY_ALIVE,
                UnitOfTime.SECONDS,
                is_stay_alive=True,
                mode=NumberMode.BOX,
                icon="mdi:timer-sand",
            ),
        ]
    )


class OmletConfigNumber(NumberEntity, RestoreEntity):
    """Represent a bounded numeric configuration value."""

    def __init__(
        self,
        device_data: OmletDeviceData,
        topic: str,
        key: str,
        minimum: int,
        maximum: int,
        unit: str | None = None,
        *,
        is_stay_alive: bool = False,
        mode: NumberMode = NumberMode.SLIDER,
        icon: str | None = None,
    ) -> None:
        """Initialize the configuration number."""
        self._device_data = device_data
        device_id = device_data.device_id
        self._topic = topic
        self._minimum = minimum
        self._maximum = maximum
        self._is_stay_alive = is_stay_alive
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_translation_key = key
        self._attr_icon = icon
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = unit
        self._attr_mode = mode
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_has_entity_name = True
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": f"Omlet Coop {device_id}",
            "manufacturer": "Omlet",
            "model": "Smart Coop Autodoor",
        }
        self._attr_native_value = (
            device_data.stay_alive if is_stay_alive else None
        )

    async def async_added_to_hass(self) -> None:
        """Restore the value and subscribe to its MQTT topic."""
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

    async def async_set_native_value(self, value: float) -> None:
        """Publish an integer configuration value."""
        numeric_value = int(value)
        if numeric_value != value or not self._within_range(numeric_value):
            raise ValueError(
                f"Value must be an integer from {self._minimum} to {self._maximum}"
            )

        if self._is_stay_alive:
            await async_publish_retained(
                self.hass,
                [(self._topic, str(numeric_value))],
            )
            self._device_data.stay_alive = numeric_value
        else:
            await async_publish_commands(
                self.hass,
                self._device_data,
                [(self._topic, str(numeric_value))],
            )
        self._attr_native_value = numeric_value
        self.async_write_ha_state()

    @callback
    def _handle_message(self, message: mqtt.ReceiveMessage) -> None:
        """Update the entity from a device-published numeric value."""
        payload = message_payload(message)
        if not payload.strip():
            return
        if not self._set_value(payload):
            _LOGGER.warning(
                "Unexpected numeric value %r received on %s",
                payload,
                self._topic,
            )
            return
        self.async_write_ha_state()

    def _set_value(self, payload: str) -> bool:
        """Parse and range-check an integer MQTT value."""
        value = payload.strip()
        if not value:
            return False
        try:
            numeric_value = int(value)
        except ValueError:
            return False
        if not self._within_range(numeric_value):
            return False
        self._attr_native_value = numeric_value
        if self._is_stay_alive:
            self._device_data.stay_alive = numeric_value
        return True

    def _within_range(self, value: int) -> bool:
        return self._minimum <= value <= self._maximum
