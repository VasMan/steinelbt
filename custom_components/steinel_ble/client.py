"""Async BLE client for Steinel Bluetooth products. Depends only on bleak."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import struct

from bleak import BleakClient
from bleak.exc import BleakError

from . import protocol as p

_LOGGER = logging.getLogger(__name__)

RESPONSE_TIMEOUT = 2.0
ATTEMPTS = 3
CONFIG_BATCH = 6  # the app never asks for more than six parameters per request


class SteinelClient:
    """Speaks the Steinel protocol over an already connected BleakClient."""

    def __init__(self, client: BleakClient, password: str | None = None,
                 auth_level: int = p.AuthLevel.ENDUSER) -> None:
        self._client = client
        self._password = password
        self._auth_level = auth_level
        self._decoder = p.FrameDecoder()
        self._lock = asyncio.Lock()
        self._pending: asyncio.Future[p.Response] | None = None
        self._live_callbacks: list[Callable[[dict[int, float]], None]] = []
        self.info: p.DeviceInfo | None = None

    @property
    def is_connected(self) -> bool:
        return self._client.is_connected

    def on_live_values(self, callback: Callable[[dict[int, float]], None]) -> None:
        self._live_callbacks.append(callback)

    async def start(self) -> p.DeviceInfo:
        """Subscribe to notifications and read the device information."""
        self._decoder.reset()
        await self._client.start_notify(p.CHAR_NOTIFY_UUID, self._on_notify)
        self.info = p.DeviceInfo.parse((await self._request(p.Cmd.DEVICE_INFO)).payload)
        return self.info

    async def disconnect(self) -> None:
        try:
            await self._client.disconnect()
        except (BleakError, TimeoutError, OSError) as err:
            _LOGGER.debug("Disconnect failed: %s", err)

    # ------------------------------------------------------------ transport

    def _on_notify(self, _char, data: bytearray) -> None:
        for frame in self._decoder.feed(bytes(data)):
            _LOGGER.debug("RX %s", frame.hex(" "))
            if frame[0] == p.Cmd.LIVE_REPORT:
                values = p.parse_live(frame[1:])
                for callback in self._live_callbacks:
                    callback(values)
                continue
            if self._pending is not None and not self._pending.done():
                try:
                    self._pending.set_result(p.Response.parse(frame))
                except p.ProtocolError as err:
                    self._pending.set_exception(err)

    async def _exchange(self, command: int, payload: bytes) -> p.Response:
        last: Exception | None = None
        for _ in range(ATTEMPTS):
            self._pending = asyncio.get_running_loop().create_future()
            _LOGGER.debug("TX %02x %s", command, payload.hex(" "))
            for chunk in p.chunks(p.encode_frame(command, payload)):
                await self._client.write_gatt_char(p.CHAR_WRITE_UUID, chunk, response=False)
            try:
                async with asyncio.timeout(RESPONSE_TIMEOUT):
                    response = await self._pending
            except TimeoutError as err:
                last = err
                continue
            finally:
                self._pending = None
            if response.command != command:
                _LOGGER.debug("Response 0x%02x does not match request 0x%02x", response.command, command)
            return response
        raise TimeoutError(f"no response to command 0x{command:02x}") from last

    async def _request(self, command: int, payload: bytes = b"") -> p.Response:
        """Send a command; if the device asks for authorisation, log in and repeat it.

        The configured level is tried first, then the other one, because the user cannot know
        which level a command needs. Without a password an empty one is sent.
        """
        async with self._lock:
            response = await self._exchange(command, payload)
            if response.status != p.Status.INVALID_AUTHORISATION or command == p.Cmd.LOGIN:
                return response.raise_for_status()
            notes = []
            levels = [self._auth_level] + [int(lv) for lv in (p.AuthLevel.ENDUSER, p.AuthLevel.INSTALLER)
                                           if lv != self._auth_level]
            for level in levels:
                name = p.AuthLevel(level).name.lower()
                login = await self._exchange(p.Cmd.LOGIN, p.login_payload(level, self._password))
                if login.status != p.Status.OK:
                    notes.append(f"login as {name}: {p.status_name(login.status)}")
                    continue
                response = await self._exchange(command, payload)
                if response.status != p.Status.INVALID_AUTHORISATION:
                    self._auth_level = level
                    return response.raise_for_status()
                notes.append(f"login as {name} accepted but the command was still refused")
            if self._password is None:
                notes.append("no password configured")
            _LOGGER.warning("Command 0x%02x needs a login that failed: %s", command, "; ".join(notes))
            raise p.AuthorisationError(command, response.status, "; ".join(notes))

    # ------------------------------------------------------------ commands

    @property
    def _instances(self) -> bool:
        return bool(self.info and self.info.instances)

    async def login(self, level: int | None = None, password: str | None = None) -> None:
        await self._request(p.Cmd.LOGIN, p.login_payload(
            self._auth_level if level is None else level, self._password if password is None else password))

    async def auth_level(self) -> int:
        return (await self._request(p.Cmd.GET_AUTH_LEVEL)).payload[0]

    async def read_config(self, ids: list[int]) -> dict[tuple[int, int], bytes]:
        """Read configuration parameters -> {(instance, id): raw little-endian data}."""
        out: dict[tuple[int, int], bytes] = {}
        command = p.Cmd.READ_CONFIG_I if self._instances else p.Cmd.READ_CONFIG
        for i in range(0, len(ids), CONFIG_BATCH):
            response = await self._request(command, p.read_config_payload(ids[i:i + CONFIG_BATCH]))
            out.update(p.parse_config(response.payload, self._instances))
        return out

    async def write_config(self, ident: int, data: bytes, instance: int = 0, persist: bool = True) -> None:
        command = p.Cmd.WRITE_CONFIG_I if self._instances else p.Cmd.WRITE_CONFIG
        await self._request(command, p.write_config_payload([(instance, ident, data)], self._instances))
        if persist:
            await self._request(p.Cmd.PERSIST_CONFIG, struct.pack("<I", p.PERSIST_MAGIC))

    async def set_mode(self, mode: int, data: bytes = b"", instance: int = 0) -> None:
        await self._request(*p.device_control(instance, mode, data, self._instances))

    async def read_modes(self, modes: list[int]) -> dict[tuple[int, int], bytes]:
        command = p.Cmd.READ_MODES_I if self._instances else p.Cmd.READ_MODES
        return p.parse_modes((await self._request(command, bytes(modes))).payload, self._instances)

    async def light_on(self, seconds: int) -> None:
        await self.set_mode(p.Mode.ON, struct.pack("<I", seconds))

    async def light_off(self, seconds: int) -> None:
        await self.set_mode(p.Mode.OFF, struct.pack("<I", seconds))

    async def sensor_mode(self) -> None:
        await self.set_mode(p.Mode.SENSOR)

    async def live_values(self, enable: bool) -> None:
        await self._request(p.Cmd.LIVE_VALUES, bytes([0, int(enable)]))
