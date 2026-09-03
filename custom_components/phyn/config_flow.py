"""Config flow for phyn integration."""
from aiophyn import async_get_api
from aiophyn.errors import RequestError
from botocore.exceptions import ClientError
import voluptuous as vol

from homeassistant import config_entries, core, exceptions
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .const import (
    DOMAIN,
    LOGGER,
    ALL_ALERT_TYPES,
    CONF_EXCLUDED_ALERT_TYPES,
    CONF_DEVICE_IDS,
    CONF_LOCAL_HOSTS,
    CONF_LOCAL_POLL_INTERVAL,
    CONF_UPDATE_INTERVAL,
    DEFAULT_LOCAL_POLL_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    MAX_LOCAL_POLL_INTERVAL,
    MAX_UPDATE_INTERVAL,
    MIN_LOCAL_POLL_INTERVAL,
    MIN_UPDATE_INTERVAL,
)
from .jnap import (
    JnapConnectionError,
    JnapError,
    JnapProtocolError,
    async_verify_device,
    normalize_mac,
)

DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_USERNAME): str,
    vol.Required(CONF_PASSWORD): str,
})
REAUTH_SCHEMA = vol.Schema({
    vol.Required(CONF_USERNAME): str,
    vol.Required(CONF_PASSWORD): str,
})


async def _get_api_and_homes(hass: core.HomeAssistant, username: str, password: str):
    """Authenticate and return (api, homes).

    Raises CannotConnect or propagates ClientError on auth failure.
    """
    session = async_get_clientsession(hass)
    try:
        api = await async_get_api(
            username, password, phyn_brand="phyn", session=session
        )
    except RequestError as request_error:
        LOGGER.error("Error connecting to the Phyn API: %s", request_error)
        raise CannotConnect from request_error

    homes = await api.home.get_homes(username)
    return api, homes


def _device_label(device: dict) -> str:
    """Return a human-readable label for a device."""
    name = device.get("device_name") or device.get("product_code", "")
    return f"{name} ({device['device_id']})" if name else device["device_id"]


def _build_device_schema(homes: list[dict], current_device_ids: list[str] | None = None) -> vol.Schema:
    """Build a schema with one multi_select per home.

    Each field key is the home name so that HA's config flow renders it as the
    field heading (HA falls back to the raw key when no translation entry exists).
    If *current_device_ids* is provided the defaults are pre-populated with the
    currently selected devices for each home (falling back to all devices in that
    home when none are currently selected).
    """
    current = set(current_device_ids) if current_device_ids else set()
    fields: dict = {}
    for home in homes:
        if not home.get("devices"):
            continue
        home_name = home.get("name", home["id"])
        device_map = {d["device_id"]: _device_label(d) for d in home["devices"]}
        all_ids = list(device_map.keys())
        if current:
            default_ids = [d for d in all_ids if d in current] or all_ids
        else:
            default_ids = all_ids
        fields[vol.Optional(home_name, default=default_ids)] = cv.multi_select(device_map)
    return vol.Schema(fields)


def _extract_device_ids(user_input: dict, homes: list[dict]) -> list[str]:
    """Flatten selected device IDs from per-home fields in a submitted form."""
    selected: list[str] = []
    seen: set[str] = set()
    for home in homes:
        if not home.get("devices"):
            continue
        home_name = home.get("name", home["id"])
        for device_id in user_input.get(home_name, []):
            if device_id not in seen:
                seen.add(device_id)
                selected.append(device_id)
    return selected


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for phyn."""

    VERSION = 1
    MINOR_VERSION = 4

    def __init__(self) -> None:
        """Initialize flow state."""
        self._username: str | None = None
        self._password: str | None = None
        self._homes: list[dict] = []

    @staticmethod
    def async_get_options_flow(config_entry):
        """Return the options flow handler."""
        return PhynOptionsFlow(config_entry)

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo):
        """Handle a DHCP-discovered Phyn Plus (MAC OUI 28:F5:37).

        If the device belongs to an already-configured account, verify its
        local JNAP endpoint and store/refresh the device's local host so
        local access follows IP changes automatically. Otherwise verify it
        really is a Phyn device (the OUI is a shared IEEE block) and offer
        account setup.
        """
        mac = normalize_mac(discovery_info.macaddress)
        host = discovery_info.ip
        LOGGER.debug("DHCP discovery: mac=%s host=%s", mac, host)

        # De-duplicate concurrent discovery flows for the same device.
        await self.async_set_unique_id(f"phyn_local_{mac}")

        for entry in self._async_current_entries(include_ignore=False):
            device_ids: list[str] = entry.data.get(CONF_DEVICE_IDS, [])
            matched = next(
                (d for d in device_ids if normalize_mac(d) == mac), None
            )
            if matched is None:
                continue
            current_hosts: dict = entry.options.get(CONF_LOCAL_HOSTS, {})
            if current_hosts.get(matched) == host:
                return self.async_abort(reason="already_configured")
            try:
                await async_verify_device(host, expected_device_id=matched)
            except JnapError as err:
                LOGGER.debug(
                    "Discovered %s at %s but JNAP verification failed: %s",
                    mac, host, err,
                )
                return self.async_abort(reason="not_phyn_local")
            self.hass.config_entries.async_update_entry(
                entry,
                options={
                    **entry.options,
                    CONF_LOCAL_HOSTS: {**current_hosts, matched: host},
                },
            )
            LOGGER.info(
                "Local access for Phyn device %s auto-configured at %s", matched, host
            )
            return self.async_abort(reason="local_host_configured")

        # Unknown device: confirm it speaks Phyn JNAP before prompting for
        # account setup, so random devices in the shared OUI block don't
        # generate discovery noise.
        try:
            await async_verify_device(host)
        except JnapError:
            return self.async_abort(reason="not_phyn_local")
        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        """Handle the initial step (credentials)."""
        errors = {}
        if user_input is not None:
            try:
                _, homes = await _get_api_and_homes(
                    self.hass,
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except ClientError as error:
                if error.response['Error']['Code'] == "NotAuthorizedException":
                    errors["base"] = "invalid_auth"
                else:
                    errors["base"] = "cannot_connect"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                self._username = user_input[CONF_USERNAME]
                self._password = user_input[CONF_PASSWORD]
                self._homes = homes

                await self.async_set_unique_id(self._username)
                self._abort_if_unique_id_configured()

                return await self.async_step_device()

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_device(self, user_input=None):
        """Select devices to monitor, grouped by home."""
        errors = {}
        if user_input is not None:
            selected = _extract_device_ids(user_input, self._homes)
            if not selected:
                errors["base"] = "no_devices_selected"
            else:
                return self.async_create_entry(
                    title=self._username,
                    data={
                        CONF_USERNAME: self._username,
                        CONF_PASSWORD: self._password,
                        CONF_DEVICE_IDS: selected,
                    },
                )

        return self.async_show_form(
            step_id="device",
            data_schema=_build_device_schema(self._homes),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}
        if user_input is not None:
            reauth_entry = self._get_reauth_entry()
            try:
                await _get_api_and_homes(
                    self.hass,
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except ClientError as error:
                if error.response['Error']['Code'] == "NotAuthorizedException":
                    errors["base"] = "invalid_auth"
                else:
                    errors["base"] = "cannot_connect"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                result = self.async_update_and_abort(
                    reauth_entry,
                    data_updates={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )
                self.hass.config_entries.async_schedule_reload(reauth_entry.entry_id)
                return result

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input=None):
        """Change device selection without re-authentication.

        Stored credentials are reused silently. If they are no longer valid the
        flow redirects to reauth instead of surfacing an unactionable error.
        """
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is None:
            # First call: fetch the live device list and show the form.
            username = reconfigure_entry.data[CONF_USERNAME]
            password = reconfigure_entry.data[CONF_PASSWORD]
            try:
                _, homes = await _get_api_and_homes(self.hass, username, password)
            except (ClientError, CannotConnect):
                return await self.async_step_reauth_confirm()

            self._homes = homes
            current_ids = reconfigure_entry.data.get(CONF_DEVICE_IDS, [])
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=_build_device_schema(self._homes, current_ids),
            )

        selected = _extract_device_ids(user_input, self._homes)
        errors = {}
        if not selected:
            errors["base"] = "no_devices_selected"
            current_ids = reconfigure_entry.data.get(CONF_DEVICE_IDS, [])
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=_build_device_schema(self._homes, current_ids),
                errors=errors,
            )

        result = self.async_update_and_abort(
            reconfigure_entry,
            data_updates={CONF_DEVICE_IDS: selected},
        )
        self.hass.config_entries.async_schedule_reload(reconfigure_entry.entry_id)
        return result


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class PhynOptionsFlow(config_entries.OptionsFlow):
    """Handle Phyn integration options.

    Covers suppressed alert types, the cloud polling interval, and per-device
    local (LAN) hosts for Phyn Plus devices.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry
        #: Maps the human-readable local-host form field key -> phyn device id.
        self._local_field_map: dict[str, str] = {}

    def _local_capable_devices(self) -> list:
        """Return the coordinator's Phyn Plus devices (local-capable)."""
        coordinator = self.hass.data.get(DOMAIN, {}).get("coordinator")
        if coordinator is None:
            return []
        return [
            device
            for device in coordinator.devices
            if device.product_code in ("PP1", "PP2")
        ]

    def _build_schema(self, user_input: dict | None = None) -> vol.Schema:
        """Build the options schema, including per-device local host fields.

        When re-showing the form after a validation error, *user_input*
        pre-populates the fields so the user's entries are not lost.
        """
        submitted = user_input or {}
        current_excluded = submitted.get(
            CONF_EXCLUDED_ALERT_TYPES,
            self._config_entry.options.get(CONF_EXCLUDED_ALERT_TYPES, []),
        )
        current_interval = submitted.get(
            CONF_UPDATE_INTERVAL,
            self._config_entry.options.get(
                CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
            ),
        )
        current_local_interval = submitted.get(
            CONF_LOCAL_POLL_INTERVAL,
            self._config_entry.options.get(
                CONF_LOCAL_POLL_INTERVAL, DEFAULT_LOCAL_POLL_INTERVAL
            ),
        )
        current_hosts: dict = self._config_entry.options.get(CONF_LOCAL_HOSTS, {})

        fields: dict = {
            vol.Optional(
                CONF_EXCLUDED_ALERT_TYPES,
                default=current_excluded,
            ): cv.multi_select(ALL_ALERT_TYPES),
            vol.Optional(
                CONF_UPDATE_INTERVAL,
                default=current_interval,
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_UPDATE_INTERVAL,
                    max=MAX_UPDATE_INTERVAL,
                    step=10,
                    unit_of_measurement="s",
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_LOCAL_POLL_INTERVAL,
                default=current_local_interval,
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_LOCAL_POLL_INTERVAL,
                    max=MAX_LOCAL_POLL_INTERVAL,
                    step=1,
                    unit_of_measurement="s",
                    mode=NumberSelectorMode.BOX,
                )
            ),
        }

        # Human-readable keys double as field labels (HA falls back to the raw
        # key when no translation exists) — same pattern as the device step.
        self._local_field_map = {}
        for device in self._local_capable_devices():
            key = f"Local IP for {device.device_name} ({device.id[-4:]})"
            self._local_field_map[key] = device.id
            current = submitted.get(key, current_hosts.get(device.id, ""))
            fields[vol.Optional(key, default=current)] = str

        return vol.Schema(fields)

    async def async_step_init(self, user_input=None):
        """Manage options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Start from the stored mapping so hosts for devices that were not
            # shown in this form (e.g. integration not loaded) are preserved.
            shown_ids = set(self._local_field_map.values())
            local_hosts: dict[str, str] = {
                device_id: host
                for device_id, host in self._config_entry.options.get(
                    CONF_LOCAL_HOSTS, {}
                ).items()
                if device_id not in shown_ids
            }
            for field_key, device_id in self._local_field_map.items():
                host = (user_input.get(field_key) or "").strip()
                if not host:
                    continue
                try:
                    await async_verify_device(host, expected_device_id=device_id)
                except JnapConnectionError:
                    errors[field_key] = "local_host_unreachable"
                except JnapProtocolError:
                    errors[field_key] = "local_host_mismatch"
                else:
                    local_hosts[device_id] = host

            if not errors:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_EXCLUDED_ALERT_TYPES: user_input.get(
                            CONF_EXCLUDED_ALERT_TYPES, []
                        ),
                        CONF_UPDATE_INTERVAL: int(
                            user_input.get(
                                CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                            )
                        ),
                        CONF_LOCAL_POLL_INTERVAL: int(
                            user_input.get(
                                CONF_LOCAL_POLL_INTERVAL,
                                DEFAULT_LOCAL_POLL_INTERVAL,
                            )
                        ),
                        CONF_LOCAL_HOSTS: local_hosts,
                    },
                )

        return self.async_show_form(
            step_id="init", data_schema=self._build_schema(user_input), errors=errors
        )
