"""ZB-IR01 to climate — YAML setup and discovery for the climate platform."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, discovery
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

DOMAIN = "zb-ir01-to-climate"

DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required("ir01_entity_id"): cv.string,
        vol.Optional("climate_id"): cv.string,
        vol.Required("climate_name"): cv.string,
        # Optional brand-specific status-report quirk flags (see climate.py).
        # No default= here — mutable/callable defaults are unreliable across
        # voluptuous/HA versions; async_setup uses conf.get(...) or [].
        vol.Optional("status_quirks"): vol.All(cv.ensure_list, [cv.string]),
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.All(cv.ensure_list, [DEVICE_SCHEMA]),
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up zb-ir01-to-climate from configuration.yaml and load climate platforms."""
    configurations = config.get(DOMAIN) or []

    for conf in configurations:
        discovery_info = {
            "ir01_entity_id": conf["ir01_entity_id"],
            "climate_id": conf.get("climate_id"),
            "climate_name": conf["climate_name"],
            "status_quirks": list(conf.get("status_quirks") or []),
        }
        hass.async_create_task(
            discovery.async_load_platform(
                hass, "climate", DOMAIN, discovery_info, config
            )
        )
    return True
