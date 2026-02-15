"""Light platform for the Domologica UNA Automation integration."""
import asyncio
import logging
import time

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DIMMERABLE_CLASSES, DOMAIN, LIGHT_CLASSES

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        DomologicaLight(coordinator, eid, info)
        for eid, info in coordinator.element_info.items()
        if info["class"] in LIGHT_CLASSES
    ]
    _LOGGER.info("Loading %s lights", len(entities))
    async_add_entities(entities)


class DomologicaLight(CoordinatorEntity, LightEntity):
    """Domologica light entity (on/off and dimmable)."""

    def __init__(self, coordinator, eid, info):
        super().__init__(coordinator)
        self._eid = eid
        self._attr_name = info["name"]
        self._is_dimmer = info["class"] in DIMMERABLE_CLASSES
        self._attr_is_on = False
        self._attr_brightness = 255
        self._last_command_time = 0
        self._verify_task = None

    @property
    def unique_id(self):
        return f"domologica_{self._eid}_light"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(**self.coordinator.device_info_dict)

    @property
    def is_on(self):
        if time.time() - self._last_command_time < 5:
            return self._attr_is_on
        data = (self.coordinator.data or {}).get(self._eid)
        if data:
            return data.get("is_on", self._attr_is_on)
        return self._attr_is_on

    @property
    def brightness(self):
        if time.time() - self._last_command_time < 5:
            return self._attr_brightness
        data = (self.coordinator.data or {}).get(self._eid)
        if data and data.get("brightness") is not None:
            return int(float(data["brightness"]) * 2.55)
        return self._attr_brightness

    @property
    def supported_color_modes(self):
        return {ColorMode.BRIGHTNESS} if self._is_dimmer else {ColorMode.ONOFF}

    @property
    def color_mode(self):
        return ColorMode.BRIGHTNESS if self._is_dimmer else ColorMode.ONOFF

    async def _verify_and_update(self):
        try:
            await asyncio.sleep(1.5)
            root = await self.coordinator.api_client.async_fetch_single_status(self._eid)
            if root is None:
                return
            from .parsers import _extract_statuses, parse_light
            statuses = _extract_statuses(root)
            real = parse_light(statuses)
            if self.coordinator.data is not None and self._eid in self.coordinator.data:
                self.coordinator.data[self._eid].update(real)
                self._attr_is_on = real.get("is_on", self._attr_is_on)
                if self._is_dimmer and real.get("brightness") is not None:
                    self._attr_brightness = int(float(real["brightness"]) * 2.55)
                self.async_write_ha_state()
        except asyncio.CancelledError:
            pass
        except Exception as err:
            _LOGGER.error("Error verifying light %s: %s", self._eid, err)

    def _start_verify_task(self):
        if self._verify_task and not self._verify_task.done():
            self._verify_task.cancel()
        self._verify_task = self.hass.async_create_task(self._verify_and_update())

    async def async_turn_on(self, **kwargs):
        was_off = not self.is_on
        self._attr_is_on = True
        self._last_command_time = time.time()

        if self._is_dimmer and ATTR_BRIGHTNESS in kwargs:
            self._attr_brightness = kwargs[ATTR_BRIGHTNESS]
            brightness_pct = int(self._attr_brightness / 2.55)

            if was_off:
                await self.coordinator.api_client.async_light_switch(self._eid, True)
                await asyncio.sleep(0.5)

            if self.coordinator.data and self._eid in self.coordinator.data:
                self.coordinator.data[self._eid]["is_on"] = True
            self.async_write_ha_state()

            await self.coordinator.api_client.async_light_set_dimmer(
                self._eid, brightness_pct
            )
        else:
            if self.coordinator.data and self._eid in self.coordinator.data:
                self.coordinator.data[self._eid]["is_on"] = True
            self.async_write_ha_state()
            await self.coordinator.api_client.async_light_switch(self._eid, True)

        self._start_verify_task()

    async def async_turn_off(self, **kwargs):
        self._attr_is_on = False
        self._last_command_time = time.time()
        if self.coordinator.data and self._eid in self.coordinator.data:
            self.coordinator.data[self._eid]["is_on"] = False
        self.async_write_ha_state()
        await self.coordinator.api_client.async_light_switch(self._eid, False)
        self._start_verify_task()
