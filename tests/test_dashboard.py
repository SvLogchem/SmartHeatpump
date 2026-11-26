"""The shipped dashboard strategy (frontend/slimme-warmtepomp-strategy.js) is run with Node against a fake hass."""
import importlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import test_ha_glue as G                      # noqa: E402  (sets up the Home Assistant stubs)

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "custom_components" / "slimme_warmtepomp" / "frontend" / "slimme-warmtepomp-strategy.js"
CHECK = Path(__file__).parent / "dashboard_check.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def _states(config=None):
    h, entry = G.make_hass(config) if config else G.make_hass()
    G.run(importlib.import_module(G.PKG).async_setup_entry(h, entry))
    coordinator = entry.runtime_data
    states = {e.entity_id: {"state": "1", "attributes": {}} for _, e in h.entities}
    for eid in list(h.states.d):
        states[eid] = {"state": "1", "attributes": {}}
    states["sensor.slimme_wp_setpoint"]["attributes"] = {"invoer_sensoren": coordinator.input_entities()}
    for role, eid in coordinator.input_entities().items():           # the user's own sensors exist in Home Assistant too
        states.setdefault(eid, {"state": "1", "attributes": {}})
    return states


def _run(states, mini=False, language=None):
    out = subprocess.run([NODE, str(CHECK), str(JS)], input=json.dumps({"states": states, "mini": mini, "language": language}),
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_dashboard_has_all_views_and_no_dangling_entities():
    r = _run(_states())
    assert [v["path"] for v in r["views"]] == ["slimme-overzicht", "slimme-leren", "slimme-instellingen", "warmtepomp", "kosten-analyse"]
    assert r["missing"] == [], r["missing"]
    assert r["strategies"] == ["slimme-warmtepomp"] and "ll-strategy-dashboard-slimme-warmtepomp" in r["element"]
    assert all(v["cards"] > 10 for v in r["views"])


def test_dashboard_uses_the_users_own_sensors():
    states = _states()
    r = _run(states)
    for own in ("sensor.room", "sensor.ret", "sensor.flow", "sensor.freq", "number.wp_target", "switch.wp"):
        assert own in r["cfg_entities"], own


def test_dashboard_lists_every_setting_exactly_once():
    from engine.settings import NUMBER_SPECS
    r = _run(_states())
    keys = [s[0] for s in NUMBER_SPECS]
    assert sorted(r["settings"]) == sorted(keys), set(keys) ^ set(r["settings"])
    assert len(r["settings"]) == len(set(r["settings"]))
    assert not r["overig"]                            # nothing falls into "Overig" while the list is complete


def test_unknown_new_setting_shows_up_under_overig():
    states = _states()
    states["number.slimme_wp_nieuwe_instelling"] = {"state": "1", "attributes": {}}
    r = _run(states)
    assert r["overig"] and "number.slimme_wp_nieuwe_instelling" in r["cfg_entities"]


def test_optional_parts_disappear_when_not_configured():
    states = _states()
    for eid in [e for e in states if "dhw" in e or e.endswith("tapwater_modus")]:
        states.pop(eid)
    r = _run(states)
    assert r["missing"] == []
    assert not any("dhw" in e for e in r["cfg_entities"])


def test_graphs_use_mini_graph_card_only_when_installed():
    assert not _run(_states(), mini=False)["text_has_mini"]
    assert _run(_states(), mini=True)["text_has_mini"]
    assert _run(_states(), mini=False)["text_has_history"]


def test_every_number_is_in_the_javascript_catalog_text():
    src = JS.read_text()
    from engine.settings import NUMBER_SPECS
    for key, *_ in NUMBER_SPECS:
        assert re.search(rf'\["{key}",\s*"', src), key


def _config_with_rooms(extra_rooms, flows):
    cfg = dict(G.CONFIG)
    cfg["extra_room_sensors"] = extra_rooms
    cfg["flow_rate_sensors"] = flows
    return cfg


def test_extra_rooms_and_any_number_of_flow_sensors_show_up():
    states = _states(_config_with_rooms(["sensor.slaapkamer", "sensor.werkkamer"], ["sensor.f1", "sensor.f2", "sensor.f3"]))
    r = _run(states)
    for own in ("sensor.slaapkamer", "sensor.werkkamer", "sensor.f1", "sensor.f2", "sensor.f3"):
        assert own in r["cfg_entities"], own
    assert "Ruimtes" in r["names"] and "Flow 3" in r["names"] and "Kamer 3" in r["names"]
    assert r["missing"] == [], r["missing"]
    # without extra rooms there is no rooms card
    assert "Ruimtes" not in _run(_states())["names"]


def test_weekly_report_and_new_settings_are_on_the_dashboard():
    r = _run(_states())
    assert "Weekrapport" in r["names"] and "sensor.slimme_wp_weekrapport" in r["cfg_entities"]
    cfg = _config_with_rooms(["sensor.slaapkamer"], ["sensor.f1"])
    cfg["notify_services"] = ["notify.mobile_app_pixel"]
    r = _run(_states(cfg))
    assert "Meerdere ruimtes" in r["names"] and "Meldingen" in r["names"]
    assert "switch.slimme_wp_weekrapport_actief" in r["cfg_entities"] and "number.slimme_wp_min_extra_kamer" in r["cfg_entities"]
    assert "number.slimme_wp_melding_te_koud_uren" in r["cfg_entities"]


def test_every_dashboard_text_has_an_english_version():
    states = _states(_config_with_rooms(["sensor.slaapkamer"], ["sensor.f1", "sensor.f2"]))
    cfg = _config_with_rooms(["sensor.slaapkamer"], ["sensor.f1", "sensor.f2"])
    cfg["notify_services"] = ["notify.mobile_app_pixel"]
    r = _run(_states(cfg))
    assert r["untranslated"] == [], r["untranslated"]


def test_dashboard_follows_the_review_points():
    r = _run(_states())
    # the status is "bezig" (the switch is "actief"); reason and plan are in the header, not repeated as tiles
    assert "Vorstbeveiliging bezig" in r["names"] and "Vorstbeveiliging actief" not in r["names"]
    assert "sensor.slimme_wp_reden" not in r["cfg_entities"] and "sensor.slimme_wp_plan" not in r["cfg_entities"]
    # statistics graphs use the "yesterday" sensors (a fixed value per day), not the running value
    assert "sensor.slimme_wp_cop_gisteren" in r["cfg_entities"] and "sensor.slimme_wp_kwh_per_graaddag_gisteren" in r["cfg_entities"]
    # thermal energy next to the costs: tiles for today / week / month and a graph per day
    for eid in ("sensor.slimme_wp_thermisch_dag", "sensor.slimme_wp_thermisch_week", "sensor.slimme_wp_thermisch_maand"):
        assert eid in r["cfg_entities"], eid
    # new status and hot water parts
    for eid in ("binary_sensor.slimme_wp_bivalent", "binary_sensor.slimme_wp_dhw_bezig", "sensor.slimme_wp_graaddagen_week"):
        assert eid in r["cfg_entities"], eid
    assert "Tapwater" in r["names"] and "Cyclus bezig" in r["names"]
    md = "\n".join(r["markdown"])
    assert "tapwater_wacht_tot" in md and "tapwater_laatste_timeout" in md
    with_rooms = _run(_states(_config_with_rooms(["sensor.slaapkamer"], ["sensor.f1"])))     # the rooms card needs extra rooms
    assert any("hoofdsensor_weg" in m for m in with_rooms["markdown"])
    assert "is not none" in md                                       # the header never shows "None"
    # relearning asks for confirmation
    assert {"entity": "button.slimme_wp_opnieuw_aanleren", "confirmation": True} in r["buttons"]
    # a correction is a difference: kelvin
    assert "stooklijn_correctie') }} K." in md and "stooklijn_handmatig') }} K (" in md


def test_hot_water_block_disappears_without_hot_water():
    states = _states()
    for eid in [e for e in states if "dhw" in e or e.endswith("tapwater_modus")]:
        states.pop(eid)
    r = _run(states)
    assert "Cyclus bezig" not in r["names"] and r["missing"] == []


def _strict_render(template, attributes):
    """Render like Home Assistant does: a missing key or attribute is an error, not an empty value."""
    jinja2 = pytest.importorskip("jinja2")
    import datetime
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.globals.update(
        state_attr=lambda entity, name: attributes.get((entity, name)), states=lambda entity: "x", now=datetime.datetime.now,
        as_timestamp=lambda v: datetime.datetime.fromisoformat(v).timestamp() if isinstance(v, str) else v.timestamp())
    env.filters["timestamp_custom"] = lambda ts, fmt="%d-%m %H:%M": datetime.datetime.fromtimestamp(ts).strftime(fmt)
    return env.from_string(template).render().strip()


def test_rooms_and_hot_water_texts_survive_missing_keys():
    S = "sensor.slimme_wp_setpoint"
    r = _run(_states(_config_with_rooms(["sensor.slaapkamer"], ["sensor.f1"])))
    rooms = next(m for m in r["markdown"] if "hoofdsensor_weg" in m)
    # exactly what rooms.combine() delivers: "tekort_bewaakt" only in mode "hoofd", "reden" only when the main sensor is gone
    for k in ({"modus": "hoofd", "hoofd": 20.1, "extra": {"a": 16.0}, "gebruikt": 20.1, "tekort_bewaakt": 1.0},
              {"modus": "hoofd", "hoofd": 20.1, "extra": {"a": 19.0}, "gebruikt": 20.1, "tekort_bewaakt": 0.0},
              {"modus": "gemiddelde", "hoofd": 20.1, "extra": {"a": 18.0}, "gebruikt": 19.05},
              {"modus": "koudste", "hoofd": 20.1, "extra": {"a": 18.0}, "gebruikt": 18.0}):
        assert "°C" in _strict_render(rooms, {(S, "kamers"): k})
    assert "ontbreekt" in _strict_render(rooms, {(S, "kamers"): {"modus": "hoofd", "hoofd": None, "extra": {}, "gebruikt": None,
                                                                 "reden": "hoofdsensor_weg"}})
    assert _strict_render(rooms, {}) == ""                                              # no rooms information at all: nothing to show
    dhw = next(m for m in r["markdown"] if "tapwater_wacht_tot" in m)
    assert _strict_render(dhw, {})                                                      # nothing waiting, no time-out
    import datetime
    later = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3)).isoformat()
    timeout = {"mode": "legionella", "at": later, "tank": 49.5, "target": 60.0}
    assert "tot" in _strict_render(dhw, {(S, "tapwater_wacht_tot"): later, (S, "tapwater_laatste_timeout"): timeout})


DUTCH_WORDS = re.compile(r"\b(de|het|een|niet|nog|van|voor|bij|als|dat|wordt|geen|nu|vloer|buiten|kamer|gemeten|geleerd|tijd|uit|aan)\b", re.I)


def test_english_dashboard_has_no_dutch_texts_left():
    states = _states(_config_with_rooms(["sensor.slaapkamer"], ["sensor.f1", "sensor.f2"]))
    nl, en = _run(states, language="nl"), _run(states, language="en-GB")
    assert en["views"][0]["title"] == "Smart HP Overview" and nl["views"][0]["title"] == "Slimme WP Overzicht"
    assert [v["path"] for v in en["views"]] == [v["path"] for v in nl["views"]]          # same URLs in both languages
    assert en["cfg_entities"] == nl["cfg_entities"]                                      # same entities
    left = [x for x in en["names"] if DUTCH_WORDS.search(x)]
    assert not left, left
    for md in en["markdown"]:
        visible = re.sub(r"\{%.*?%\}|\{\{.*?\}\}", " ", md, flags=re.S)
        assert not DUTCH_WORDS.search(visible), visible
    assert any("Setpoint - return difference" in md for md in en["markdown"])
    assert any("setpoint - retour" in md for md in nl["markdown"])
