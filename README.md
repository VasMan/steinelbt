# Steinel Bluetooth for Home Assistant

Local control of Steinel lights and sensors that have Bluetooth built in, using the protocol
of the Steinel Smart Remote app. See [PROTOCOL.md](PROTOCOL.md) for the protocol itself.

**Status: untested against hardware.** The protocol was recovered from the app's code and the
framing code passes its self-tests, but no command has been sent to a real device yet. Start
with `probe.py` below.

## What you get

| Entity | Products | Notes |
|---|---|---|
| Light | Cubo, iHF L8xx, RS PRO LED R10/R20/R30, RS PRO 5100, iHF 3D, XLED Connect spots | On / off override, see below |
| Select "Mode" | same | Sensor / On / Off |
| Number "Stay-on time" | any product that has the parameter | seconds |
| Number "Twilight threshold" | any product that has the parameter | lux |
| Motion, brightness | all | only with "live values" enabled |
| Temperature, humidity, CO2, VOC, air pressure | multisensors | only with "live values" enabled |

### How the light behaves

These are sensor lights. Bluetooth cannot switch them like a normal lamp. It can only tell
the light to ignore its sensor for a while:

* **On** keeps the light on for the configured duration, then it returns to sensor operation.
* **Off** keeps the light off for the configured duration, then it returns to sensor operation.
* **Sensor** (in the Mode select) returns to sensor operation immediately.

The duration defaults to 4 hours, which is what the app sends. You can change it in the
integration's options. The device does not report its mode, so Home Assistant shows the last
command it sent. There is no dimming command in the app.

### Connection

A Steinel device accepts one Bluetooth connection at a time. By default the integration
connects only when it needs to and disconnects after 20 seconds, so the Smart Remote app
keeps working. With "live values" enabled it stays connected.

If a password was set in the app, enter it when adding the device.

## Try it from a PC first

```bash
pip install bleak
```

```bash
python probe.py
```

That lists Steinel devices in range. Then, with the address it printed:

```bash
python probe.py AA:BB:CC:DD:EE:FF -v
```

```bash
python probe.py AA:BB:CC:DD:EE:FF --on 60
```

If the first command prints the product and its parameters, the transport is right. If
`--on 60` turns the light on for a minute, the control command is right. If anything fails,
the `-v` output shows every frame sent and received.

## Install

Copy `custom_components/steinel_ble` into the `custom_components` folder of your Home
Assistant configuration directory and restart. The device should then be discovered
automatically; otherwise add "Steinel Bluetooth" under Settings, Devices & services.

Needs a Bluetooth adapter or an ESPHome Bluetooth proxy with active connections.
