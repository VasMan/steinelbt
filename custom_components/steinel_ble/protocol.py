"""Wire protocol of Steinel Bluetooth products (as spoken by the Smart Remote app 4.0.8).

Pure Python, no Home Assistant or bleak imports, so it can be unit tested and reused.

Transport
---------
One GATT service with a notify characteristic (device -> host) and a write-without-response
characteristic (host -> device). Both carry a byte stream of frames:

    COBS( command | payload | CRC16-LE ) 0x00

CRC is CRC-16/XMODEM (poly 0x1021, MSB first) seeded with 0x1D0F, over command+payload.
The host splits the encoded frame into chunks of at most 20 bytes.

Responses are ``command | status | payload``. Frames whose first byte is 0x07 are unsolicited
live-value reports and carry ``type | len | data`` records instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
import struct

SERVICE_UUID = "2672b000-875a-47ff-b1ef-f3f6872db917"
CHAR_NOTIFY_UUID = "2672b004-875a-47ff-b1ef-f3f6872db917"
CHAR_WRITE_UUID = "2672b005-875a-47ff-b1ef-f3f6872db917"
DFU_SERVICE_UUID = "0000fe59-0000-1000-8000-00805f9b34fb"  # advertised while in bootloader

CHUNK_SIZE = 20
CRC_SEED = 0x1D0F
MAX_PASSWORD_LEN = 12
PERSIST_MAGIC = -1437246811 & 0xFFFFFFFF
RESET_MAGIC = 0x5AA5AA55


class Cmd(IntEnum):
    WRITE_CONFIG = 0x01          # (id u16, len u8, data)*
    READ_CONFIG = 0x02           # (id u16)*  ->  (id u16, len u8, data)*
    PERSIST_CONFIG = 0x03        # u32 magic (PERSIST_MAGIC or RESET_MAGIC)
    WRITE_NETWORK = 0x04
    READ_NETWORK = 0x05
    LIVE_VALUES = 0x06           # 0x00, enable u8
    LIVE_REPORT = 0x07           # unsolicited, device -> host
    GROUP_COMMAND = 0x08         # command u8, value u8
    DEVICE_CONTROL = 0x09        # mode u8, len u8, data
    READ_MODES = 0x0E            # (mode u8)*  ->  (mode u8, len u8, data)*
    READ_MODES_I = 0x0F          # (mode u8)*  ->  (instance u8, mode u8, len u8, data)*
    WRITE_CONFIG_I = 0x14        # (instance u8, id u16, len u8, data)*
    READ_CONFIG_I = 0x15         # (id u16)*  ->  (instance u8, id u16, len u8, data)*
    DEVICE_CONTROL_I = 0x16      # instance u8, mode u8, len u8, data
    GET_AUTH_LEVEL = 0xD0
    SET_PASSWORD = 0xD1          # level u8, len u8, ascii
    RESET_PASSWORD = 0xD3
    LOGIN = 0xD4                 # level u8, len u8, ascii
    LOGOUT = 0xD5
    DEVICE_INFO = 0xE0
    EXTENDED_INFO = 0xE4


class Status(IntEnum):
    OK = 0
    INVALID_COMMAND = 1
    INVALID_PARAMETER = 2
    INVALID_VALUE = 3
    INVALID_AUTHORISATION = 4
    INACTIVE_KNX_PARAMETERS = 5
    GENERAL_ERROR = 6


class AuthLevel(IntEnum):
    NONE = 0
    ENDUSER = 1
    INSTALLER = 2


class Mode(IntEnum):
    """Device-control mode ids (payload of DEVICE_CONTROL)."""

    SENSOR = 0        # normal sensor operation, no data
    TEST = 1          # walk-test mode, no data
    ON = 2            # light permanently on for <u32 seconds> (app sends 14400 = 4 h)
    OFF = 3           # light permanently off for <u32 seconds>
    TEACH = 4         # teach current brightness as threshold after <u32 seconds> (0 = now)
    NIGHTMATIC = 8    # XLED spots: data 1 = nightmatic, 2 = nightmatic + sensor


class Param(IntEnum):
    """Configuration parameter ids (READ_CONFIG / WRITE_CONFIG)."""

    STAY_ON_TIME = 0x101          # u16 seconds
    BASIC_ILLUMINATION = 0x103    # u16
    HVAC_SWITCH_ON_DELAY = 0x104  # u16
    HVAC_STAY_ON_TIME = 0x105     # u16
    CLOCK = 0x108                 # u32 seconds since midnight (written to group masters)
    SWITCH_ON_TIME = 0x109        # u32
    SWITCH_OFF_TIME = 0x10A       # u32
    SAVETIME_START = 0x10C        # u32
    SAVETIME_END = 0x10D          # u32
    LIGHT_LEVEL = 0x201           # u16 lux twilight threshold (2..2000)
    CONSTANT_LIGHT_SETPOINT = 0x202
    ADAPTIVE_RANGE_MODE = 0x303
    IR_SENSITIVITY = 0x30D
    SENSOR_ENABLED = 0x50E        # u8


class Live(IntEnum):
    """Keys of decoded live values."""

    MOTION_SIGNAL = 1
    MOTION = 26
    BRIGHTNESS = 2
    TEMPERATURE = 4
    HUMIDITY = 5
    CO2 = 6
    VOC = 7
    AIR_PRESSURE = 8
    PRESENCE_STATUS = 154
    PRESENCE_DISTANCE = 155
    PRESENCE_DIRECTION = 156


class ProtocolError(Exception):
    """Malformed data from the device."""


class CommandError(Exception):
    """The device answered with a non-OK status."""

    def __init__(self, command: int, status: int) -> None:
        self.command = command
        self.status = status
        try:
            name = Status(status).name
        except ValueError:
            name = str(status)
        super().__init__(f"command 0x{command:02x} failed: {name}")


class AuthorisationError(CommandError):
    """The device wants a (different) login for this command."""


# ---------------------------------------------------------------- framing

def crc16(data: bytes, crc: int = CRC_SEED) -> int:
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021 if crc & 0x8000 else crc << 1) & 0xFFFF
    return crc


def cobs_encode(data: bytes) -> bytes:
    out = bytearray()
    block = bytearray()
    for byte in data:
        if byte:
            block.append(byte)
            if len(block) == 254:
                out.append(255)
                out += block
                block.clear()
        else:
            out.append(len(block) + 1)
            out += block
            block.clear()
    out.append(len(block) + 1)
    out += block
    return bytes(out)


def cobs_decode(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data):
        code = data[i]
        if code == 0 or i + code > len(data) + 0:
            raise ProtocolError("invalid COBS data")
        out += data[i + 1:i + code]
        i += code
        if code != 255 and i < len(data):
            out.append(0)
    return bytes(out)


def encode_frame(command: int, payload: bytes = b"") -> bytes:
    raw = bytes([command]) + payload
    return cobs_encode(raw + struct.pack("<H", crc16(raw))) + b"\x00"


def chunks(frame: bytes, size: int = CHUNK_SIZE) -> list[bytes]:
    return [frame[i:i + size] for i in range(0, len(frame), size)]


class FrameDecoder:
    """Reassembles notification data into CRC-checked frames."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def reset(self) -> None:
        self._buf.clear()

    def feed(self, data: bytes) -> list[bytes]:
        frames = []
        for byte in data:
            if byte:
                self._buf.append(byte)
                continue
            raw, self._buf = bytes(self._buf), bytearray()
            if not raw:
                continue
            try:
                decoded = cobs_decode(raw)
            except ProtocolError:
                continue
            if len(decoded) < 3:
                continue
            body, crc = decoded[:-2], struct.unpack("<H", decoded[-2:])[0]
            if crc16(body) == crc:
                frames.append(body)
        return frames


@dataclass
class Response:
    command: int
    status: int
    payload: bytes

    @classmethod
    def parse(cls, frame: bytes) -> "Response":
        if len(frame) < 2:
            raise ProtocolError(f"short response {frame.hex()}")
        return cls(frame[0], frame[1], frame[2:])

    def raise_for_status(self) -> "Response":
        if self.status == Status.INVALID_AUTHORISATION:
            raise AuthorisationError(self.command, self.status)
        if self.status != Status.OK:
            raise CommandError(self.command, self.status)
        return self


# ---------------------------------------------------------------- payloads

@dataclass
class DeviceInfo:
    product_number: int
    abilities: int
    advertising_state: int
    advertising_remaining: int
    targets: int
    hardware_version: int
    software_version: str
    raw: bytes = field(repr=False, default=b"")

    @property
    def tlv_parameters(self) -> bool:
        return bool(self.abilities & 1)

    @property
    def instances(self) -> bool:
        """Device uses the instance-aware command variants (0x14/0x15/0x16/0x0F)."""
        return bool(self.abilities & 2)

    @property
    def extended_info(self) -> bool:
        return bool(self.abilities & 4)

    @classmethod
    def parse(cls, p: bytes) -> "DeviceInfo":
        if len(p) < 11:
            raise ProtocolError(f"device info too short: {p.hex()}")
        product, abilities, state, remaining = struct.unpack_from("<HHBH", p, 0)
        return cls(product, abilities, state, remaining, p[7], p[8], f"{p[10]}.{p[9]}", bytes(p))


@dataclass
class Advertisement:
    """Manufacturer specific data, without the 2 byte company id."""

    product_number: int
    network_id: int | None = None
    group: int | None = None
    role: int | None = None
    quick_info: int | None = None

    @classmethod
    def parse(cls, data: bytes) -> "Advertisement | None":
        if len(data) < 2:
            return None
        adv = cls(struct.unpack_from("<H", data, 0)[0])
        if len(data) >= 5:
            adv.network_id, adv.group, adv.role = data[2], data[3], data[4]
        if len(data) >= 6:
            adv.quick_info = data[5]
        return adv


def login_payload(level: int, password: str | None) -> bytes:
    pw = (password or "").encode("ascii", "ignore")[:MAX_PASSWORD_LEN]
    return bytes([level, len(pw)]) + pw


def read_config_payload(ids: list[int]) -> bytes:
    return b"".join(struct.pack("<H", i) for i in ids)


def parse_config(payload: bytes, instances: bool) -> dict[tuple[int, int], bytes]:
    """-> {(instance, id): data}"""
    out: dict[tuple[int, int], bytes] = {}
    i = 0
    head = 4 if instances else 3
    while i + head <= len(payload):
        instance = 0
        if instances:
            instance = payload[i]
            i += 1
        ident, length = struct.unpack_from("<HB", payload, i)
        i += 3
        out[(instance, ident)] = bytes(payload[i:i + length])
        i += length
    return out


def write_config_payload(items: list[tuple[int, int, bytes]], instances: bool) -> bytes:
    out = bytearray()
    for instance, ident, data in items:
        if instances:
            out.append(instance)
        out += struct.pack("<HB", ident, len(data)) + data
    return bytes(out)


def device_control(instance: int, mode: int, data: bytes, instances: bool) -> tuple[int, bytes]:
    """-> (command, payload)"""
    if instances:
        return Cmd.DEVICE_CONTROL_I, bytes([instance, mode, len(data)]) + data
    return Cmd.DEVICE_CONTROL, bytes([mode, len(data)]) + data


def parse_modes(payload: bytes, instances: bool) -> dict[tuple[int, int], bytes]:
    """-> {(instance, mode): data}"""
    out: dict[tuple[int, int], bytes] = {}
    i = 0
    head = 3 if instances else 2
    while i + head <= len(payload):
        instance = 0
        if instances:
            instance = payload[i]
            i += 1
        mode, length = payload[i], payload[i + 1]
        i += 2
        out[(instance, mode)] = bytes(payload[i:i + length])
        i += length
    return out


def parse_live(payload: bytes) -> dict[int, float]:
    """Decode a LIVE_REPORT payload into {Live key: value}."""
    out: dict[int, float] = {}
    i = 0
    while i + 2 <= len(payload):
        kind, length = payload[i], payload[i + 1]
        d = payload[i + 2:i + 2 + length]
        if len(d) < length:
            break
        i += 2 + length
        if kind in (0, 1) and length == 3:
            out[Live.MOTION_SIGNAL] = struct.unpack_from("<H", d)[0] / 255
            out[Live.MOTION] = d[2]
        elif kind == 2 and length == 2:
            out[Live.BRIGHTNESS] = struct.unpack_from("<H", d)[0]
        elif kind == 4 and length == 2:
            out[Live.TEMPERATURE] = struct.unpack_from("<h", d)[0] / 100
        elif kind == 5 and length == 2:
            out[Live.HUMIDITY] = struct.unpack_from("<H", d)[0] / 10
        elif kind == 6 and length == 2:
            out[Live.CO2] = struct.unpack_from("<H", d)[0]
        elif kind == 7 and length == 2:
            out[Live.VOC] = struct.unpack_from("<H", d)[0]
        elif kind == 8 and length == 4:
            out[Live.AIR_PRESSURE] = struct.unpack_from("<I", d)[0] / 100
        elif kind == 9 and length == 4:
            out[Live.PRESENCE_STATUS] = d[0]
            out[Live.PRESENCE_DISTANCE] = struct.unpack_from("<H", d, 1)[0]
            out[Live.PRESENCE_DIRECTION] = d[3]
    return out
