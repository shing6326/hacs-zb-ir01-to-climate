# The HA climate object created by easyiot ZB-IR01 with status feedback

This is a minimum implementation of an integration providing a sensor value to sync to a climate object.

### Installation

Copy this folder to `<config_dir>/custom_components/zb-ir01-to-climate/`.


Add the following to your `configuration.yaml` file:

```yaml
# Example configuration.yaml entry
zb-ir01-to-climate:
  sensor_entity_id: sensor.0xf4b3b1fffe132df2_last_received_command
  climate_id: climate.my_ac
  climate_name: My AC
```
