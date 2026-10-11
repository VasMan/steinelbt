"""Connection handling and polling for one Steinel device."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
import logging
import struct
from typing import Any

from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import protocol as p
from .client import SteinelClient
from .const import (
    CONF_AUTH_LEVEL,
    CONF_LIVE_VALUES,
    DOMAIN,
    IDLE_DISCONNECT,
    LIVE_POLL_INTERVAL,
    POLL_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

POLLED_PARAMS = [p.Param.STAY_ON_TIME, p.Param.LIGHT_LEVEL]

type SteinelConfigEntry = ConfigEntry[SteinelCoordinator]


@dataclass
class SteinelData:
    info: p.DeviceInfo | None = None
    config: dict[int, int] = field(default_factory=dict)  # parameter id -> value (instance 0)
    live: dict[int, float] = field(default_factory=dict)
    mode: int | None = None  # last mode we set; the device cannot report it


class SteinelCoordinator(DataUpdateCoordinator[SteinelData]):
    """Connects on demand, polls configuration and forwards live values."""

    config_entry: SteinelConfigEntry

    def __init__(self, hass: HomeAssistant, entry: SteinelConfigEntry) -> None:
        self.address: str = entry.data[CONF_ADDRESS]
        self.live_enabled: bool = entry.options.get(CONF_LIVE_VALUES, False)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {self.address}",
            update_interval=timedelta(seconds=LIVE_POLL_INTERVAL if self.live_enabled else POLL_INTERVAL),
        )
        self.data = SteinelData()
        self._client: SteinelClient | None = None
        self._connect_lock = asyncio.Lock()
        self._cancel_idle: Callable[[], None] | None = None

    # ------------------------------------------------------------ connection

    async def _ensure_client(self) -> SteinelClient:
        async with self._connect_lock:
            if self._client and self._client.is_connected:
                return self._client
            device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
            if device is None:
                raise HomeAssistantError(f"Steinel device {self.address} is not in range")
            bleak_client = await establish_connection(
                BleakClientWithServiceCache, device, self.name, disconnected_callback=self._on_disconnect
            )
            entry = self.config_entry
            client = SteinelClient(
                bleak_client, entry.data.get(CONF_PASSWORD), entry.data.get(CONF_AUTH_LEVEL, p.AuthLevel.ENDUSER)
            )
            client.on_live_values(self._on_live_values)
            try:
                self.data.info = await client.start()
                if self.live_enabled:
                    await client.live_values(True)
            except BaseException:
                await client.disconnect()
                raise
            self._client = client
            return client

    @callback
    def _on_disconnect(self, _client: Any) -> None:
        _LOGGER.debug("%s disconnected", self.address)
        self._client = None

    @callback
    def _on_live_values(self, values: dict[int, float]) -> None:
        self.data.live.update(values)
        self.async_update_listeners()

    @callback
    def _schedule_idle_disconnect(self) -> None:
        if self._cancel_idle:
            self._cancel_idle()
            self._cancel_idle = None
        if not self.live_enabled:
            self._cancel_idle = async_call_later(self.hass, IDLE_DISCONNECT, self._idle_disconnect)

    async def _idle_disconnect(self, _now: Any) -> None:
        self._cancel_idle = None
        await self.async_disconnect()

    async def async_disconnect(self) -> None:
        if self._cancel_idle:
            self._cancel_idle()
            self._cancel_idle = None
        client, self._client = self._client, None
        if client:
            await client.disconnect()

    async def async_run[T](self, func: Callable[[SteinelClient], Awaitable[T]]) -> T:
        """Run a client call, connecting first; the connection is dropped again when idle."""
        try:
            client = await self._ensure_client()
            return await func(client)
        except p.AuthorisationError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise ConfigEntryAuthFailed(f"The device wants a login for this: {err}") from err
        except (BleakError, TimeoutError, p.CommandError, p.ProtocolError) as err:
            await self.async_disconnect()
            raise HomeAssistantError(f"Steinel command failed: {err}") from err
        finally:
            self._schedule_idle_disconnect()

    # ------------------------------------------------------------ polling

    async def _async_update_data(self) -> SteinelData:
        async def read(client: SteinelClient) -> dict[tuple[int, int], bytes]:
            try:
                return await client.read_config(list(POLLED_PARAMS))
            except p.AuthorisationError:
                raise
            except p.CommandError as err:  # product without these parameters
                _LOGGER.debug("%s has no pollable parameters: %s", self.address, err)
                return {}

        try:
            raw = await self.async_run(read)
        except ConfigEntryAuthFailed:
            raise
        except HomeAssistantError as err:
            raise UpdateFailed(str(err)) from err
        for (instance, ident), value in raw.items():
            if instance == 0 and len(value) in (1, 2, 4):
                self.data.config[ident] = int.from_bytes(value, "little")
        return self.data

    # ------------------------------------------------------------ actions

    async def async_set_mode(self, mode: int, seconds: int | None = None) -> None:
        data = b"" if seconds is None else struct.pack("<I", seconds)
        await self.async_run(lambda client: client.set_mode(mode, data))
        self.data.mode = mode
        self.async_update_listeners()

    async def async_write_param(self, ident: int, value: int, size: int = 2) -> None:
        await self.async_run(lambda client: client.write_config(ident, value.to_bytes(size, "little")))
        self.data.config[ident] = value
        self.async_update_listeners()
