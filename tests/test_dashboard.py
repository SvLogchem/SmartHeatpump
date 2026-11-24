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
    return states


def _run(states, mini=False):
    out = subprocess.run([NODE, str(CHECK), str(JS)], input=json.dumps({"states": states, "mini": mini}),
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
