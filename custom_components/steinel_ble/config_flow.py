"""Config flow for Steinel Bluetooth devices."""
from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_ADDRESS, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import protocol as p
from .client import SteinelClient
from .const import (
    CONF_AUTH_LEVEL,
    CONF_LIVE_VALUES,
    CONF_OFF_DURATION,
    CONF_ON_DURATION,
    DEFAULT_DURATION,
    DOMAIN,
    product_name,
)

_LOGGER = logging.getLogger(__name__)

LEVELS = {"enduser": p.AuthLevel.ENDUSER, "installer": p.AuthLevel.INSTALLER}
AUTH_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_PASSWORD): str,
        vol.Required(CONF_AUTH_LEVEL, default="enduser"): selector.SelectSelector(
            selector.SelectSelectorConfig(options=list(LEVELS), translation_key=CONF_AUTH_LEVEL)
        ),
    }
)
DURATION = selector.NumberSelector(
    selector.NumberSelectorConfig(min=1, max=86400, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX)
)


def _title(info: BluetoothServiceInfoBleak) -> str:
    adv = next((p.Advertisement.parse(v) for v in info.manufacturer_data.values()), None)
    model = product_name(adv.product_number) if adv else "Steinel"
    return f"{model} ({info.address[-5:]})"


class SteinelConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}
        self._info: BluetoothServiceInfoBleak | None = None
        self._detail = ""

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SteinelOptionsFlow()

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._info = discovery_info
        self.context["title_placeholders"] = {"name": _title(discovery_info)}
        return await self.async_step_auth()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._info = self._discovered[user_input[CONF_ADDRESS]]
            await self.async_set_unique_id(self._info.address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return await self.async_step_auth()
        configured = self._async_current_ids(include_ignore=False)
        for info in bluetooth.async_discovered_service_info(self.hass, connectable=True):
            if info.address not in configured and p.SERVICE_UUID in info.service_uuids:
                self._discovered[info.address] = info
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In({a: _title(i) for a, i in self._discovered.items()})}
            ),
        )

    async def async_step_auth(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._info is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                CONF_ADDRESS: self._info.address,
                CONF_PASSWORD: user_input.get(CONF_PASSWORD),
                CONF_AUTH_LEVEL: int(LEVELS[user_input[CONF_AUTH_LEVEL]]),
            }
            if not (error := await self._async_try(data)):
                return self.async_create_entry(title=_title(self._info), data=data)
            errors["base"] = error
        return self.async_show_form(
            step_id="auth",
            data_schema=AUTH_SCHEMA,
            errors=errors,
            description_placeholders={"name": _title(self._info), "detail": self._detail},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                **entry.data,
                CONF_PASSWORD: user_input.get(CONF_PASSWORD),
                CONF_AUTH_LEVEL: int(LEVELS[user_input[CONF_AUTH_LEVEL]]),
            }
            if not (error := await self._async_try(data)):
                return self.async_update_reload_and_abort(entry, data=data)
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=AUTH_SCHEMA,
            errors=errors,
            description_placeholders={"detail": self._detail},
        )

    async def _async_try(self, data: dict[str, Any]) -> str | None:
        """Connect once; with a password also check that the device accepts it."""
        device = bluetooth.async_ble_device_from_address(self.hass, data[CONF_ADDRESS], connectable=True)
        if device is None:
            return "cannot_connect"
        client: SteinelClient | None = None
        self._detail = ""
        try:
            bleak_client = await establish_connection(BleakClientWithServiceCache, device, data[CONF_ADDRESS])
            client = SteinelClient(bleak_client, data[CONF_PASSWORD], data[CONF_AUTH_LEVEL])
            await client.start()
            if data[CONF_PASSWORD]:
                # The password may belong to the other level; try the chosen one first.
                levels = [data[CONF_AUTH_LEVEL]] + [int(v) for v in LEVELS.values() if v != data[CONF_AUTH_LEVEL]]
                failure: p.CommandError | None = None
                for level in levels:
                    try:
                        await client.login(level, data[CONF_PASSWORD])
                    except p.CommandError as err:
                        _LOGGER.warning("Login at level %s rejected: %s", level, err)
                        failure = failure or err
                        continue
                    data[CONF_AUTH_LEVEL] = level
                    failure = None
                    break
                if failure:
                    raise failure
        except p.CommandError as err:
            _LOGGER.warning("Steinel device %s refused the connection test: %s", data[CONF_ADDRESS], err)
            self._detail = str(err)
            return "invalid_auth" if err.command == p.Cmd.LOGIN else "command_failed"
        except (BleakError, TimeoutError, p.ProtocolError) as err:
            _LOGGER.debug("Connection test failed: %s", err)
            return "cannot_connect"
        finally:
            if client:
                await client.disconnect()
        return None


class SteinelOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_LIVE_VALUES: user_input[CONF_LIVE_VALUES],
                    CONF_ON_DURATION: int(user_input[CONF_ON_DURATION]),
                    CONF_OFF_DURATION: int(user_input[CONF_OFF_DURATION]),
                }
            )
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LIVE_VALUES, default=options.get(CONF_LIVE_VALUES, False)): bool,
                    vol.Required(CONF_ON_DURATION, default=options.get(CONF_ON_DURATION, DEFAULT_DURATION)): DURATION,
                    vol.Required(CONF_OFF_DURATION, default=options.get(CONF_OFF_DURATION, DEFAULT_DURATION)): DURATION,
                }
            ),
        )
