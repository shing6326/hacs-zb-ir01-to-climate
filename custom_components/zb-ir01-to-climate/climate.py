from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    HVAC_MODE_OFF, HVAC_MODE_HEAT, HVAC_MODE_COOL, HVAC_MODE_AUTO, HVAC_MODE_DRY, HVAC_MODE_FAN_ONLY,
    SUPPORT_TARGET_TEMPERATURE, SUPPORT_FAN_MODE, SUPPORT_SWING_MODE
)
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.const import TEMP_CELSIUS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change

import asyncio
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
    "mode": {
        "on": "860100000087",
        "off": "860100010086",
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
    },
    "swing": {
        "on": "860105000082",
        "off": "860105010083",
        "vertical": "860107080088",
        "horizontal": "860108080087"
    }
}

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    if discovery_info is None:
        return
    ir01_entity_id = discovery_info.get("ir01_entity_id")
    climate_name = discovery_info.get("climate_name")
    climate_id = discovery_info.get("climate_id")
    async_add_entities([ZBACClimateEntity(hass, ir01_entity_id, climate_name, climate_id)])

class ZBACClimateEntity(ClimateEntity):
    def __init__(self, hass, ir01_entity_id, climate_name, climate_id):
        self.hass = hass
        self._ir01_entity_id = ir01_entity_id
        self._name = climate_name
        self.entity_id = climate_id or None
        self._attr_temperature_unit = TEMP_CELSIUS

        self._target_temperature = 26
        self._fan_mode = "auto"
        self._hvac_mode = HVAC_MODE_OFF
        self._swing_mode = "off"
        self._last_command = ""
        self._last_received_command = ""

        # Subscribe to changes in the sensor
        self._sensor_unsub = async_track_state_change(
            self.hass, "sensor." + self._ir01_entity_id + "_last_received_command", self.async_sensor_state_listener
        )

    async def async_sensor_state_listener(self, entity_id, old_state, new_state):
        if new_state is None:
            return
        self._last_received_command = new_state.state
        if self.parse_sensor_data(new_state.state):
            self.async_write_ha_state()  # Update the state in Home Assistant

    @property
    def name(self):
        return self._name

    @property
    def hvac_mode(self):
        return self._hvac_mode

    @property
    def hvac_modes(self):
        return [HVAC_MODE_OFF, HVAC_MODE_COOL, HVAC_MODE_HEAT, HVAC_MODE_AUTO, HVAC_MODE_DRY, HVAC_MODE_FAN_ONLY]

    @property
    def target_temperature(self):
        return self._target_temperature

    @property
    def target_temperature_step(self):
        return 1.0

    @property
    def fan_mode(self):
        return self._fan_mode

    @property
    def fan_modes(self):
        return ["auto", "low", "medium", "high"]

    @property
    def swing_mode(self):
        return self._swing_mode

    @property
    def swing_modes(self):
        return ["on", "off", "vertical", "horizontal"]

    @property
    def supported_features(self):
        return SUPPORT_TARGET_TEMPERATURE | SUPPORT_FAN_MODE | SUPPORT_SWING_MODE

    def is_hex(self, val):
        try:
            int(val, 16)
            return True
        except ValueError:
            return False

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
            return False
        try:
            if not self.verify_checksum(data):
                raise ValueError(f"Invalid checksum.")
            power = data[2:4]
            mode = data[4:6]
            temp = data[6:8]
            fan = data[8:10]
            # special handle of fan_only signal, the toshiba remote returns 08ff000603f2 when in fan mode
            if power == 'ff' and mode == '00':
                power = '00'
                mode = '03'
            # validate parsed value
            if power != '00' and power != '01':
                raise ValueError("Invalid power value.")
            if not self.is_hex(temp) or not -1 < int(temp, 16) < 16:
                raise ValueError("Invalid temperature value.")
            if not self.is_hex(mode) or not -1 < int(mode, 16) < 5:
                raise ValueError("Invalid hvac mode value.")
            if not self.is_hex(fan) or not -1 < int(fan, 16) < 4:
                raise ValueError("Invalid fan mode value.")
            # Set temperature and fan mode
            self._target_temperature = int(temp, 16) + 16
            self._fan_mode = ["auto", "low", "medium", "high"][int(fan, 16)]
            # Set HVAC mode
            if power == '01':
                self._hvac_mode = HVAC_MODE_OFF
            else:
                self._hvac_mode = {
                    '00': HVAC_MODE_AUTO,
                    '01': HVAC_MODE_COOL,
                    '02': HVAC_MODE_DRY,
                    '03': HVAC_MODE_FAN_ONLY,
                    '04': HVAC_MODE_HEAT
                }.get(mode, HVAC_MODE_OFF)
            return True
        except ValueError as e:
            _LOGGER.warning(f"Error parsing sensor data '{data}': {e}")
            return False

    async def send_command(self, command):
        """ Helper function to send command to the climate device. """
        # Replace with actual method to send the command
        await self.hass.services.async_call(
            'text', 'set_value', {
                "entity_id": "text." + self._ir01_entity_id + "_send_command",
                "value": '"'+command+'"'
            }
        )
        self._last_command = command  # You might want to store more specific state
        self.async_write_ha_state()  # Inform Home Assistant of state change
    
    async def async_set_temperature(self, **kwargs):
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is not None:
            hex_code = code['temperature'].get(str(int(temperature)), None)
            if hex_code:
                self._target_temperature = temperature
                await self.send_command(hex_code)
            else:
                _LOGGER.warning(f"Error locating code with temperature '{temperature}'.")
    
    async def async_set_hvac_mode(self, hvac_mode):
        hex_code = code['mode'].get(hvac_mode, None)
        if hex_code:
            if self._hvac_mode == HVAC_MODE_OFF and hvac_mode != HVAC_MODE_OFF:
                await self.send_command(code['mode']['on'])
                await asyncio.sleep(0.5)
            self._hvac_mode = hvac_mode
            await self.send_command(hex_code)
        else:
            _LOGGER.warning(f"Error locating code with hvac mode '{hvac_mode}'.")
    
    async def async_turn_on(self):
        await async_set_hvac_mode(HVAC_MODE_AUTO)
    
    async def async_turn_off(self):
        await async_set_hvac_mode(HVAC_MODE_OFF)
    
    async def async_set_fan_mode(self, fan_mode):
        hex_code = code['fan_speed'].get(fan_mode, None)
        if hex_code:
            self._fan_mode = fan_mode
            await self.send_command(hex_code)
        else:
            _LOGGER.warning(f"Error locating code with fan mode '{fan_mode}'.")

    async def async_set_swing_mode(self, swing_mode):
        hex_code = code['swing'].get(swing_mode, None)
        if hex_code:
            self._swing_mode = swing_mode
            await self.send_command(hex_code)
        else:
            _LOGGER.warning(f"Error locating code with swing mode '{swing_mode}'.")

    async def async_will_remove_from_hass(self):
        # Unsubscribe from sensor's state changes when entity is removed
        if self._sensor_unsub:
            self._sensor_unsub()
