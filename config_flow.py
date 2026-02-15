"""Config flow for the Domologica UNA Automation integration.

Step 1: Connection and configuration parameters.
Step 2: Discovery and device name customization.
"""
import logging 

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import DEFAULT_POLLING_INTERVAL, DEFAULT_TRAVEL_TIME, DOMAIN, INTEGRATION_NAME, TYPE_LABELS
from .api_client import DomologicaApiClient

_LOGGER = logging.getLogger(__name__)


class DomologicaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup via UI."""

    VERSION = 2

    def __init__(self):
        """Initialize the config flow."""
        self._user_input: dict = {}
        self._discovered: dict = {}
        self._naming_key_to_eid: dict = {}

    async def async_step_user(self, user_input=None):
        """Step 1: Connection to the controller."""
        errors = {}

        if user_input is not None:
            try:
                client = DomologicaApiClient(
                    self.hass,
                    user_input["base_url"],
                    user_input["username"],
                    user_input["password"],
                )
                if await client.async_test_connection():
                    # Discover elements from the controller
                    discovered = await client.async_discover_elements()
                    self._user_input = user_input

                    # Filter out Delios elements if not enabled
                    if not user_input.get("enable_delios", False):
                        discovered = {
                            eid: info for eid, info in discovered.items()
                            if info["class"] != "DeliosMainUnitElement"
                        }

                    self._discovered = discovered

                    if self._discovered:
                        return await self.async_step_naming()

                    # No elements found: create entry without custom names
                    return self.async_create_entry(
                        title=f"{INTEGRATION_NAME} ({user_input['base_url']})",
                        data={**user_input, "custom_names": {}},
                    )
                else:
                    errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Error during connection test")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("base_url", default="http://"): str,
                    vol.Required("username"): str,
                    vol.Required("password"): str,
                    vol.Optional(
                        "polling_interval", default=DEFAULT_POLLING_INTERVAL
                    ): int,
                    vol.Optional(
                        "travel_time", default=DEFAULT_TRAVEL_TIME
                    ): int,
                    vol.Optional(
                        "enable_delios", default=False
                    ): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_naming(self, user_input=None):
        """Step 2: Device name customization."""
        if user_input is not None:
            custom_names = {}
            for key, value in user_input.items():
                if key in self._naming_key_to_eid:
                    eid = self._naming_key_to_eid[key]
                    custom_names[eid] = value.strip()

            return self.async_create_entry(
                title=f"{INTEGRATION_NAME} ({self._user_input['base_url']})",
                data={
                    **self._user_input,
                    "custom_names": custom_names,
                },
            )

        # Sort by type then by name for visual grouping
        sorted_elements = sorted(
            self._discovered.items(),
            key=lambda x: (x[1]["class"], x[1]["name"]),
        )

        # Dynamic schema: one name field per element
        schema = {}
        self._naming_key_to_eid = {}

        for eid, info in sorted_elements:
            type_label = TYPE_LABELS.get(info["class"], info["class"])
            name_key = f"{type_label} (ID {eid})"
            self._naming_key_to_eid[name_key] = eid
            schema[vol.Required(name_key, default=info["name"])] = str

        return self.async_show_form(
            step_id="naming",
            data_schema=vol.Schema(schema),
            description_placeholders={
                "count": str(len(self._discovered)),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return DomologicaOptionsFlowHandler()


class DomologicaOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle settings changes after installation."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(
            "polling_interval",
            self.config_entry.data.get("polling_interval", DEFAULT_POLLING_INTERVAL),
        )
        current_travel = self.config_entry.options.get(
            "travel_time",
            self.config_entry.data.get("travel_time", DEFAULT_TRAVEL_TIME),
        )
        current_delios = self.config_entry.options.get(
            "enable_delios",
            self.config_entry.data.get("enable_delios", False),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "polling_interval", default=current_interval
                    ): int,
                    vol.Optional(
                        "travel_time", default=current_travel
                    ): int,
                    vol.Optional(
                        "enable_delios", default=current_delios
                    ): bool,
                }
            ),
        )
