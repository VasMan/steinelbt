"""Talk to a Steinel Bluetooth device from a PC, without Home Assistant.

    pip install bleak
    python probe.py                      # scan and list Steinel devices
    python probe.py AA:BB:CC:DD:EE:FF    # connect, print device info and parameters
    python probe.py <address> --on 60    # light on for 60 s
    python probe.py <address> --off 60   # light off for 60 s
    python probe.py <address> --sensor   # back to sensor operation
    python probe.py <address> --live 30  # print live sensor values for 30 s
    python probe.py <address> --password secret [--installer] ...

Close the Smart Remote app first: the device accepts one connection at a time.
Add -v to see every frame.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
from pathlib import Path
import sys
import types

from bleak import BleakClient, BleakScanner

# Import protocol.py / client.py without importing the Home Assistant parts of the package.
_pkg = types.ModuleType("steinel_ble_lib")
_pkg.__path__ = [str(Path(__file__).parent / "custom_components" / "steinel_ble")]
sys.modules["steinel_ble_lib"] = _pkg
p = importlib.import_module("steinel_ble_lib.protocol")
SteinelClient = importlib.import_module("steinel_ble_lib.client").SteinelClient
PRODUCTS = importlib.import_module("steinel_ble_lib.products").PRODUCTS


def describe(number: int) -> str:
    return PRODUCTS[number][0] if number in PRODUCTS else "unknown product"


async def scan() -> None:
    print("Scanning for 10 s ...")
    found = await BleakScanner.discover(timeout=10, return_adv=True)
    for device, adv in found.values():
        if p.SERVICE_UUID not in adv.service_uuids and p.DFU_SERVICE_UUID not in adv.service_uuids:
            continue
        info = next((p.Advertisement.parse(v) for v in adv.manufacturer_data.values()), None)
        company = next(iter(adv.manufacturer_data), None)
        print(f"{device.address}  rssi {adv.rssi}  name {adv.local_name!r}  company 0x{company or 0:04x}")
        if info:
            print(f"    product {info.product_number} ({describe(info.product_number)})  "
                  f"network {info.network_id}  group {info.group}  role {info.role}  quick-info {info.quick_info}")


async def run(args: argparse.Namespace) -> None:
    level = p.AuthLevel.INSTALLER if args.installer else p.AuthLevel.ENDUSER
    async with BleakClient(args.address) as bleak_client:
        client = SteinelClient(bleak_client, args.password, level)
        info = await client.start()
        print(f"Product {info.product_number} ({describe(info.product_number)})")
        print(f"  hardware {info.hardware_version}  software {info.software_version}  "
              f"abilities 0x{info.abilities:04x} (instances={info.instances})  raw {info.raw.hex(' ')}")
        try:
            print(f"  authorisation level: {p.AuthLevel(await client.auth_level()).name}")
        except (p.CommandError, ValueError, TimeoutError) as err:
            print(f"  authorisation level: ? ({err})")
        if args.password:
            await client.login()
            print("  logged in")
        try:
            config = await client.read_config([p.Param.STAY_ON_TIME, p.Param.LIGHT_LEVEL])
            for (instance, ident), data in config.items():
                print(f"  parameter 0x{ident:03x} instance {instance}: {int.from_bytes(data, 'little')} ({data.hex(' ')})")
        except p.CommandError as err:
            print(f"  could not read parameters: {err}")
        if args.on is not None:
            await client.light_on(args.on)
            print(f"Light on for {args.on} s")
        if args.off is not None:
            await client.light_off(args.off)
            print(f"Light off for {args.off} s")
        if args.sensor:
            await client.sensor_mode()
            print("Sensor operation")
        if args.live:
            client.on_live_values(lambda values: print({p.Live(k).name: round(v, 2) for k, v in values.items()}))
            await client.live_values(True)
            await asyncio.sleep(args.live)
            await client.live_values(False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("address", nargs="?")
    parser.add_argument("--password")
    parser.add_argument("--installer", action="store_true", help="log in as installer instead of end user")
    parser.add_argument("--on", type=int, metavar="SECONDS")
    parser.add_argument("--off", type=int, metavar="SECONDS")
    parser.add_argument("--sensor", action="store_true")
    parser.add_argument("--live", type=int, metavar="SECONDS")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    if args.verbose:
        logging.getLogger("bleak").setLevel(logging.INFO)
    asyncio.run(run(args) if args.address else scan())


if __name__ == "__main__":
    main()
