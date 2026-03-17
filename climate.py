"""Climate platform for the Domologica UNA Automation integration.

Manages: ThermostatElement, ModbusSamsungAir2Element.
Uses optimistic state updates: after sending a command the UI reflects
the expected state immediately; the next coordinator poll confirms or
corrects it.
"""
import logging

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import callback
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
        self._optimistic: dict = {}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Clear optimistic overrides when real data arrives."""
        self._optimistic.clear()
        super()._handle_coordinator_update()

    @property
    def unique_id(self):
        return f"domologica_{self._eid}_climate"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(**self.coordinator.device_info_dict)

    @property
    def _data(self) -> dict:
        real = (self.coordinator.data or {}).get(self._eid, {})
        if self._optimistic:
            merged = dict(real)
            merged.update(self._optimistic)
            return merged
        return real

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
            self._optimistic["t_mode"] = "Off"
        elif hvac_mode == HVACMode.HEAT:
            await api.async_thermostat_set_season(self._eid, "Winter")
            self._optimistic["season"] = "Winter"
            if self._data.get("t_mode") == "Off":
                await api.async_thermostat_set_mode(self._eid, "TMax")
                self._optimistic["t_mode"] = "TMax"
        elif hvac_mode == HVACMode.COOL:
            await api.async_thermostat_set_season(self._eid, "Summer")
            self._optimistic["season"] = "Summer"
            if self._data.get("t_mode") == "Off":
                await api.async_thermostat_set_mode(self._eid, "TMin")
                self._optimistic["t_mode"] = "TMin"
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        api = self.coordinator.api_client
        season = self._data.get("season", "Winter")
        if season == "Winter":
            await api.async_thermostat_set_temp_max(self._eid, temp)
            self._optimistic["t_max"] = temp
        else:
            await api.async_thermostat_set_temp_min(self._eid, temp)
            self._optimistic["t_min"] = temp
        self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        vesta_mode = THERMOSTAT_PRESET_REVERSE.get(preset_mode)
        if vesta_mode:
            await self.coordinator.api_client.async_thermostat_set_mode(
                self._eid, vesta_mode
            )
            self._optimistic["t_mode"] = vesta_mode
            self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        speed_map = {"auto": 0, "low": 33, "medium": 66, "high": 100}
        speed = speed_map.get(fan_mode, 0)
        await self.coordinator.api_client.async_thermostat_set_speed(
            self._eid, speed
        )
        self._optimistic["speed"] = speed
        self.async_write_ha_state()


# ── Samsung AC ───────────────────────────────────────────────

# Mapping from hvac_mode HA → Vesta API action
SAMSUNG_HVAC_ACTIONS = {
    HVACMode.HEAT: "setseasonwinter",
    HVACMode.COOL: "setseasonsummer",
}

# Mapping from hvac_mode HA → internal mode string
SAMSUNG_MODE_STRINGS = {
    HVACMode.HEAT: "heat",
    HVACMode.COOL: "cool",
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
        ]
        self._attr_fan_modes = FAN_MODES
        self._optimistic: dict = {}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Clear optimistic overrides when real data arrives."""
        self._optimistic.clear()
        super()._handle_coordinator_update()

    @property
    def unique_id(self):
        return f"domologica_{self._eid}_climate"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(**self.coordinator.device_info_dict)

    @property
    def _data(self) -> dict:
        real = (self.coordinator.data or {}).get(self._eid, {})
        if self._optimistic:
            merged = dict(real)
            merged.update(self._optimistic)
            return merged
        return real

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
        }
        return mode_map.get(mode, HVACMode.HEAT)

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
        return HVACAction.IDLE

    @property
    def fan_mode(self) -> str:
        speed = self._data.get("fan_speed", 0) or 0
        fan_map = {0: "auto", 1: "low", 2: "medium", 3: "high"}
        return fan_map.get(int(speed), "auto")

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
            self._optimistic["is_on"] = False
        else:
            if not self._data.get("is_on", False):
                await api.async_light_switch(self._eid, True)
            action = SAMSUNG_HVAC_ACTIONS.get(hvac_mode)
            if action:
                await api.async_samsung_ac_set_mode(self._eid, action)
            self._optimistic["is_on"] = True
            self._optimistic["mode"] = SAMSUNG_MODE_STRINGS.get(hvac_mode, "heat")
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is not None:
            await self.coordinator.api_client.async_samsung_ac_set_temp(
                self._eid, temp
            )
            self._optimistic["target_temp"] = temp
            self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        speed_map = {"auto": 0, "low": 1, "medium": 2, "high": 3}
        speed = speed_map.get(fan_mode, 0)
        await self.coordinator.api_client.async_samsung_ac_set_fan(
            self._eid, speed
        )
        self._optimistic["fan_speed"] = speed
        self.async_write_ha_state()
