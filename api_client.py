"""Asynchronous API client for the Domologica system (Master SRL UNA/Vesta)."""
import asyncio 
import logging
import xml.etree.ElementTree as ET 
from urllib.parse import quote

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONNECT_TIMEOUT,
    ELEMENT_CLASS_TO_PLATFORM,
    IGNORED_CLASSES,
    MAX_CONCURRENT_REQUESTS,
    REQUEST_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class DomologicaApiClient:
    """Asynchronous HTTP client for communicating with the Vesta control unit."""

    def __init__(
        self,
        hass: HomeAssistant,
        base_url: str,
        username: str,
        password: str,
    ) -> None:
        self.hass = hass
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    @property
    def _auth(self) -> aiohttp.BasicAuth:
        return aiohttp.BasicAuth(self.username, self.password)

    @property
    def _timeout(self) -> aiohttp.ClientTimeout:
        return aiohttp.ClientTimeout(
            total=REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT
        )

    def _session(self) -> aiohttp.ClientSession:
        return async_get_clientsession(self.hass, verify_ssl=False)

    # ── XML Reading ──────────────────────────────────────────────

    async def async_get_xml(self, endpoint: str) -> ET.Element | None:
        """Performs a GET request on an endpoint and returns the parsed XML."""
        url = f"{self.base_url}{endpoint}"
        async with self._semaphore:
            try:
                session = self._session()
                async with session.get(
                    url, auth=self._auth, timeout=self._timeout
                ) as resp:
                    if resp.status == 401:
                        _LOGGER.error("Authentication failed for %s", url)
                        return None
                    if resp.status != 200:
                        _LOGGER.error("HTTP %s for %s", resp.status, url)
                        return None
                    content = await resp.text()
                    if not content or not content.strip().startswith("<"):
                        return None
                    return ET.fromstring(content)
            except asyncio.TimeoutError:
                _LOGGER.error("Timeout during request to %s", url)
                return None
            except aiohttp.ClientError as err:
                _LOGGER.error("Connection error to %s: %s", url, err)
                return None
            except ET.ParseError as err:
                _LOGGER.error("Invalid XML from %s: %s", url, err)
                return None

    # ── Connection Test ─────────────────────────────────────────

    async def async_test_connection(self) -> bool:
        """Verifies that the control unit is reachable and credentials are valid."""
        root = await self.async_get_xml("/api/maps.xml")
        if root is None:
            return False
        # Verify that it is a valid maps XML
        return root.tag == "MapScenes"

    # ── Discovery ────────────────────────────────────────────────

    async def async_discover_elements(self) -> dict[str, dict]:
        """Discovers all elements from all scenes."""
        element_info: dict[str, dict] = {}

        maps_root = await self.async_get_xml("/api/maps.xml")
        if maps_root is None:
            _LOGGER.error("Unable to read maps.xml")
            return element_info

        scene_ids = [
            s.findtext("id").strip()
            for s in maps_root.findall(".//MapScene")
            if s.findtext("id")
        ]

        for sid in scene_ids:
            scene_root = await self.async_get_xml(f"/api/maps/{sid}.xml")
            if scene_root is None:
                continue

            scene_name = scene_root.findtext("name", "").strip()

            for el in scene_root.findall(".//Element"):
                eid = el.findtext("id")
                ename = el.findtext("name")
                eclass = el.findtext("classId")

                if not eid or not eclass:
                    continue

                eid = eid.strip()
                eclass = eclass.strip()

                if eclass in IGNORED_CLASSES:
                    continue

                if eclass not in ELEMENT_CLASS_TO_PLATFORM:
                    _LOGGER.warning(
                        "Unsupported class ignored: %s (name=%s, id=%s, scene=%s)",
                        eclass, ename, eid, scene_name,
                    )
                    continue

                _LOGGER.info(
                    "Discovered element: id=%s, class=%s, name=%s, scene=%s",
                    eid, eclass, (ename or "").strip(), scene_name,
                )
                element_info[eid] = {
                    "name": (ename or "").strip(),
                    "class": eclass,
                    "scene": scene_name,
                }

            # Small pause to avoid stressing the control unit
            await asyncio.sleep(0.2)

        _LOGGER.info("Discovery completed: %s elements found", len(element_info))
        for eid, info in element_info.items():
            _LOGGER.info("  -> %s: %s (%s)", eid, info["name"], info["class"])
        return element_info

    # ── Polling statuses ────────────────────────────────────────────

    async def async_fetch_all_statuses(self) -> ET.Element | None:
        """Retrieves the statuses of all elements."""
        return await self.async_get_xml("/api/element_xml_statuses.xml")

    async def async_fetch_single_status(self, element_id: str) -> ET.Element | None:
        """Retrieves the status of a single element."""
        numeric_id = element_id.split("/")[-1] if "/" in element_id else element_id
        return await self.async_get_xml(
            f"/api/element_xml_statuses/{numeric_id}.xml"
        )

    # ── Sending commands ────────────────────────────────────────────

    async def async_send_action(
        self,
        element_id: str,
        action: str,
        arguments: dict | None = None,
    ) -> bool:
        """Sends an action to an element.

        Args:
            element_id: Numeric ID of the element.
            action: Name of the action (e.g. "switchon", "setdimmer").
            arguments: Optional dictionary {index: {value, type}}.
                       E.g. {0: {"value": "50", "type": "int"}}

        Returns:
            True if the action was successful.
        """
        numeric_id = element_id.split("/")[-1] if "/" in element_id else element_id

        # Build URL with parameters
        params = f"_method=put&action={quote(action, safe='')}"

        if arguments:
            for idx, arg in sorted(arguments.items()):
                arg_val = quote(str(arg["value"]), safe="")
                arg_type = quote(str(arg.get("type", "int")), safe="")
                params += (
                    f"&{quote(f'arguments[{idx}][value]', safe='')}"
                    f"={arg_val}"
                    f"&{quote(f'arguments[{idx}][type]', safe='')}"
                    f"={arg_type}"
                )

        url = f"{self.base_url}/elements/{numeric_id}?{params}"

        async with self._semaphore:
            try:
                session = self._session()
                async with session.get(
                    url, auth=self._auth, timeout=self._timeout
                ) as resp:
                    if resp.status != 200:
                        _LOGGER.error(
                            "Command failed HTTP %s: %s %s",
                            resp.status, action, element_id,
                        )
                        return False
                    content = await resp.text()
                    # Response contains <bool>true</bool> if successful
                    if "<bool>true</bool>" in content:
                        return True
                    # Some commands do not return XML but are successful
                    if content.strip() == "" or resp.status == 200:
                        return True
                    _LOGGER.warning(
                        "Unexpected response for %s on %s: %s",
                        action, element_id, content[:200],
                    )
                    return True
            except asyncio.TimeoutError:
                _LOGGER.error("Command timeout %s on %s", action, element_id)
                return False
            except aiohttp.ClientError as err:
                _LOGGER.error("Command error %s on %s: %s", action, element_id, err)
                return False

    # ── Helpers for specific commands ─────────────────────────────

    async def async_light_switch(self, eid: str, turn_on: bool) -> bool:
        action = "switchon" if turn_on else "switchoff"
        return await self.async_send_action(eid, action)

    async def async_light_set_dimmer(self, eid: str, value: int) -> bool:
        return await self.async_send_action(
            eid, "setdimmer", {0: {"value": str(value), "type": "int"}}
        )

    async def async_cover_command(self, eid: str, command: str) -> bool:
        action_map = {"open": "turnup", "close": "turndown", "stop": "stop"}
        action = action_map.get(command, command)
        return await self.async_send_action(eid, action)

    async def async_thermostat_set_mode(self, eid: str, mode: str) -> bool:
        return await self.async_send_action(
            eid, "setTMode", {0: {"value": mode, "type": "QString"}}
        )

    async def async_thermostat_set_season(self, eid: str, season: str) -> bool:
        return await self.async_send_action(
            eid, "setSeason", {0: {"value": season, "type": "QString"}}
        )

    async def async_thermostat_set_temp_max(self, eid: str, temp: float) -> bool:
        value = str(int(temp * 10))
        return await self.async_send_action(
            eid, "setTMax", {0: {"value": value, "type": "QString"}}
        )

    async def async_thermostat_set_temp_min(self, eid: str, temp: float) -> bool:
        value = str(int(temp * 10))
        return await self.async_send_action(
            eid, "setTMin", {0: {"value": value, "type": "QString"}}
        )

    async def async_thermostat_set_speed(self, eid: str, speed: int) -> bool:
        return await self.async_send_action(
            eid, "setSpeed", {0: {"value": str(speed), "type": "int"}}
        )

    async def async_samsung_ac_set_temp(self, eid: str, temp: float) -> bool:
        return await self.async_send_action(
            eid, "settemperaturedesired",
            {0: {"value": str(int(temp)), "type": "int"}},
        )

    async def async_samsung_ac_set_fan(self, eid: str, speed: int) -> bool:
        return await self.async_send_action(
            eid, "setdimmer", {0: {"value": str(speed), "type": "int"}}
        )

    async def async_samsung_ac_set_mode(self, eid: str, action: str) -> bool:
        return await self.async_send_action(eid, action)

    async def async_water_heater_set_temp(self, eid: str, temp: float) -> bool:
        return await self.async_send_action(
            eid, "settemperaturedesiredH2O",
            {0: {"value": str(int(temp)), "type": "int"}},
        )

    async def async_water_heater_set_mode(self, eid: str, action: str) -> bool:
        return await self.async_send_action(eid, action)

    async def async_button_press(self, eid: str, action: str) -> bool:
        return await self.async_send_action(eid, action)

    async def async_switch_command(self, eid: str, turn_on: bool) -> bool:
        action = "Runpwm" if turn_on else "Stoppwm"
        return await self.async_send_action(eid, action)
