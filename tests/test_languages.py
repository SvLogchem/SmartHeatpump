"""Entity names follow the language of Home Assistant; entity ids and unique ids never change."""
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import test_ha_glue as G                      # noqa: E402  (sets up the Home Assistant stubs)

FULL = {**G.CONFIG, "extra_room_sensors": ["sensor.x"], "notify_services": ["notify.a"], "open_sensors": ["binary_sensor.w"],
        "presence_entities": ["person.a"], "grid_power_sensor": "sensor.grid"}


def entities(language=None):
    h, entry = G.make_hass(FULL)
    if language:
        h.config.language = language
    G.run(importlib.import_module(G.PKG).async_setup_entry(h, entry))
    return h, [(e.entity_id, e._attr_unique_id, e._attr_name) for _, e in h.entities]


def test_every_entity_name_has_an_english_translation():
    from engine.names_en import NAMES_EN
    _, ents = entities()
    missing = sorted({n for _, _, n in ents if n not in NAMES_EN})
    assert not missing, missing
    assert len(set(NAMES_EN.values())) == len(NAMES_EN)              # no two entities with the same English name
    assert all(en.startswith(("Smart HP", "Smart Control")) for en in NAMES_EN.values())


@pytest.mark.parametrize("language", ["en", "en-GB", "de", "fr"])
def test_other_languages_get_english_names_but_the_same_ids(language):
    _, dutch = entities("nl")
    _, other = entities(language)
    assert [(a, b) for a, b, _ in dutch] == [(a, b) for a, b, _ in other]
    assert all(n.startswith(("Smart HP", "Smart Control")) for _, _, n in other)
    assert all(n.startswith(("Slimme WP", "Slimme Regeling")) for _, _, n in dutch)


@pytest.mark.parametrize("language", [None, "nl", "nl-BE"])
def test_dutch_stays_dutch(language):
    _, ents = entities(language)
    assert all(n.startswith(("Slimme WP", "Slimme Regeling")) for _, _, n in ents)


def test_entity_ids_keep_the_v1_pattern_in_english_too():
    _, ents = entities("en")
    ids = {a for a, _, _ in ents}
    for expected in ("sensor.slimme_wp_setpoint", "switch.slimme_wp_regeling_actief", "climate.slimme_wp_thermostaat",
                     "number.slimme_wp_setpoint_dag", "sensor.slimme_wp_weekrapport"):
        assert expected in ids, expected


def test_english_device_name():
    h, _ = entities("en")
    dev = [e for _, e in h.entities][0].device_info
    assert dev["name"] == "Smart Heat Pump"
    h2, _ = entities("nl")
    assert [e for _, e in h2.entities][0].device_info["name"] == "Slimme Warmtepomp"
