"""Button platform for the Domologica UNA Automation integration.

Handles: SwitchElement (scenarios), UpDownSwitchElement (general blinds command).
"""
import logging 

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    for eid, info in coordinator.element_info.items():
        if info["class"] == "SwitchElement":
            entities.append(
                DomologicaScenarioButton(
                    coordinator, eid, info["name"], "simulatepressure",
                )
            )

        elif info["class"] == "UpDownSwitchElement":
            entities.append(
                DomologicaUpDownButton(
                    coordinator, eid, f"{info['name']} Up", "simulateup",
                )
            )
            entities.append(
                DomologicaUpDownButton(
                    coordinator, eid, f"{info['name']} Down", "simulatedown",
                )
            )

    _LOGGER.info("Loading %s button entities", len(entities))
    async_add_entities(entities)


class DomologicaScenarioButton(CoordinatorEntity, ButtonEntity):
    """Button for scenario activation (SwitchElement)."""

    def __init__(self, coordinator, eid, name, action):
        super().__init__(coordinator)
        self._eid = eid
        self._action = action
        self._attr_name = name

    @property
    def unique_id(self):
        return f"domologica_{self._eid}_button_{self._action}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(**self.coordinator.device_info_dict)

    async def async_press(self) -> None:
        await self.coordinator.api_client.async_button_press(
            self._eid, self._action
        )


class DomologicaUpDownButton(CoordinatorEntity, ButtonEntity):
    """Button for general up/down command (UpDownSwitchElement)."""

    def __init__(self, coordinator, eid, name, action):
        super().__init__(coordinator)
        self._eid = eid
        self._action = action
        self._attr_name = name
        self._attr_icon = (
            "mdi:arrow-up-bold" if "up" in action else "mdi:arrow-down-bold"
        )

    @property
    def unique_id(self):
        return f"domologica_{self._eid}_button_{self._action}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(**self.coordinator.device_info_dict)

    async def async_press(self) -> None:
        await self.coordinator.api_client.async_button_press(
            self._eid, self._action
        )
