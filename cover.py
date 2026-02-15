"""Cover platform for the Domologica UNA Automation integration."""
import asyncio
import logging
import time

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature, 
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        DomologicaCover(coordinator, eid, info["name"], coordinator.travel_time)
        for eid, info in coordinator.element_info.items()
        if info["class"] == "ShutterElement"
    ]
    _LOGGER.info("Loading %s shutters", len(entities))
    async_add_entities(entities)


class DomologicaCover(CoordinatorEntity, CoverEntity):
    """Domologica shutter entity with position estimation."""

    def __init__(self, coordinator, eid, name, travel_time):
        super().__init__(coordinator)
        self._eid = eid
        self._attr_name = name
        self._travel_time = travel_time
        self._attr_device_class = CoverDeviceClass.SHUTTER
        self._attr_supported_features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
        )
        self._attr_current_cover_position = 50
        self._last_tick = None
        self._verify_task = None

    @property
    def unique_id(self):
        return f"domologica_{self._eid}_cover"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(**self.coordinator.device_info_dict)

    @property
    def is_closed(self):
        if self.is_opening or self.is_closing:
            return False
        return self._attr_current_cover_position <= 0

    @property
    def current_cover_position(self):
        if not self.coordinator.data or self._eid not in self.coordinator.data:
            return int(self._attr_current_cover_position)

        data = self.coordinator.data.get(self._eid, {})
        is_opening = data.get("is_opening", False)
        is_closing = data.get("is_closing", False)

        now = time.time()
        if (is_opening or is_closing) and self._last_tick:
            diff = now - self._last_tick
            movement = (diff / max(1, self._travel_time)) * 100
            if is_opening:
                self._attr_current_cover_position = min(
                    100, self._attr_current_cover_position + movement
                )
            else:
                self._attr_current_cover_position = max(
                    0, self._attr_current_cover_position - movement
                )

        self._last_tick = now if (is_opening or is_closing) else None
        return int(self._attr_current_cover_position)

    @property
    def is_opening(self):
        if not self.coordinator.data:
            return False
        return self.coordinator.data.get(self._eid, {}).get("is_opening", False)

    @property
    def is_closing(self):
        if not self.coordinator.data:
            return False
        return self.coordinator.data.get(self._eid, {}).get("is_closing", False)

    async def _verify_and_update(self):
        try:
            await asyncio.sleep(1.5)
            root = await self.coordinator.api_client.async_fetch_single_status(self._eid)
            if root is None:
                return
            from .parsers import _extract_statuses, parse_cover
            statuses = _extract_statuses(root)
            real = parse_cover(statuses)
            if self.coordinator.data is not None:
                if self._eid not in self.coordinator.data:
                    self.coordinator.data[self._eid] = {}
                self.coordinator.data[self._eid].update(real)
                if not real.get("is_opening") and not real.get("is_closing"):
                    self._last_tick = None
                self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error("Error verifying shutter %s: %s", self._eid, err)

    def _start_verify_task(self):
        if self._verify_task and not self._verify_task.done():
            self._verify_task.cancel()
        self._verify_task = self.hass.async_create_task(self._verify_and_update())

    async def async_open_cover(self, **kwargs):
        if self.coordinator.data:
            self.coordinator.data.setdefault(self._eid, {}).update(
                {"is_opening": True, "is_closing": False}
            )
        self._last_tick = time.time()
        self.async_write_ha_state()
        await self.coordinator.api_client.async_cover_command(self._eid, "open")
        self._start_verify_task()

    async def async_close_cover(self, **kwargs):
        if self.coordinator.data:
            self.coordinator.data.setdefault(self._eid, {}).update(
                {"is_opening": False, "is_closing": True}
            )
        self._last_tick = time.time()
        self.async_write_ha_state()
        await self.coordinator.api_client.async_cover_command(self._eid, "close")
        self._start_verify_task()

    async def async_stop_cover(self, **kwargs):
        if self.coordinator.data:
            self.coordinator.data.setdefault(self._eid, {}).update(
                {"is_opening": False, "is_closing": False}
            )
        self._last_tick = None
        self.async_write_ha_state()
        await self.coordinator.api_client.async_cover_command(self._eid, "stop")
        self._start_verify_task()
