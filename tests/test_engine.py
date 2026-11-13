"""Unit tests for the pure-Python engine."""
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from engine.controller import Inputs, SmartController
from engine.dhw import DhwController
from engine.model import HouseModel
from engine.planner import PlanInput, plan
from engine.prices import PriceCurve, PriceStats, parse_price_forecast, weight_for
from engine.regression import RidgeEW
from engine.settings import DEFAULTS
from engine.solar import solar_elevation

TZ = ZoneInfo("Europe/Amsterdam")


def test_ridge_recovers_parameters_and_respects_prior():
    r = RidgeEW([0.0, 0.0], [1e-3, 1e-3], [-10, -10], [10, 10], forget=1.0)
    rng = random.Random(0)
    for _ in range(500):
        x = [rng.uniform(-3, 3), rng.uniform(-3, 3)]
        r.update(x, 2.0 * x[0] - 0.5 * x[1] + rng.gauss(0, 0.05))
    a, b = r.solve()
    assert a == pytest.approx(2.0, abs=0.05) and b == pytest.approx(-0.5, abs=0.05)
    # without data the prior is returned
    empty = RidgeEW([1.5, 2.5], [1.0, 1.0], [0, 0], [9, 9])
    assert empty.solve() == [1.5, 2.5]


def test_ridge_bounds_and_roundtrip():
    r = RidgeEW([0.5], [0.1], [0.0], [1.0])
    for _ in range(50):
        r.update([1.0], 7.0)
    assert r.solve()[0] == 1.0
    r2 = RidgeEW([0.5], [0.1], [0.0], [1.0])
    r2.from_dict(r.to_dict())
    assert r2.solve() == r.solve()


def test_solar_elevation_amsterdam():
    noon = datetime(2026, 11, 12, 11, 30, tzinfo=timezone.utc)
    assert 15 < solar_elevation(noon, 52.37, 4.9) < 22
    assert solar_elevation(datetime(2026, 11, 12, 0, 0, tzinfo=timezone.utc), 52.37, 4.9) < 0
    summer = datetime(2026, 6, 21, 11, 0, tzinfo=timezone.utc)
    assert 55 < solar_elevation(summer, 52.37, 4.9) < 63


def test_price_parsing_common_formats():
    now = datetime(2026, 11, 12, 15, 0, tzinfo=TZ)
    nordpool = {"raw_today": [{"start": "2026-11-12T15:00:00+01:00", "end": "2026-11-12T16:00:00+01:00", "value": 0.2}],
                "raw_tomorrow": [{"start": "2026-11-13T00:00:00+01:00", "end": "2026-11-13T01:00:00+01:00", "value": 0.1}]}
    frank = {"prices": [{"from": "2026-11-12T16:00:00+01:00", "till": "2026-11-12T17:00:00+01:00", "price": 0.3}]}
    epex = {"data": [{"start_time": "2026-11-12T17:00:00+01:00", "end_time": "x", "price_per_kwh": 0.25}]}
    entsoe = {"prices_today": [{"time": "2026-11-12 18:00:00+01:00", "price": 0.4}]}
    flat = {"today": [0.1] * 24, "tomorrow": [0.2] * 24}
    assert [p for _, p in parse_price_forecast(nordpool, now)] == [0.2, 0.1]
    assert parse_price_forecast(frank, now)[0][1] == 0.3
    assert parse_price_forecast(epex, now)[0][1] == 0.25
    assert parse_price_forecast(entsoe, now)[0][1] == 0.4
    slots = parse_price_forecast(flat, now)
    assert len(slots) == 48 and slots[0][0].hour == 0 and slots[24][1] == 0.2
    assert parse_price_forecast({"junk": [1, "a"], "x": "y"}, now) == []


def test_price_weights():
    assert weight_for(0.2, 0.2) == 1.0
    assert weight_for(0.5, 0.2) > 2.0
    assert weight_for(-0.1, 0.2) == 0.2 or weight_for(-0.1, 0.2) < 0.5
    assert weight_for(None, 0.2) == 1.0
    now = datetime(2026, 11, 12, 0, 0, tzinfo=TZ)
    c = PriceCurve([(now + timedelta(hours=i), 0.1 if i < 12 else 0.3) for i in range(24)], None)
    assert c.weight(now + timedelta(hours=2)) < c.weight(now + timedelta(hours=14))
    assert not c.covers(now + timedelta(hours=30))
    stats = PriceStats()
    for i in range(20):
        stats.add(i * 1000.0, 0.2)
    assert stats.reference() == 0.2


def test_dhw_cycle():
    s = {**DEFAULTS}
    d = DhwController()
    t = datetime(2026, 11, 12, 6, 0, tzinfo=TZ)
    assert d.step(t, 45.0, s, 1.0, False, True).request is None          # warm enough, nothing to do
    r = d.step(t, 38.0, s, 1.0, False, True)                              # below minimum
    assert r.request is True and r.mode == "normal" and r.setpoint == s["dhw_doel_temp"]
    assert d.step(t + timedelta(minutes=30), 47.0, s, 1.0, False, True).request is True
    r = d.step(t + timedelta(minutes=45), 50.5, s, 1.0, False, True)
    assert r.request is False and not r.active
    # opportunistic top-up only when cheap
    assert d.step(t + timedelta(hours=1), 43.0, s, 1.5, False, True).request is None
    assert d.step(t + timedelta(hours=1), 43.0, s, 0.5, False, True).mode == "topup"
    d.step(t + timedelta(hours=2), 50.0, s, 1.0, False, True)
    # legionella after the interval
    later = t + timedelta(days=7, hours=1)
    r = d.step(later, 50.0, s, 1.0, False, True)
    assert r.mode == "legionella" and r.setpoint == s["dhw_legionella_temp"]
    assert d.step(later + timedelta(minutes=50), 60.5, s, 1.0, False, True).request is False
    assert d.last_legionella == later + timedelta(minutes=50)
    # runaway protection
    d.step(later + timedelta(hours=2), 30.0, s, 1.0, False, True)
    r = d.step(later + timedelta(hours=5), 31.0, s, 1.0, False, True)
    assert r.request is False and d.timeouts == 1
    # disabled stops a running cycle
    d.step(later + timedelta(hours=6), 30.0, s, 1.0, False, True)
    assert d.step(later + timedelta(hours=6, minutes=5), 31.0, s, 1.0, False, False).request is False


def _plan_input(model, to_fn, now, tr, f, bedtime=True):
    sp = lambda t: 21.0  # noqa: E731
    return PlanInput(
        now=now, tr=tr, f=f, model=model, to_fn=to_fn, sun_fn=lambda t: 0.0, sp_fn=sp,
        price_fn=lambda t: 1.0,
        s_base_fn=lambda t, to, sun, spv: model.floor_equilibrium(spv, to, sun),
        w_offset=3.5, s_min=20.0, s_max=40.0,
        bedtime=now.replace(hour=21, minute=0) if bedtime else None,
        quiet_fn=lambda t: t.hour >= 21 or t.hour < 7, quiet_boost=1.5, tol_low=0.3, tol_high=0.5,
        d_max=4.0, bias=0.0, hard_min_room=16.0)


def test_planner_precharges_before_bedtime_when_evening_turns_cold():
    m = HouseModel()
    now = datetime(2026, 11, 12, 15, 0, tzinfo=TZ)
    # floor in equilibrium for 8 degrees, but the evening drops to -4: a reactive controller would fall behind
    cold = lambda t: 8.0 - 12.0 * min(1.0, max(0.0, (t - now).total_seconds() / (7 * 3600)))  # noqa: E731
    f_eq = m.floor_equilibrium(21.0, 8.0, 0.0)
    res = plan(_plan_input(m, cold, now, 21.0, f_eq))
    assert res.kind == "voorverwarmen" and res.delta >= 1
    assert res.start is not None and res.start < now.replace(hour=21)
    # same house in a mild, stable evening: no extra heat needed
    mild = plan(_plan_input(m, lambda t: 8.0, now, 21.0, f_eq))
    assert mild.kind != "voorverwarmen"


def test_planner_never_boosts_inside_quiet_hours_beyond_cap():
    m = HouseModel()
    now = datetime(2026, 11, 12, 22, 0, tzinfo=TZ)
    res = plan(_plan_input(m, lambda t: -5.0, now, 19.8, 24.0, bedtime=False))
    assert res.delta_now <= 4.0
    assert all(isinstance(x[1], float) for x in res.trajectory)


def _inp(now, **kw):
    base = dict(now=now, room=20.5, outside=5.0, flow=30.0, ret=27.0, freq=0.0, switch_state="on",
                target_current=28.0, settings={})
    base.update(kw)
    return Inputs(**base)


def test_controller_holds_when_sensors_missing():
    c = SmartController()
    d = c.step(_inp(datetime(2026, 11, 12, 12, 0, tzinfo=TZ), room=None))
    assert d.sensor_problem and d.setpoint is None and d.switch is None


def test_controller_uses_local_time_for_night_program():
    c = SmartController()
    # 23:30 local = 22:30 UTC. v1 used the UTC hour and would still have been on "Dag".
    d = c.step(_inp(datetime(2026, 11, 12, 23, 30, tzinfo=TZ)))
    assert d.program == "Nacht" and d.room_setpoint == pytest.approx(DEFAULTS["setpoint_nacht"])
    d = c.step(_inp(datetime(2026, 11, 13, 12, 0, tzinfo=TZ)))
    assert d.program == "Dag"


def test_manual_preset_reverts_at_next_program_change():
    c = SmartController()
    t = datetime(2026, 11, 12, 20, 0, tzinfo=TZ)
    d = c.step(_inp(t, preset="Handmatig", manual_temp=22.0))
    assert d.room_setpoint == 22.0 and not d.revert_manual
    d = c.step(_inp(t + timedelta(hours=4), preset="Handmatig", manual_temp=22.0))  # 00:00 -> night
    assert d.revert_manual


def test_summer_mode_has_hysteresis_and_switches_off():
    c = SmartController()
    t = datetime(2026, 5, 20, 12, 0, tzinfo=TZ)
    d = c.step(_inp(t, outside=22.0, room=22.0))
    assert d.summer
    t += timedelta(hours=1)
    d = c.step(_inp(t, outside=22.0, room=22.0))
    assert d.switch == "off"
    # a single cool reading does not flip it back (24h mean + 1K hysteresis)
    d = c.step(_inp(t + timedelta(minutes=10), outside=17.5, room=21.0, switch_state="off"))
    assert d.summer


def test_hvac_off_turns_switch_off_only_when_regeling_active():
    c = SmartController()
    t = datetime(2026, 11, 12, 12, 0, tzinfo=TZ)
    assert c.step(_inp(t, hvac_on=False)).switch == "off"
    assert c.step(_inp(t + timedelta(minutes=2), hvac_on=False, regeling_actief=False)).switch is None


def test_compressor_guard_blocks_early_switch_off_and_on():
    c = SmartController()
    t = datetime(2026, 11, 12, 12, 0, tzinfo=TZ)
    # overshoot: pump should stop, but it has only just been observed running
    assert c.step(_inp(t, room=22.5, switch_state="on")).switch is None
    assert c.step(_inp(t + timedelta(minutes=16), room=22.5, switch_state="on")).switch == "off"
    # now it is cold, but the stand-still time (10 min) has not passed
    t2 = t + timedelta(minutes=18)
    assert c.step(_inp(t2, room=19.0, switch_state="off")).switch is None
    assert c.step(_inp(t2 + timedelta(minutes=12), room=19.0, switch_state="off")).switch == "on"


def test_dither_quantiser_averages_to_raw_value():
    c = SmartController()
    now = datetime(2026, 11, 12, 12, 0, tzinfo=TZ)
    cur, outs = 27.0, []
    for i in range(96):                       # 8 hours of 5-minute steps, raw = 27.3
        now += timedelta(minutes=5)
        cur = c._quantize(27.3, 1.0, cur, 5 / 60, now)
        outs.append(cur)
    assert set(outs) <= {27.0, 28.0}
    assert sum(outs) / len(outs) == pytest.approx(27.3, abs=0.12)


def test_state_roundtrip():
    c = SmartController()
    c.model.learn_room(-0.1, 3.0, 15.0, 0.1)
    c.tracker.bias = 1.0
    c.dhw.last_legionella = datetime(2026, 11, 1, tzinfo=TZ)
    c2 = SmartController()
    c2.import_state(c.export_state())
    assert c2.model.params == c.model.params and c2.tracker.bias == 1.0
    assert c2.dhw.last_legionella == c.dhw.last_legionella
    c2.import_state({"model": "garbage"})  # must not raise


def test_shadow_mode_calculates_everything_but_sends_nothing():
    c = SmartController()
    t = datetime(2026, 11, 12, 12, 0, tzinfo=TZ)
    d = c.step(_inp(t, room=22.8, switch_state="on", regeling_actief=False))
    assert d.shadow and d.setpoint is not None and d.reason != "regeling_uit"
    assert d.switch is None and d.dhw_request is None
    # same inputs with the controller active: the calculation is identical
    d2 = SmartController().step(_inp(t, room=22.8, switch_state="on"))
    assert d2.setpoint == d.setpoint and not d2.shadow


def test_default_compressor_threshold_matches_v1():
    assert DEFAULTS["min_freq"] == 2.0


# ---------------------------------------------------------------- v2.1 features
def _t(minutes=0):
    return datetime(2026, 11, 12, 14, 0, tzinfo=TZ) + timedelta(minutes=minutes)


def test_open_window_pauses_heating_after_delay_but_not_in_emergency():
    c = SmartController()
    c.step(_inp(_t(-90), room=20.9))                                        # compressor guard: running for a while already
    d = c.step(_inp(_t(0), room=20.9, windows_open=True))
    assert not d.window_open and d.reason != "raam_open"                    # delay not over yet
    d = c.step(_inp(_t(10), room=20.9, windows_open=True))
    assert d.window_open and d.coasting and d.reason == "raam_open"
    d = c.step(_inp(_t(12), room=15.0, windows_open=True))                  # below minimum room temperature
    assert not d.coasting
    d = c.step(_inp(_t(14), room=20.9, windows_open=False))
    assert not d.window_open


def test_open_window_is_excluded_from_learning():
    c = SmartController()
    for i in range(0, 200, 6):
        c.step(_inp(_t(i), room=20.5, windows_open=True))
    assert c.model.windows_room == 0


def test_away_lowers_setpoint_after_debounce_and_return_time_restores_it():
    c = SmartController()
    d = c.step(_inp(_t(0), away=True))
    assert not d.away and d.room_setpoint == DEFAULTS["setpoint_dag"]       # debounce (30 min)
    d = c.step(_inp(_t(40), away=True))
    assert d.away and d.room_setpoint == DEFAULTS["afwezig_setpoint"]
    ret = _t(40 + 24 * 60)
    d = c.step(_inp(_t(41), away=True, return_at=_t(41) + timedelta(hours=6)))
    assert d.room_setpoint == DEFAULTS["afwezig_setpoint"]
    d = c.step(_inp(_t(42 + 6 * 60), away=True, return_at=_t(41) + timedelta(hours=6)))
    assert d.room_setpoint == DEFAULTS["setpoint_dag"]                      # return time passed: normal again
    d = c.step(_inp(_t(43 + 6 * 60), away=False))
    assert not d.away
    # an explicit manual choice always wins over away
    c2 = SmartController()
    c2.step(_inp(_t(0), away=True, preset="Handmatig", manual_temp=22.0))
    d = c2.step(_inp(_t(40), away=True, preset="Handmatig", manual_temp=22.0))
    assert d.room_setpoint == 22.0


def test_grid_limiter_needs_sustained_overload_and_releases():
    c = SmartController()
    s = {"netimport_limiet": 3000.0}
    c.step(_inp(_t(-90), room=20.9, settings=s))
    d = c.step(_inp(_t(0), room=20.9, grid_import_w=4500.0, settings=s))
    assert not d.grid_limited
    d = c.step(_inp(_t(3), room=20.9, grid_import_w=4500.0, settings=s))
    assert not d.grid_limited                                               # a short spike (cooking) is ignored
    d = c.step(_inp(_t(7), room=20.9, grid_import_w=4500.0, settings=s))
    assert d.grid_limited and d.coasting and d.reason == "netlimiet"
    d = c.step(_inp(_t(20), room=20.9, grid_import_w=1000.0, settings=s))
    assert not d.grid_limited
    # never longer than 45 minutes, then a 15 minute pause
    c = SmartController()
    c.step(_inp(_t(-90), room=20.9, settings=s))
    for m in (0, 6, 7):
        c.step(_inp(_t(m), room=20.9, grid_import_w=4500.0, settings=s))
    assert c.step(_inp(_t(30), room=20.9, grid_import_w=4500.0, settings=s)).grid_limited
    assert not c.step(_inp(_t(55), room=20.9, grid_import_w=4500.0, settings=s)).grid_limited
    # disabled with limit 0
    assert not SmartController().step(_inp(_t(0), grid_import_w=9e9, settings={"netimport_limiet": 0.0})).grid_limited


def test_daily_cop_and_compressor_starts():
    c = SmartController()
    t = _t(0)
    c.step(_inp(t - timedelta(minutes=10), freq=0.0, power_w=0.0))          # known idle state before the first run
    heating = [(40, 900.0)] * 5 + [(0, 0.0)] * 5          # one run: 10 minutes on at 900 W
    for _ in range(3):                                      # three runs
        for freq, w in heating:
            c.step(_inp(t, freq=freq, power_w=w, flow_lh=900.0, flow=34.0, ret=29.0))
            t += timedelta(minutes=2)
    d = c.step(_inp(t, freq=0.0, power_w=0.0))
    assert d.starts_today == 3
    assert d.cop_today is None or d.cop_today > 1.0        # thermal / electric energy
    nxt = c.step(_inp(t + timedelta(days=1), freq=0.0))
    assert nxt.starts_today == 0 and nxt.starts_yesterday == 3
    c2 = SmartController()
    c2.import_state(c.export_state())
    assert c2.yesterday == c.yesterday and c2.day_key == c.day_key


def test_learned_curve_is_published_only_when_model_is_trusted():
    c = SmartController()
    assert c.step(_inp(_t(0))).diag["geleerde_stooklijn"] is None


# ---------------------------------------------------------------- zacht draaien (modulatie)
def test_modulation_learner_finds_lowest_gap_that_keeps_compressor_running():
    from engine.modulation import ModulationLearner
    m = ModulationLearner()
    for _ in range(12):
        m.observe(0.0, False, 0.0, None)          # gap too small: compressor stops
        m.observe(1.0, True, 18.0, 2.0)
        m.observe(2.0, True, 30.0, 3.5)
        m.observe(4.0, True, 50.0, 5.5)
    assert m.floor() == 1.0
    assert m.freq_at_floor() == 18.0
    m2 = ModulationLearner()
    m2.from_dict(m.to_dict())
    assert m2.floor() == 1.0
    assert ModulationLearner().floor() is None     # nothing learned: never interferes


def test_soft_running_caps_setpoint_just_above_return_when_little_heat_is_needed():
    c = SmartController()
    for _ in range(12):
        c.mod.observe(1.0, True, 18.0, 2.0)
        c.mod.observe(3.0, True, 40.0, 4.0)
    t = _t(0)
    inp = _inp(t, room=21.1, ret=26.0, flow=28.0, freq=30.0, target_current=29.0)
    d = c.step(inp)
    assert not d.coasting
    assert d.soft and d.setpoint_raw <= 26.0 + 1.0 + DEFAULTS["modulatie_marge"] + 0.01
    # room clearly cold: no capping, full heat
    c2 = SmartController()
    for _ in range(12):
        c2.mod.observe(1.0, True, 18.0, 2.0)
    d2 = c2.step(_inp(t, room=19.5, ret=26.0, flow=28.0, freq=30.0, target_current=29.0))
    assert not d2.soft
    # switch off: never capped
    c3 = SmartController()
    for _ in range(12):
        c3.mod.observe(1.0, True, 18.0, 2.0)
    d3 = c3.step(_inp(t, room=21.1, ret=26.0, flow=28.0, freq=30.0, target_current=29.0, modulation_enabled=False))
    assert not d3.soft


def test_modulation_state_survives_restart():
    c = SmartController()
    for _ in range(10):
        c.mod.observe(1.5, True, 20.0, 2.0)
    c2 = SmartController()
    c2.import_state(c.export_state())
    assert c2.mod.floor() == 1.5


# ---------------------------------------------------------------- frequentiegrens
def _fill(c):
    for _ in range(12):
        c.mod.observe(1.0, True, 30.0, 2.0)     # small gap: 30 Hz holds the temperature
        c.mod.observe(3.0, True, 50.0, 4.0)
        c.mod.observe(5.0, True, 80.0, 6.5)     # large gap: boost at 80 Hz


def test_gap_cap_follows_learned_frequency_table():
    from engine.modulation import ModulationLearner
    m = ModulationLearner()
    assert m.gap_cap(50.0) is None                       # nothing learned: no cap
    for _ in range(12):
        m.observe(1.0, True, 30.0, 2.0); m.observe(3.0, True, 50.0, 4.0); m.observe(5.0, True, 80.0, 6.5)
    assert m.gap_cap(50.0) == pytest.approx(3.0 - 0.25)
    assert m.gap_cap(80.0) is None                       # nothing exceeds 80 Hz: no cap needed
    assert m.gap_cap(0.0) is None                        # 0 = off
    assert m.table() == {"+1.0": 30, "+3.0": 50, "+5.0": 80}


def test_frequency_limit_caps_boost_in_quiet_hours_but_not_by_day_or_in_emergency():
    quiet = datetime(2026, 11, 12, 22, 30, tzinfo=TZ)
    day = datetime(2026, 11, 12, 14, 0, tzinfo=TZ)
    kw = dict(room=20.6, ret=24.0, flow=28.0, freq=40.0, target_current=29.0)
    c = SmartController(); _fill(c)
    d = c.step(_inp(quiet, **kw))
    assert d.freq_limited and d.setpoint_raw < 29.0       # held at the house base level, no extra boost
    c = SmartController(); _fill(c)
    d = c.step(_inp(day, **kw))
    assert not d.freq_limited                                # 80 Hz allowed by day
    c = SmartController(); _fill(c)
    d = c.step(_inp(quiet, **dict(kw, room=15.5)))
    assert not d.freq_limited                                # emergency: comfort first
    c = SmartController(); _fill(c)
    d = c.step(_inp(quiet, modulation_enabled=False, **kw))
    assert not d.freq_limited


def test_frequency_table_is_published_for_the_dashboard():
    c = SmartController(); _fill(c)
    d = c.step(_inp(_t(0), room=21.0))
    assert d.diag["frequentie_tabel"]["+5.0"] == 80


def test_setpoint_never_below_pump_minimum_even_when_coasting_with_cold_return():
    # cold floor / summer: return 15 C -> coast used to ask for 14 C, the pump only accepts 20
    for room, ret in ((22.5, 15.0), (21.0, 15.0), (23.0, 17.5)):
        c = SmartController()
        c.step(_inp(_t(-90), room=room, ret=ret, flow=16.0))
        d = c.step(_inp(_t(0), room=room, ret=ret, flow=16.0, outside=22.0))
        assert d.setpoint_raw >= DEFAULTS["min_setpoint"]
        assert d.setpoint is None or d.setpoint >= DEFAULTS["min_setpoint"]
    c = SmartController()
    d = c.step(_inp(_t(0), room=22.5, ret=15.0, settings={"min_setpoint": 24.0}))
    assert d.setpoint_raw >= 24.0


def test_no_absurd_cop_during_and_after_defrost():
    c = SmartController()
    kw = dict(freq=40.0, power_w=900.0, flow_lh=900.0, room=20.8)
    c.step(_inp(_t(-30), flow=34.0, ret=29.0, **kw))
    d = c.step(_inp(_t(0), flow=24.0, ret=29.0, **kw))            # defrost: water runs backwards
    assert d.defrost and d.cop == 0.0 and d.thermal_kw == 0.0
    # defrost is over, but the water is still settling: a 9 K spread would give COP > 10
    d = c.step(_inp(_t(2), flow=38.0, ret=29.0, **kw))
    assert not d.defrost and d.cop == 0.0 and d.thermal_kw == 0.0
    # after the settling time a normal COP is reported again
    d = c.step(_inp(_t(8), flow=34.0, ret=29.0, **kw))
    assert 2.0 < d.cop < 8.0
    # and nothing above the plausible maximum is ever reported
    d = c.step(_inp(_t(30), flow=40.0, ret=29.0, freq=40.0, power_w=300.0, flow_lh=900.0, room=20.8))
    assert d.cop == 0.0


def test_defrost_period_is_not_learned_from():
    c = SmartController()
    for i in range(0, 30, 6):
        c.step(_inp(_t(i), flow=24.0, ret=29.0, freq=40.0, room=20.8))
    assert c.model.windows_room == 0


# ---------------------------------------------------------------- ontdooien leren
def test_defrost_learner_measures_duration_interval_and_recovery():
    from engine.defrost import DefrostLearner
    dl = DefrostLearner()
    t = _t(0)
    for cycle in range(4):
        for _ in range(10):                                   # normal heating, spread 5 K
            dl.update(t, False, 5.0, True); t += timedelta(minutes=1)
        for _ in range(2):                                    # 2 minutes of defrost
            dl.update(t, True, -4.0, True, unit_temp=-3.0); t += timedelta(minutes=1)
        dl.update(t, False, 12.0, True); t += timedelta(minutes=1)   # overshoot, water not settled
        dl.update(t, False, 8.0, True); t += timedelta(minutes=1)
        dl.update(t, False, 5.2, True); t += timedelta(minutes=1)    # settled
    s = dl.summary()
    assert s["aantal"] == 4 and 1.5 <= s["duur_min"] <= 2.5
    assert s["interval_min"] and 12 <= s["interval_min"] <= 16
    assert dl.rec_n == 4 and 1.0 <= dl.recovery <= 3.5
    assert 1.0 <= dl.wait_minutes(3.0) <= 5.0
    assert s["unit_buiten_temp"] == -3.0
    d2 = DefrostLearner(); d2.from_dict(dl.to_dict())
    assert d2.n == 4 and d2.last_start == dl.last_start


def test_defrost_wait_uses_setting_until_enough_is_learned():
    from engine.defrost import DefrostLearner
    assert DefrostLearner().wait_minutes(3.0) == 3.0
    c = SmartController()
    d = c.step(_inp(_t(0), room=20.8))
    assert d.diag["ontdooi_wachttijd_min"] == 3.0
    c2 = SmartController(); c2.import_state(c.export_state())
    assert c2.defl.n == 0


# ---------------------------------------------------------------- voorspelling en ijsvorming
def _cycle_history(dl, start, n=5, every=50):
    t = start
    for _ in range(n):
        for _ in range(every - 3):
            dl.update(t, False, 5.0, True); t += timedelta(minutes=1)
        for _ in range(2):
            dl.update(t, True, -4.0, True); t += timedelta(minutes=1)
        dl.update(t, False, 5.0, True); t += timedelta(minutes=1)
    return t


def test_defrost_prediction_counts_down_to_the_learned_interval():
    from engine.defrost import DefrostLearner
    dl = DefrostLearner()
    assert dl.minutes_until_next(_t(0)) is None                 # nothing learned yet
    end = _cycle_history(dl, _t(0))
    m = dl.minutes_until_next(end)
    assert m is not None and -2.0 <= m <= 50.0
    later = dl.minutes_until_next(end + timedelta(minutes=30))
    assert later == pytest.approx(m - 30, abs=0.2)


def _icing_run(cops_after_defrost, cop_between, *, extra=None, cycles=None):
    """Feed the monitor: per cycle a defrost followed by a post-defrost COP and a steady COP."""
    from engine.defrost import DefrostLearner
    from engine.icing import IcingMonitor
    dl, ic = DefrostLearner(), IcingMonitor()
    t = _t(0)

    def step(cop, **kw):
        nonlocal t
        a = dict(cop=cop, heating=cop > 0, settling=False, defrost=False, unit_diff=None, outside=1.0,
                 freq_running=True, last_end=dl.last_end, last_interval=dl.last_interval,
                 mean_interval=dl.interval, n_defrosts=dl.n, since_last_min=dl.minutes_since_last(t))
        a.update(kw)
        ic.update(t, **a); t += timedelta(minutes=1)

    for post in cops_after_defrost:
        for _ in range(25):
            dl.update(t, False, 5.0, True); step(cop_between)
        for _ in range(2):
            dl.update(t, True, -4.0, True); step(0.0, defrost=True, heating=False, settling=True)
        dl.update(t, False, 5.0, True)
        for _ in range(11):
            dl.update(t, False, 5.0, True); step(post)
    return ic, dl, step


def test_icing_monitor_stays_quiet_on_a_healthy_pump():
    ic, *_ = _icing_run([4.0] * 8, 3.6)
    assert ic.level == "ok" and ic.reasons == []


def test_icing_monitor_flags_defrosts_that_stop_restoring_the_cop():
    ic, *_ = _icing_run([4.0] * 6 + [3.0, 2.4, 2.0, 1.8, 1.8], 3.6)
    assert "herstelt_niet" in ic.reasons and ic.level in ("let_op", "ijs")


def test_icing_monitor_flags_collapsing_cop_between_defrosts():
    ic, dl, step = _icing_run([4.0] * 4, 3.6)
    for _ in range(14):
        step(2.2)
    assert "cop_zakt" in ic.reasons


def test_icing_monitor_critical_when_cop_stays_around_one():
    ic, dl, step = _icing_run([4.0] * 3, 3.6)
    for _ in range(40):
        step(1.1)
    assert ic.level == "ijs" and "kritiek" in ic.reasons


def test_icing_state_survives_restart_and_controller_publishes_it():
    c = SmartController()
    c.ice.cop_ref, c.ice.ref_n = 3.9, 4
    c2 = SmartController(); c2.import_state(c.export_state())
    assert c2.ice.cop_ref == 3.9 and c2.ice.ref_n == 4
    d = c2.step(_inp(_t(0), room=20.8))
    assert d.ice_level == "ok" and d.diag["ijsvorming"]["niveau"] == "ok"


# ---------------------------------------------------------------- coil tracker (real pump data, Nov 2026)
def _coil_series(tr, start, pre, peak, *, heating=True):
    """pre-defrost drift, then a defrost whose coil rises to `peak` within ~2 minutes."""
    t = start
    for i in range(12):                       # 12 minutes of slow drift at `pre`
        tr.update(t, pre + 0.1 * (i % 2), heating); t += timedelta(minutes=1)
    seen = []
    for v in (pre + 0.4 * (peak - pre), peak, pre + 0.7 * (peak - pre), 0.0, pre * 0.1):
        seen.append(tr.update(t, v, heating)); t += timedelta(seconds=30)
    for _ in range(8):
        tr.update(t, -1.0, heating); t += timedelta(minutes=1)
    return t, seen


def test_coil_tracker_detects_a_defrost_and_measures_a_healthy_peak():
    from engine.coil import CoilTracker
    tr = CoilTracker()
    _, seen = _coil_series(tr, _t(0), -5.0, 38.0)
    assert seen[0] is True and tr.last_peak == pytest.approx(38.0)
    assert tr.weak_streak == 0 and not tr.cold and tr.peak_ref == pytest.approx(38.0)


def test_coil_tracker_weak_defrosts_build_a_streak_like_the_6_7_nov_icing_episode():
    from engine.coil import CoilTracker
    from engine.icing import IcingMonitor
    tr, ic = CoilTracker(), IcingMonitor()
    t = _t(0)
    for peak in (1.3, 2.0):
        t, _ = _coil_series(tr, t, -20.0, peak)
    assert tr.weak_streak == 2 and tr.cold
    ic.update(t, cop=0.0, heating=False, settling=False, defrost=False, unit_diff=None, outside=3.0,
              freq_running=True, last_end=None, last_interval=None, mean_interval=None, n_defrosts=0,
              since_last_min=None, coil_weak_streak=tr.weak_streak, coil_cold=tr.cold)
    assert ic.level == "ijs" and "ontdooi_zwak" in ic.reasons and "coil_koud" in ic.reasons
    t, _ = _coil_series(tr, t, -5.0, 36.0)
    assert tr.weak_streak == 0


def test_coil_tracker_ignores_normal_drift_and_non_heating():
    from engine.coil import CoilTracker
    tr = CoilTracker()
    t = _t(0)
    for i in range(60):
        assert tr.update(t, -3.0 + 0.05 * i, True) is False; t += timedelta(minutes=1)
    tr2 = CoilTracker()
    _, seen = _coil_series(tr2, _t(0), -5.0, 38.0, heating=False)
    assert not any(seen) and tr2.n == 0


def test_coil_state_persists():
    from engine.coil import CoilTracker
    tr = CoilTracker(); _coil_series(tr, _t(0), -5.0, 38.0)
    other = CoilTracker(); other.from_dict(tr.to_dict())
    assert other.peak_ref == tr.peak_ref and other.n == 1


# ---------------------------------------------------------------- frost protection
def test_frost_keeps_the_pump_on_when_thermostat_is_off():
    c = SmartController()
    t = datetime(2026, 11, 12, 3, 0, tzinfo=TZ)
    d = c.step(_inp(t, hvac_on=False, outside=1.0))
    assert d.frost and d.switch is None and d.setpoint == 20.0 and d.reason == "vorstbeveiliging"
    d = c.step(_inp(t + timedelta(minutes=2), hvac_on=False, outside=1.0, switch_state="off"))
    assert d.switch == "on" and d.frost_forced


def test_frost_protection_can_be_disabled_and_respects_shadow_mode():
    c = SmartController()
    t = datetime(2026, 11, 12, 3, 0, tzinfo=TZ)
    assert c.step(_inp(t, hvac_on=False, outside=1.0, frost_enabled=False)).switch == "off"
    c2 = SmartController()
    d = c2.step(_inp(t, hvac_on=False, outside=1.0, switch_state="off", regeling_actief=False))
    assert d.frost and d.switch is None


def test_frost_threshold_is_adjustable_and_released_after_15_minutes():
    c = SmartController()
    t = datetime(2026, 11, 12, 3, 0, tzinfo=TZ)
    assert not c.step(_inp(t, hvac_on=False, outside=4.0)).frost             # default limit 3
    assert c.step(_inp(t, hvac_on=False, outside=4.0, settings={"vorst_buiten": 5.0})).frost
    assert c.step(_inp(t + timedelta(minutes=1), hvac_on=False, outside=2.0)).frost
    assert c.step(_inp(t + timedelta(minutes=10), hvac_on=False, outside=6.0)).frost   # still held
    assert not c.step(_inp(t + timedelta(minutes=27), hvac_on=False, outside=6.0)).frost


def test_frost_when_return_water_stays_too_cold():
    c = SmartController()
    t = datetime(2026, 11, 12, 12, 0, tzinfo=TZ)
    assert not c.step(_inp(t, hvac_on=False, outside=10.0, ret=7.0)).frost
    assert c.step(_inp(t + timedelta(minutes=6), hvac_on=False, outside=10.0, ret=7.0)).frost
    assert c.step(_inp(t + timedelta(minutes=7), hvac_on=False, outside=10.0, ret=8.5)).frost   # hysteresis 1 K
    assert not c.step(_inp(t + timedelta(minutes=8), hvac_on=False, outside=10.0, ret=9.5)).frost


def test_frost_overrules_summer_mode_and_coasting_switch_off():
    c = SmartController()
    t = datetime(2026, 11, 12, 12, 0, tzinfo=TZ)
    for i in range(2):
        d = c.step(_inp(t + timedelta(minutes=10 * i), outside=2.0, room=23.0, switch_state="on",
                        settings={"stookgrens": 0.5}))
    assert d.frost and d.switch != "off"


# ---------------------------------------------------------------- never switch off around a defrost
def test_hvac_off_waits_for_a_running_defrost_before_switching_off():
    c = SmartController()
    t = datetime(2026, 11, 12, 12, 0, tzinfo=TZ)
    d = c.step(_inp(t, hvac_on=False, freq=40.0, flow=20.0, ret=27.0))       # flow < return: defrost
    assert d.defrost and d.defrost_hold and d.switch is None
    d = c.step(_inp(t + timedelta(minutes=1), hvac_on=False, freq=40.0, flow=30.0, ret=27.0))
    assert d.defrost_hold and d.switch is None and d.reason == "wacht_ontdooien"   # settling window
    d = c.step(_inp(t + timedelta(minutes=30), hvac_on=False, freq=40.0, flow=30.0, ret=27.0))
    assert d.switch == "off" and not d.defrost_hold


def test_hvac_off_waits_when_a_defrost_is_expected_soon():
    c = SmartController()
    t = datetime(2026, 11, 12, 6, 0, tzinfo=TZ)
    for i in range(4):                                  # learn a 52 min cycle
        base = t + timedelta(minutes=52 * i)
        c.step(_inp(base, freq=40.0, flow=30.0, ret=27.0))
        c.step(_inp(base + timedelta(minutes=1), freq=40.0, flow=20.0, ret=27.0))
        c.step(_inp(base + timedelta(minutes=2), freq=40.0, flow=20.0, ret=27.0))
        c.step(_inp(base + timedelta(minutes=3), freq=40.0, flow=30.0, ret=27.0))
    last = t + timedelta(minutes=52 * 3)
    soon = c.step(_inp(last + timedelta(minutes=47), hvac_on=False, freq=40.0, flow=30.0, ret=27.0))
    assert soon.defrost_hold and soon.switch is None
    later = c.step(_inp(last + timedelta(minutes=70), hvac_on=False, freq=40.0, flow=30.0, ret=27.0))
    assert later.switch == "off"
