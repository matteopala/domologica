"""Climate platform for the Domologica UNA Automation integration.

Manages: ThermostatElement, ModbusSamsungAir2Element.
"""
import logging 

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, THERMOSTAT_PRESET_MAP, THERMOSTAT_PRESET_REVERSE

_LOGGER = logging.getLogger(__name__)

FAN_MODES = ["auto", "low", "medium", "high"]


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    for eid, info in coordinator.element_info.items():
        if info["class"] == "ThermostatElement":
            entities.append(DomologicaThermostat(coordinator, eid, info))
        elif info["class"] == "ModbusSamsungAir2Element":
            entities.append(DomologicaSamsungAC(coordinator, eid, info))

    _LOGGER.info("Loading %s climate entities", len(entities))
    async_add_entities(entities)


# ── Thermostat ───────────────────────────────────────────────


class DomologicaThermostat(CoordinatorEntity, ClimateEntity):
    """Climate entity for UNA/Vesta thermostat."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_min_temp = 5.0
    _attr_max_temp = 35.0

    def __init__(self, coordinator, eid, info):
        super().__init__(coordinator)
        self._eid = eid
        self._attr_name = info["name"]
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.PRESET_MODE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL]
        self._attr_preset_modes = ["comfort", "eco", "schedule"]
        self._attr_fan_modes = FAN_MODES

    @property
    def unique_id(self):
        return f"domologica_{self._eid}_climate"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(**self.coordinator.device_info_dict)

    @property
    def _data(self) -> dict:
        return (self.coordinator.data or {}).get(self._eid, {})

    @property
    def current_temperature(self) -> float | None:
        return self._data.get("temperature")

    @property
    def target_temperature(self) -> float | None:
        season = self._data.get("season", "Winter")
        if season == "Winter":
            return self._data.get("t_max")
        return self._data.get("t_min")

    @property
    def hvac_mode(self) -> HVACMode:
        t_mode = self._data.get("t_mode", "Off")
        if t_mode == "Off":
            return HVACMode.OFF
        season = self._data.get("season", "Winter")
        return HVACMode.HEAT if season == "Winter" else HVACMode.COOL

    @property
    def hvac_action(self) -> HVACAction:
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if self._data.get("zone_active_winter"):
            return HVACAction.HEATING
        if self._data.get("zone_active_summer"):
            return HVACAction.COOLING
        return HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        t_mode = self._data.get("t_mode", "Off")
        return THERMOSTAT_PRESET_MAP.get(t_mode)

    @property
    def fan_mode(self) -> str:
        speed = self._data.get("speed", 0) or 0
        if speed <= 0:
            return "auto"
        if speed <= 33:
            return "low"
        if speed <= 66:
            return "medium"
        return "high"

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "season": self._data.get("season"),
            "t_mode": self._data.get("t_mode"),
            "delta_t": self._data.get("delta_t"),
            "reactivity": self._data.get("reactivity"),
            "calibration": self._data.get("calibration"),
        }

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        api = self.coordinator.api_client
        if hvac_mode == HVACMode.OFF:
            await api.async_thermostat_set_mode(self._eid, "Off")
        elif hvac_mode == HVACMode.HEAT:
            await api.async_thermostat_set_season(self._eid, "Winter")
            if self._data.get("t_mode") == "Off":
                await api.async_thermostat_set_mode(self._eid, "TMax")
        elif hvac_mode == HVACMode.COOL:
            await api.async_thermostat_set_season(self._eid, "Summer")
            if self._data.get("t_mode") == "Off":
                await api.async_thermostat_set_mode(self._eid, "TMin")
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        api = self.coordinator.api_client
        season = self._data.get("season", "Winter")
        if season == "Winter":
            await api.async_thermostat_set_temp_max(self._eid, temp)
        else:
            await api.async_thermostat_set_temp_min(self._eid, temp)
        await self.coordinator.async_request_refresh()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        vesta_mode = THERMOSTAT_PRESET_REVERSE.get(preset_mode)
        if vesta_mode:
            await self.coordinator.api_client.async_thermostat_set_mode(
                self._eid, vesta_mode
            )
            await self.coordinator.async_request_refresh()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        speed_map = {"auto": 0, "low": 33, "medium": 66, "high": 100}
        speed = speed_map.get(fan_mode, 0)
        await self.coordinator.api_client.async_thermostat_set_speed(
            self._eid, speed
        )
        await self.coordinator.async_request_refresh()


# ── Samsung AC ───────────────────────────────────────────────

# Mapping from hvac_mode HA → Vesta API action
SAMSUNG_HVAC_ACTIONS = {
    HVACMode.HEAT: "setseasonwinter",
    HVACMode.COOL: "setseasonsummer",
    HVACMode.AUTO: "Set AC unit Mode Auto",
    HVACMode.DRY: "Set AC unit Mode Dry",
    HVACMode.FAN_ONLY: "Set AC unit Mode Fan",
}


class DomologicaSamsungAC(CoordinatorEntity, ClimateEntity):
    """Climate entity for Samsung air conditioners via Modbus."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1.0
    _attr_min_temp = 16.0
    _attr_max_temp = 30.0

    def __init__(self, coordinator, eid, info):
        super().__init__(coordinator)
        self._eid = eid
        self._attr_name = info["name"]
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )
        self._attr_hvac_modes = [
            HVACMode.OFF,
            HVACMode.HEAT,
            HVACMode.COOL,
            HVACMode.AUTO,
            HVACMode.DRY,
            HVACMode.FAN_ONLY,
        ]
        self._attr_fan_modes = FAN_MODES

    @property
    def unique_id(self):
        return f"domologica_{self._eid}_climate"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(**self.coordinator.device_info_dict)

    @property
    def _data(self) -> dict:
        return (self.coordinator.data or {}).get(self._eid, {})

    @property
    def current_temperature(self) -> float | None:
        return self._data.get("current_temp")

    @property
    def target_temperature(self) -> float | None:
        return self._data.get("target_temp")

    @property
    def hvac_mode(self) -> HVACMode:
        if not self._data.get("is_on", False):
            return HVACMode.OFF
        mode = self._data.get("mode", "off")
        mode_map = {
            "heat": HVACMode.HEAT,
            "cool": HVACMode.COOL,
            "auto": HVACMode.AUTO,
            "dry": HVACMode.DRY,
            "fan_only": HVACMode.FAN_ONLY,
        }
        return mode_map.get(mode, HVACMode.AUTO)

    @property
    def hvac_action(self) -> HVACAction:
        if not self._data.get("is_on", False):
            return HVACAction.OFF
        mode = self._data.get("mode", "off")
        delta_t = self._data.get("delta_t", 0) or 0
        if mode == "heat":
            return HVACAction.HEATING if delta_t > 0 else HVACAction.IDLE
        if mode == "cool":
            return HVACAction.COOLING if delta_t < 0 else HVACAction.IDLE
        if mode == "dry":
            return HVACAction.DRYING
        if mode == "fan_only":
            return HVACAction.FAN
        return HVACAction.IDLE

    @property
    def fan_mode(self) -> str:
        speed = self._data.get("fan_speed", 0) or 0
        if speed <= 0:
            return "auto"
        if speed <= 33:
            return "low"
        if speed <= 66:
            return "medium"
        return "high"

    @property
    def extra_state_attributes(self) -> dict:
        attrs = {}
        if self._data.get("error_code"):
            attrs["error_code"] = self._data["error_code"]
        if self._data.get("is_connected") is not None:
            attrs["connected"] = self._data["is_connected"]
        if self._data.get("delta_t") is not None:
            attrs["delta_t"] = self._data["delta_t"]
        return attrs

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        api = self.coordinator.api_client
        if hvac_mode == HVACMode.OFF:
            await api.async_light_switch(self._eid, False)
        else:
            # Turn on if off
            if not self._data.get("is_on", False):
                await api.async_light_switch(self._eid, True)
            # Set mode
            action = SAMSUNG_HVAC_ACTIONS.get(hvac_mode)
            if action:
                await api.async_samsung_ac_set_mode(self._eid, action)
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is not None:
            await self.coordinator.api_client.async_samsung_ac_set_temp(
                self._eid, temp
            )
            await self.coordinator.async_request_refresh()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        speed_map = {"auto": 0, "low": 33, "medium": 66, "high": 100}
        speed = speed_map.get(fan_mode, 0)
        await self.coordinator.api_client.async_samsung_ac_set_fan(
            self._eid, speed
        )
        await self.coordinator.async_request_refresh()
