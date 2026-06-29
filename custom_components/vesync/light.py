"""Support for VeSync bulbs and wall dimmers."""

import logging

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pyvesync.const import ProductTypes

from .common import VeSyncDevice, has_feature
from .const import DEV_TYPE_TO_HA, DOMAIN, VS_DISCOVERY, VS_LIGHTS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up lights."""

    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    @callback
    def discover(devices):
        """Add new devices to platform."""
        _setup_entities(devices, async_add_entities, coordinator)

    config_entry.async_on_unload(
        async_dispatcher_connect(hass, VS_DISCOVERY.format(VS_LIGHTS), discover)
    )

    _setup_entities(
        hass.data[DOMAIN][config_entry.entry_id][VS_LIGHTS],
        async_add_entities,
        coordinator,
    )


@callback
def _setup_entities(devices, async_add_entities, coordinator):
    """Check if device is online and add entity."""
    entities = []
    for dev in devices:
        if DEV_TYPE_TO_HA.get(dev.device_type) in ("walldimmer", "bulb-dimmable"):
            entities.append(VeSyncDimmableLightHA(dev, coordinator))
        if DEV_TYPE_TO_HA.get(dev.device_type) in ("bulb-tunable-white",):
            entities.append(VeSyncTunableWhiteLightHA(dev, coordinator))
        if getattr(dev, "supports_nightlight", False):
            entities.append(VeSyncNightLightHA(dev, coordinator))

    async_add_entities(entities, update_before_add=True)


def _vesync_brightness_to_ha(vesync_brightness):
    try:
        # check for validity of brightness value received
        brightness_value = int(vesync_brightness)
    except (ValueError, TypeError):
        # deal if any unexpected/non numeric value
        _LOGGER.debug(
            "VeSync - received unexpected 'brightness' value from pyvesync api: %s",
            vesync_brightness,
        )
        return None
    # convert percent brightness to ha expected range
    return round((max(1, brightness_value) / 100) * 255)


def _ha_brightness_to_vesync(ha_brightness):
    # get brightness from HA data
    brightness = int(ha_brightness)
    # ensure value between 1-255
    brightness = max(1, min(brightness, 255))
    # convert to percent that vesync api expects
    brightness = round((brightness / 255) * 100)
    return max(1, min(brightness, 100))


class VeSyncBaseLight(VeSyncDevice, LightEntity):
    """Base class for VeSync Light Devices Representations."""

    def __init__(self, light, coordinator):
        """Initialize the VeSync light device."""
        super().__init__(light, coordinator)

    @property
    def brightness(self):
        """Get light brightness."""
        # get value from pyvesync library api
        return _vesync_brightness_to_ha(self.device.state.brightness)

    async def async_turn_on(self, **kwargs):
        """Turn the device on."""
        attribute_adjustment_only = False
        # set white temperature
        if (
            self.color_mode in (ColorMode.COLOR_TEMP,)
            and ATTR_COLOR_TEMP_KELVIN in kwargs
        ):
            # get white temperature from HA data
            color_temp = int(kwargs[ATTR_COLOR_TEMP_KELVIN])
            # ensure value between min-max supported Mireds
            color_temp = max(self.min_mireds, min(color_temp, self.max_mireds))
            # convert Mireds to Percent value that api expects
            color_temp = round(
                ((color_temp - self.min_mireds) / (self.max_mireds - self.min_mireds))
                * 100
            )
            # flip cold/warm to what pyvesync api expects
            color_temp = 100 - color_temp
            # ensure value between 0-100
            color_temp = max(0, min(color_temp, 100))
            # call pyvesync library api method to set color_temp
            await self.device.set_color_temp(color_temp)
            # flag attribute_adjustment_only, so it doesn't turn_on the device redundantly
            attribute_adjustment_only = True
        # set brightness level
        if (
            self.color_mode in (ColorMode.BRIGHTNESS, ColorMode.COLOR_TEMP)
            and ATTR_BRIGHTNESS in kwargs
        ):
            # get brightness from HA data
            brightness = _ha_brightness_to_vesync(kwargs[ATTR_BRIGHTNESS])
            await self.device.set_brightness(brightness)
            # flag attribute_adjustment_only, so it doesn't turn_on the device redundantly
            attribute_adjustment_only = True
        # check flag if should skip sending the turn_on command
        if attribute_adjustment_only:
            return
        # send turn_on command to pyvesync api
        await self.device.turn_on()


class VeSyncDimmableLightHA(VeSyncBaseLight, LightEntity):
    """Representation of a VeSync dimmable light device."""

    def __init__(self, device, coordinator) -> None:
        """Initialize the VeSync dimmable light device."""
        super().__init__(device, coordinator)

    @property
    def color_mode(self):
        """Set color mode for this entity."""
        return ColorMode.BRIGHTNESS

    @property
    def supported_color_modes(self):
        """Flag supported color_modes (in an array format)."""
        return [ColorMode.BRIGHTNESS]


class VeSyncTunableWhiteLightHA(VeSyncBaseLight, LightEntity):
    """Representation of a VeSync Tunable White Light device."""

    def __init__(self, device, coordinator) -> None:
        """Initialize the VeSync Tunable White Light device."""
        super().__init__(device, coordinator)

    @property
    def color_temp(self):
        """Get device white temperature."""
        # get value from pyvesync library api
        result = self.device.state.color_temp
        try:
            # check for validity of color_temp value received
            color_temp_value = int(result)
        except (ValueError, TypeError):
            # deal if any unexpected/non numeric value
            _LOGGER.debug(
                "VeSync - received unexpected 'color_temp' value from pyvesync api: %s",
                result,
            )
            return 0
        # flip cold/warm
        color_temp_value = 100 - color_temp_value
        # ensure value between 0-100
        color_temp_value = max(0, min(color_temp_value, 100))
        # convert percent value to Mireds
        color_temp_value = round(
            self.min_mireds
            + ((self.max_mireds - self.min_mireds) / 100 * color_temp_value)
        )
        # ensure value between minimum and maximum Mireds
        return max(self.min_mireds, min(color_temp_value, self.max_mireds))

    @property
    def min_mireds(self):
        """Set device coldest white temperature."""
        return 154  # 154 Mireds ( 1,000,000 divided by 6500 Kelvin = 154 Mireds)

    @property
    def max_mireds(self):
        """Set device warmest white temperature."""
        return 370  # 370 Mireds  ( 1,000,000 divided by 2700 Kelvin = 370 Mireds)

    @property
    def color_mode(self):
        """Set color mode for this entity."""
        return ColorMode.COLOR_TEMP

    @property
    def supported_color_modes(self):
        """Flag supported color_modes (in an array format)."""
        return [ColorMode.COLOR_TEMP]


class VeSyncNightLightHA(VeSyncDimmableLightHA):
    """Representation of the night light on a VeSync device."""

    def __init__(self, device, coordinator) -> None:
        """Initialize the VeSync device."""
        super().__init__(device, coordinator)
        self.device = device
        self.has_brightness = has_feature(
            self.device, "details", "nightlight_brightness"
        )

    @property
    def unique_id(self):
        """Return the ID of this device."""
        return f"{super().unique_id}-night-light"

    @property
    def name(self):
        """Return the name of the device."""
        return f"{super().name} night light"

    @property
    def brightness(self):
        """Get night light brightness."""
        if self.has_brightness:
            return _vesync_brightness_to_ha(self.device.state.nightlight_brightness)
        status = self.device.state.nightlight_status
        return {"on": 255, "dim": 125, "off": 0}.get(status, 0)

    @property
    def is_on(self):
        """Return True if night light is on."""
        if self.has_brightness:
            brightness = self.device.state.nightlight_brightness
            return brightness is not None and brightness > 0
        status = self.device.state.nightlight_status
        return status in ["on", "dim"]

    @property
    def entity_category(self):
        """Return the configuration entity category."""
        return EntityCategory.CONFIG

    async def async_turn_on(self, **kwargs):
        """Turn the night light on."""
        if self.device.product_type in (ProductTypes.PURIFIER, ProductTypes.FAN):
            if ATTR_BRIGHTNESS in kwargs and kwargs[ATTR_BRIGHTNESS] < 255:
                await self.device.set_nightlight_mode("dim")
            else:
                await self.device.set_nightlight_mode("on")
        elif ATTR_BRIGHTNESS in kwargs:
            await self.device.set_nightlight_brightness(
                _ha_brightness_to_vesync(kwargs[ATTR_BRIGHTNESS])
            )
        else:
            await self.device.set_nightlight_brightness(100)

    async def async_turn_off(self, **kwargs):
        """Turn the night light off."""
        if self.device.product_type in (ProductTypes.PURIFIER, ProductTypes.FAN):
            await self.device.set_nightlight_mode("off")
        else:
            await self.device.set_nightlight_brightness(0)
