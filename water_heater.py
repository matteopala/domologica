"""Water Heater platform for the Domologica UNA Automation integration.

Handles: ModbusSamsungElement (Samsung EHS2 - Domestic Hot Water).
"""
import logging

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, WATER_HEATER_MODES, WATER_HEATER_MODE_ACTIONS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        DomologicaWaterHeater(coordinator, eid, info)
        for eid, info in coordinator.element_info.items()
        if info["class"] == "ModbusSamsungElement"
    ]
    _LOGGER.info("Loading %s water heater entities", len(entities))
    async_add_entities(entities)


class DomologicaWaterHeater(CoordinatorEntity, WaterHeaterEntity):
    """Water heater entity for Samsung EHS2 Domestic Hot Water."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 30.0
    _attr_max_temp = 65.0

    def __init__(self, coordinator, eid, info):
        super().__init__(coordinator)
        self._eid = eid
        self._attr_name = info["name"]
        self._attr_supported_features = (
            WaterHeaterEntityFeature.TARGET_TEMPERATURE
            | WaterHeaterEntityFeature.OPERATION_MODE
            | WaterHeaterEntityFeature.ON_OFF
        )
        self._attr_operation_list = WATER_HEATER_MODES

    @property
    def unique_id(self):
        return f"domologica_{self._eid}_water_heater"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(**self.coordinator.device_info_dict)

    @property
    def _data(self) -> dict:
        return (self.coordinator.data or {}).get(self._eid, {})

    @property
    def current_temperature(self) -> float | None:
        return self._data.get("h2o_measured")

    @property
    def target_temperature(self) -> float | None:
        return self._data.get("h2o_setted")

    @property
    def current_operation(self) -> str | None:
        h2o_mode = self._data.get("h2o_mode")
        if h2o_mode is not None:
            mode_map = {0: "eco", 1: "standard", 2: "power", 3: "force"}
            return mode_map.get(h2o_mode, "standard")
        return "standard"

    @property
    def is_away_mode_on(self) -> bool:
        return not self._data.get("is_on", False)

    @property
    def extra_state_attributes(self) -> dict:
        attrs = {}
        if self._data.get("water_in") is not None:
            attrs["water_in_temperature"] = self._data["water_in"]
        if self._data.get("water_out") is not None:
            attrs["water_out_temperature"] = self._data["water_out"]
        if self._data.get("error_code") is not None:
            attrs["error_code"] = self._data["error_code"]
        if self._data.get("is_connected") is not None:
            attrs["connected"] = self._data["is_connected"]
        if self._data.get("is_heating") is not None:
            attrs["heating"] = self._data["is_heating"]
        if self._data.get("h2o_operation") is not None:
            attrs["h2o_operation"] = self._data["h2o_operation"]
        return attrs

    async def async_set_temperature(self, **kwargs) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is not None:
            await self.coordinator.api_client.async_water_heater_set_temp(
                self._eid, temp
            )
            await self.coordinator.async_request_refresh()

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        action = WATER_HEATER_MODE_ACTIONS.get(operation_mode)
        if action:
            await self.coordinator.api_client.async_water_heater_set_mode(
                self._eid, action
            )
            await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.api_client.async_light_switch(self._eid, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.api_client.async_light_switch(self._eid, False)
        await self.coordinator.async_request_refresh()
