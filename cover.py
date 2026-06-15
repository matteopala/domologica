"""Cover platform for the Domologica UNA Automation integration.

Uses RestoreEntity to persist the estimated position across HA restarts.
"""
import asyncio
import logging
import time

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Minimum time (seconds) a cover must have been moving before we trust an
# end-of-travel snap. The device briefly drops the movement flag right after
# a command is issued (a sub-second "isgoingup" flicker); this guard prevents
# that transient from snapping the position prematurely.
_MIN_MOVE_BEFORE_SNAP = 3.0


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        DomologicaCover(coordinator, eid, info["name"], coordinator.travel_time)
        for eid, info in coordinator.element_info.items()
        if info["class"] == "ShutterElement"
    ]
    _LOGGER.info("Loading %s shutters", len(entities))
    async_add_entities(entities)


class DomologicaCover(CoordinatorEntity, RestoreEntity, CoverEntity):
    """Domologica shutter entity with position estimation and state persistence."""

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
        self._attr_current_cover_position = 50  # default, overridden by restore
        self._last_tick = None
        self._verify_task = None
        # End-of-travel snap: the device only reports movement flags, never a
        # real position, and supports only full OPEN/CLOSE (no set_position).
        # So a completed open/close always lands at an endpoint. _target holds
        # that commanded endpoint (100 / 0); STOP clears it to keep the
        # time-estimated partial position.
        self._target = None
        self._was_moving = False
        self._move_started = None
        # After a commanded move finishes, the controller sometimes keeps
        # reporting the movement flag (e.g. it doesn't clear isgoingdown at the
        # bottom limit), which would leave the entity stuck "opening"/"closing".
        # Once we consider the move complete we trust that until the device
        # reports a *different* movement state (e.g. an external command).
        self._completed = False
        self._completed_flags = None

    async def async_added_to_hass(self) -> None:
        """Restore last known position when HA starts."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state is not None:
            restored_pos = last_state.attributes.get("current_position")
            if restored_pos is not None:
                try:
                    self._attr_current_cover_position = float(restored_pos)
                    _LOGGER.debug(
                        "Restored cover %s position to %s%%",
                        self._eid, int(restored_pos),
                    )
                except (ValueError, TypeError):
                    pass

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
        moving = is_opening or is_closing

        now = time.time()
        if moving and self._last_tick:
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

        # Decide whether the commanded full OPEN/CLOSE (no STOP) is complete:
        #  - the device reported movement ended (normal case, e.g. opening), or
        #  - enough time elapsed for a full travel even though the controller is
        #    still latching the movement flag (e.g. isgoingdown at the bottom).
        # Either way, snap to the commanded endpoint. Without this the time
        # estimate would freeze wherever it happened to be when the motor's
        # finecorsa stopped — so the cover "often doesn't reach 100%". The
        # _MIN_MOVE_BEFORE_SNAP guard ignores the brief post-command flag flicker.
        if self._target is not None and self._move_started is not None:
            elapsed = now - self._move_started
            device_stopped = (
                self._was_moving and not moving and elapsed >= _MIN_MOVE_BEFORE_SNAP
            )
            timed_out = elapsed >= self._travel_time + _MIN_MOVE_BEFORE_SNAP
            if device_stopped or timed_out:
                self._attr_current_cover_position = self._target
                # Remember the device flags at completion; is_opening/is_closing
                # report "stopped" until the device reports something different.
                self._completed = True
                self._completed_flags = (is_opening, is_closing)
                self._target = None
                self._move_started = None
                moving = False

        self._was_moving = moving
        self._last_tick = now if moving else None
        return int(self._attr_current_cover_position)

    def _movement_settled(self) -> bool:
        """True while we trust a just-completed move over the device's flags.

        Cleared as soon as the device reports a different movement state than it
        had at completion (e.g. an externally triggered move), so external
        movement is never hidden.
        """
        if not self._completed:
            return False
        data = self.coordinator.data.get(self._eid, {}) if self.coordinator.data else {}
        current = (data.get("is_opening", False), data.get("is_closing", False))
        if current != self._completed_flags:
            self._completed = False
            return False
        return True

    @property
    def is_opening(self):
        if not self.coordinator.data or self._movement_settled():
            return False
        return self.coordinator.data.get(self._eid, {}).get("is_opening", False)

    @property
    def is_closing(self):
        if not self.coordinator.data or self._movement_settled():
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
        now = time.time()
        self._last_tick = now
        self._move_started = now
        self._was_moving = True
        self._target = 100
        self._completed = False
        self.async_write_ha_state()
        await self.coordinator.api_client.async_cover_command(self._eid, "open")
        self._start_verify_task()

    async def async_close_cover(self, **kwargs):
        if self.coordinator.data:
            self.coordinator.data.setdefault(self._eid, {}).update(
                {"is_opening": False, "is_closing": True}
            )
        now = time.time()
        self._last_tick = now
        self._move_started = now
        self._was_moving = True
        self._target = 0
        self._completed = False
        self.async_write_ha_state()
        await self.coordinator.api_client.async_cover_command(self._eid, "close")
        self._start_verify_task()

    async def async_stop_cover(self, **kwargs):
        if self.coordinator.data:
            self.coordinator.data.setdefault(self._eid, {}).update(
                {"is_opening": False, "is_closing": False}
            )
        self._last_tick = None
        # Explicit STOP → keep the time-estimated partial position; cancel any
        # pending endpoint snap so we don't jump to 0/100.
        self._target = None
        self._was_moving = False
        self._move_started = None
        self._completed = False
        self.async_write_ha_state()
        await self.coordinator.api_client.async_cover_command(self._eid, "stop")
        self._start_verify_task()
