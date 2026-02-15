"""Sensor platform for the Domologica UNA Automation integration.

Handles: TASensorElement, DeliosMainUnitElement, PowerMenagementElement (sensors).
Includes energy sensors (kWh) computed via Riemann sum integration.
"""
import logging
import time

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Delios Inverter sensor definitions
DELIOS_SENSORS = {
    "grid_voltage": ("Grid Voltage", SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT, SensorStateClass.MEASUREMENT),
    "grid_current": ("Grid Current", SensorDeviceClass.CURRENT, UnitOfElectricCurrent.AMPERE, SensorStateClass.MEASUREMENT),
    "grid_power_in": ("Grid Power In", SensorDeviceClass.POWER, UnitOfPower.WATT, SensorStateClass.MEASUREMENT),
    "grid_power_out": ("Grid Power Out", SensorDeviceClass.POWER, UnitOfPower.WATT, SensorStateClass.MEASUREMENT),
    "pv1_voltage": ("PV1 Voltage", SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT, SensorStateClass.MEASUREMENT),
    "pv1_current": ("PV1 Current", SensorDeviceClass.CURRENT, UnitOfElectricCurrent.AMPERE, SensorStateClass.MEASUREMENT),
    "pv1_power": ("PV1 Power", SensorDeviceClass.POWER, UnitOfPower.WATT, SensorStateClass.MEASUREMENT),
    "pv2_voltage": ("PV2 Voltage", SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT, SensorStateClass.MEASUREMENT),
    "pv2_current": ("PV2 Current", SensorDeviceClass.CURRENT, UnitOfElectricCurrent.AMPERE, SensorStateClass.MEASUREMENT),
    "pv2_power": ("PV2 Power", SensorDeviceClass.POWER, UnitOfPower.WATT, SensorStateClass.MEASUREMENT),
    "battery_voltage": ("Battery Voltage", SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT, SensorStateClass.MEASUREMENT),
    "battery_current": ("Battery Current", SensorDeviceClass.CURRENT, UnitOfElectricCurrent.AMPERE, SensorStateClass.MEASUREMENT),
    "battery_charge": ("Battery Charge", SensorDeviceClass.BATTERY, PERCENTAGE, SensorStateClass.MEASUREMENT),
    "inverter_temperature": ("Inverter Temperature", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, SensorStateClass.MEASUREMENT),
    "case_temperature": ("Case Temperature", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, SensorStateClass.MEASUREMENT),
    "energy_total": ("Total Energy", SensorDeviceClass.ENERGY, UnitOfEnergy.WATT_HOUR, SensorStateClass.TOTAL_INCREASING),
    "energy_in": ("Energy In", SensorDeviceClass.ENERGY, UnitOfEnergy.WATT_HOUR, SensorStateClass.TOTAL_INCREASING),
    "energy_out": ("Energy Out", SensorDeviceClass.ENERGY, UnitOfEnergy.WATT_HOUR, SensorStateClass.TOTAL_INCREASING),
    "energy_battery": ("Battery Energy", SensorDeviceClass.ENERGY, UnitOfEnergy.WATT_HOUR, SensorStateClass.TOTAL_INCREASING),
    "frequency_in": ("Frequency In", SensorDeviceClass.FREQUENCY, UnitOfFrequency.HERTZ, SensorStateClass.MEASUREMENT),
    "frequency_out": ("Frequency Out", SensorDeviceClass.FREQUENCY, UnitOfFrequency.HERTZ, SensorStateClass.MEASUREMENT),
}

# Delios power metrics for which to create energy (kWh) sensors
DELIOS_POWER_KEYS = {"grid_power_in", "grid_power_out", "pv1_power", "pv2_power"}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    for eid, info in coordinator.element_info.items():
        eclass = info["class"]

        if eclass == "TASensorElement":
            # Power sensor (W)
            entities.append(DomologicaPowerSensor(coordinator, eid, info["name"]))
            # Energy sensor (kWh) derived via integration
            entities.append(
                DomologicaEnergySensor(coordinator, eid, info["name"], "power")
            )

        elif eclass == "DeliosMainUnitElement":
            for key, (name, dev_class, unit, state_class) in DELIOS_SENSORS.items():
                entities.append(
                    DomologicaDeliosSensor(
                        coordinator, eid, info["name"], key, name,
                        dev_class, unit, state_class,
                    )
                )
            # Energy sensors (kWh) for Delios power metrics
            for power_key in DELIOS_POWER_KEYS:
                power_name = DELIOS_SENSORS[power_key][0]
                entities.append(
                    DomologicaDeliosEnergySensor(
                        coordinator, eid, info["name"],
                        power_key, f"{power_name} Energy",
                    )
                )

        elif eclass == "PowerMenagementElement":
            entities.append(
                DomologicaPowerMgmtSensor(
                    coordinator, eid, info["name"], "current_power",
                    "Current Consumption", SensorDeviceClass.POWER,
                    UnitOfPower.WATT, SensorStateClass.MEASUREMENT,
                )
            )
            entities.append(
                DomologicaPowerMgmtSensor(
                    coordinator, eid, info["name"], "max_power",
                    "Maximum Threshold", SensorDeviceClass.POWER,
                    UnitOfPower.WATT, SensorStateClass.MEASUREMENT,
                )
            )
            # Energy sensor (kWh) for current consumption
            entities.append(
                DomologicaEnergySensor(
                    coordinator, eid, f"{info['name']} Consumption", "current_power"
                )
            )

    _LOGGER.info("Loading %s sensors", len(entities))
    async_add_entities(entities)


# -- Power Sensor (TASensorElement) ----------------------------


class DomologicaPowerSensor(CoordinatorEntity, SensorEntity):
    """Power sensor (TASensorElement)."""

    def __init__(self, coordinator, eid, name):
        super().__init__(coordinator)
        self._eid = eid
        self._attr_name = name
        self._attr_device_class = SensorDeviceClass.POWER
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfPower.WATT

    @property
    def unique_id(self):
        return f"domologica_{self._eid}_power"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(**self.coordinator.device_info_dict)

    @property
    def native_value(self):
        data = (self.coordinator.data or {}).get(self._eid)
        if data and data.get("power") is not None:
            try:
                return float(data["power"])
            except (ValueError, TypeError):
                return None
        return None


# -- Energy Sensor (kWh) - Riemann Integration ----------------


class DomologicaEnergySensor(CoordinatorEntity, SensorEntity):
    """Energy sensor (kWh) computed by integrating power (W) over time.

    Uses the trapezoidal rule to integrate power readings over time.
    The value is cumulative and increasing (TOTAL_INCREASING): HA handles
    resets on restart automatically via the statistics engine.
    """

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, coordinator, eid, name, power_key):
        super().__init__(coordinator)
        self._eid = eid
        self._power_key = power_key
        self._attr_name = f"{name} Energy"
        self._cumulative_energy: float = 0.0
        self._last_power: float | None = None
        self._last_update: float | None = None

    @property
    def unique_id(self):
        return f"domologica_{self._eid}_energy_{self._power_key}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(**self.coordinator.device_info_dict)

    @property
    def native_value(self):
        if self._last_update is None:
            return None
        return round(self._cumulative_energy, 3)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Integrate power over time on each coordinator update."""
        self._update_energy()
        super()._handle_coordinator_update()

    def _update_energy(self):
        """Incremental energy calculation via trapezoidal rule."""
        data = (self.coordinator.data or {}).get(self._eid)
        if not data:
            return

        current_power = data.get(self._power_key)
        if current_power is None:
            return

        try:
            current_power = max(0.0, float(current_power))
        except (ValueError, TypeError):
            return

        now = time.monotonic()

        if self._last_power is not None and self._last_update is not None:
            time_delta_hours = (now - self._last_update) / 3600.0
            # Trapezoidal rule: average of two readings x time
            avg_power = (self._last_power + current_power) / 2.0
            energy_kwh = (avg_power * time_delta_hours) / 1000.0
            if energy_kwh > 0:
                self._cumulative_energy += energy_kwh

        self._last_power = current_power
        self._last_update = now


# -- Delios Inverter Sensors (separate device) -----------------


class DomologicaDeliosSensor(CoordinatorEntity, SensorEntity):
    """Individual Delios inverter sensor (from parameter string).

    All Delios sensors are grouped under a separate "Delios Inverter"
    device in the Home Assistant device registry.
    """

    def __init__(
        self, coordinator, eid, parent_name, metric_key, metric_name,
        device_class, unit, state_class,
    ):
        super().__init__(coordinator)
        self._eid = eid
        self._parent_name = parent_name
        self._metric_key = metric_key
        self._attr_name = f"{parent_name} {metric_name}"
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_unit_of_measurement = unit

    @property
    def unique_id(self):
        return f"domologica_{self._eid}_delios_{self._metric_key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Separate device for the Delios inverter."""
        return DeviceInfo(**self.coordinator.delios_device_info_dict(
            self._eid, self._parent_name
        ))

    @property
    def native_value(self):
        data = (self.coordinator.data or {}).get(self._eid)
        if not data or not isinstance(data, dict):
            return None
        metric = data.get(self._metric_key)
        if isinstance(metric, dict):
            return metric.get("value")
        return None


class DomologicaDeliosEnergySensor(CoordinatorEntity, SensorEntity):
    """Energy sensor (kWh) for Delios power metrics.

    Integrates instantaneous Delios power readings (grid in/out, PV1, PV2)
    over time to obtain cumulative energy counts.
    """

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, coordinator, eid, parent_name, power_key, metric_name):
        super().__init__(coordinator)
        self._eid = eid
        self._parent_name = parent_name
        self._power_key = power_key
        self._attr_name = f"{parent_name} {metric_name}"
        self._cumulative_energy: float = 0.0
        self._last_power: float | None = None
        self._last_update: float | None = None

    @property
    def unique_id(self):
        return f"domologica_{self._eid}_delios_energy_{self._power_key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Separate device for the Delios inverter."""
        return DeviceInfo(**self.coordinator.delios_device_info_dict(
            self._eid, self._parent_name
        ))

    @property
    def native_value(self):
        if self._last_update is None:
            return None
        return round(self._cumulative_energy, 3)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Integrate Delios power over time."""
        self._update_energy()
        super()._handle_coordinator_update()

    def _update_energy(self):
        """Incremental energy calculation via trapezoidal rule."""
        data = (self.coordinator.data or {}).get(self._eid)
        if not data or not isinstance(data, dict):
            return

        # Delios data is a dict with "value" key
        metric = data.get(self._power_key)
        if not isinstance(metric, dict):
            return
        raw_value = metric.get("value")
        if raw_value is None:
            return

        try:
            current_power = max(0.0, float(raw_value))
        except (ValueError, TypeError):
            return

        now = time.monotonic()

        if self._last_power is not None and self._last_update is not None:
            time_delta_hours = (now - self._last_update) / 3600.0
            avg_power = (self._last_power + current_power) / 2.0
            energy_kwh = (avg_power * time_delta_hours) / 1000.0
            if energy_kwh > 0:
                self._cumulative_energy += energy_kwh

        self._last_power = current_power
        self._last_update = now


# -- Power Management Sensor -----------------------------------


class DomologicaPowerMgmtSensor(CoordinatorEntity, SensorEntity):
    """Power Management sensor (consumption and threshold)."""

    def __init__(
        self, coordinator, eid, parent_name, data_key, suffix_name,
        device_class, unit, state_class,
    ):
        super().__init__(coordinator)
        self._eid = eid
        self._data_key = data_key
        self._attr_name = f"{parent_name} {suffix_name}"
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_unit_of_measurement = unit

    @property
    def unique_id(self):
        return f"domologica_{self._eid}_pwrmgmt_{self._data_key}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(**self.coordinator.device_info_dict)

    @property
    def native_value(self):
        data = (self.coordinator.data or {}).get(self._eid)
        if data and data.get(self._data_key) is not None:
            try:
                return float(data[self._data_key])
            except (ValueError, TypeError):
                return None
        return None
