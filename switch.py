"""Switch platform for the Domologica UNA Automation integration.

Handles: PowerMenagementElement (load management start/stop).
"""
import logging

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        DomologicaPowerSwitch(coordinator, eid, info)
        for eid, info in coordinator.element_info.items()
        if info["class"] == "PowerMenagementElement"
    ]
    _LOGGER.info("Loading %s switch entities", len(entities))
    async_add_entities(entities)


class DomologicaPowerSwitch(CoordinatorEntity, SwitchEntity):
    """Switch for load management start/stop (PowerMenagementElement)."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator, eid, info):
        super().__init__(coordinator)
        self._eid = eid
        self._attr_name = info["name"]
        self._attr_icon = "mdi:flash-auto"

    @property
    def unique_id(self):
        return f"domologica_{self._eid}_switch"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(**self.coordinator.device_info_dict)

    @property
    def is_on(self) -> bool:
        data = (self.coordinator.data or {}).get(self._eid)
        if data:
            return data.get("is_running", False)
        return False

    @property
    def extra_state_attributes(self) -> dict:
        data = (self.coordinator.data or {}).get(self._eid, {})
        attrs = {}
        if data.get("current_power") is not None:
            attrs["current_power_w"] = data["current_power"]
        if data.get("max_power") is not None:
            attrs["max_power_w"] = data["max_power"]
        if data.get("is_normal") is not None:
            attrs["normal_measure"] = data["is_normal"]
        return attrs

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.api_client.async_switch_command(self._eid, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.api_client.async_switch_command(self._eid, False)
        await self.coordinator.async_request_refresh()
