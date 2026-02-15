# Domologica UNA Automation - Home Assistant Integration

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Custom Home Assistant integration for **Master SRL UNA/Vesta** home automation systems with **SideraHome** interface.

## Supported Devices

| Device Type | HA Platform | Features |
|---|---|---|
| Lights (on/off) | `light` | Switch on/off |
| Dimmable lights | `light` | Switch on/off, brightness |
| Shutters | `cover` | Open, close, stop, position estimation |
| Power sensors (TA) | `sensor` | Power consumption (W) + energy (kWh) |
| Thermostat | `climate` | Temperature, mode, season, fan, presets |
| Samsung AC | `climate` | Temperature, HVAC mode, fan speed |
| Samsung EHS2 (hot water) | `water_heater` | Temperature, operation mode (ECO/STD/PWR/FORCE) |
| Delios Inverter | `sensor` | 20+ metrics: PV, battery, grid, temperature, energy |
| Power Management | `sensor` + `switch` | Current/max power, load shedding on/off |
| Status elements | `binary_sensor` | System status, alarm status |
| Scenarios | `button` | Trigger scene activation |
| General shutter control | `button` | All shutters up/down |

## Installation

### Via HACS (recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu (top right) and select **Custom repositories**
3. Add the repository URL and select **Integration** as category
4. Search for **Domologica UNA Automation** and install
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/domologica` folder to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** > **Devices & Services** > **Add Integration**
2. Search for **Domologica**
3. Enter your system details:
   - **Base URL**: The IP address of your controller (e.g. `http://192.168.5.2`)
   - **Username**: Your SideraHome credentials
   - **Password**: Your SideraHome password
   - **Polling interval**: How often to poll for status updates (default: 30s)
   - **Shutter travel time**: Time for shutters to fully open/close (default: 25s)
   - **Enable Delios Inverter**: Enable if you want this integration to manage the Delios inverter (disabled by default if you use the dedicated Delios integration)
4. In the next step you can **rename** each discovered device before it is created in Home Assistant

## Options

After installation, you can adjust settings via **Settings** > **Devices & Services** > **Domologica** > **Configure**:

- **Polling interval**: Adjust the status polling frequency
- **Shutter travel time**: Fine-tune position estimation for your shutters
- **Enable Delios Inverter**: Toggle Delios inverter management on/off

## Energy Sensors

The integration automatically creates **energy sensors (kWh)** from power sensors using Riemann sum integration (trapezoidal rule). These are compatible with the Home Assistant **Energy Dashboard**:

- Power sensors (TASensorElement) get a companion energy sensor
- Power Management elements get a consumption energy sensor
- Delios inverter power metrics (grid in/out, PV1, PV2) get companion energy sensors

## Supported Element Classes

This integration auto-discovers all elements from your system and creates the appropriate Home Assistant entities:

- `LightElement`, `DimmerableLightLedElement`
- `ShutterElement`
- `TASensorElement`
- `ThermostatElement`
- `ModbusSamsungAir2Element`
- `ModbusSamsungElement`
- `DeliosMainUnitElement`
- `PowerMenagementElement`
- `StatusElement`
- `SwitchElement`, `UpDownSwitchElement`

Elements of type `WebPageElement` and `VirtualKeypadElement` are ignored as they are not controllable devices.

## Troubleshooting

- **Connection failed**: Verify the controller IP is reachable from your HA instance and credentials match your SideraHome login
- **No entities found**: Check the controller maps configuration - elements must be assigned to a map/scene
- **Slow response**: Increase the polling interval; the controller has limited concurrent request capacity

## Author

Matteo P. ([@matteopala](https://github.com/matteopala)) 

## License

Apache License 2.0 - see [LICENSE](LICENSE) for details.
