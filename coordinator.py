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

        # Auto-detected alarm sensor IDs (populated during discovery)
        self._auto_alarm_state_eid: str = ""
        self._auto_alarm_siren_eid: str = ""

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

    @property
    def alarm_pin(self) -> str:
        """Alarm PIN (options take precedence over initial config)."""
        return self.entry.options.get(
            "alarm_pin",
            self.entry.data.get("alarm_pin", ""),
        )

    @property
    def alarm_state_eid(self) -> str:
        """Element ID of the StatusElement for armed/disarmed state.

        Priority: options > config data > auto-detected.
        """
        return (
            self.entry.options.get("alarm_state_eid")
            or self.entry.data.get("alarm_state_eid")
            or self._auto_alarm_state_eid
        )

    @property
    def alarm_siren_eid(self) -> str:
        """Element ID of the StatusElement for siren/triggered state.

        Priority: options > config data > auto-detected.
        """
        return (
            self.entry.options.get("alarm_siren_eid")
            or self.entry.data.get("alarm_siren_eid")
            or self._auto_alarm_siren_eid
        )

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

        # Auto-detect alarm sensors from real polling data
        self._auto_detect_alarm_sensors()

        return True

    def _auto_detect_alarm_sensors(self) -> None:
        """Detect alarm StatusElements from first-fetch polling data.

        Heuristic:
        1. Only StatusElements that report statuson/statusoff in their
           runtime status have ``has_status_flag=True`` — these are the
           alarm-related sensors (other StatusElements use different IDs).
        2. At setup time the siren is not sounding, so the siren sensor
           reports ``statuson`` (is_on=True).  The alarm state sensor
           reports ``statusoff`` (is_on=False) because the alarm is
           typically disarmed during configuration.

        Only runs when a VirtualKeypadElement exists and the EIDs are
        not already set manually via options / config data.
        """
        # Skip if both are already manually configured
        if self.alarm_state_eid and self.alarm_siren_eid:
            return

        has_keypad = any(
            info["class"] == "VirtualKeypadElement"
            for info in self.element_info.values()
        )
        if not has_keypad:
            return

        data = self.data or {}

        # Collect StatusElements whose polling data has has_status_flag
        flagged: list[tuple[str, dict, dict]] = []
        for eid, info in self.element_info.items():
            if info["class"] != "StatusElement":
                continue
            edata = data.get(eid, {})
            if edata.get("has_status_flag"):
                flagged.append((eid, info, edata))

        if len(flagged) != 2:
            if flagged:
                _LOGGER.warning(
                    "Expected 2 alarm StatusElements with statuson/statusoff, "
                    "found %s — skipping auto-detection. "
                    "Set alarm_state_eid / alarm_siren_eid manually in options.",
                    len(flagged),
                )
            return

        # The one currently ON is the siren (not sounding at setup)
        # The one currently OFF is the alarm state (disarmed at setup)
        for eid, info, edata in flagged:
            if edata.get("is_on"):
                if not self._auto_alarm_siren_eid:
                    self._auto_alarm_siren_eid = eid
                    _LOGGER.info(
                        "Auto-detected alarm siren sensor: id=%s, name=%s "
                        "(statuson at startup = siren silent)",
                        eid, info["name"],
                    )
            else:
                if not self._auto_alarm_state_eid:
                    self._auto_alarm_state_eid = eid
                    _LOGGER.info(
                        "Auto-detected alarm state sensor: id=%s, name=%s "
                        "(statusoff at startup = alarm disarmed)",
                        eid, info["name"],
                    )

    async def _async_update_data(self) -> dict:
        """Periodic status retrieval via XML polling."""
        root = await self.api_client.async_fetch_all_statuses()

        if root is None:
            raise UpdateFailed("Error retrieving XML statuses")

        return parse_all_statuses(root, self.element_info)
