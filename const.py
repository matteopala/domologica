"""Constants for the Domologica UNA Automation integration (Master SRL UNA/Vesta)."""

DOMAIN = "domologica"
VERSION = "1.0.0"
INTEGRATION_NAME = "Domologica UNA Automation"
MANUFACTURER = "Matteo Pala"
MODEL = "UNA/Vesta"  
 
# Type labels for config flow and device registry
TYPE_LABELS = {
    "LightElement": "Light",
    "DimmerableLightLedElement": "Dimmable Light",
    "ShutterElement": "Shutter",
    "TASensorElement": "Power Sensor",
    "ThermostatElement": "Thermostat",
    "ModbusSamsungAir2Element": "Air Conditioner",
    "ModbusSamsungElement": "Water Heater",
    "DeliosMainUnitElement": "Delios Inverter",
    "PowerMenagementElement": "Load Management",
    "StatusElement": "Status",
    "SwitchElement": "Scenario",
    "UpDownSwitchElement": "Shutter Control",
}

PLATFORMS = [
    "light",
    "cover",
    "sensor",
    "climate",
    "water_heater",
    "binary_sensor",
    "button",
    "switch",
]

# HTTP request timeouts
REQUEST_TIMEOUT = 30
CONNECT_TIMEOUT = 10
MAX_CONCURRENT_REQUESTS = 3

# Default configuration
DEFAULT_POLLING_INTERVAL = 30
DEFAULT_TRAVEL_TIME = 25

# Mapping classId -> HA platform
ELEMENT_CLASS_TO_PLATFORM = {
    "LightElement": "light",
    "DimmerableLightLedElement": "light",
    "ShutterElement": "cover",
    "TASensorElement": "sensor",
    "ThermostatElement": "climate",
    "ModbusSamsungAir2Element": "climate",
    "ModbusSamsungElement": "water_heater",
    "DeliosMainUnitElement": "sensor",
    "PowerMenagementElement": ["sensor", "switch"],
    "StatusElement": "binary_sensor",
    "SwitchElement": "button",
    "UpDownSwitchElement": "button",
}

# Classes to completely ignore
IGNORED_CLASSES = {
    "WebPageElement",
    "VirtualKeypadElement",
}

# Light classes
LIGHT_CLASSES = {"LightElement", "DimmerableLightLedElement"}
DIMMERABLE_CLASSES = {"DimmerableLightLedElement"}

# Samsung AC Mode mapping (numeric value -> string)
SAMSUNG_AC_MODE_MAP = {
    0: "auto",
    1: "cool",
    2: "dry",
    3: "fan_only",
    4: "heat",
}

# Water heater operation modes
WATER_HEATER_MODES = ["eco", "standard", "power", "force"]
WATER_HEATER_MODE_ACTIONS = {
    "eco": "Set AC Temperature H2O Mode ECO",
    "standard": "Set AC Temperature H2O Mode STANDARD",
    "power": "Set AC Temperature H2O Mode POWER",
    "force": "Set AC Temperature H2O Mode FORCE",
}

# Thermostat tMode -> HA preset
THERMOSTAT_PRESET_MAP = {
    "TMax": "comfort",
    "TMin": "eco",
    "Chrono": "schedule",
    "Off": "off",
}
THERMOSTAT_PRESET_REVERSE = {v: k for k, v in THERMOSTAT_PRESET_MAP.items()}
