"""Binary sensors for the Omlet smart coop autodoor."""

import logging
from collections.abc import Mapping

from homeassistant.components import mqtt
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import ACTION_ROOT, DOMAIN, TOPIC_ROOT
from .models import OmletDeviceData, message_payload

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Omlet binary sensors."""
    device_data = hass.data[DOMAIN][entry.entry_id]
    device_id = device_data.device_id
    action_topic = (
        f"{ACTION_ROOT.format(device_id=device_id)}/door/state"
    )
    async_add_entities(
        [
            OmletBinarySensor(
                device_data,
                f"{TOPIC_ROOT.format(device_id=device_id)}/connected",
                "connected",
                BinarySensorDeviceClass.CONNECTIVITY,
                {"true": True, "false": False, "1": True, "0": False},
            ),
            OmletBinarySensor(
                device_data,
                f"{TOPIC_ROOT.format(device_id=device_id)}/recoveryAppRunning",
                "recovery_app_running",
                BinarySensorDeviceClass.RUNNING,
                {"true": True, "false": False, "1": True, "0": False},
                entity_category=EntityCategory.DIAGNOSTIC,
                icon="mdi:application-cog",
            ),
            OmletFaultSensor(
                device_data,
                f"{TOPIC_ROOT.format(device_id=device_id)}/door/fault",
                "door_fault",
            ),
            OmletFaultSensor(
                device_data,
                f"{TOPIC_ROOT.format(device_id=device_id)}/light/fault",
                "light_fault",
            ),
            OmletPendingSensor(
                device_data,
                action_topic,
                "open",
                "mdi:door-open",
            ),
            OmletPendingSensor(
                device_data,
                action_topic,
                "close",
                "mdi:door-closed",
            ),
            OmletPendingSensor(
                device_data,
                action_topic,
                "stop",
                "mdi:stop-circle",
            ),
        ]
    )


class OmletBinarySensor(BinarySensorEntity, RestoreEntity):
    """Represent a boolean value published by the device."""

    def __init__(
        self,
        device_data: OmletDeviceData,
        topic: str,
        key: str,
        device_class: BinarySensorDeviceClass,
        values: Mapping[str, bool],
        entity_category: EntityCategory | None = None,
        icon: str = "mdi:wifi-check",
    ):
        """Initialize the binary sensor."""
        self._device_data = device_data
        device_id = device_data.device_id
        self._topic = topic
        self._values = values
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_class = device_class
        self._attr_entity_category = entity_category
        self._attr_icon = icon
        self._attr_has_entity_name = True
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": f"Omlet Coop {device_id}",
            "manufacturer": "Omlet",
            "model": "Smart Coop Autodoor",
        }
        self._attr_is_on = None

    async def async_added_to_hass(self) -> None:
        """Restore the last state and subscribe to the MQTT topic."""
        await super().async_added_to_hass()
        self._device_data.register_entity(self)
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in ("on", "off"):
            self._attr_is_on = last_state.state == "on"

        self.async_on_remove(
            await mqtt.async_subscribe(
                self.hass, self._topic, self._handle_message
            )
        )

    @callback
    def _handle_message(self, message: mqtt.ReceiveMessage) -> None:
        """Update the sensor for a non-empty MQTT message."""
        payload = message_payload(message).strip().lower()
        if not payload:
            return
        if payload not in self._values:
            _LOGGER.warning(
                "Unexpected value %r received on %s", payload, self._topic
            )
            return
        self._attr_is_on = self._values[payload]
        self.async_write_ha_state()


class OmletFaultSensor(BinarySensorEntity, RestoreEntity):
    """Represent a reported device fault, treating unknown values as faults."""

    _NO_FAULT_VALUES = {"none", "off", "false", "0"}

    def __init__(
        self, device_data: OmletDeviceData, topic: str, key: str
    ) -> None:
        """Initialize a fault sensor."""
        self._device_data = device_data
        device_id = device_data.device_id
        self._topic = topic
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:alert-circle-outline"
        self._attr_has_entity_name = True
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": f"Omlet Coop {device_id}",
            "manufacturer": "Omlet",
            "model": "Smart Coop Autodoor",
        }
        self._attr_is_on = None

    async def async_added_to_hass(self) -> None:
        """Restore the last state and subscribe to the MQTT topic."""
        await super().async_added_to_hass()
        self._device_data.register_entity(self)
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in ("on", "off"):
            self._attr_is_on = last_state.state == "on"

        self.async_on_remove(
            await mqtt.async_subscribe(
                self.hass, self._topic, self._handle_message
            )
        )

    @callback
    def _handle_message(self, message: mqtt.ReceiveMessage) -> None:
        """Treat known clear values as healthy and all other reports as faults."""
        payload = message_payload(message).strip().lower()
        if not payload:
            return
        self._attr_is_on = payload not in self._NO_FAULT_VALUES
        self.async_write_ha_state()


class OmletPendingSensor(BinarySensorEntity):
    """Represent whether a retained door command is awaiting device receipt."""

    def __init__(
        self, device_data: OmletDeviceData, topic: str, action: str, icon: str
    ) -> None:
        """Initialize a command-pending sensor."""
        self._device_data = device_data
        device_id = device_data.device_id
        self._topic = topic
        self._action = action
        self._attr_unique_id = f"{device_id}_{action}_pending"
        self._attr_translation_key = f"{action}_pending"
        self._attr_icon = icon
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": f"Omlet Coop {device_id}",
            "manufacturer": "Omlet",
            "model": "Smart Coop Autodoor",
        }
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Subscribe and recover a pending action from its retained message."""
        await super().async_added_to_hass()
        self._device_data.register_entity(self)
        self.async_on_remove(
            await mqtt.async_subscribe(
                self.hass, self._topic, self._handle_message
            )
        )

    @callback
    def _handle_message(self, message: mqtt.ReceiveMessage) -> None:
        """Reflect the action topic, clearing all indicators on an empty value."""
        payload = message_payload(message).strip().lower()
        if not payload:
            self._attr_is_on = False
        elif payload in ("open", "close", "stop"):
            self._attr_is_on = payload == self._action
        else:
            _LOGGER.warning(
                "Unexpected door action %r received on %s",
                payload,
                self._topic,
            )
            return
        self.async_write_ha_state()
