from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    HVAC_MODE_OFF, HVAC_MODE_HEAT, HVAC_MODE_COOL, HVAC_MODE_AUTO, HVAC_MODE_DRY, HVAC_MODE_FAN_ONLY,
    SUPPORT_TARGET_TEMPERATURE, SUPPORT_FAN_MODE
)
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.const import TEMP_CELSIUS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change

import logging
import json

_LOGGER = logging.getLogger(__name__)

code = {
    "temperature": {
        "16": "860102000085",
        "17": "860102010084",
        "18": "860102020087",
        "19": "860102030086",
        "20": "860102040081",
        "21": "860102050080",
        "22": "860102060083",
        "23": "860102070082",
        "24": "86010208008d",
        "25": "86010209008c",
        "26": "8601020a008f",
        "27": "8601020b008e",
        "28": "8601020c0089",
        "29": "8601020d0088",
        "30": "8601020e008b",
        "31": "8601020f0000",
        "32": "860102100095"
    },
    "poweron": "860100000087",
    "poweroff": "860100010086",
    "mode": {
        "auto": "860101000086",
        "cool": "860101010087",
        "dry": "860101020084",
        "fan_only": "860101030085",
        "heat": "860101040082"
    },
    "fan_speed": {
        "auto": "860104000083",
        "low": "860104010082",
        "medium": "860104020081",
        "high": "860104030080"
    }
}

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    if discovery_info is None:
        return
    sensor_entity_id = discovery_info.get("sensor_entity_id")
    climate_name = discovery_info.get("climate_name")
    climate_id = discovery_info.get("climate_id")
    async_add_entities([ZBACClimateEntity(hass, sensor_entity_id, climate_name, climate_id)])

class ZBACClimateEntity(ClimateEntity):
    def __init__(self, hass, sensor_entity_id, climate_name, climate_id):
        self.hass = hass
        self._sensor_entity_id = sensor_entity_id
        self._name = climate_name
        self.entity_id = climate_id or None
        self._attr_temperature_unit = TEMP_CELSIUS
        self._state = {}

        # Subscribe to changes in the sensor
        self._sensor_unsub = async_track_state_change(
            self.hass, self._sensor_entity_id, self.async_sensor_state_listener
        )

    async def async_sensor_state_listener(self, entity_id, old_state, new_state):
        if new_state is None:
            return
        parsed_state = self.parse_sensor_data(new_state.state)
        if parsed_state:
            self._state = parsed_state
            self.async_write_ha_state()  # Update the state in Home Assistant

    @property
    def name(self):
        return self._name

    @property
    def hvac_mode(self):
        if self._state.get('switch', '') == '01':
            return HVAC_MODE_OFF
        elif self._state.get('mode', '') == '00':
            return HVAC_MODE_AUTO
        elif self._state.get('mode', '') == '01':
            return HVAC_MODE_COOL
        elif self._state.get('mode', '') == '02':
            return HVAC_MODE_DRY
        elif self._state.get('mode', '') == '03':
            return HVAC_MODE_FAN_ONLY
        elif self._state.get('mode', '') == '04':
            return HVAC_MODE_HEAT

    @property
    def hvac_modes(self):
        return [HVAC_MODE_OFF, HVAC_MODE_COOL, HVAC_MODE_HEAT, HVAC_MODE_AUTO, HVAC_MODE_DRY, HVAC_MODE_FAN_ONLY]

    @property
    def current_temperature(self):
        return self._state.get('temperature', 0)

    @property
    def target_temperature(self):
        return self._state.get('temperature', 0)

    @property
    def target_temperature_step(self):
        return 1.0

    @property
    def fan_mode(self):
        return self._state.get('air_volume', 'auto')

    @property
    def fan_modes(self):
        return ["auto", "low", "medium", "high"]

    @property
    def supported_features(self):
        return SUPPORT_TARGET_TEMPERATURE | SUPPORT_FAN_MODE


    def verify_checksum(self, data):
        try:
            # Convert the string into a list of integers, excluding the last two characters (checksum)
            input_data = [int(data[i:i + 2], 16) for i in range(0, len(data) - 2, 2)]
            # Extract the checksum from the last two characters of the data string
            received_checksum = int(data[-2:], 16)
            # Calculate the XOR of all bytes
            calculated_checksum = 0
            for byte in input_data:
                calculated_checksum ^= byte
            # Compare the received checksum with the calculated checksum
            return received_checksum == calculated_checksum
        except ValueError:
            # Handle invalid data format
            return False

    def parse_sensor_data(self, data):
        if data[0:2] != "08":
            return {}
        if not self.verify_checksum(data):
            _LOGGER.error(f"Invalid checksum of data '{data}'")
            return {}
        try:
            switch = data[2:4]
            mode = data[4:6]
            # special handle of fan_only signal, the toshiba remote returns 08ff000603f2 when in fan mode
            if switch == "ff" and mode == "00":
                switch = "00"
                mode = "03"
            # Check if the temperature data slice is correct
            temp_hex = data[6:8]
            temperature = int(temp_hex, 16) + 16
            air_volume = ["auto", "low", "medium", "high"][int(data[8:10], 16)]
            if switch != "00" and switch != "01" or int(temperature) < 16 or int(temperature) > 32:
                raise ValueError("Invalid on/off or temperature value")
            return {"switch": switch, "mode": mode, "temperature": temperature, "air_volume": air_volume}
        except ValueError as e:
            _LOGGER.error(f"Error parsing sensor data '{data}': {e}")
            return {}

    async def send_command(self, command):
        """ Helper function to send command to the climate device. """
        # Replace with actual method to send the command
        await self.hass.services.async_call(
            'text', 'set_value', {
                "entity_id": "text.0xf4b3b1fffe132df2_send_command",
                "value": '"'+command+'"'
            }
        )
        self._state['last_command'] = command  # You might want to store more specific state
        self.async_write_ha_state()  # Inform Home Assistant of state change
    
    async def async_set_temperature(self, **kwargs):
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is not None:
            hex_code = code['temperature'].get(str(int(temperature)), None)
            if hex_code:
                await self.send_command(hex_code)
    
    async def async_set_hvac_mode(self, hvac_mode):
        hex_code = code['mode'].get(hvac_mode, None)
        if hex_code:
            await self.send_command(hex_code)
    
    async def async_turn_on(self):
        await self.send_command(code['poweron'])
    
    async def async_turn_off(self):
        await self.send_command(code['poweroff'])
    
    async def async_set_fan_mode(self, fan_mode):
        hex_code = code['fan_speed'].get(fan_mode, None)
        if hex_code:
            await self.send_command(hex_code)
    
    async def async_will_remove_from_hass(self):
        # Unsubscribe from sensor's state changes when entity is removed
        if self._sensor_unsub:
            self._sensor_unsub()
