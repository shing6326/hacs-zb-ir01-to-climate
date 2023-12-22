from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, discovery
import voluptuous as vol

DOMAIN = "zb-ir01-to-climate"

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required("sensor_entity_id"): cv.entity_id,
    }),
}, extra=vol.ALLOW_EXTRA)

async def async_setup(hass: HomeAssistant, config: dict):
    sensor_entity_id = config[DOMAIN].get("sensor_entity_id")
    hass.async_create_task(
        discovery.async_load_platform(hass, "climate", DOMAIN, {"sensor_entity_id": sensor_entity_id}, config)
    )
    return True
