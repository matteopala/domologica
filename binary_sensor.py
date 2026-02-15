"""Binary Sensor platform for the Domologica UNA Automation integration.

Handles: StatusElement (system status, alarms).
"""
import logging 

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _guess_device_class(name: str) -> BinarySensorDeviceClass:
    """Deduce device_class from element name."""
    name_lower = name.lower()
    if "allarme" in name_lower or "alarm" in name_lower or "antifurto" in name_lower or "theft" in name_lower:
        return BinarySensorDeviceClass.SAFETY
    if "stato" in name_lower or "status" in name_lower:
        return BinarySensorDeviceClass.POWER
    return BinarySensorDeviceClass.PROBLEM


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        DomologicaStatusSensor(coordinator, eid, info)
        for eid, info in coordinator.element_info.items()
        if info["class"] == "StatusElement"
    ]
    _LOGGER.info("Loading %s binary sensor entities", len(entities))
    async_add_entities(entities)


class DomologicaStatusSensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for StatusElement (status on/off)."""

    def __init__(self, coordinator, eid, info):
        super().__init__(coordinator)
        self._eid = eid
        self._attr_name = info["name"]
        self._attr_device_class = _guess_device_class(info["name"])

    @property
    def unique_id(self):
        return f"domologica_{self._eid}_binary"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(**self.coordinator.device_info_dict)

    @property
    def is_on(self) -> bool | None:
        data = (self.coordinator.data or {}).get(self._eid)
        if data is None:
            return None
        return data.get("is_on", False)
