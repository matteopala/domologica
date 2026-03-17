"""Binary Sensor platform for the Domologica UNA Automation integration.

Handles: StatusElement (system status, alarm indicators).
All StatusElements are read-only indicators.

Alarm-related StatusElements detected by the coordinator receive
specialised treatment:
  - alarm_state_eid  → device_class POWER,  normal logic
                        (statuson = armed/on, statusoff = disarmed/off)
  - alarm_siren_eid  → device_class SOUND,  **inverted** logic
                        (statuson = siren silent → is_on=False,
                         statusoff = siren sounding → is_on=True)
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
    """Deduce device_class from element name (fallback for non-alarm sensors)."""
    name_lower = name.lower()
    if "allarme" in name_lower or "alarm" in name_lower or "antifurto" in name_lower:
        return BinarySensorDeviceClass.SAFETY
    if "stato" in name_lower or "status" in name_lower:
        return BinarySensorDeviceClass.POWER
    return BinarySensorDeviceClass.PROBLEM


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    alarm_state_eid = coordinator.alarm_state_eid
    alarm_siren_eid = coordinator.alarm_siren_eid

    for eid, info in coordinator.element_info.items():
        if info["class"] != "StatusElement":
            continue

        if eid == alarm_siren_eid:
            # Siren sensor: inverted logic, SOUND device class
            entities.append(
                DomologicaAlarmSirenSensor(coordinator, eid, info)
            )
        elif eid == alarm_state_eid:
            # Alarm armed/disarmed: POWER device class, normal logic
            entities.append(
                DomologicaStatusSensor(
                    coordinator, eid, info,
                    device_class=BinarySensorDeviceClass.POWER,
                )
            )
        else:
            entities.append(
                DomologicaStatusSensor(coordinator, eid, info)
            )

    _LOGGER.info("Loading %s binary sensor entities", len(entities))
    async_add_entities(entities)


class DomologicaStatusSensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for StatusElement (status on/off)."""

    def __init__(self, coordinator, eid, info, device_class=None):
        super().__init__(coordinator)
        self._eid = eid
        self._attr_name = info["name"]
        self._attr_device_class = (
            device_class if device_class is not None
            else _guess_device_class(info["name"])
        )

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


class DomologicaAlarmSirenSensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for the alarm siren with inverted logic.

    The Vesta controller reports:
      statuson  → siren is silent  (normal)
      statusoff → siren is sounding (alarm triggered)

    This sensor inverts the value so that:
      is_on = True  → siren is sounding
      is_on = False → siren is silent
    """

    _attr_device_class = BinarySensorDeviceClass.SOUND

    def __init__(self, coordinator, eid, info):
        super().__init__(coordinator)
        self._eid = eid
        self._attr_name = info["name"]

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
        # Inverted: statuson (is_on=True from parser) means siren OFF
        return not data.get("is_on", True)
