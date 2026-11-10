"""Sensor platform for Slimme Warmtepomp."""
import logging
from datetime import timedelta
from homeassistant.components.sensor import SensorEntity
from homeassistant.util import dt as dt_util
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class SlimmeWarmtepompSensor(SensorEntity):
    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config = config_entry.data
        self._attr_name = "Ideaal Warmtepomp Setpoint"
        self._attr_unique_id = f"{config_entry.entry_id}_setpoint"
        
        self._room_sensor_id = self._config.get("room_temp_sensor")
        self._outside_sensor_id = self._config.get("outside_temp_sensor")
        self._weather_id = self._config.get("weather_entity")
        
        self._compressor_start_time = None
        self._is_running = False
        self._state = 22.0

    async def async_update(self):
        base_setpoint = self._get_float("number.slimme_wp_basis_temperatuur", 22.0)
        helling = self._get_float("number.slimme_wp_stooklijn", 0.4)
        horizon_uren = int(self._get_float("number.slimme_wp_horizon", 4.0))
        zon_factor = self._get_float("number.slimme_wp_zon_factor", 2.0)
        minimum_minuten = self._get_float("number.slimme_wp_minimum_runtime", 15.0)
        waakhond_marge = self._get_float("number.slimme_wp_waakhond_marge", 0.5)
        
        control_mode = self._config.get("control_mode", "retour")
        actuele_retour = self._get_float(self._config.get("return_temp_sensor"), 20.0)
        actuele_aanvoer = self._get_float(self._config.get("flow_temp_sensor"), 25.0)
        freq = self._get_float(self._config.get("compressor_freq_sensor"), 0.0)

        actuele_wp_temp = actuele_aanvoer if control_mode == "aanvoer" else actuele_retour

        currently_running = freq >= 30.0
        if currently_running and not self._is_running:
            self._compressor_start_time = dt_util.utcnow()
            self._is_running = True
        elif not currently_running:
            self._is_running = False
            self._compressor_start_time = None

        actueel_buiten = self._get_float(self._outside_sensor_id, 10.0)
        verwacht_buiten = actueel_buiten
        verwacht_bewolking = 100.0

        if self._weather_id:
            try:
                response = await self.hass.services.async_call(
                    "weather", "get_forecasts", 
                    {"entity_id": self._weather_id, "type": "hourly"},
                    blocking=True, return_response=True
                )
                if self._weather_id in response:
                    forecasts = response[self._weather_id].get("forecast", [])
                    target_time = dt_util.utcnow() + timedelta(hours=horizon_uren)
                    for forecast in forecasts:
                        fc_time = dt_util.parse_datetime(forecast["datetime"])
                        if fc_time and fc_time > target_time:
                            verwacht_buiten = forecast.get("temperature", actueel_buiten)
                            verwacht_bewolking = forecast.get("cloud_coverage", 100.0)
                            break
            except Exception as e:
                _LOGGER.warning("Kon weersvoorspelling niet ophalen: %s", e)

        gecombineerd_buiten = (actueel_buiten * 0.7) + (verwacht_buiten * 0.3)
        weather_part = helling * (20.0 - gecombineerd_buiten)

        sun_deduction = 0.0
        sun_state = self.hass.states.get("sun.sun")
        if sun_state:
            elevation = float(sun_state.attributes.get("elevation", 0.0))
            if elevation > 0:
                cloud_factor = 1.0 - (verwacht_bewolking / 100.0)
                zon_kracht = min(elevation / 45.0, 1.0)
                sun_deduction = zon_factor * cloud_factor * zon_kracht

        target_room = 21.0
        current_room = self._get_float(self._room_sensor_id, target_room)
        room_error = target_room - current_room
        compensation_part = room_error * 2.0

        ideal_setpoint = base_setpoint + weather_part + compensation_part - sun_deduction

        if self._is_running and self._compressor_start_time:
            draaitijd = dt_util.utcnow() - self._compressor_start_time
            if draaitijd.total_seconds() < (minimum_minuten * 60):
                marge = ideal_setpoint - actuele_wp_temp
                if marge < waakhond_marge:
                    ideal_setpoint = actuele_wp_temp + waakhond_marge

        self._state = round(ideal_setpoint, 1)

    @property
    def state(self):
        return self._state

    @property
    def unit_of_measurement(self):
        return "°C"

    def _get_float(self, entity_id, default_value):
        if not entity_id: return default_value
        state = self.hass.states.get(entity_id)
        try:
            return float(state.state) if state and state.state not in ['unknown', 'unavailable'] else default_value
        except ValueError:
            return default_value

async def async_setup_entry(hass, config_entry, async_add_entities):
    async_add_entities([SlimmeWarmtepompSensor(hass, config_entry)])
