"""Smoke test of the Home Assistant glue using stand-in HA classes (see ha_stubs.py)."""
import asyncio
import importlib
import os
from pathlib import Path
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
        self.d[eid] = types.SimpleNamespace(entity_id=eid, state=str(state), attributes=attrs)

    def async_all(self, domains=None):
        domains = [domains] if isinstance(domains, str) else domains
        return [s for eid, s in self.d.items() if domains is None or eid.split(".")[0] in domains]


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
        self.bus = types.SimpleNamespace(async_listen_once=lambda *a, **k: (lambda: None), async_listen=lambda *a, **k: (lambda: None))

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
    entry = types.SimpleNamespace(entry_id="abc123", data=dict(config), options={}, runtime_data=None,
                                  async_on_unload=lambda cb: None)
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


def test_config_flow_cleans_its_data():
    cf = importlib.import_module(f"{PKG}.config_flow")
    assert cf._clean({"room_temp_sensor": "sensor.a", "outside_temp_sensor": "sensor.b", "return_temp_sensor": "",
                      "flow_rate_sensors": [], "extra_tapwater": True, "setpoint_step": "0.5", "control_mode": "retour"}) == {
        "room_temp_sensor": "sensor.a", "outside_temp_sensor": "sensor.b", "setpoint_step": 0.5,
        "control_mode": "retour"}
    assert cf.SlimmeWarmtepompConfigFlow.VERSION == 2


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


def test_icing_notification_is_sent_once_per_12_hours(setup):
    import dataclasses
    from datetime import timezone, timedelta
    h, entry, c = setup
    run(c.async_request_refresh())
    h.services.calls.clear()
    dec = dataclasses.replace(c.data, ice_level="ijs", ice_warning=True)
    t0 = datetime.now(timezone.utc)
    run(c._notify_icing(dec, t0))
    run(c._notify_icing(dec, t0 + timedelta(hours=1)))
    sent = [x for x in h.services.calls if x[0] == "persistent_notification"]
    assert len(sent) == 1
    run(c._notify_icing(dec, t0 + timedelta(hours=13)))
    assert len([x for x in h.services.calls if x[0] == "persistent_notification"]) == 2
    ids = {e.entity_id for _, e in h.entities}
    assert {"sensor.slimme_wp_ijsvorming", "sensor.slimme_wp_volgende_ontdooi",
            "binary_sensor.slimme_wp_ijsvorming_alarm"} <= ids


def test_relearn_button_uses_percentage_setting(setup):
    h, entry, c = setup
    by_uid = {e._attr_unique_id: e for _, e in h.entities}
    assert "button.slimme_wp_opnieuw_aanleren" in {e.entity_id for _, e in h.entities}
    c.controller.pi_i, c.controller.trim = 2.0, {2: 1.0}
    run(by_uid["abc123_herleer_percentage"].async_set_native_value(50.0))
    run(by_uid["abc123_opnieuw_aanleren"].async_press())
    assert abs(c.controller.pi_i - 1.0) < 1e-6 and abs(c.controller.trim[2] - 0.5) < 1e-6


def test_forecast_falls_back_to_daily_when_hourly_is_not_supported(setup):
    from homeassistant.exceptions import HomeAssistantError
    h, entry, c = setup
    types_asked = []

    async def fake_call(domain, service, data, blocking=False, return_response=False):
        if domain == "weather":
            types_asked.append(data["type"])
            if data["type"] != "daily":
                raise HomeAssistantError("not supported")
            day = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
            return {data["entity_id"]: {"forecast": [
                {"datetime": (day + timedelta(days=i)).isoformat(), "temperature": 8.0, "templow": 2.0} for i in range(1, 5)]}}
    h.services.async_call = fake_call
    c._forecast_at, c._forecast_type = None, None
    run(c._refresh_forecast(datetime.now().astimezone()))
    assert types_asked == ["hourly", "twice_daily", "daily"]
    assert len(c._forecast) == 4 and all(abs(f[1] - 5.0) < 1e-9 for f in c._forecast)       # mean of high and low
    assert c._forecast_type == "daily"
    # the working type is remembered: the next refresh asks for it directly
    types_asked.clear(); c._forecast_at = None
    run(c._refresh_forecast(datetime.now().astimezone()))
    assert types_asked == ["daily"]


def test_decision_changes_are_logged_at_debug_level(setup, caplog):
    import logging
    h, entry, c = setup
    c._last_logged = None
    with caplog.at_level(logging.DEBUG):
        run(c._async_update_data())
    assert any("Decision: reason=" in r.getMessage() for r in caplog.records)
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        run(c._async_update_data())             # unchanged decision: no new line
    assert not any("Decision: reason=" in r.getMessage() for r in caplog.records)


def test_dashboard_strategy_is_served_and_loaded_in_the_frontend(monkeypatch, tmp_path):
    import types as _t
    init = importlib.import_module(PKG)
    registered, added = [], []
    http_mod = sys.modules.get("homeassistant.components.http") or _t.ModuleType("homeassistant.components.http")
    frontend_mod = sys.modules.get("homeassistant.components.frontend") or _t.ModuleType("homeassistant.components.frontend")

    class StaticPathConfig:
        def __init__(self, url_path, path, cache_headers):
            self.url_path, self.path, self.cache_headers = url_path, path, cache_headers

    monkeypatch.setattr(http_mod, "StaticPathConfig", StaticPathConfig, raising=False)
    monkeypatch.setattr(frontend_mod, "add_extra_js_url", lambda hass, url, es5=False: added.append(url), raising=False)
    monkeypatch.setitem(sys.modules, "homeassistant.components.http", http_mod)
    monkeypatch.setitem(sys.modules, "homeassistant.components.frontend", frontend_mod)

    async def reg(paths):
        registered.extend(paths)
    h, _ = make_hass()
    h.http = types.SimpleNamespace(async_register_static_paths=reg)
    run(init._register_dashboard_strategy(h))
    assert len(registered) == 1 and registered[0].url_path == "/slimme_warmtepomp_frontend"
    assert (Path(registered[0].path) / "slimme-warmtepomp-strategy.js").is_file()
    assert added == [f"/slimme_warmtepomp_frontend/slimme-warmtepomp-strategy.js?v={init.VERSION}"]


def test_failing_dashboard_registration_never_breaks_the_integration(caplog):
    init = importlib.import_module(PKG)
    h, _ = make_hass()                     # no hass.http at all
    run(init._register_dashboard_strategy(h))
    assert any("dashboard strategy" in r.getMessage() for r in caplog.records)


def test_setpoint_sensor_exposes_the_connected_sensors_for_the_dashboard(setup):
    h, entry, c = setup
    attrs = c.input_entities()
    assert attrs["kamer"] == "sensor.room" and attrs["retour"] == "sensor.ret" and attrs["pomp_schakelaar"] == "switch.wp"
    sp = next(e for p, e in h.entities if e.entity_id == "sensor.slimme_wp_setpoint")
    assert sp.extra_state_attributes["invoer_sensoren"] == attrs


def test_several_rooms_and_flow_sensors_reach_the_controller():
    cfg = {**CONFIG, "extra_room_sensors": ["sensor.slaap", "sensor.studeer"], "room_mode": "koudste",
           "flow_rate_sensors": ["sensor.flow1", "sensor.flow2", "sensor.flow3"]}
    cfg.pop("flow_rate_sensor_1")
    h, entry = make_hass(cfg)
    h.states.set("sensor.slaap", 18.0); h.states.set("sensor.studeer", 19.5)
    h.states.set("sensor.flow2", 600, unit_of_measurement="l/h"); h.states.set("sensor.flow3", "unavailable")
    h.states.set("sensor.flow1", 15, unit_of_measurement="l/min")
    assert run(importlib.import_module(PKG).async_setup_entry(h, entry)) is True
    c = entry.runtime_data
    inp = run(c._build_inputs())
    assert inp.room == 18.0                                                  # coldest of 20.5 / 18.0 / 19.5
    assert inp.flow_lh == pytest.approx(900.0 + 600.0)                       # 15 l/min = 900 l/h, the unavailable sensor is skipped
    assert c.decision_diag_rooms() if hasattr(c, "decision_diag_rooms") else True
    assert c.data.diag["kamers"]["gebruikt"] == 18.0
    assert c.input_entities()["debiet_3"] == "sensor.flow3" and c.input_entities()["kamer_3"] == "sensor.studeer"
    ids = {e.entity_id for _, e in h.entities}
    assert "number.slimme_wp_min_extra_kamer" in ids                         # guard-room setting exists only with extra rooms


def test_guard_room_setting_and_notify_settings_are_absent_by_default(setup):
    h, entry, c = setup
    ids = {e.entity_id for _, e in h.entities}
    assert "number.slimme_wp_min_extra_kamer" not in ids and "number.slimme_wp_melding_te_koud_uren" not in ids
    assert "switch.slimme_wp_weekrapport_actief" not in ids


def test_old_flow_rate_fields_are_migrated_to_a_list():
    init = importlib.import_module(PKG)
    updates = []
    entry = types.SimpleNamespace(version=1, data={"room_temp_sensor": "sensor.r", "flow_rate_sensor_1": "sensor.f1",
                                                   "flow_rate_sensor_2": "sensor.f2"})
    h, _ = make_hass()
    h.config_entries.async_update_entry = lambda e, data=None, version=None: updates.append((data, version))
    assert run(init.async_migrate_entry(h, entry)) is True
    data, version = updates[0]
    assert version == 2 and data["flow_rate_sensors"] == ["sensor.f1", "sensor.f2"]
    assert "flow_rate_sensor_1" not in data and data["room_temp_sensor"] == "sensor.r"


def _notify_setup(**extra):
    cfg = {**CONFIG, "notify_services": ["notify.mobile_app_pixel"], **extra}
    h, entry = make_hass(cfg)
    assert run(importlib.import_module(PKG).async_setup_entry(h, entry)) is True
    return h, entry, entry.runtime_data


def test_messages_go_to_the_chosen_notify_service_in_the_ha_language():
    import dataclasses
    from datetime import timezone, timedelta
    h, entry, c = _notify_setup()
    h.config.language = "en"
    run(c.async_request_refresh()); h.services.calls.clear()
    dec = dataclasses.replace(c.data, ice_level="ijs", ice_warning=True, diag={**c.data.diag, "ijsvorming": {"redenen": ["cop_zakt"]}})
    t0 = datetime.now(timezone.utc)
    run(c._notify_icing(dec, t0)); run(c._notify_icing(dec, t0 + timedelta(hours=1)))
    sent = [x for x in h.services.calls if x[0] == "notify"]
    assert len(sent) == 1 and sent[0][1] == "mobile_app_pixel"
    assert "icing" in sent[0][2]["title"].lower() and "COP drops" in sent[0][2]["message"]
    h.config.language = "nl"; h.services.calls.clear()
    run(c._notify_icing(dec, t0 + timedelta(hours=14)))
    assert "ijsvorming" in [x for x in h.services.calls if x[0] == "notify"][0][2]["title"].lower()


def test_cold_room_message_after_the_configured_number_of_hours():
    import dataclasses
    from datetime import timezone, timedelta
    h, entry, c = _notify_setup()
    run(c.async_request_refresh())
    dec = dataclasses.replace(c.data, room_setpoint=21.0, summer=False, defrost=False)
    inp = run(c._build_inputs()); inp = dataclasses.replace(inp, room=18.0)
    h.services.calls.clear()
    t0 = datetime.now(timezone.utc)
    run(c._notify_cold(dec, inp, t0)); run(c._notify_cold(dec, inp, t0 + timedelta(hours=2)))
    assert not [x for x in h.services.calls if x[0] == "notify"]              # not yet 3 hours
    run(c._notify_cold(dec, inp, t0 + timedelta(hours=3, minutes=1)))
    assert len([x for x in h.services.calls if x[0] == "notify"]) == 1
    warm = dataclasses.replace(inp, room=20.9)
    run(c._notify_cold(dec, warm, t0 + timedelta(hours=4)))                    # back in range: the timer resets
    assert c._cold_since is None


def test_health_problem_becomes_a_repair_issue_and_a_message_and_clears_again():
    from datetime import timezone, timedelta
    issues = sys.modules["homeassistant.helpers.issue_registry"].ISSUES
    issues.created.clear(); issues.deleted.clear()
    h, entry, c = _notify_setup()
    h.states.set("sensor.ret", "unavailable")
    t0 = datetime.now(timezone.utc)
    run(c._check_health(t0)); assert not issues.created
    h.services.calls.clear()
    run(c._check_health(t0 + timedelta(minutes=31)))
    assert "unavailable_retour" in issues.created
    assert issues.created["unavailable_retour"]["translation_key"] == "unavailable"
    assert [x for x in h.services.calls if x[0] == "notify"]
    run(c._check_health(t0 + timedelta(minutes=35)))
    assert len(issues.created) == 1                                           # not created twice
    h.states.set("sensor.ret", 27.0)
    run(c._check_health(t0 + timedelta(minutes=40)))
    assert "unavailable_retour" in issues.deleted


def test_weekly_report_sensor_and_monday_message():
    from datetime import timezone, timedelta
    h, entry, c = _notify_setup()
    u = c.controller.usage
    base = datetime(2026, 11, 2, 0, 0, tzinfo=datetime.now().astimezone().tzinfo)
    for day in range(8):
        for hr in range(24):
            u.update(base + timedelta(days=day, hours=hr), dt_h=1.0, e_dt=1.0, outside=5.0, base=18.0, el_kwh=0.5, th_kwh=1.5,
                     price=0.25, heating=True, defrost=False, regeling_actief=True, in_band=True)
    monday = base + timedelta(days=7, hours=9)                                # Monday 9 Nov, 09:00
    assert monday.weekday() == 0
    h.services.calls.clear()
    run(c._weekly_report(monday, c.data))
    sent = [x for x in h.services.calls if x[0] == "notify"]
    assert len(sent) == 1 and "kWh" in sent[0][2]["message"]
    run(c._weekly_report(monday + timedelta(hours=1), c.data))
    assert len([x for x in h.services.calls if x[0] == "notify"]) == 1       # once per week
    sensor = next(e for p, e in h.entities if e.entity_id == "sensor.slimme_wp_weekrapport")
    assert sensor.native_value == pytest.approx(84.0) and "kWh" in sensor.extra_state_attributes["rapport"]
    assert sensor.extra_state_attributes["comfort_percentage"] == 100
    # a restart in the same week does not send it again
    run(c.async_save()); assert c._week_sent


def test_export_and_import_settings_and_learned_state(tmp_path):
    h, entry = make_hass()
    h.config.path = lambda name: str(tmp_path / name)
    h.config_entries.async_entries = lambda domain=None: [entry]
    handlers = {}
    h.services.async_register = lambda domain, name, fn, schema=None, supports_response=None: handlers.__setitem__(name, fn)

    async def exec_job(fn, *a):
        return fn(*a)
    h.async_add_executor_job = exec_job
    init = importlib.import_module(PKG)
    run(init.async_setup(h, {}))
    assert {"exporteer", "importeer", "reset_model"} <= set(handlers)
    run(init.async_setup_entry(h, entry))
    c = entry.runtime_data
    c.settings["setpoint_dag"] = 21.5
    c.switches["prijssturing_actief"] = False
    c.controller.mod.observe(3.0, True, 50.0, 4.0)
    call = types.SimpleNamespace(data={"leerstatus": True})
    out = run(handlers["exporteer"](call))
    assert out["instellingen"]["setpoint_dag"] == 21.5 and out["schakelaars"]["prijssturing_actief"] is False
    assert (tmp_path / "slimme_warmtepomp_export.json").is_file() and "leerstatus" in out

    c.settings["setpoint_dag"] = 19.0; c.switches["prijssturing_actief"] = True
    c.controller.mod.reset()
    res = run(handlers["importeer"](types.SimpleNamespace(data={})))            # reads the file
    assert res["leerstatus"] and not res["overgeslagen"]
    assert c.settings["setpoint_dag"] == 21.5 and c.switches["prijssturing_actief"] is False
    assert c.controller.mod.bins                                                  # the learned table is back

    # without the learned part only settings come back; garbage and out-of-range values are handled
    c.controller.mod.reset()
    bad = {**out, "instellingen": {"setpoint_dag": 99.0, "bestaat_niet": 1.0, "glycol": "veel"}, "schakelaars": {"leren_actief": "ja"}}
    res = run(handlers["importeer"](types.SimpleNamespace(data={"data": bad, "leerstatus": False})))
    assert c.settings["setpoint_dag"] == 25.0                                    # clamped to the maximum of the setting
    assert sorted(res["overgeslagen"]) == ["bestaat_niet", "glycol", "leren_actief"] and not res["leerstatus"]
    assert not c.controller.mod.bins
    with pytest.raises(Exception):
        run(c.import_bundle({"iets": "anders"}))
