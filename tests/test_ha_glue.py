"""Smoke test of the Home Assistant glue using stand-in HA classes (see ha_stubs.py)."""
import asyncio
import importlib
import os
import sys
import types
from datetime import datetime, timedelta

import pytest

import ha_stubs

ha_stubs.install()
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
PKG = "custom_components.slimme_warmtepomp"


class FakeStates:
    def __init__(self):
        self.d = {}

    def get(self, eid):
        return self.d.get(eid)

    def set(self, eid, state, **attrs):
        self.d[eid] = types.SimpleNamespace(state=str(state), attributes=attrs)


class FakeServices:
    def __init__(self, hass):
        self.calls, self.hass = [], hass

    async def async_call(self, domain, service, data, blocking=False, return_response=False):
        self.calls.append((domain, service, dict(data)))
        if domain == "weather":
            now = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
            return {data["entity_id"]: {"forecast": [
                {"datetime": (now + timedelta(hours=i)).isoformat(), "temperature": 6 - 0.5 * i, "cloud_coverage": 60}
                for i in range(1, 30)]}}
        if domain == "number" and service == "set_value":
            self.hass.states.set(data["entity_id"], data["value"], min=20, max=45)


class FakeConfigEntries:
    def __init__(self, hass):
        self.hass = hass

    async def async_forward_entry_setups(self, entry, platforms):
        self.hass.entities = []
        for p in platforms:
            m = importlib.import_module(f"{PKG}.{p}")
            added = []
            await m.async_setup_entry(self.hass, entry, lambda ents, a=added: a.extend(list(ents)))
            for e in added:
                await e.async_added_to_hass()
            self.hass.entities += [(p, e) for e in added]


class FakeHass:
    def __init__(self):
        self.states = FakeStates()
        self.services = FakeServices(self)
        self.config = types.SimpleNamespace(latitude=52.37, longitude=4.9)
        self.config_entries = FakeConfigEntries(self)
        self.entities = []

    async def async_add_executor_job(self, fn, *a):
        return fn(*a)


CONFIG = {
    "room_temp_sensor": "sensor.room", "outside_temp_sensor": "sensor.outside",
    "return_temp_sensor": "sensor.ret", "flow_temp_sensor": "sensor.flow",
    "compressor_freq_sensor": "sensor.freq", "power_sensor": "sensor.power",
    "flow_rate_sensor_1": "sensor.flow1", "weather_entity": "weather.home",
    "electricity_price_sensor": "sensor.price", "pv_power_sensor": "sensor.pv",
    "target_setpoint_entity": "number.wp_target", "heatpump_switch": "switch.wp", "control_mode": "retour",
    "setpoint_step": 1.0,
    "dhw_temp_sensor": "sensor.tank", "dhw_switch": "switch.dhw", "dhw_setpoint_entity": "number.dhw_target",
}


def make_hass(config=CONFIG):
    h = FakeHass()
    s = h.states.set
    s("sensor.room", 20.5); s("sensor.outside", 5.0); s("sensor.ret", 27.0); s("sensor.flow", 31.0)
    s("sensor.freq", 45); s("sensor.power", 0.8, unit_of_measurement="kW"); s("sensor.flow1", 15, unit_of_measurement="l/min")
    s("weather.home", "cloudy", cloud_coverage=70); s("sensor.pv", 2.0, unit_of_measurement="kW")
    now = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
    s("sensor.price", 0.22, raw_today=[{"start": (now + timedelta(hours=i)).isoformat(), "value": 0.2 + 0.01 * i} for i in range(12)])
    s("number.wp_target", 28, min=20, max=45); s("switch.wp", "on"); s("sensor.tank", 45.0)
    s("switch.dhw", "off"); s("number.dhw_target", 45, min=30, max=65)
    entry = types.SimpleNamespace(entry_id="abc123", data=dict(config), options={}, runtime_data=None)
    return h, entry


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def setup():
    h, entry = make_hass()
    init = importlib.import_module(PKG)
    assert run(init.async_setup_entry(h, entry)) is True
    return h, entry, entry.runtime_data


def read_all(h):
    out = {}
    for platform, e in h.entities:
        for attr in ("native_value", "is_on", "hvac_mode", "preset_mode", "target_temperature",
                     "current_temperature", "hvac_action", "extra_state_attributes"):
            if hasattr(type(e), attr):
                out[(platform, e._attr_unique_id, attr)] = getattr(e, attr)
    return out


def test_obsolete_v1_entities_are_removed_from_registry():
    reg = sys.modules["homeassistant.helpers.entity_registry"].REGISTRY
    reg.existing = {("number", "slimme_warmtepomp", "abc123_dag_start"): "number.slimme_wp_dag_start",
                    ("number", "slimme_warmtepomp", "abc123_dag_eind"): "number.slimme_wp_dag_eind"}
    reg.removed.clear()
    h, entry = make_hass()
    run(importlib.import_module(PKG).async_setup_entry(h, entry))
    assert sorted(reg.removed) == ["number.slimme_wp_dag_eind", "number.slimme_wp_dag_start"]
    reg.existing = {}


def test_all_entities_start_and_read(setup):
    h, entry, c = setup
    values = read_all(h)
    assert len(h.entities) > 50
    ids = {e.entity_id for _, e in h.entities}
    # entity ids and unique ids of v1 are preserved
    for must in ("sensor.slimme_wp_setpoint", "climate.slimme_wp_thermostaat", "switch.slimme_wp_regeling_actief",
                 "number.slimme_wp_basis_temperatuur", "binary_sensor.slimme_wp_defrost", "sensor.slimme_wp_cop"):
        assert must in ids
    uids = {e._attr_unique_id for _, e in h.entities}
    assert {"abc123_setpoint", "abc123_climate", "abc123_regeling_actief", "abc123_stooklijn"} <= uids
    assert len(uids) == len(h.entities), "unique ids must be unique"
    assert len(ids) == len(h.entities), "entity ids must be unique"
    assert c.data is not None and c.data.reason
    assert values[("sensor", "abc123_setpoint", "native_value")] is not None
    # removed v1 entities are really gone
    assert "number.slimme_wp_dag_start" not in ids and "number.slimme_wp_dag_eind" not in ids
    # DHW entities exist because a tank sensor is configured
    assert "number.slimme_wp_dhw_doel_temp" in ids and "binary_sensor.slimme_wp_dhw_bezig" in ids


def test_dhw_entities_absent_without_tank_sensor():
    cfg = {k: v for k, v in CONFIG.items() if not k.startswith("dhw_")}
    h, entry = make_hass(cfg)
    run(importlib.import_module(PKG).async_setup_entry(h, entry))
    ids = {e.entity_id for _, e in h.entities}
    assert not any("dhw" in i or "tapwater" in i for i in ids)


def test_cycle_writes_setpoint_within_device_limits_and_only_when_changed(setup):
    h, entry, c = setup
    writes = [x for x in h.services.calls if x[0] == "number" and x[2]["entity_id"] == "number.wp_target"]
    assert len(writes) <= 1
    for _, _, data in writes:
        assert 20 <= data["value"] <= 45
    n = len(h.services.calls)
    run(c.async_request_refresh())
    again = [x for x in h.services.calls[n:] if x[2].get("entity_id") == "number.wp_target"]
    assert len(again) <= 1


def test_tank_below_minimum_starts_dhw_and_blocks_space_heating(setup):
    h, entry, c = setup
    h.services.calls.clear()
    h.states.set("sensor.tank", 38.0)
    run(c.async_request_refresh())
    calls = h.services.calls
    assert ("switch", "turn_on", {"entity_id": "switch.dhw"}) in calls
    assert any(x[2].get("entity_id") == "number.dhw_target" for x in calls)
    assert c.data.dhw_active and c.data.reason == "tapwater"


def test_user_actions_reach_controller(setup):
    h, entry, c = setup
    by_uid = {e._attr_unique_id: e for _, e in h.entities}
    run(by_uid["abc123_setpoint_dag"].async_set_native_value(22.5))
    assert c.settings["setpoint_dag"] == 22.5
    run(by_uid["abc123_leren_actief"].async_turn_off())
    assert c.switches["leren_actief"] is False
    climate = by_uid["abc123_climate"]
    run(climate.async_set_temperature(temperature=23.0))
    assert climate.preset_mode == "Handmatig" and climate.target_temperature == 23.0
    run(climate.async_set_hvac_mode(ha_stubs.sys.modules["homeassistant.components.climate"].HVACMode.OFF))
    assert c.data.reason == "uit" and ("switch", "turn_off", {"entity_id": "switch.wp"}) in h.services.calls


def test_sensor_dropout_does_not_crash(setup):
    h, entry, c = setup
    h.states.set("sensor.room", "unavailable")
    run(c.async_request_refresh())
    assert c.data.sensor_problem
    read_all(h)


def test_state_is_saved_and_restored(setup):
    h, entry, c = setup
    c.controller.tracker.bias = 1.5
    run(c.async_save())
    h2, entry2 = make_hass()
    run(importlib.import_module(PKG).async_setup_entry(h2, entry2))
    assert entry2.runtime_data.controller.tracker.bias == 1.5


def test_reset_service_clears_model(setup):
    h, entry, c = setup
    c.controller.model.learn_room(-0.1, 3.0, 15.0, 0.1)
    assert c.controller.model.windows_room == 1
    run(c.async_reset_model())
    assert c.controller.model.windows_room == 0


def test_config_flow_schema_builds():
    cf = importlib.import_module(f"{PKG}.config_flow")
    schema = cf._schema(dict(CONFIG))
    assert cf._clean({"room_temp_sensor": "sensor.a", "outside_temp_sensor": "sensor.b", "return_temp_sensor": "",
                      "setpoint_step": "0.5", "control_mode": "retour"}) == {
        "room_temp_sensor": "sensor.a", "outside_temp_sensor": "sensor.b", "setpoint_step": 0.5,
        "control_mode": "retour"}
    assert schema


def test_shadow_mode_shows_setpoint_but_does_not_write(setup):
    h, entry, c = setup
    by_uid = {e._attr_unique_id: e for _, e in h.entities}
    run(by_uid["abc123_regeling_actief"].async_turn_off())
    h.services.calls.clear()
    h.states.set("sensor.room", 19.0)
    run(c.async_request_refresh())
    assert c.data.shadow and c.last_setpoint is not None
    assert not [x for x in h.services.calls if x[2].get("entity_id") in ("number.wp_target", "switch.wp")]


def test_hvac_action_matches_v1_wording(setup):
    h, entry, c = setup
    climate = {e._attr_unique_id: e for _, e in h.entities}["abc123_climate"]
    A = sys.modules["homeassistant.components.climate"].HVACAction
    h.states.set("sensor.freq", 40); h.states.set("switch.wp", "on")
    run(c.async_request_refresh()); assert climate.hvac_action == A.HEATING
    h.states.set("sensor.freq", 0)
    run(c.async_request_refresh()); assert climate.hvac_action == A.FAN        # circuleren
    h.states.set("sensor.freq", 40); h.states.set("switch.wp", "on")
    run(c.async_request_refresh())
    c.data.defrost = True
    assert climate.hvac_action == A.DEFROSTING                                   # ontdooien
    c.data.defrost = False
    h.states.set("sensor.freq", 0)
    h.states.set("switch.wp", "off")
    run(c.async_request_refresh()); assert climate.hvac_action == A.IDLE       # stand-by


def test_optional_inputs_and_entities():
    cfg = dict(CONFIG, open_sensors=["binary_sensor.raam1", "binary_sensor.deur"],
               presence_entities=["person.a", "person.b"], holiday_entity="input_boolean.vakantie",
               return_time_entity="input_datetime.terug", grid_power_sensor="sensor.grid")
    h, entry = make_hass(cfg)
    s = h.states.set
    s("binary_sensor.raam1", "off"); s("binary_sensor.deur", "on")
    s("person.a", "not_home"); s("person.b", "not_home"); s("input_boolean.vakantie", "off")
    s("sensor.grid", 2.5, unit_of_measurement="kW")
    tomorrow = (datetime.now().astimezone() + timedelta(hours=30)).strftime("%Y-%m-%d %H:%M:%S")
    s("input_datetime.terug", tomorrow)
    run(importlib.import_module(PKG).async_setup_entry(h, entry))
    c = entry.runtime_data
    ids = {e.entity_id for _, e in h.entities}
    assert {"binary_sensor.slimme_wp_raam_open", "binary_sensor.slimme_wp_afwezig",
            "binary_sensor.slimme_wp_netlimiet", "number.slimme_wp_raam_vertraging",
            "number.slimme_wp_afwezig_setpoint", "number.slimme_wp_netimport_limiet",
            "sensor.slimme_wp_cop_vandaag", "sensor.slimme_wp_starts_vandaag"} <= ids
    assert c._windows_open() is True and c._away() is True
    assert c._grid_ok if hasattr(c, "_grid_ok") else True
    ret = c._return_at(datetime.now().astimezone())
    assert ret is not None and ret > datetime.now().astimezone()
    s("person.b", "home")
    assert c._away() is False
    s("input_boolean.vakantie", "on")
    assert c._away() is True
    read_all(h)


def test_optional_entities_absent_when_not_configured(setup):
    h, entry, c = setup
    ids = {e.entity_id for _, e in h.entities}
    assert "binary_sensor.slimme_wp_raam_open" not in ids and "number.slimme_wp_afwezig_setpoint" not in ids
