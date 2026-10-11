# Steinel Bluetooth protocol

Recovered by static analysis of the Steinel **Smart Remote** Android app, version 4.0.8
(.NET MAUI, written by Arendi, protected with Babel Obfuscator). Nothing here has been
checked against real hardware yet; items I could not pin down are marked **unverified**.

The app talks to two different kinds of hardware. This document covers the first.

| | Service UUID | What it is |
|---|---|---|
| **Bluetooth products** | `2672b000-875a-47ff-b1ef-f3f6872db917` | Lights and sensors with built-in Bluetooth |
| Smart Remote dongle | `0000ad00-0200-1193-e311-af8c804128a9` | Bluetooth-to-infrared bridge for older sensors |

## Discovery

Devices advertise the 128-bit service UUID above. A device in firmware-update mode advertises
the Nordic DFU service `0xFE59` instead.

Manufacturer-specific data, after the two-byte company id:

| Offset | Size | Meaning |
|---|---|---|
| 0 | 2 | Product number, little endian (the Steinel article number, e.g. 7568 = XLED Home) |
| 2 | 1 | Mesh network id |
| 3 | 1 | Group number |
| 4 | 1 | Role: non-zero = group master, 2 = no mesh network |
| 5 | 1 | Quick info (optional; 1 = emergency light ready, 2 = emergency light fault, 3 = battery fault) |

## GATT

| Characteristic | Direction | Property |
|---|---|---|
| `2672b004-875a-47ff-b1ef-f3f6872db917` | device to host | notify |
| `2672b005-875a-47ff-b1ef-f3f6872db917` | host to device | write without response |

Both carry a byte stream. The host writes at most 20 bytes per write.

## Framing

```
COBS( command | payload | CRC16 little endian ) 0x00
```

* CRC-16/XMODEM (polynomial 0x1021, MSB first, no reflection) with initial value **0x1D0F**,
  over `command | payload`. Check value for `"123456789"` is `0xE5CC`.
* Standard COBS, terminated by a single zero byte.
* Response: `command | status | payload`.
* A frame from the device whose first byte is `0x07` is an unsolicited live-value report.
* The app waits 2 s for a response and tries each command three times.

Example, "read device information": `04 e0 b2 31 00`.

Status codes: 0 OK, 1 invalid command, 2 invalid parameter, 3 invalid value,
4 invalid authorisation, 5 inactive KNX parameters, 6 general error.

## Commands

All multi-byte values are little endian.

| Cmd | Name | Request payload | Response payload |
|---|---|---|---|
| `01` | Write configuration | (`id` u16, `len` u8, data)* | |
| `02` | Read configuration | (`id` u16)* | (`id` u16, `len` u8, data)* |
| `03` | Persist / reset configuration | u32 magic: `AA555AA5` persist, `5AA5AA55` factory reset | |
| `04` | Write mesh network configuration | group, network id, is-master, n, n neighbour groups | |
| `05` | Read mesh network configuration | | |
| `06` | Live values | `00`, enable u8 | |
| `07` | Live value report (device to host) | | (type u8, len u8, data)* |
| `08` | Group command | command u8, value u8 | |
| `09` | Device control | `mode` u8, `len` u8, data | |
| `0A` | Write device name | **unverified** | |
| `0C` / `0D` | Set / get KNX programming mode | | |
| `0E` | Read modes | (`mode` u8)* | (`mode` u8, `len` u8, data)* |
| `0F` | Read modes, with instances | (`mode` u8)* | (`instance` u8, `mode` u8, `len` u8, data)* |
| `10`-`13` | DALI addressing and push-button configuration | | |
| `14` | Write configuration, with instances | (`instance` u8, `id` u16, `len` u8, data)* | |
| `15` | Read configuration, with instances | (`id` u16)* | (`instance` u8, `id` u16, `len` u8, data)* |
| `16` | Device control, with instance | `instance` u8, `mode` u8, `len` u8, data | |
| `D0` | Get authorisation level | | level u8 |
| `D1` | Set password | level u8, len u8, ASCII (max 12) | |
| `D3` | Reset password | `00` | |
| `D4` | Log in | level u8, len u8, ASCII (max 12) | |
| `D5` | Log out | | |
| `E0` | Device information | | 11 bytes, see below |
| `E4` | Extended information (version list) | (type u8)* | |

Authorisation levels: 0 none, 1 end user, 2 installer. The app does not log in up front. It
sends the command, and if the status is 4 it asks the user for the password, logs in and
repeats the command.

Whether a device wants the plain (`01`/`02`/`09`/`0E`) or the instance-aware
(`14`/`15`/`16`/`0F`) commands is given by bit 1 of the abilities word in the device
information. The app asks for at most six parameters per read.

### Device information (`E0`)

| Offset | Size | Meaning |
|---|---|---|
| 0 | 2 | Product number |
| 2 | 2 | Abilities: bit 0 TLV parameters, bit 1 instance-aware commands, bit 2 extended info |
| 4 | 1 | Advertising state: 0 off, 1 permanently on, 2 on after power cycle, 3 after manual activation, 4 after becoming a slave |
| 5 | 2 | Remaining advertising time in seconds |
| 7 | 1 | Number of targets |
| 8 | 1 | Hardware version |
| 9 | 2 | Software version (byte order **unverified**) |

### Device control modes (`09` / `16`)

| Mode | Data | Effect |
|---|---|---|
| 0 | none | Normal sensor operation |
| 1 | none | Test mode |
| 2 | u32 seconds | Light on for that long. The app always sends 14400 (4 h). |
| 3 | u32 seconds | Light off for that long. The app always sends 14400 (4 h). |
| 4 | u32 seconds | Teach the current brightness as twilight threshold after that delay (0 = now) |
| 8 | u8 | XLED spots: 1 = Nightmatic, 2 = Nightmatic with sensor |
| 15 | u32 seconds | Timed teach on XLED spots and multisensors |

Modes 2 and 3 are sent by the app's drivers for Cubo, iHF L8xx, RS PRO LED R10/R20/R30,
RS PRO 5100, iHF 3D and the XLED Connect spots. Whether the firmware accepts durations other
than 14400 is **unverified**. Devices do not report which of modes 0-3 is active.

### Configuration parameters

| Id | Type | Meaning |
|---|---|---|
| `0101` | u16 | Stay-on time in seconds |
| `0103` | u16 | Basic illumination |
| `0104` / `0105` | u16 | HVAC switch-on delay / stay-on time |
| `0108` | u32 | Time of day in seconds (the app writes it to group masters on connect) |
| `0109` / `010A` | u32 | Switch-on / switch-off time |
| `010C` / `010D` | u32 | Night saving start / end |
| `0201` | u16 | Twilight threshold in lux (2 to 2000) |
| `0202` | u16 | Constant-light setpoint |
| `0303` | u8 | Adaptive range mode |
| `030A`-`030C` | u32 | True Presence height, radius, scenario |
| `030D` | u8 or u32 | Infrared sensitivity |
| `050E` | u8 | Sensor enabled |
| `0502`-`0518` | u8 | Assorted presence-detector options (relay/DALI output, IQ mode, push-button mode, LED off, ...) |

### Live value records (`07`)

| Type | Len | Data |
|---|---|---|
| 0, 1 | 3 | motion signal u16 (divide by 255), motion flag u8 |
| 2 | 2 | brightness u16, lux |
| 3 | 6 | radar target: angle i16, distance u16 (/255), signal u8 (/255), motion flag u8 |
| 4 | 2 | temperature i16, 0.01 degC |
| 5 | 2 | relative humidity u16, 0.1 % |
| 6 | 2 | CO2 u16, ppm |
| 7 | 2 | VOC u16 |
| 8 | 4 | air pressure u32, 0.01 hPa |
| 9 | 4 | True Presence: status u8, distance u16, direction u8 |

### Group command (`08`)

The app only ever sends command 1 with a flags byte: bit 1 is set when advertising is
permanently on, bit 0 is toggled by two UI actions. I did not trace which. **Unverified**,
and not used by the integration.
