"""Constants for the Omlet smart coop autodoor integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "omlet_coop"
CONF_DEVICE_ID = "device_id"
DEFAULT_STAY_ALIVE = 60
MIN_STAY_ALIVE = 30
MAX_STAY_ALIVE = 9000
DEVICE_AVAILABILITY_TIMEOUT = timedelta(minutes=15)
PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.COVER,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.TIME,
]

TOPIC_ROOT = "device/{device_id}/status"
CONFIG_ROOT = "device/{device_id}/configuration/door"
ACTION_ROOT = "device/{device_id}/action"
