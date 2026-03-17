"""Alarm Control Panel platform for the Domologica UNA Automation integration.

Uses VirtualKeypadElement with userpinverify action to toggle the alarm.
State is read from linked StatusElement sensors when configured:
  - alarm_state_eid: armed (statuson) / disarmed (statusoff)
  - alarm_siren_eid: normal (statuson) / triggered (statusoff)
Falls back to optimistic state if the linked sensors are not configured.
"""
import logging

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
)
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    for eid, info in coordinator.element_info.items():
        if info["class"] == "VirtualKeypadElement":
            entities.append(
                DomologicaAlarmControlPanel(coordinator, eid, info["name"])
            )

    _LOGGER.info("Loading %s alarm control panel entities", len(entities))
    async_add_entities(entities)


class DomologicaAlarmControlPanel(CoordinatorEntity, AlarmControlPanelEntity):
    """Alarm control panel for Domologica VirtualKeypadElement.

    When alarm_state_eid and/or alarm_siren_eid are configured in the
    integration options, the panel reads the real armed/triggered state
    from the linked StatusElement sensors via the coordinator polling data.

    Without linked sensors the state is tracked optimistically (arm_away
    sets ARMED_AWAY, disarm sets DISARMED).
    """

    _attr_icon = "mdi:shield-home"
    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_AWAY
    )
    _attr_code_arm_required = False

    def __init__(self, coordinator, eid, name):
        super().__init__(coordinator)
        self._eid = eid
        self._attr_name = name
        # Optimistic override: set after a command, cleared on next poll.
        # When set, takes priority over both real data and the pure fallback.
        self._optimistic_override: AlarmControlPanelState | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Clear optimistic override when fresh polling data arrives."""
        self._optimistic_override = None
        super()._handle_coordinator_update()

    # ── Helpers ────────────────────────────────────────────────

    @property
    def _alarm_state_eid(self) -> str:
        """Element ID of the StatusElement that tracks armed/disarmed."""
        return self.coordinator.alarm_state_eid

    @property
    def _alarm_siren_eid(self) -> str:
        """Element ID of the StatusElement that tracks siren on/off."""
        return self.coordinator.alarm_siren_eid

    # ── HA properties ─────────────────────────────────────────

    @property
    def unique_id(self):
        return f"domologica_{self._eid}_alarm_panel"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(**self.coordinator.device_info_dict)

    @property
    def alarm_state(self) -> AlarmControlPanelState:
        """Return alarm state.

        Priority:
        1. Optimistic override (set after a command, cleared on next poll)
        2. Real data from linked StatusElement sensors
        3. DISARMED as ultimate fallback (no sensors linked, no command sent)
        """
        # --- Optimistic override (immediate UI feedback) ----------
        if self._optimistic_override is not None:
            return self._optimistic_override

        data = self.coordinator.data or {}

        # --- Siren sensor (element 34-like) -----------------------
        # statusoff = siren sounding → TRIGGERED (overrides everything)
        if self._alarm_siren_eid:
            siren_data = data.get(self._alarm_siren_eid, {})
            siren_normal = siren_data.get("is_on", True)
            if not siren_normal:
                return AlarmControlPanelState.TRIGGERED

        # --- Armed/disarmed sensor (element 31-like) --------------
        if self._alarm_state_eid:
            state_data = data.get(self._alarm_state_eid, {})
            is_armed = state_data.get("is_on", False)
            return (
                AlarmControlPanelState.ARMED_AWAY
                if is_armed
                else AlarmControlPanelState.DISARMED
            )

        # --- Ultimate fallback ------------------------------------
        return AlarmControlPanelState.DISARMED

    @property
    def available(self) -> bool:
        """Available only if alarm PIN is configured."""
        pin = self.coordinator.alarm_pin
        return bool(pin) and super().available

    # ── Commands ──────────────────────────────────────────────

    async def async_alarm_arm_away(self, code=None) -> None:
        """Arm the alarm (send PIN verify to toggle)."""
        pin = self.coordinator.alarm_pin
        if not pin:
            _LOGGER.error("Alarm PIN not configured")
            return

        success = await self.coordinator.api_client.async_keypad_verify_pin(
            self._eid, pin
        )
        if success:
            self._optimistic_override = AlarmControlPanelState.ARMED_AWAY
            self.async_write_ha_state()

    async def async_alarm_disarm(self, code=None) -> None:
        """Disarm the alarm (send PIN verify to toggle)."""
        pin = self.coordinator.alarm_pin
        if not pin:
            _LOGGER.error("Alarm PIN not configured")
            return

        success = await self.coordinator.api_client.async_keypad_verify_pin(
            self._eid, pin
        )
        if success:
            self._optimistic_override = AlarmControlPanelState.DISARMED
            self.async_write_ha_state()
