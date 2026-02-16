"""Alarm Control Panel platform for the Domologica UNA Automation integration.

Handles: StatusElement with 'antifurto' in the name (burglar alarm on/off).
Uses switchon/switchoff actions on the SideraHome API.
"""
import logging

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ALARM_KEYWORDS, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _is_alarm_element(info: dict) -> bool:
    """Return True if this StatusElement represents a burglar alarm."""
    name_lower = (info.get("name") or "").lower()
    return any(kw in name_lower for kw in ALARM_KEYWORDS)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        DomologicaAlarm(coordinator, eid, info)
        for eid, info in coordinator.element_info.items()
        if info["class"] == "StatusElement" and _is_alarm_element(info)
    ]
    _LOGGER.info("Loading %s alarm control panel entities", len(entities))
    async_add_entities(entities)


class DomologicaAlarm(CoordinatorEntity, AlarmControlPanelEntity):
    """Alarm control panel for StatusElement (antifurto on/off)."""

    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_AWAY
    )
    _attr_code_arm_required = False

    def __init__(self, coordinator, eid, info):
        super().__init__(coordinator)
        self._eid = eid
        self._attr_name = info["name"]

    @property
    def unique_id(self):
        return f"domologica_{self._eid}_alarm"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(**self.coordinator.device_info_dict)

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        data = (self.coordinator.data or {}).get(self._eid)
        if data is None:
            return None
        if data.get("is_on", False):
            return AlarmControlPanelState.ARMED_AWAY
        return AlarmControlPanelState.DISARMED

    async def async_alarm_disarm(self, code=None) -> None:
        """Send disarm (switchoff) command."""
        await self.coordinator.api_client.async_alarm_command(
            self._eid, arm=False
        )
        # Optimistic update
        if self.coordinator.data and self._eid in self.coordinator.data:
            self.coordinator.data[self._eid]["is_on"] = False
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_alarm_arm_away(self, code=None) -> None:
        """Send arm away (switchon) command."""
        await self.coordinator.api_client.async_alarm_command(
            self._eid, arm=True
        )
        # Optimistic update
        if self.coordinator.data and self._eid in self.coordinator.data:
            self.coordinator.data[self._eid]["is_on"] = True
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
