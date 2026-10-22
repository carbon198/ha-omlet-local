"""MQTT command helpers for the Omlet smart coop autodoor."""

from collections.abc import Iterable

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant

from .const import ACTION_ROOT
from .models import OmletDeviceData


async def async_publish_retained(
    hass: HomeAssistant, commands: Iterable[tuple[str, str]]
) -> None:
    """Publish retained QoS 2 messages."""
    for topic, payload in commands:
        await mqtt.async_publish(
            hass,
            topic,
            payload,
            qos=2,
            retain=True,
        )


async def async_publish_commands(
    hass: HomeAssistant,
    device_data: OmletDeviceData,
    commands: Iterable[tuple[str, str]],
) -> None:
    """Wake the device using its configured duration, then send commands."""
    action_root = ACTION_ROOT.format(device_id=device_data.device_id)
    await async_publish_retained(
        hass,
        [
            (f"{action_root}/stayAlive", str(device_data.stay_alive)),
            *commands,
        ],
    )
