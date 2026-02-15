"""XML parser for Domologica element states."""
import logging
import re
import xml.etree.ElementTree as ET

_LOGGER = logging.getLogger(__name__)


def _extract_statuses(element_status: ET.Element) -> dict:
    """Extracts all Status tags into a dictionary {id: value_text | None}."""
    result = {}
    for status in element_status.findall("Status"):
        sid = status.get("id")
        if sid is None:
            # Status without id attribute (e.g. <Status>isswitchedoff</Status>)
            sid = (status.text or "").strip()
            if sid:
                result[sid] = None
            continue
        value_el = status.find("value")
        result[sid] = value_el.text if value_el is not None else None
    return result


def _has_status(statuses: dict, *names: str) -> bool:
    """Checks if at least one of the names is present as a key (case-insensitive)."""
    lower_keys = {k.lower() for k in statuses}
    return any(n.lower() in lower_keys for n in names)


def _get_status_value(statuses: dict, *names: str) -> str | None:
    """Searches for a value by name (case-insensitive), returns the first found."""
    lower_map = {k.lower(): v for k, v in statuses.items()}
    for name in names:
        val = lower_map.get(name.lower())
        if val is not None:
            return val
    return None


def _safe_float(value: str | None, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_int(value: str | None, default: int | None = None) -> int | None:
    if value is None:
        return default
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default


# ── Parsers by element type ──────────────────────────────────


def parse_light(statuses: dict) -> dict:
    is_on = _has_status(statuses, "isswitchedon")
    brightness = _get_status_value(statuses, "getdimmer")
    return {
        "is_on": is_on,
        "brightness": _safe_int(brightness),
    }


def parse_cover(statuses: dict) -> dict:
    return {
        "is_opening": _has_status(statuses, "isgoingup"),
        "is_closing": _has_status(statuses, "isgoingdown"),
    }


def parse_ta_sensor(statuses: dict) -> dict:
    power = _get_status_value(statuses, "TA Value")
    return {
        "power": _safe_float(power),
    }


def parse_thermostat(statuses: dict) -> dict:
    temperature_raw = _get_status_value(statuses, "temperature")
    temperature = _safe_float(temperature_raw)
    if temperature is not None and temperature > 100:
        temperature = temperature / 10.0  # Normalize if value > 100

    t_min = _safe_float(_get_status_value(statuses, "tMin"))
    t_max = _safe_float(_get_status_value(statuses, "tMax"))
    speed = _safe_int(_get_status_value(statuses, "speed"))
    season = _get_status_value(statuses, "season") or "Winter"
    t_mode = _get_status_value(statuses, "tMode") or "Off"
    delta_t = _safe_float(_get_status_value(statuses, "deltat"))
    calibration = _safe_float(_get_status_value(statuses, "calibration"))
    defrost = _safe_float(_get_status_value(statuses, "defrost"))
    reactivity = _safe_int(_get_status_value(statuses, "reactivity"))

    zone_active_winter = _has_status(statuses, "zoneactive")
    zone_active_summer = _has_status(statuses, "zoneactivesummer")

    return {
        "temperature": temperature,
        "t_min": t_min,
        "t_max": t_max,
        "speed": speed,
        "season": season,
        "t_mode": t_mode,
        "delta_t": delta_t,
        "calibration": calibration,
        "defrost": defrost,
        "reactivity": reactivity,
        "zone_active_winter": zone_active_winter,
        "zone_active_summer": zone_active_summer,
    }


def parse_samsung_ac(statuses: dict) -> dict:
    current_temp = _safe_float(
        _get_status_value(statuses, "Get AC unit Temperature Room")
    )
    target_temp = _safe_float(
        _get_status_value(statuses, "Get AC unit Temperature Setted")
    )
    error_code = _safe_int(
        _get_status_value(statuses, "Get AC unit Error Code")
    )
    speed = _safe_int(_get_status_value(statuses, "speed"))
    delta_t = _safe_float(_get_status_value(statuses, "deltat"))

    is_on = not _has_status(statuses, "IsSwitchedOff")
    is_connected = _has_status(statuses, "IsConnected")

    # Determine mode from flags
    mode = "off"
    if is_on:
        if _has_status(statuses, "Get AC unit Mode is Heat"):
            mode = "heat"
        elif _has_status(statuses, "Get AC unit Mode is Cool"):
            mode = "cool"
        elif _has_status(statuses, "Get AC unit Mode is Auto"):
            mode = "auto"
        elif _has_status(statuses, "Get AC unit Mode is Dry"):
            mode = "dry"
        elif _has_status(statuses, "Get AC unit Mode is Fan"):
            mode = "fan_only"

    # Fallback: parse from parameter field if available
    if current_temp is None or target_temp is None:
        param = _get_status_value(statuses, "parameter")
        if param:
            parsed = _parse_parameter_string(param)
            if current_temp is None:
                current_temp = _safe_float(
                    parsed.get("AC unit Temperature Room")
                )
            if target_temp is None:
                target_temp = _safe_float(
                    parsed.get("AC unit Temperature Setted")
                )

    return {
        "is_on": is_on,
        "is_connected": is_connected,
        "mode": mode,
        "current_temp": current_temp,
        "target_temp": target_temp,
        "fan_speed": speed,
        "error_code": error_code,
        "delta_t": delta_t,
    }


def parse_samsung_water(statuses: dict) -> dict:
    h2o_measured = _safe_float(
        _get_status_value(statuses, "Get AC unit H2O Temperature Measured")
    )
    h2o_setted = _safe_float(
        _get_status_value(statuses, "Get AC unit H2O Temperature Setted")
    )
    h2o_mode = _safe_int(
        _get_status_value(statuses, "Get AC unit H2O Mode")
    )
    h2o_operation = _safe_int(
        _get_status_value(statuses, "Get AC unit H2O Operation")
    )
    water_in = _safe_float(
        _get_status_value(statuses, "Get AC unit Water In Temperature")
    )
    water_out = _safe_float(
        _get_status_value(statuses, "Get AC unit Water Out Temperature")
    )
    error_code = _safe_int(
        _get_status_value(statuses, "Get AC unit Error Code")
    )
    is_on = _has_status(statuses, "isswitchedon")
    is_connected = _has_status(statuses, "IsConnected")
    is_heating = _has_status(statuses, "Get AC unit Mode is Heat")

    return {
        "is_on": is_on,
        "is_connected": is_connected,
        "is_heating": is_heating,
        "h2o_measured": h2o_measured,
        "h2o_setted": h2o_setted,
        "h2o_mode": h2o_mode,
        "h2o_operation": h2o_operation,
        "water_in": water_in,
        "water_out": water_out,
        "error_code": error_code,
    }


def parse_delios(statuses: dict) -> dict:
    """Parsing of the Delios inverter parameter field.

    Format: "Delios InverterV (Input Volt Phase R)=225;...;Delios Inverter (Inverter Status)=0"
    """
    param = _get_status_value(statuses, "parameter")
    if not param:
        return {}

    metrics = {}
    # Map parameter names -> clean keys
    key_map = {
        "Input Volt Phase R": ("grid_voltage", "V"),
        "Input Ampere Phase R": ("grid_current", "A"),
        "Input Watt Phase R": ("grid_power_in", "W"),
        "Output Volt Phase R": ("output_voltage", "V"),
        "Output Ampere Phase R": ("output_current", "A"),
        "Output Watt Phase R": ("grid_power_out", "W"),
        "Frequency In": ("frequency_in", "Hz"),
        "Frequency Out": ("frequency_out", "Hz"),
        "Inverter Charge Percent": ("inverter_charge", "%"),
        "Input Volt Photovoltaic 1": ("pv1_voltage", "V"),
        "Input Ampere Photovoltaic 1": ("pv1_current", "A"),
        "Input Watt Photovoltaic 1": ("pv1_power", "W"),
        "Input Volt Photovoltaic 2": ("pv2_voltage", "V"),
        "Input Ampere Photovoltaic 2": ("pv2_current", "A"),
        "Input Watt Photovoltaic 2": ("pv2_power", "W"),
        "Battery Volt": ("battery_voltage", "V"),
        "Battery Ampere": ("battery_current", "A"),
        "Battery Charge Percent": ("battery_charge", "%"),
        "Inverter Temperature": ("inverter_temperature", "°C"),
        "Case Temperature": ("case_temperature", "°C"),
        "Energy Battery": ("energy_battery", "W"),
        "Energy Total": ("energy_total", "W"),
        "Energy In": ("energy_in", "W"),
        "Energy Out": ("energy_out", "W"),
        "Inverter Status": ("inverter_status", None),
    }

    for pair in param.split(";"):
        pair = pair.strip()
        if "=" not in pair:
            continue
        raw_name, raw_value = pair.split("=", 1)
        # Extract the name between parentheses
        match = re.search(r"\((.+?)\)", raw_name)
        if match:
            name = match.group(1)
        else:
            # No parentheses, use the name after "Delios Inverter"
            name = raw_name.replace("Delios Inverter", "").strip()
            if name.startswith("(") and name.endswith(")"):
                name = name[1:-1]

        if name in key_map:
            key, unit = key_map[name]
            metrics[key] = {
                "value": _safe_float(raw_value.strip()),
                "unit": unit,
            }

    return metrics


def parse_power_management(statuses: dict) -> dict:
    current_power = _safe_float(_get_status_value(statuses, "pwmValue"))
    max_power = _safe_float(_get_status_value(statuses, "MaxWattCalculatedValue"))
    is_running = _has_status(statuses, "IsRun")
    is_normal = _has_status(statuses, "NormalMeasure")

    return {
        "current_power": current_power,
        "max_power": max_power,
        "is_running": is_running,
        "is_normal": is_normal,
    }


def parse_status_element(statuses: dict) -> dict:
    is_on = _has_status(statuses, "statuson")
    return {"is_on": is_on}


def parse_switch_element(statuses: dict) -> dict:
    is_released = _has_status(statuses, "released")
    return {"released": is_released}


def parse_updown_switch(statuses: dict) -> dict:
    return {}


# ── Utility ──────────────────────────────────────────────────


def _parse_parameter_string(param: str) -> dict:
    """Generic parameter field parsing (format 'name:value:unit;...')."""
    result = {}
    for part in param.split(";"):
        part = part.strip()
        if not part:
            continue
        segments = part.split(":")
        if len(segments) >= 2:
            name = segments[0].strip()
            value = segments[1].strip()
            result[name] = value
    return result


# ── Main parser ──────────────────────────────────────────────

PARSER_MAP = {
    "LightElement": parse_light,
    "DimmerableLightLedElement": parse_light,
    "ShutterElement": parse_cover,
    "TASensorElement": parse_ta_sensor,
    "ThermostatElement": parse_thermostat,
    "ModbusSamsungAir2Element": parse_samsung_ac,
    "ModbusSamsungElement": parse_samsung_water,
    "DeliosMainUnitElement": parse_delios,
    "PowerMenagementElement": parse_power_management,
    "StatusElement": parse_status_element,
    "SwitchElement": parse_switch_element,
    "UpDownSwitchElement": parse_updown_switch,
}


def parse_all_statuses(
    root: ET.Element, element_info: dict[str, dict]
) -> dict[str, dict]:
    """Global parsing of element_xml_statuses.xml."""
    results = {}
    if root is None:
        return results

    for el_status in root.findall(".//ElementStatus"):
        path_el = el_status.find("ElementPath")
        if path_el is None or not path_el.text:
            continue

        eid = path_el.text.strip()

        # Determine element class
        info = element_info.get(eid)
        if not info:
            continue

        eclass = info.get("class", "")
        parser = PARSER_MAP.get(eclass)
        if not parser:
            continue

        # Extract all statuses
        statuses = _extract_statuses(el_status)

        # Apply the specific parser
        try:
            results[eid] = parser(statuses)
        except Exception as err:
            _LOGGER.error(
                "Error parsing element %s (%s): %s", eid, eclass, err
            )

    return results
