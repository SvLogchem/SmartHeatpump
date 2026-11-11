"""Sensor platform for Slimme Warmtepomp."""
import logging
from datetime import timedelta
from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.const import UnitOfPower, UnitOfTemperature, EntityCategory
from homeassistant.util import dt as dt_util
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class SlimmeWarmtepompBaseSensor(SensorEntity):
    def __init__(self, hass, config_entry):
        self.hass = hass
        self._config = config_entry.data
        self._config_entry = config_entry
        self._entry_id = config_entry.entry_id

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": "Slimme Warmtepomp",
            "manufacturer": "Custom HEMS",
            "model": "Zelflerende Regeling",
            "sw_version": "1.0.0",
        }

class SlimmeWarmtepompSetpointSensor(SlimmeWarmtepompBaseSensor, RestoreEntity):
    def __init__(self, hass, config_entry):
        super().__init__(hass, config_entry)
        self._attr_name = "Warmtepomp Setpoint"
        self.entity_id = "sensor.slimme_wp_setpoint"
        self._attr_unique_id = f"{self._entry_id}_setpoint"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        
        self._room_sensor_id = self._config.get("room_temp_sensor")
        self._outside_sensor_id = self._config.get("outside_temp_sensor")
        self._weather_id = self._config.get("weather_entity")
        self._target_setpoint_entity = self._config.get("target_setpoint_entity")
        
        self._compressor_start_time = None
        self._is_running = False
        self._state = 22.0
        
        self._learned_cooling_coeff = 0.025
        self._learned_min_freq = 30.0
        self._last_room_temp = None
        self._last_update_time = None
        self._last_smoothed_setpoint = None
        self._last_auto_program = None
        
        self.debug_verwacht_buiten = 0.0
        self.debug_verwacht_bewolking = 100.0
        self.debug_zon_reductie = 0.0
        self.debug_voorspelde_afkoeling = 0.0
        self.debug_actief_programma = "Dag"
        self.is_defrosting_active = False
        self.is_summer_mode = False
        self.is_dure_stroom = False

        self.calculated_thermisch_kw = 0.0
        self.calculated_cop = 0.0
        self.calculated_elektrisch_w = 0.0

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state:
            if 'geleerde_min_frequentie_hz' in last_state.attributes:
                try: self._learned_min_freq = float(last_state.attributes['geleerde_min_frequentie_hz'])
                except ValueError: pass
            if 'geleerde_afkoel_coefficient' in last_state.attributes:
                try: self._learned_cooling_coeff = float(last_state.attributes['geleerde_afkoel_coefficient'])
                except ValueError: pass

    def _get_flow_in_liter_per_hour(self, entity_id):
        if not entity_id: return 0.0
        state = self.hass.states.get(entity_id)
        if not state or state.state in ['unknown', 'unavailable']: return 0.0
        try: val = float(state.state)
        except ValueError: return 0.0
        unit = state.attributes.get("unit_of_measurement", "").strip().lower()
        if unit in ["l/s", "liter/seconde", "l/sec"]: return val * 3600.0
        elif unit in ["l/min", "liter/minuut", "l/m"]: return val * 60.0
        elif unit in ["l/h", "liter/uur", "l/hour"]: return val
        elif unit in ["m3/h", "m³/h", "m3/hour"]: return val * 1000.0
        return val

    def _get_power_in_watts(self, entity_id):
        if not entity_id: return 0.0
        state = self.hass.states.get(entity_id)
        if not state or state.state in ['unknown', 'unavailable']: return 0.0
        try: val = float(state.state)
        except ValueError: return 0.0
        unit = state.attributes.get("unit_of_measurement", "").strip().lower()
        if unit in ["kw", "kilowatt"]: return val * 1000.0
        return val

    async def async_update(self):
        now = dt_util.utcnow()
        room_state = self.hass.states.get(self._room_sensor_id)
        current_room = float(room_state.state) if room_state and room_state.state not in ['unknown', 'unavailable'] else 20.0
        outside_state = self.hass.states.get(self._outside_sensor_id)
        actueel_buiten = float(outside_state.state) if outside_state and outside_state.state not in ['unknown', 'unavailable'] else 5.0
        freq = self._get_float(self._config.get("compressor_freq_sensor"), 0.0)
        actuele_retour = self._get_float(self._config.get("return_temp_sensor"), 20.0)
        actuele_aanvoer = self._get_float(self._config.get("flow_temp_sensor"), 25.0)

        is_heating = freq >= self._learned_min_freq
        delta_t_check = actuele_aanvoer - actuele_retour
        self.is_defrosting_active = is_heating and (delta_t_check < 0)

        if self.is_defrosting_active:
            return

        if 10.0 <= freq < self._learned_min_freq:
            self._learned_min_freq = max(15.0, (0.95 * self._learned_min_freq) + (0.05 * freq))
        
        if self._last_room_temp is not None and self._last_update_time is not None and not is_heating:
            time_diff_hours = (now - self._last_update_time).total_seconds() / 3600.0
            if 0.1 < time_diff_hours < 2.0:
                temp_diff = self._last_room_temp - current_room
                if temp_diff > 0 and (current_room - actueel_buiten) > 0:
                    measured_coeff = temp_diff / (time_diff_hours * (current_room - actueel_buiten))
                    if 0.005 < measured_coeff < 0.1:
                        self._learned_cooling_coeff = (0.98 * self._learned_cooling_coeff) + (0.02 * measured_coeff)

        self._last_room_temp = current_room
        self._last_update_time = now

        base_setpoint = self._get_float("number.slimme_wp_basis_temperatuur", 22.0)
        setpoint_offset = self._get_float("number.slimme_wp_setpoint_offset", 0.0)
        helling = self._get_float("number.slimme_wp_stooklijn", 0.4)
        horizon_uren = int(self._get_float("number.slimme_wp_horizon", 4.0))
        zon_factor = self._get_float("number.slimme_wp_zon_factor", 2.0)
        stookgrens = self._get_float("number.slimme_wp_stookgrens", 18.0)
        
        setpoint_dag = self._get_float("number.slimme_wp_setpoint_dag", 21.0)
        setpoint_nacht = self._get_float("number.slimme_wp_setpoint_nacht", 20.4)
        dag_start = int(self._get_float("number.slimme_wp_dag_start", 9.0))
        dag_eind = int(self._get_float("number.slimme_wp_dag_eind", 21.0))
        nacht_start = int(self._get_float("number.slimme_wp_nacht_start", 23.0))
        nacht_eind = int(self._get_float("number.slimme_wp_nacht_eind", 7.0))
        max_prijs = self._get_float("number.slimme_wp_max_stroomprijs", 0.35)
        max_flow_grens = self._get_float("number.slimme_wp_max_flow_temp", 40.0)

        control_mode = self._config.get("control_mode", "retour")
        actuele_wp_temp = actuele_aanvoer if control_mode == "aanvoer" else actuele_retour

        verwacht_buiten = actueel_buiten
        verwacht_bewolking = 100.0
        predicted_future_cooling = 0.0

        if self._weather_id:
            try:
                response = await self.hass.services.async_call(
                    "weather", "get_forecasts", {"entity_id": self._weather_id, "type": "hourly"},
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
            except Exception: pass

        self.debug_verwacht_buiten = verwacht_buiten
        self.debug_verwacht_bewolking = verwacht_bewolking

        predicted_delta_t = current_room - verwacht_buiten
        if predicted_delta_t > 0:
            predicted_future_cooling = self._learned_cooling_coeff * predicted_delta_t * horizon_uren
        self.debug_voorspelde_afkoeling = predicted_future_cooling

        gecombineerd_buiten = (actueel_buiten * 0.7) + (verwacht_buiten * 0.3)
        weather_part = helling * (20.0 - gecombineerd_buiten)
        if verwacht_buiten < 0: weather_part += abs(verwacht_buiten) * 0.15

        sun_deduction = 0.0
        sun_state = self.hass.states.get("sun.sun")
        if sun_state:
            elevation = float(sun_state.attributes.get("elevation", 0.0))
            if elevation > 0:
                sun_deduction = zon_factor * (1.0 - (verwacht_bewolking / 100.0)) * min(elevation / 45.0, 1.0)
        self.debug_zon_reductie = sun_deduction

        huidig_uur = now.hour
        in_nacht = (huidig_uur >= nacht_start or huidig_uur < nacht_eind) if nacht_start > nacht_eind else (nacht_start <= huidig_uur < nacht_eind)
        
        current_auto_program = "Nacht" if in_nacht else "Dag"
        if self._last_auto_program is not None and current_auto_program != self._last_auto_program:
            try:
                await self.hass.services.async_call(
                    "climate", "set_preset_mode",
                    {"entity_id": "climate.slimme_warmtepomp_thermostaat", "preset_mode": current_auto_program},
                    blocking=False
                )
            except Exception: pass
        self._last_auto_program = current_auto_program
        
        actief_ruimte_setpoint = setpoint_nacht if in_nacht else setpoint_dag
        self.debug_actief_programma = current_auto_program

        climate_state = self.hass.states.get("climate.slimme_warmtepomp_thermostaat")
        if climate_state:
            preset = climate_state.attributes.get("preset_mode")
            if preset == "Handmatig":
                handmatig_temp = climate_state.attributes.get("temperature")
                if handmatig_temp is not None:
                    actief_ruimte_setpoint = float(handmatig_temp)
                    self.debug_actief_programma = "Handmatig"

        compensation_part = (actief_ruimte_setpoint - current_room) * 2.0
        if predicted_future_cooling > 0.3: compensation_part += predicted_future_cooling * 1.5

        ideal_setpoint = base_setpoint + setpoint_offset + weather_part + compensation_part - sun_deduction
        if dag_start <= huidig_uur < dag_eind: ideal_setpoint += 1.0
        if in_nacht: ideal_setpoint -= 1.0

        if self._last_smoothed_setpoint is not None:
            verschil = ideal_setpoint - self._last_smoothed_setpoint
            if verschil > 0.5: ideal_setpoint = self._last_smoothed_setpoint + 0.5
            elif verschil < -0.5: ideal_setpoint = self._last_smoothed_setpoint - 0.5
        self._last_smoothed_setpoint = ideal_setpoint

        self.is_summer_mode = actueel_buiten >= stookgrens
        self.is_dure_stroom = False

        if self.is_summer_mode:
            ideal_setpoint = actuele_wp_temp - 2.0
        else:
            if current_room > actief_ruimte_setpoint:
                ideal_setpoint = actuele_wp_temp - 1.0
            else:
                if dag_start <= huidig_uur < dag_eind:
                    ideal_setpoint = max(ideal_setpoint, base_setpoint)

        price_sensor_id = self._config.get("electricity_price_sensor")
        if price_sensor_id:
            huidige_prijs = self._get_float(price_sensor_id, 0.20)
            if huidige_prijs > max_prijs:
                ideal_setpoint = actuele_wp_temp - 2.0
                self.is_dure_stroom = True

        if ideal_setpoint > max_flow_grens: ideal_setpoint = max_flow_grens

        flow_lh = self._get_flow_in_liter_per_hour(self._config.get("flow_rate_sensor_1")) + self._get_flow_in_liter_per_hour(self._config.get("flow_rate_sensor_2"))
        power_w = self._get_power_in_watts(self._config.get("power_sensor"))
        
        self.calculated_elektrisch_w = round(power_w, 1)
        self.calculated_thermisch_kw = 0.0
        self.calculated_cop = 0.0
        
        if flow_lh > 0 and delta_t_check > 0:
            self.calculated_thermisch_kw = round((flow_lh * 4.186 * delta_t_check) / 3600.0, 2)
            if self.calculated_elektrisch_w > 100:
                cop = round(self.calculated_thermisch_kw / (self.calculated_elektrisch_w / 1000.0), 2)
                if 1.0 <= cop <= 8.0: self.calculated_cop = cop

        self._state = round(ideal_setpoint, 1)

        if self._target_setpoint_entity:
            try:
                await self.hass.services.async_call("number", "set_value", {"entity_id": self._target_setpoint_entity, "value": self._state}, blocking=False)
            except Exception: pass

    @property
    def native_value(self):
        return self._state

    @property
    def extra_state_attributes(self):
        return {
            "voorspelde_buiten_temp_over_horizon": round(self.debug_verwacht_buiten, 1),
            "voorspelde_afkoeling_c": round(self.debug_voorspelde_afkoeling, 2),
            "zon_compensatie_reductie_c": round(self.debug_zon_reductie, 2),
            "geleerde_min_frequentie_hz": round(self._learned_min_freq, 1),
            "geleerde_afkoel_coefficient": round(self._learned_cooling_coeff, 5),
            "actief_programma": self.debug_actief_programma,
            "ontdooi_actief": self.is_defrosting_active,
            "zomermodus_actief": self.is_summer_mode,
            "dure_stroom_actief": self.is_dure_stroom,
        }

    def _get_float(self, entity_id, default_value):
        if not entity_id: return default_value
        state = self.hass.states.get(entity_id)
        try: return float(state.state) if state and state.state not in ['unknown', 'unavailable'] else default_value
        except ValueError: return default_value

class SlimmeWarmtepompThermischVermogenSensor(SlimmeWarmtepompBaseSensor):
    def __init__(self, hass, config_entry, setpoint_sensor):
        super().__init__(hass, config_entry)
        self._setpoint_sensor = setpoint_sensor
        self._attr_name = "Warmtepomp Thermisch Vermogen"
        self._attr_unique_id = f"{self._entry_id}_thermisch_vermogen"
        self._attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_device_class = SensorDeviceClass.POWER
    @property
    def native_value(self): return self._setpoint_sensor.calculated_thermisch_kw

class SlimmeWarmtepompCopSensor(SlimmeWarmtepompBaseSensor):
    def __init__(self, hass, config_entry, setpoint_sensor):
        super().__init__(hass, config_entry)
        self._setpoint_sensor = setpoint_sensor
        self._attr_name = "Warmtepomp COP"
        self._attr_unique_id = f"{self._entry_id}_cop"
        self._attr_state_class = SensorStateClass.MEASUREMENT
    @property
    def native_value(self): return self._setpoint_sensor.calculated_cop

class SlimmeWarmtepompElektrischVermogenSensor(SlimmeWarmtepompBaseSensor):
    def __init__(self, hass, config_entry, setpoint_sensor):
        super().__init__(hass, config_entry)
        self._setpoint_sensor = setpoint_sensor
        self._attr_name = "Warmtepomp Elektrisch Vermogen"
        self._attr_unique_id = f"{self._entry_id}_elektrisch_vermogen"
        self._attr_native_unit_of_measurement = UnitOfPower.WATT
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_device_class = SensorDeviceClass.POWER
    @property
    def native_value(self): return self._setpoint_sensor.calculated_elektrisch_w

class SlimmeWarmtepompVoorspeldeBuitenTempSensor(SlimmeWarmtepompBaseSensor):
    def __init__(self, hass, config_entry, setpoint_sensor):
        super().__init__(hass, config_entry)
        self._setpoint_sensor = setpoint_sensor
        self._attr_name = "Voorspelde Buitentemperatuur Horizon"
        self._attr_unique_id = f"{self._entry_id}_voorspelde_buiten_temp"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
    @property
    def native_value(self): return round(self._setpoint_sensor.debug_verwacht_buiten, 1)

class SlimmeWarmtepompVoorspeldeAfkoelingSensor(SlimmeWarmtepompBaseSensor):
    def __init__(self, hass, config_entry, setpoint_sensor):
        super().__init__(hass, config_entry)
        self._setpoint_sensor = setpoint_sensor
        self._attr_name = "Voorspelde Huis Afkoeling"
        self._attr_unique_id = f"{self._entry_id}_voorspelde_afkoeling"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
    @property
    def native_value(self): return round(self._setpoint_sensor.debug_voorspelde_afkoeling, 2)

class SlimmeWarmtepompZonReductieSensor(SlimmeWarmtepompBaseSensor):
    def __init__(self, hass, config_entry, setpoint_sensor):
        super().__init__(hass, config_entry)
        self._setpoint_sensor = setpoint_sensor
        self._attr_name = "Verwachte Zon Reductie"
        self._attr_unique_id = f"{self._entry_id}_zon_reductie"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
    @property
    def native_value(self): return round(self._setpoint_sensor.debug_zon_reductie, 2)

async def async_setup_entry(hass, config_entry, async_add_entities):
    setpoint_sensor = SlimmeWarmtepompSetpointSensor(hass, config_entry)
    async_add_entities([
        setpoint_sensor,
        SlimmeWarmtepompThermischVermogenSensor(hass, config_entry, setpoint_sensor),
        SlimmeWarmtepompCopSensor(hass, config_entry, setpoint_sensor),
        SlimmeWarmtepompElektrischVermogenSensor(hass, config_entry, setpoint_sensor),
        SlimmeWarmtepompVoorspeldeBuitenTempSensor(hass, config_entry, setpoint_sensor),
        SlimmeWarmtepompVoorspeldeAfkoelingSensor(hass, config_entry, setpoint_sensor),
        SlimmeWarmtepompZonReductieSensor(hass, config_entry, setpoint_sensor)
    ])
