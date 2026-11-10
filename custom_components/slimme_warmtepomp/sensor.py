"""Sensor platform for Slimme Warmtepomp."""
import logging
from datetime import timedelta
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import UnitOfPower, UnitOfTemperature
from homeassistant.util import dt as dt_util
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class SlimmeWarmtepompBaseSensor(SensorEntity):
    """Gedeelde basisklasse voor de warmtepomp sensoren."""
    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config = config_entry.data
        self._config_entry = config_entry
        self._entry_id = config_entry.entry_id

    @property
    def device_info(self):
        """Groepeert alle sensoren onder het centrale warmtepomp apparaat."""
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": "Slimme Warmtepomp",
            "manufacturer": "Custom HEMS",
            "model": "Zelflerende Regeling",
            "sw_version": "1.0.0",
        }

class SlimmeWarmtepompSetpointSensor(SlimmeWarmtepompBaseSensor):
    """Hoofdsensor: Berekent het ideale water-setpoint."""
    def __init__(self, hass, config_entry):
        super().__init__(hass, config_entry)
        self._attr_name = "Ideaal Warmtepomp Setpoint"
        self._attr_unique_id = f"{self._entry_id}_setpoint"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        
        self._room_sensor_id = self._config.get("room_temp_sensor")
        self._outside_sensor_id = self._config.get("outside_temp_sensor")
        self._weather_id = self._config.get("weather_entity")
        
        self._compressor_start_time = None
        self._is_running = False
        self._state = 22.0
        
        self._learned_cooling_coeff = 0.025
        self._last_room_temp = None
        self._last_update_time = None
        
        self.calculated_thermisch_kw = 0.0
        self.calculated_cop = 0.0
        self.calculated_elektrisch_w = 0.0
        self.calculated_flow_lh = 0.0

    def _get_flow_in_liter_per_hour(self, entity_id):
        if not entity_id:
            return 0.0
        state_obj = self.hass.states.get(entity_id)
        if not state_obj or state_obj.state in ['unknown', 'unavailable']:
            return 0.0
        try:
            val = float(state_obj.state)
        except ValueError:
            return 0.0
        unit = state_obj.attributes.get("unit_of_measurement", "").strip().lower()
        if unit in ["l/s", "liter/seconde", "l/sec"]:
            return val * 3600.0
        elif unit in ["l/min", "liter/minuut", "l/m"]:
            return val * 60.0
        elif unit in ["l/h", "liter/uur", "l/hour"]:
            return val
        elif unit in ["m3/h", "m³/h", "m3/hour"]:
            return val * 1000.0
        elif unit in ["m3/s", "m³/s"]:
            return val * 3600.0 * 1000.0
        return val

    def _get_power_in_watts(self, entity_id):
        if not entity_id:
            return 0.0
        state_obj = self.hass.states.get(entity_id)
        if not state_obj or state_obj.state in ['unknown', 'unavailable']:
            return 0.0
        try:
            val = float(state_obj.state)
        except ValueError:
            return 0.0
        unit = state_obj.attributes.get("unit_of_measurement", "").strip().lower()
        if unit in ["kw", "kilowatt"]:
            return val * 1000.0
        return val

    async def async_update(self):
        now = dt_util.utcnow()
        
        room_state = self.hass.states.get(self._room_sensor_id)
        current_room = float(room_state.state) if room_state and room_state.state not in ['unknown', 'unavailable'] else 20.0

        outside_state = self.hass.states.get(self._outside_sensor_id)
        actueel_buiten = float(outside_state.state) if outside_state and outside_state.state not in ['unknown', 'unavailable'] else 5.0

        freq = self._get_float(self._config.get("compressor_freq_sensor"), 0.0)
        is_heating = freq >= 30.0
        
        if self._last_room_temp is not None and self._last_update_time is not None and not is_heating:
            time_diff_hours = (now - self._last_update_time).total_seconds() / 3600.0
            if 0.1 < time_diff_hours < 2.0:
                temp_diff = self._last_room_temp - current_room
                if temp_diff > 0:
                    delta_t_indoordoor = current_room - actueel_buiten
                    if delta_t_indoordoor > 0:
                        measured_coeff = temp_diff / (time_diff_hours * delta_t_indoordoor)
                        if 0.005 < measured_coeff < 0.1:
                            self._learned_cooling_coeff = (0.98 * self._learned_cooling_coeff) + (0.02 * measured_coeff)

        self._last_room_temp = current_room
        self._last_update_time = now

        base_setpoint = self._get_float("number.slimme_wp_basis_temperatuur", 22.0)
        helling = self._get_float("number.slimme_wp_stooklijn", 0.4)
        horizon_uren = int(self._get_float("number.slimme_wp_horizon", 4.0))
        zon_factor = self._get_float("number.slimme_wp_zon_factor", 2.0)
        minimum_minuten = self._get_float("number.slimme_wp_minimum_runtime", 15.0)
        waakhond_marge = self._get_float("number.slimme_wp_waakhond_marge", 0.5)
        
        setpoint_dag = self._get_float("number.slimme_wp_setpoint_dag", 21.0)
        setpoint_nacht = self._get_float("number.slimme_wp_setpoint_nacht", 20.4)
        dag_start = int(self._get_float("number.slimme_wp_dag_start", 9.0))
        dag_eind = int(self._get_float("number.slimme_wp_dag_eind", 21.0))
        nacht_start = int(self._get_float("number.slimme_wp_nacht_start", 23.0))
        nacht_eind = int(self._get_float("number.slimme_wp_nacht_eind", 7.0))
        max_prijs = self._get_float("number.slimme_wp_max_stroomprijs", 0.35)
        max_flow_grens = self._get_float("number.slimme_wp_max_flow_temp", 40.0)
        pv_boost_val = self._get_float("number.slimme_wp_pv_boost", 1.0)
        bivalent_grens = self._get_float("number.slimme_wp_bivalent_temp", -7.0)

        control_mode = self._config.get("control_mode", "retour")
        actuele_retour = self._get_float(self._config.get("return_temp_sensor"), 20.0)
        actuele_aanvoer = self._get_float(self._config.get("flow_temp_sensor"), 25.0)
        actuele_wp_temp = actuele_aanvoer if control_mode == "aanvoer" else actuele_retour

        currently_running = is_heating
        if currently_running and not self._is_running:
            self._compressor_start_time = now
            self._is_running = True
        elif not currently_running:
            self._is_running = False
            self._compressor_start_time = None

        verwacht_buiten = actueel_buiten
        verwacht_bewolking = 100.0
        predicted_future_cooling = 0.0

        if self._weather_id:
            try:
                response = await self.hass.services.async_call(
                    "weather", "get_forecasts", 
                    {"entity_id": self._weather_id, "type": "hourly"},
                    blocking=True, return_response=True
                )
                if self._weather_id in response:
                    forecasts = response[self._weather_id].get("forecast", [])
                    target_time = now + timedelta(hours=horizon_uren)
                    for forecast in forecasts:
                        fc_time = dt_util.parse_datetime(forecast["datetime"])
                        if fc_time and fc_time > target_time:
                            verwacht_buiten = forecast.get("temperature", actueel_buiten)
                            verwacht_bewolking = forecast.get("cloud_coverage", 100.0)
                            break
            except Exception as e:
                _LOGGER.warning("Kon weersvoorspelling niet ophalen: %s", e)

        predicted_delta_t = current_room - verwacht_buiten
        if predicted_delta_t > 0:
            predicted_future_cooling = self._learned_cooling_coeff * predicted_delta_t * horizon_uren

        gecombineerd_buiten = (actueel_buiten * 0.7) + (verwacht_buiten * 0.3)
        weather_part = helling * (20.0 - gecombineerd_buiten)

        if verwacht_buiten < 0:
            weather_part += abs(verwacht_buiten) * 0.15

        sun_deduction = 0.0
        sun_state = self.hass.states.get("sun.sun")
        if sun_state:
            elevation = float(sun_state.attributes.get("elevation", 0.0))
            if elevation > 0:
                cloud_factor = 1.0 - (verwacht_bewolking / 100.0)
                zon_kracht = min(elevation / 45.0, 1.0)
                sun_deduction = zon_factor * cloud_factor * zon_kracht

        huidig_uur = now.hour
        in_nacht = False
        if nacht_start > nacht_eind:
            in_nacht = huidig_uur >= nacht_start or huidig_uur < nacht_eind
        else:
            in_nacht = nacht_start <= huidig_uur < nacht_eind

        actief_ruimte_setpoint = setpoint_nacht if in_nacht else setpoint_dag
        room_error = actief_ruimte_setpoint - current_room
        compensation_part = room_error * 2.0

        if predicted_future_cooling > 0.3:
            compensation_part += predicted_future_cooling * 1.5

        ideal_setpoint = base_setpoint + weather_part + compensation_part - sun_deduction

        if dag_start <= huidig_uur < dag_eind:
            ideal_setpoint += 1.0
        if in_nacht:
            ideal_setpoint -= 1.0

        if dag_start <= huidig_uur < dag_eind:
            if current_room > actief_ruimte_setpoint:
                min_vloer_behoud = base_setpoint
                if ideal_setpoint < min_vloer_behoud:
                    ideal_setpoint = min_vloer_behoud

        if self._is_running and self._compressor_start_time:
            draaitijd = now - self._compressor_start_time
            if draaitijd.total_seconds() < (minimum_minuten * 60):
                marge = ideal_setpoint - actuele_wp_temp
                if marge < waakhond_marge:
                    ideal_setpoint = actuele_wp_temp + waakhond_marge

        price_sensor_id = self._config.get("electricity_price_sensor")
        huidige_prijs = self._get_float(price_sensor_id, 0.20) if price_sensor_id else 0.20
        toekomstige_prijs = huidige_prijs

        if price_sensor_id:
            price_state = self.hass.states.get(price_sensor_id)
            if price_state:
                attrs = price_state.attributes
                raw_prices = []
                for key in ["raw_today", "rawToday", "forecast"]:
                    if key in attrs and isinstance(attrs[key], list):
                        raw_prices.extend(attrs[key])
                for key in ["raw_tomorrow", "rawTomorrow"]:
                    if key in attrs and isinstance(attrs[key], list):
                        raw_prices.extend(attrs[key])
                        
                if raw_prices:
                    target_time = now + timedelta(hours=2)
                    for entry in raw_prices:
                        start_str = entry.get("start") or entry.get("time")
                        val = entry.get("value") or entry.get("price")
                        if start_str and val is not None:
                            parsed_time = dt_util.parse_datetime(str(start_str))
                            if parsed_time and parsed_time >= target_time:
                                toekomstige_prijs = float(val)
                                break

        prijs_verschil = toekomstige_prijs - huidige_prijs
        if prijs_verschil < -0.05:
            ideal_setpoint -= 0.5
        elif prijs_verschil > 0.05:
            ideal_setpoint += 0.8

        if price_sensor_id and huidige_prijs > max_prijs:
            ideal_setpoint = actuele_wp_temp - 2.0

        if actueel_buiten < bivalent_grens:
            _LOGGER.warning(f"Bivalente grens bereikt: {actueel_buiten}°C")

        pv_sensor_id = self._config.get("pv_power_sensor")
        pv_power = self._get_float(pv_sensor_id, 0.0)
        if pv_power > 500:
            ideal_setpoint += pv_boost_val

        if ideal_setpoint > max_flow_grens:
            ideal_setpoint = max_flow_grens

        flow_id_1 = self._config.get("flow_rate_sensor_1")
        flow_id_2 = self._config.get("flow_rate_sensor_2")
        power_sensor_id = self._config.get("power_sensor")
        voltage_sensor_id = self._config.get("voltage_sensor")
        current_sensor_id = self._config.get("current_sensor")
        
        self.calculated_flow_lh = self._get_flow_in_liter_per_hour(flow_id_1) + self._get_flow_in_liter_per_hour(flow_id_2)
        
        power_w = self._get_power_in_watts(power_sensor_id)
        if power_w == 0.0 and voltage_sensor_id and current_sensor_id:
            voltage = self._get_float(voltage_sensor_id, 230.0)
            current = self._get_float(current_sensor_id, 0.0)
            power_w = voltage * current
        
        self.calculated_elektrisch_w = round(power_w, 1)
        self.calculated_thermisch_kw = 0.0
        self.calculated_cop = 0.0
        
        if self.calculated_flow_lh > 0:
            delta_t = actuele_aanvoer - actuele_retour
            if delta_t > 0:
                self.calculated_thermisch_kw = round((self.calculated_flow_lh * 4.186 * delta_t) / 3600.0, 2)
                if self.calculated_elektrisch_w > 100:
                    p_elektrisch_kw = self.calculated_elektrisch_w / 1000.0
                    cop = round(self.calculated_thermisch_kw / p_elektrisch_kw, 2)
                    if 1.0 <= cop <= 8.0:
                        self.calculated_cop = cop

        self._state = round(ideal_setpoint, 1)

    @property
    def native_value(self):
        return self._state

    def _get_float(self, entity_id, default_value):
        if not entity_id: return default_value
        state = self.hass.states.get(entity_id)
        try:
            return float(state.state) if state and state.state not in ['unknown', 'unavailable'] else default_value
        except ValueError:
            return default_value


class SlimmeWarmtepompThermischVermogenSensor(SlimmeWarmtepompBaseSensor):
    def __init__(self, hass, config_entry, setpoint_sensor):
        super().__init__(hass, config_entry)
        self._setpoint_sensor = setpoint_sensor
        self._attr_name = "Warmtepomp Thermisch Vermogen"
        self._attr_unique_id = f"{self._entry_id}_thermisch_vermogen"
        self._attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return self._setpoint_sensor.calculated_thermisch_kw


class SlimmeWarmtepompCopSensor(SlimmeWarmtepompBaseSensor):
    def __init__(self, hass, config_entry, setpoint_sensor):
        super().__init__(hass, config_entry)
        self._setpoint_sensor = setpoint_sensor
        self._attr_name = "Warmtepomp COP"
        self._attr_unique_id = f"{self._entry_id}_cop"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return self._setpoint_sensor.calculated_cop


class SlimmeWarmtepompElektrischVermogenSensor(SlimmeWarmtepompBaseSensor):
    def __init__(self, hass, config_entry, setpoint_sensor):
        super().__init__(hass, config_entry)
        self._setpoint_sensor = setpoint_sensor
        self._attr_name = "Warmtepomp Elektrisch Vermogen"
        self._attr_unique_id = f"{self._entry_id}_elektrisch_vermogen"
        self._attr_native_unit_of_measurement = UnitOfPower.WATT
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return self._setpoint_sensor.calculated_elektrisch_w


async def async_setup_entry(hass, config_entry, async_add_entities):
    setpoint_sensor = SlimmeWarmtepompSetpointSensor(hass, config_entry)
    thermisch_sensor = SlimmeWarmtepompThermischVermogenSensor(hass, config_entry, setpoint_sensor)
    cop_sensor = SlimmeWarmtepompCopSensor(hass, config_entry, setpoint_sensor)
    elektrisch_sensor = SlimmeWarmtepompElektrischVermogenSensor(hass, config_entry, setpoint_sensor)

    async_add_entities([
        setpoint_sensor,
        thermisch_sensor,
        cop_sensor,
        elektrisch_sensor
    ])
