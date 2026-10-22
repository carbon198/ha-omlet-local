"""Sensors for the Omlet smart coop autodoor."""

import logging
from datetime import datetime, timezone

from homeassistant.components import mqtt
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .clock import (
    device_local_datetime,
    format_device_datetime,
    parse_device_datetime,
)
from .commands import async_publish_commands
from .const import DOMAIN, TOPIC_ROOT
from .models import OmletDeviceData, message_payload

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Omlet sensors."""
    device_data = hass.data[DOMAIN][entry.entry_id]
    device_id = device_data.device_id
    topic_root = TOPIC_ROOT.format(device_id=device_id)
    datetime_topic = f"device/{device_id}/configuration/general/datetime"
    timezone_topic = f"device/{device_id}/configuration/general/timeZone"
    async_add_entities(
        [
            OmletSensor(
                device_data,
                f"{topic_root}/batteryLevel",
                "battery",
                SensorDeviceClass.BATTERY,
                PERCENTAGE,
                icon="mdi:battery",
            ),
            OmletSensor(
                device_data,
                f"{topic_root}/wifi/signalStrength",
                "wifi_signal",
                SensorDeviceClass.SIGNAL_STRENGTH,
                "dBm",
                icon="mdi:wifi",
            ),
            OmletSensor(
                device_data,
                f"{topic_root}/wifi/powerLevel",
                "wifi_power_level",
                entity_category=EntityCategory.DIAGNOSTIC,
                icon="mdi:wifi",
            ),
            OmletSensor(
                device_data,
                f"{topic_root}/door/lightLevel",
                "light_level",
                unit=PERCENTAGE,
                icon="mdi:brightness-6",
            ),
            OmletSensor(
                device_data,
                f"{topic_root}/uptime",
                "uptime",
                entity_category=EntityCategory.DIAGNOSTIC,
                icon="mdi:timer-outline",
            ),
            OmletSensor(
                device_data,
                f"{topic_root}/door/timeOfFlight",
                "door_time_of_flight",
                entity_category=EntityCategory.DIAGNOSTIC,
                icon="mdi:timer-sand",
            ),
            OmletTextSensor(
                device_data,
                f"{topic_root}/powerSource",
                "power_source",
                icon="mdi:power-plug",
            ),
            OmletTextSensor(
                device_data,
                f"{topic_root}/door/time/lastOpen",
                "last_open",
                icon="mdi:door-open",
            ),
            OmletTextSensor(
                device_data,
                f"{topic_root}/door/time/lastClose",
                "last_close",
                icon="mdi:door-closed",
            ),
            OmletTextSensor(
                device_data,
                f"{topic_root}/general/resetReason",
                "reset_reason",
                icon="mdi:restart-alert",
            ),
            OmletTextSensor(
                device_data,
                f"{topic_root}/general/wakeupReason",
                "wakeup_reason",
                icon="mdi:alarm",
            ),
            OmletTextSensor(
                device_data,
                f"{topic_root}/general/disconnectReason",
                "disconnect_reason",
                icon="mdi:lan-disconnect",
            ),
            OmletTextSensor(
                device_data,
                f"{topic_root}/bluetooth/signalStrength",
                "bluetooth_signal",
                icon="mdi:bluetooth",
            ),
            OmletTextSensor(
                device_data,
                f"{topic_root}/wifi/ssid",
                "wifi_ssid",
                icon="mdi:wifi",
                enabled_default=False,
            ),
            OmletTextSensor(
                device_data,
                f"{topic_root}/firmware/current",
                "firmware_current",
                icon="mdi:chip",
            ),
            OmletTextSensor(
                device_data,
                f"{topic_root}/firmware/previous",
                "firmware_previous",
                icon="mdi:chip",
            ),
            OmletTextSensor(
                device_data,
                f"{topic_root}/firmware/lastCheck",
                "firmware_last_check",
                icon="mdi:calendar-check",
            ),
            OmletTextSensor(
                device_data,
                timezone_topic,
                "device_timezone",
                icon="mdi:earth",
            ),
            OmletDeviceClockSensor(
                device_data,
                datetime_topic,
                timezone_topic,
            ),
        ]
    )


class OmletDeviceClockSensor(SensorEntity, RestoreEntity):
    """Monitor device time and correct it when it drifts."""

    _DRIFT_THRESHOLD_SECONDS = 60

    def __init__(
        self,
        device_data: OmletDeviceData,
        datetime_topic: str,
        timezone_topic: str,
    ) -> None:
        """Initialize the device clock monitor."""
        self._device_data = device_data
        self._datetime_topic = datetime_topic
        self._timezone_topic = timezone_topic
        self._datetime_payload: str | None = None
        self._timezone_payload: str | None = None
        self._sync_in_progress: bool = False
        self._attr_unique_id = f"{device_data.device_id}_device_datetime"
        self._attr_translation_key = "device_datetime"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:clock-outline"
        self._attr_has_entity_name = True
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_data.device_id)},
            "name": f"Omlet Coop {device_data.device_id}",
            "manufacturer": "Omlet",
            "model": "Smart Coop Autodoor",
        }
        self._attr_native_value = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to device time and time zone reports."""
        await super().async_added_to_hass()
        self._device_data.register_entity(self)
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (
            "unknown",
            "unavailable",
        ):
            self._attr_native_value = last_state.state
        self.async_on_remove(
            await mqtt.async_subscribe(
                self.hass, self._datetime_topic, self._handle_datetime_message
            )
        )
        self.async_on_remove(
            await mqtt.async_subscribe(
                self.hass, self._timezone_topic, self._handle_timezone_message
            )
        )

    @callback
    def _handle_datetime_message(self, message: mqtt.ReceiveMessage) -> None:
        """Check newly reported device time for drift."""
        payload = message_payload(message).strip()
        if not payload:
            return
        self._datetime_payload = payload
        self._attr_native_value = payload
        self.async_write_ha_state()
        self.hass.async_create_task(self._async_sync_if_needed())

    @callback
    def _handle_timezone_message(self, message: mqtt.ReceiveMessage) -> None:
        """Recheck the clock when the device time zone is reported."""
        payload = message_payload(message).strip()
        if not payload:
            return
        self._timezone_payload = payload
        if self._datetime_payload is not None:
            self.hass.async_create_task(self._async_sync_if_needed())

    async def _async_sync_if_needed(self) -> None:
        """Publish the current device-local time when drift exceeds one minute."""
        if (
            self._sync_in_progress
            or self._datetime_payload is None
            or self._timezone_payload is None
        ):
            return

        self._sync_in_progress = True
        try:
            reported_time = parse_device_datetime(self._datetime_payload)
            current_time = device_local_datetime(
                self._timezone_payload, datetime.now(timezone.utc)
            ).replace(microsecond=0)
            drift = (current_time - reported_time).total_seconds()
            if abs(drift) <= self._DRIFT_THRESHOLD_SECONDS:
                return

            corrected_time = format_device_datetime(current_time)
            _LOGGER.info(
                "Device clock differs by %.0f seconds; publishing a correction",
                drift,
            )
            await async_publish_commands(
                self.hass,
                self._device_data,
                [(self._datetime_topic, corrected_time)],
            )
        except ValueError as err:
            _LOGGER.warning("Could not evaluate device clock drift: %s", err)
        except HomeAssistantError:
            _LOGGER.exception("Could not publish device clock correction")
        finally:
            self._sync_in_progress = False


class OmletSensor(SensorEntity, RestoreEntity):
    """Represent a numeric value published by the device."""

    def __init__(
        self,
        device_data: OmletDeviceData,
        topic: str,
        key: str,
        device_class: SensorDeviceClass | None = None,
        unit: str | None = None,
        entity_category: EntityCategory | None = None,
        icon: str | None = None,
    ) -> None:
        """Initialize the sensor."""
        self._device_data = device_data
        device_id = device_data.device_id
        self._topic = topic
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_entity_category = entity_category
        self._attr_icon = icon
        self._attr_has_entity_name = True
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": f"Omlet Coop {device_id}",
            "manufacturer": "Omlet",
            "model": "Smart Coop Autodoor",
        }
        self._attr_native_value: float | int | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last state and subscribe to the MQTT topic."""
        await super().async_added_to_hass()
        self._device_data.register_entity(self)
        last_state = await self.async_get_last_state()
        if last_state is not None:
            try:
                self._attr_native_value = float(last_state.state)
                if self._attr_native_value.is_integer():
                    self._attr_native_value = int(self._attr_native_value)
            except ValueError:
                _LOGGER.warning(
                    "Could not restore numeric state %r for %s",
                    last_state.state,
                    self._topic,
                )

        self.async_on_remove(
            await mqtt.async_subscribe(
                self.hass, self._topic, self._handle_message
            )
        )

    @callback
    def _handle_message(self, message: mqtt.ReceiveMessage) -> None:
        """Update the sensor for a valid, non-empty MQTT message."""
        payload = message_payload(message).strip()
        if not payload:
            return
        try:
            value = float(payload)
        except ValueError:
            _LOGGER.warning(
                "Unexpected numeric value %r received on %s", payload, self._topic
            )
            return
        if value.is_integer():
            value = int(value)
        self._attr_native_value = value
        self.async_write_ha_state()


class OmletTextSensor(SensorEntity, RestoreEntity):
    """Represent a text value published by the device."""

    def __init__(
        self,
        device_data: OmletDeviceData,
        topic: str,
        key: str,
        icon: str | None = None,
        enabled_default: bool = True,
    ) -> None:
        """Initialize the text sensor."""
        self._device_data = device_data
        device_id = device_data.device_id
        self._topic = topic
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_translation_key = key
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = icon
        self._attr_entity_registry_enabled_default = enabled_default
        self._attr_has_entity_name = True
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": f"Omlet Coop {device_id}",
            "manufacturer": "Omlet",
            "model": "Smart Coop Autodoor",
        }
        self._attr_native_value: str | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last state and subscribe to the MQTT topic."""
        await super().async_added_to_hass()
        self._device_data.register_entity(self)
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (
            "unknown",
            "unavailable",
        ):
            self._attr_native_value = last_state.state

        self.async_on_remove(
            await mqtt.async_subscribe(
                self.hass, self._topic, self._handle_message
            )
        )

    @callback
    def _handle_message(self, message: mqtt.ReceiveMessage) -> None:
        """Update the sensor for a non-empty MQTT message."""
        payload = message_payload(message).strip()
        if not payload:
            return
        self._attr_native_value = payload
        self.async_write_ha_state()
