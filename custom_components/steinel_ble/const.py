"""Constants for the Steinel Bluetooth integration."""
from __future__ import annotations

from .products import PRODUCTS

DOMAIN = "steinel_ble"

CONF_AUTH_LEVEL = "auth_level"
CONF_LIVE_VALUES = "live_values"
CONF_ON_DURATION = "on_duration"
CONF_OFF_DURATION = "off_duration"

DEFAULT_DURATION = 14400  # what the app sends for "4 h on" / "4 h off"
POLL_INTERVAL = 300
LIVE_POLL_INTERVAL = 60
IDLE_DISCONNECT = 20

# Product types (Arendi.SmartRemoteLibrary.Product.ProductType)
TYPE_IHF_3D = 9
TYPE_RS_PRO_5100 = 14
TYPE_CUBO = 40
TYPE_IHF_LED = 45
TYPE_XLED_SPOT = 46
TYPE_RX0 = 48

# Products whose app driver sends the "on for n seconds" / "off for n seconds" modes
LIGHT_TYPES = {TYPE_IHF_3D, TYPE_RS_PRO_5100, TYPE_CUBO, TYPE_IHF_LED, TYPE_XLED_SPOT, TYPE_RX0}
CLASS_MULTISENSOR = 7


def product_name(number: int | None) -> str:
    if number in PRODUCTS:
        return PRODUCTS[number][0]
    return f"Steinel {number}" if number else "Steinel"


def product_type(number: int | None) -> int | None:
    return PRODUCTS[number][1] if number in PRODUCTS else None


def product_class(number: int | None) -> int | None:
    return PRODUCTS[number][3] if number in PRODUCTS else None
