"""The setup wizard: step order, the optional screens, suggestions, reconfigure, and the pump profile."""
import importlib
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import test_ha_glue as G                      # noqa: E402  (sets up the Home Assistant stubs)

ER = sys.modules["homeassistant.helpers.entity_registry"]


def keys(result):
    out = {}
    for k in result["data_schema"]:
        name = getattr(k, "key", None) or getattr(k, "schema", None) or str(k)
        out[name] = k
    return out


def make_flow(states=None, entry=None):
    mod = importlib.import_module(G.PKG + ".config_flow")
    h, _ = G.make_hass()
    h.states.d.clear()
    for eid, (state, attrs, platform) in (states or {}).items():
        h.states.set(eid, state, **attrs)
        ER.REGISTRY.entities[eid] = types.SimpleNamespace(platform=platform, entity_id=eid)
    h.services.async_services = lambda: {"notify": {"mobile_app_pixel": object(), "send_message": object(), "persistent_notification": object()}}

    class Flow(mod.SlimmeWarmtepompConfigFlow):
        def __init__(self):
            super().__init__()
            self.hass = h
            self.updated = None

        async def async_set_unique_id(self, uid):
            return None

        def _abort_if_unique_id_configured(self):
            return None

        def async_show_form(self, *, step_id, data_schema=None, **kw):
            return {"type": "form", "step_id": step_id, "data_schema": data_schema}

        def async_create_entry(self, *, title, data):
            return {"type": "create_entry", "title": title, "data": data}

        def _get_reconfigure_entry(self):
            return entry

        def async_update_reload_and_abort(self, e, *, data):
            self.updated = data
            return {"type": "abort", "reason": "reconfigure_successful", "data": data}

    return Flow(), h


@pytest.fixture(autouse=True)
def clean_registry():
    ER.REGISTRY.entities.clear()
    yield
    ER.REGISTRY.entities.clear()


STATES = {
    "sensor.warmtepomp_retour_temp": ("27", {"friendly_name": "Warmtepomp Retour Temp", "unit_of_measurement": "°C"}, "localtuya"),
    "sensor.warmtepomp_aanvoer_temp": ("31", {"friendly_name": "Warmtepomp Aanvoer Temp", "unit_of_measurement": "°C"}, "localtuya"),
    "sensor.warmtepomp_compressor_frequentie": ("40", {"friendly_name": "Compressor frequentie", "unit_of_measurement": "Hz"}, "localtuya"),
    "number.warmtepomp_setpoint": ("28", {"friendly_name": "Setpoint verwarmen"}, "localtuya"),
    "switch.warmtepomp_schakelaar": ("on", {"friendly_name": "Warmtepomp aan/uit"}, "localtuya"),
    "sensor.woonkamer_temperatuur": ("20.5", {"friendly_name": "Woonkamer temperatuur", "unit_of_measurement": "°C"}, "zha"),
    "sensor.tuin_buitentemperatuur": ("5", {"friendly_name": "Tuin buiten temperatuur", "unit_of_measurement": "°C"}, "zha"),
    "sensor.belimo_flow_rate": ("900", {"friendly_name": "Belimo flow rate", "unit_of_measurement": "l/h"}, "belimo"),
}


def test_wizard_walks_through_the_steps_and_only_asks_for_ticked_extras():
    flow, _ = make_flow(STATES)
    r = G.run(flow.async_step_user())
    assert r["step_id"] == "user" and "pump_source" in keys(r) and "pump_profile" in keys(r)
    assert "localtuya" in ER.REGISTRY.entities["number.warmtepomp_setpoint"].platform
    r = G.run(flow.async_step_user({"control_mode": "retour", "setpoint_step": "0.5", "pump_profile": "algemeen",
                                    "pump_source": "localtuya", "pump_source_filter": True}))
    assert r["step_id"] == "basis"
    assert {"room_temp_sensor", "extra_room_sensors", "room_mode", "outside_temp_sensor"} <= set(keys(r))
    r = G.run(flow.async_step_basis({"room_temp_sensor": "sensor.woonkamer_temperatuur", "extra_room_sensors": ["sensor.slaap"],
                                     "room_mode": "hoofd", "outside_temp_sensor": "sensor.tuin_buitentemperatuur",
                                     "return_temp_sensor": "sensor.warmtepomp_retour_temp"}))
    assert r["step_id"] == "pomp" and "flow_rate_sensors" in keys(r)
    r = G.run(flow.async_step_pomp({"compressor_freq_sensor": "sensor.warmtepomp_compressor_frequentie",
                                    "flow_rate_sensors": ["sensor.belimo_flow_rate", "sensor.belimo2"]}))
    assert r["step_id"] == "aansturing"
    r = G.run(flow.async_step_aansturing({"target_setpoint_entity": "number.warmtepomp_setpoint", "heatpump_switch": "switch.warmtepomp_schakelaar"}))
    assert r["step_id"] == "extras" and "extra_tapwater" in keys(r)
    r = G.run(flow.async_step_extras({"extra_weer_prijs": True, "extra_meldingen": True}))
    assert r["step_id"] == "weer_prijs"
    r = G.run(flow.async_step_weer_prijs({"weather_entity": "weather.home"}))
    assert r["step_id"] == "meldingen"
    r = G.run(flow.async_step_meldingen({"notify_services": ["notify.mobile_app_pixel"]}))
    assert r["type"] == "create_entry"
    d = r["data"]
    assert d["setpoint_step"] == 0.5 and d["pump_profile"] == "algemeen" and d["pump_source"] == "localtuya"
    assert d["flow_rate_sensors"] == ["sensor.belimo_flow_rate", "sensor.belimo2"] and d["extra_room_sensors"] == ["sensor.slaap"]
    assert d["weather_entity"] == "weather.home" and d["notify_services"] == ["notify.mobile_app_pixel"]
    assert "dhw_temp_sensor" not in d and not any(k.startswith("extra_") and k != "extra_room_sensors" for k in d)
    assert all(v not in (None, "", []) for v in d.values())


def test_wizard_without_extras_finishes_right_after_the_extras_screen():
    flow, _ = make_flow(STATES)
    G.run(flow.async_step_user({"control_mode": "retour", "setpoint_step": "1.0", "pump_profile": "alsavo", "pump_source_filter": True}))
    G.run(flow.async_step_basis({"room_temp_sensor": "sensor.r", "room_mode": "hoofd", "outside_temp_sensor": "sensor.o"}))
    G.run(flow.async_step_pomp({})); G.run(flow.async_step_aansturing({}))
    r = G.run(flow.async_step_extras({}))
    assert r["type"] == "create_entry" and r["data"]["room_temp_sensor"] == "sensor.r" and r["data"]["setpoint_step"] == 1.0


def test_wizard_prefills_suggestions_from_unit_and_name():
    flow, _ = make_flow(STATES)
    G.run(flow.async_step_user({"control_mode": "retour", "setpoint_step": "1.0", "pump_profile": "alsavo", "pump_source": "localtuya", "pump_source_filter": True}))
    basis = keys(G.run(flow.async_step_basis()))
    assert basis["room_temp_sensor"].kw.get("default") == "sensor.woonkamer_temperatuur"
    assert basis["outside_temp_sensor"].kw.get("default") == "sensor.tuin_buitentemperatuur"
    assert basis["return_temp_sensor"].description["suggested_value"] == "sensor.warmtepomp_retour_temp"
    assert basis["flow_temp_sensor"].description["suggested_value"] == "sensor.warmtepomp_aanvoer_temp"
    pomp = keys(G.run(flow.async_step_pomp()))
    assert pomp["compressor_freq_sensor"].description["suggested_value"] == "sensor.warmtepomp_compressor_frequentie"
    assert pomp["flow_rate_sensors"].description["suggested_value"] == ["sensor.belimo_flow_rate"]
    aans = keys(G.run(flow.async_step_aansturing()))
    assert aans["target_setpoint_entity"].description["suggested_value"] == "number.warmtepomp_setpoint"
    assert aans["heatpump_switch"].description["suggested_value"] == "switch.warmtepomp_schakelaar"


def test_meldingen_screen_is_skipped_when_there_is_no_notify_service():
    flow, h = make_flow(STATES)
    h.services.async_services = lambda: {"notify": {"persistent_notification": object()}}
    G.run(flow.async_step_user({"control_mode": "retour", "setpoint_step": "1.0", "pump_profile": "alsavo", "pump_source_filter": True}))
    G.run(flow.async_step_basis({"room_temp_sensor": "sensor.r", "room_mode": "hoofd", "outside_temp_sensor": "sensor.o"}))
    G.run(flow.async_step_pomp({})); G.run(flow.async_step_aansturing({}))
    assert G.run(flow.async_step_extras({"extra_meldingen": True}))["type"] == "create_entry"


def test_reconfigure_starts_from_current_values_and_removes_unticked_parts():
    entry = types.SimpleNamespace(data={"room_temp_sensor": "sensor.r", "outside_temp_sensor": "sensor.o", "setpoint_step": 1.0,
                                        "control_mode": "retour", "dhw_temp_sensor": "sensor.tank", "dhw_switch": "switch.dhw",
                                        "flow_rate_sensors": ["sensor.f1", "sensor.f2"]}, options={})
    flow, _ = make_flow(STATES, entry)
    r = G.run(flow.async_step_reconfigure())
    assert r["step_id"] == "user" and keys(r)["control_mode"].kw["default"] == "retour" and keys(r)["setpoint_step"].kw["default"] == "1.0"
    G.run(flow.async_step_user({"control_mode": "aanvoer", "setpoint_step": "1.0", "pump_profile": "alsavo", "pump_source_filter": True}))
    basis = keys(G.run(flow.async_step_basis()))
    assert basis["room_temp_sensor"].kw["default"] == "sensor.r"
    G.run(flow.async_step_basis({"room_temp_sensor": "sensor.r", "room_mode": "hoofd", "outside_temp_sensor": "sensor.o"}))
    pomp = keys(G.run(flow.async_step_pomp()))
    assert pomp["flow_rate_sensors"].description["suggested_value"] == ["sensor.f1", "sensor.f2"]      # not re-guessed
    G.run(flow.async_step_pomp({"flow_rate_sensors": ["sensor.f1"]})); G.run(flow.async_step_aansturing({}))
    extras = keys(G.run(flow.async_step_extras()))
    assert extras["extra_tapwater"].kw["default"] is True and extras["extra_weer_prijs"].kw["default"] is False
    r = G.run(flow.async_step_extras({"extra_tapwater": False}))                                       # untick hot water
    assert r["type"] == "abort" and r["reason"] == "reconfigure_successful"
    assert "dhw_temp_sensor" not in flow.updated and "dhw_switch" not in flow.updated
    assert flow.updated["control_mode"] == "aanvoer" and flow.updated["flow_rate_sensors"] == ["sensor.f1"]


def test_pump_profile_sets_the_starting_values_of_a_new_installation():
    def settings(profile):
        cfg = {**G.CONFIG}
        if profile:
            cfg["pump_profile"] = profile
        h, entry = G.make_hass(cfg)
        G.run(importlib.import_module(G.PKG).async_setup_entry(h, entry))
        return entry.runtime_data.settings
    assert settings("algemeen")["pomp_start_verschil"] == 3.5 and settings("algemeen")["pomp_min_vermogen"] == 100.0
    assert settings("alsavo")["pomp_start_verschil"] == 2.8 and settings(None)["pomp_start_verschil"] == 2.8


# ---------------------------------------------------------------- translations
import json  # noqa: E402

TR = Path(__file__).parent.parent / "custom_components" / "slimme_warmtepomp" / "translations"


def _shape(node):
    return {k: _shape(v) for k, v in node.items()} if isinstance(node, dict) else None


def test_dutch_and_english_translations_have_the_same_structure_and_no_empty_text():
    nl, en = (json.loads((TR / f"{lang}.json").read_text()) for lang in ("nl", "en"))
    assert _shape(nl) == _shape(en)

    def texts(node):
        for v in node.values():
            if isinstance(v, dict):
                yield from texts(v)
            else:
                yield v
    assert all(isinstance(t, str) and t.strip() for t in texts(nl)) and all(isinstance(t, str) and t.strip() for t in texts(en))


@pytest.mark.parametrize("lang", ["nl", "en"])
def test_every_wizard_field_has_a_label_and_every_label_belongs_to_a_field(lang):
    tr = json.loads((TR / f"{lang}.json").read_text())["config"]["step"]
    flow, _ = make_flow(STATES)
    flow._data = {"pump_source": "localtuya", "pump_source_filter": True}
    for step in ("user", "basis", "pomp", "aansturing", "extras", "weer_prijs", "zon_net", "ramen", "aanwezigheid", "tapwater", "meldingen"):
        form = G.run(getattr(flow, f"async_step_{step}")())
        fields = set(keys(form))
        labelled = set(tr[step]["data"])
        assert fields == labelled, (step, fields ^ labelled)
        assert set(tr[step].get("data_description", {})) <= labelled, step
        assert tr[step]["title"]


@pytest.mark.parametrize("lang", ["nl", "en"])
def test_selector_options_and_repair_issues_are_translated(lang):
    tr = json.loads((TR / f"{lang}.json").read_text())
    mod = importlib.import_module(G.PKG + ".config_flow")
    for key, options in {"control_mode": ["retour", "aanvoer"], "setpoint_step": ["0.5", "1.0"],
                         "pump_profile": list(mod.PROFILES), "room_mode": list(mod.ROOM_MODES)}.items():
        assert set(tr["selector"][key]["options"]) == set(options), key
    from pathlib import Path as _P
    src = (_P(G.__file__).parent.parent / "custom_components" / "slimme_warmtepomp" / "engine" / "health.py").read_text()
    for kind in ("unavailable", "stale", "implausible", "outside"):
        assert f'"{kind}"' in src and kind in tr["issues"], kind
        assert tr["issues"][kind]["title"] and tr["issues"][kind]["description"]
    assert {"reset_model", "exporteer", "importeer"} <= set(tr["services"])
