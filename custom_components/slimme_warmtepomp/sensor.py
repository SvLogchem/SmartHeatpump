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
        self._attr_extra_state_attributes = {}

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

    async def async_update(self):
        room_state = self.hass.states.get(self._room_sensor_id)
        if not room_state or room_state.state in ['unknown', 'unavailable']:
            current_room = 20.0
        else:
            current_room = float(room_state.state)

        outside_state = self.hass.states.get(self._outside_sensor_id)
        if not outside_state or outside_state.state in ['unknown', 'unavailable']:
            actueel_buiten = 5.0
        else:
            actueel_buiten = float(outside_state.state)

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
        freq = self._get_float(self._config.get("compressor_freq_sensor"), 0.0)

        actuele_wp_temp = actuele_aanvoer if control_mode == "aanvoer" else actuele_retour

        currently_running = freq >= 30.0
        if currently_running and not self._is_running:
            self._compressor_start_time = dt_util.utcnow()
            self._is_running = True
        elif not currently_running:
            self._is_running = False
            self._compressor_start_time = None

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

        huidig_uur = dt_util.now().hour
        in_nacht = False
        if nacht_start > nacht_eind:
            in_nacht = huidig_uur >= nacht_start or huidig_uur < nacht_eind
        else:
            in_nacht = nacht_start <= huidig_uur < nacht_eind

        actief_ruimte_setpoint = setpoint_nacht if in_nacht else setpoint_dag
        room_error = actief_ruimte_setpoint - current_room
        compensation_part = room_error * 2.0

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
            draaitijd = dt_util.utcnow() - self._compressor_start_time
            if draaitijd.total_seconds() < (minimum_minuten * 60):
                marge = ideal_setpoint - actuele_wp_temp
                if marge < waakhond_marge:
                    ideal_setpoint = actuele_wp_temp + waakhond_marge

        price_sensor_id = self._config.get("electricity_price_sensor")
        huidige_prijs = self._get_float(price_sensor_id, 0.20) if price_sensor_id else 0.20
        if price_sensor_id and huidige_prijs > max_prijs:
            ideal_setpoint = actuele_wp_temp - 2.0

        dhw_sensor_id = self._config.get("dhw_status_sensor")
        if dhw_sensor_id:
            dhw_state = self.hass.states.get(dhw_sensor_id)
            if dhw_state and dhw_state.state in ['on', 'active', 'heating', 'dhw']:
                pass

        if actueel_buiten < bivalent_grens:
            _LOGGER.warning(f"Bivalente grens bereikt: {actueel_buiten}°C")

        pv_sensor_id = self._config.get("pv_power_sensor")
        pv_power = self._get_float(pv_sensor_id, 0.0)
        if pv_power < -1500:
            ideal_setpoint += pv_boost_val

        if ideal_setpoint > max_flow_grens:
            ideal_setpoint = max_flow_grens

        flow_id_1 = self._config.get("flow_rate_sensor_1")
        flow_id_2 = self._config.get("flow_rate_sensor_2")
        power_sensor_id = self._config.get("power_sensor")
        
        flow_l_h = self._get_flow_in_liter_per_hour(flow_id_1) + self._get_flow_in_liter_per_hour(flow_id_2)
        power_w = self._get_float(power_sensor_id, 0.0)
        
        p_thermisch_kw = 0.0
        cop_waarde = 0.0
        
        if flow_l_h > 0:
            delta_t = actuele_aanvoer - actuele_retour
            if delta_t > 0:
                p_thermisch_kw = round((flow_l_h * 4.186 * delta_t) / 3600.0, 2)
                if power_w > 100:
                    p_elektrisch_kw = power_w / 1000.0
                    cop_waarde = round(p_thermisch_kw / p_elektrisch_kw, 2)
                    if cop_waarde < 1.0 or cop_waarde > 8.0:
                        cop_waarde = 0.0

        self._state = round(ideal_setpoint, 1)
        self._attr_extra_state_attributes = {
            "thermisch_vermogen_kw": p_thermisch_kw,
            "cop": cop_waarde,
            "actuele_aanvoer": actuele_aanvoer,
            "actuele_retour": actuele_retour,
            "totaal_flow_l_h": flow_l_h,
            "elektrisch_vermogen_w": power_w
        }

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
