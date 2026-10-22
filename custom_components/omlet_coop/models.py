"""Runtime data for an Omlet smart coop autodoor."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .const import DEFAULT_STAY_ALIVE, DEVICE_AVAILABILITY_TIMEOUT


def message_payload(message: mqtt.ReceiveMessage) -> str:
    """Decode an MQTT message payload as UTF-8 text."""
    payload = message.payload
    if isinstance(payload, str):
        return payload
    return payload.decode()


@dataclass
class OmletDeviceData:
    """Mutable settings and shared device availability for all entities."""

    device_id: str
    stay_alive: int = DEFAULT_STAY_ALIVE
    _hass: HomeAssistant | None = field(default=None, init=False, repr=False)
    _last_check_in: datetime | None = field(default=None, init=False, repr=False)
    _unsubscribe: Callable[[], None] | None = field(
        default=None, init=False, repr=False
    )
    _cancel_timeout: Callable[[], None] | None = field(
        default=None, init=False, repr=False
    )
    _entities: set[Entity] = field(default_factory=set, init=False, repr=False)

    @property
    def available(self) -> bool:
        """Return whether the device has sent a fresh status publication."""
        return self._last_check_in is not None and (
            dt_util.utcnow() - self._last_check_in < DEVICE_AVAILABILITY_TIMEOUT
        )

    @property
    def last_check_in(self) -> datetime | None:
        """Return when the last fresh status publication was received."""
        return self._last_check_in

    async def async_setup(self, hass: HomeAssistant) -> None:
        """Listen for fresh publications from the device."""
        self._hass = hass
        self._unsubscribe = await mqtt.async_subscribe(
            hass,
            f"device/{self.device_id}/#",
            self._handle_device_message,
        )

    def async_unload(self) -> None:
        """Stop listening and cancel the pending availability timeout."""
        if self._cancel_timeout is not None:
            self._cancel_timeout()
            self._cancel_timeout = None
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        self._entities = set()

    def register_entity(self, entity: Entity) -> None:
        """Make an entity follow the shared device availability."""
        self._entities.add(entity)
        entity._attr_available = self.available
        entity.async_on_remove(lambda: self._entities.discard(entity))

    @callback
    def _handle_device_message(self, message: mqtt.ReceiveMessage) -> None:
        """Refresh availability for fresh messages, excluding command echoes."""
        if message.retain:
            return

        device_root = f"device/{self.device_id}"
        action_root = f"{device_root}/action/"
        door_config_root = f"{device_root}/configuration/door/"
        clock_topic = f"{device_root}/configuration/general/datetime"
        if (
            message.topic.startswith(action_root)
            and message_payload(message).strip()
        ) or (
            message.topic.startswith(door_config_root)
            or message.topic == clock_topic
        ):
            return

        was_available = self.available
        self._last_check_in = dt_util.utcnow()
        if self._cancel_timeout is not None:
            self._cancel_timeout()
        assert self._hass is not None
        self._cancel_timeout = async_call_later(
            self._hass,
            DEVICE_AVAILABILITY_TIMEOUT.total_seconds(),
            self._handle_timeout,
        )
        if not was_available:
            self._write_entity_states()

    @callback
    def _handle_timeout(self, _now: datetime) -> None:
        """Mark entities unavailable once the last check-in has expired."""
        if self.available:
            assert self._last_check_in is not None
            remaining = (
                self._last_check_in
                + DEVICE_AVAILABILITY_TIMEOUT
                - dt_util.utcnow()
            ).total_seconds()
            assert self._hass is not None
            self._cancel_timeout = async_call_later(
                self._hass, max(remaining, 0), self._handle_timeout
            )
            return

        self._cancel_timeout = None
        self._write_entity_states()

    @callback
    def _write_entity_states(self) -> None:
        """Write all entity states after an availability transition."""
        for entity in tuple(self._entities):
            entity._attr_available = self.available
            entity.async_write_ha_state()
