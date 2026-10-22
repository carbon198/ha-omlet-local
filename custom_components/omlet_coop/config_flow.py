"""Config flow for the Omlet smart coop autodoor integration."""

from typing import Any

import probatio

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import CONF_DEVICE_ID, DOMAIN


class OmletCoopConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Omlet smart coop autodoor."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure the device ID used in its MQTT topics."""
        errors: dict[str, str] = {}
        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID].strip()
            if (
                not device_id
                or "/" in device_id
                or "+" in device_id
                or "#" in device_id
            ):
                errors[CONF_DEVICE_ID] = "invalid_device_id"
            else:
                await self.async_set_unique_id(device_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Omlet Coop {device_id}",
                    data={CONF_DEVICE_ID: device_id},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=probatio.Schema(
                {probatio.Required(CONF_DEVICE_ID): str}
            ),
            errors=errors,
        )
