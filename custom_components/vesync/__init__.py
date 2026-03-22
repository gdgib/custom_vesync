"""VeSync integration."""

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from pyvesync.vesync import VeSync

from .common import async_process_devices
from .const import (
    DOMAIN,
    POLLING_INTERVAL,
    SERVICE_UPDATE_DEVS,
    UPDATE_LISTENER,
    VS_BINARY_SENSORS,
    VS_BUTTON,
    VS_DISCOVERY,
    VS_FANS,
    VS_HUMIDIFIERS,
    VS_LIGHTS,
    VS_MANAGER,
    VS_NUMBERS,
    VS_SENSORS,
    VS_SWITCHES,
)

PLATFORMS = {
    Platform.SWITCH: VS_SWITCHES,
    Platform.FAN: VS_FANS,
    Platform.LIGHT: VS_LIGHTS,
    Platform.SENSOR: VS_SENSORS,
    Platform.HUMIDIFIER: VS_HUMIDIFIERS,
    Platform.NUMBER: VS_NUMBERS,
    Platform.BINARY_SENSOR: VS_BINARY_SENSORS,
    Platform.BUTTON: VS_BUTTON,
}

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.removed(DOMAIN, raise_if_present=False)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up Vesync as config entry."""
    username = config_entry.data[CONF_USERNAME]
    password = config_entry.data[CONF_PASSWORD]

    time_zone = str(hass.config.time_zone)

    manager = VeSync(username, password, time_zone)

    login = await hass.async_add_executor_job(manager.login)

    if not login:
        _LOGGER.error("Unable to login to the VeSync server")
        raise ConfigEntryAuthFailed("Error logging in with username and password")

    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = {}
    hass.data[DOMAIN][config_entry.entry_id][VS_MANAGER] = manager

    # Create a DataUpdateCoordinator for the manager
    async def async_update_data():
        """Fetch data from API endpoint."""
        try:
            await hass.async_add_executor_job(manager.update)
        except Exception as err:
            raise UpdateFailed(f"Update failed: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="vesync",
        update_method=async_update_data,
        update_interval=timedelta(seconds=config_entry.options[POLLING_INTERVAL]),
    )

    # Fetch initial data so we have data when entities subscribe
    await coordinator.async_config_entry_first_refresh()

    # Store the coordinator instance in hass.data
    hass.data[DOMAIN][config_entry.entry_id]["coordinator"] = coordinator

    # pyvesync appends to device lists on each update() call rather than
    # replacing them, so after login() + update() each device appears twice.
    # Deduplicate by CID before building the entity list.
    for _attr in ("fans", "bulbs", "outlets", "switches", "kitchen"):
        _device_list = getattr(manager, _attr, None)
        if _device_list:
            _seen: set[str] = set()
            setattr(
                manager,
                _attr,
                [d for d in _device_list if d.cid not in _seen and not _seen.add(d.cid)],  # type: ignore[func-returns-value]
            )

    device_dict = await async_process_devices(hass, manager)
    platforms_list: list = []

    for p, vs_p in PLATFORMS.items():
        hass.data[DOMAIN][config_entry.entry_id][vs_p] = []
        if device_dict[vs_p]:
            hass.data[DOMAIN][config_entry.entry_id][vs_p].extend(device_dict[vs_p])
            platforms_list.append(p)

    # Store loaded platforms
    hass.data[DOMAIN][config_entry.entry_id]["loaded_platforms"] = platforms_list

    await hass.config_entries.async_forward_entry_setups(config_entry, platforms_list)

    # Add update listener and store it
    update_listener = config_entry.add_update_listener(async_update_options)
    hass.data[DOMAIN][config_entry.entry_id][UPDATE_LISTENER] = update_listener

    async def async_new_device_discovery(service: ServiceCall) -> None:
        """Discover if new devices should be added."""
        manager = hass.data[DOMAIN][config_entry.entry_id][VS_MANAGER]
        dev_dict = await async_process_devices(hass, manager)
        platforms_to_setup = []

        async def _add_new_devices(platform: str) -> None:
            """Add new devices to hass."""
            old_devices = hass.data[DOMAIN][config_entry.entry_id][PLATFORMS[platform]]
            if new_devices := list(
                set(dev_dict.get(VS_SWITCHES, [])).difference(old_devices)
            ):
                old_devices.extend(new_devices)
                if old_devices:
                    async_dispatcher_send(
                        hass, VS_DISCOVERY.format(PLATFORMS[platform]), new_devices
                    )
                else:
                    platforms_to_setup.append(platform)

        for k in PLATFORMS:
            _add_new_devices(k)

        if platforms_to_setup:
            await hass.config_entries.async_forward_entry_setups(
                config_entry, platforms_to_setup
            )

    hass.services.async_register(
        DOMAIN, SERVICE_UPDATE_DEVS, async_new_device_discovery
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    loaded_platforms = hass.data[DOMAIN][entry.entry_id]["loaded_platforms"]
    if unload_ok := await hass.config_entries.async_unload_platforms(
        entry, loaded_platforms
    ):
        del hass.data[DOMAIN][entry.entry_id]
        if not hass.data[DOMAIN]:
            del hass.data[DOMAIN]
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old entry."""

    if entry.version == 1:
        username = entry.data[CONF_USERNAME]
        password = entry.data[CONF_PASSWORD]

        _LOGGER.debug("Migrating VeSync config entry")

        hass.config_entries.async_update_entry(
            entry,
            version=2,
            data={
                CONF_USERNAME: username,
                CONF_PASSWORD: password,
            },
            options={
                POLLING_INTERVAL: 60,
            },
        )

    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update options."""

    await hass.config_entries.async_reload(entry.entry_id)
