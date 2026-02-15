"""DataUpdateCoordinator for the Domologica UNA Automation integration."""
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
) 

from .api_client import DomologicaApiClient
from .const import (
    DEFAULT_POLLING_INTERVAL,
    DEFAULT_TRAVEL_TIME,
    DOMAIN,
    INTEGRATION_NAME,
    MANUFACTURER,
    MODEL,
)
from .parsers import parse_all_statuses

_LOGGER = logging.getLogger(__name__)


class DomologicaCoordinator(DataUpdateCoordinator):
    """Central data manager for the Domologica controller."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        username: str,
        password: str,
        entry: ConfigEntry,
    ) -> None:
        self.entry = entry
        self.element_info: dict[str, dict] = {}

        # API client
        self.api_client = DomologicaApiClient(hass, host, username, password)

        # Polling interval
        scan_interval = entry.options.get(
            "polling_interval",
            entry.data.get("polling_interval", DEFAULT_POLLING_INTERVAL),
        )
        self.travel_time = entry.options.get(
            "travel_time",
            entry.data.get("travel_time", DEFAULT_TRAVEL_TIME),
        )

        # Unique identifier for the device registry
        self.device_id = host.replace("http://", "").replace("https://", "").replace(".", "_").replace(":", "_")
        self.device_name = f"{INTEGRATION_NAME} ({host.replace('http://', '').replace('https://', '')})"

        super().__init__(
            hass,
            _LOGGER,
            name=INTEGRATION_NAME,
            update_interval=timedelta(seconds=scan_interval),
        )

    @property
    def device_info_dict(self) -> dict:
        """Device information for the main controller."""
        return {
            "identifiers": {(DOMAIN, self.device_id)},
            "name": self.device_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
            "sw_version": self.entry.data.get("sw_version", ""),
            "configuration_url": self.api_client.base_url,
        }

    def delios_device_info_dict(self, eid: str, element_name: str) -> dict:
        """Device information for the Delios inverter (separate device)."""
        return {
            "identifiers": {(DOMAIN, f"{self.device_id}_delios_{eid}")},
            "name": element_name,
            "manufacturer": "Delios",
            "model": "Inverter",
            "via_device": (DOMAIN, self.device_id),
        }

    async def async_setup(self) -> bool:
        """Discover elements from the controller."""
        _LOGGER.info("Starting discovery on %s", self.api_client.base_url)

        self.element_info = await self.api_client.async_discover_elements()

        if not self.element_info:
            _LOGGER.error("No elements found during discovery")
            return False

        # Filter out Delios elements if not enabled
        enable_delios = self.entry.options.get(
            "enable_delios",
            self.entry.data.get("enable_delios", False),
        )
        if not enable_delios:
            before = len(self.element_info)
            self.element_info = {
                eid: info for eid, info in self.element_info.items()
                if info["class"] != "DeliosMainUnitElement"
            }
            skipped = before - len(self.element_info)
            if skipped:
                _LOGGER.info("Delios disabled: skipped %s elements", skipped)

        # Apply custom names from onboarding
        custom_names = self.entry.data.get("custom_names", {})
        for eid, custom_name in custom_names.items():
            if eid in self.element_info and custom_name:
                _LOGGER.debug(
                    "Custom name for %s: %s -> %s",
                    eid, self.element_info[eid]["name"], custom_name,
                )
                self.element_info[eid]["name"] = custom_name

        _LOGGER.info(
            "Discovery completed: %s elements found", len(self.element_info)
        )

        # Initial data fetch
        await self.async_config_entry_first_refresh()
        return True

    async def _async_update_data(self) -> dict:
        """Periodic status retrieval via XML polling."""
        root = await self.api_client.async_fetch_all_statuses()

        if root is None:
            raise UpdateFailed("Error retrieving XML statuses")

        return parse_all_statuses(root, self.element_info)
