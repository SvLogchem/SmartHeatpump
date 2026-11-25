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
    assert len(slots) == 48 and slots[0][0].astimezone(TZ).hour == 0 and slots[24][1] == 0.2
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
    # legionella after the interval (with a neutral price in the afternoon, see test_legionella_waits_for_the_afternoon...)
    later = t + timedelta(days=7, hours=7)
    r = d.step(later, 50.0, s, 1.0, False, True)
    assert r.mode == "legionella" and r.setpoint == s["dhw_legionella_temp"]
    assert d.step(later + timedelta(minutes=50), 60.5, s, 1.0, False, True).request is False
    assert d.last_legionella == later + timedelta(minutes=50)
    # runaway protection
    d.step(later + timedelta(hours=2), 30.0, s, 1.0, False, True)
    r = d.step(later + timedelta(hours=5), 31.0, s, 1.0, False, True)
    assert r.request is False and d.timeouts == 1
    # disabled stops a running cycle (after the wait that follows a time-out)
    d.step(later + timedelta(hours=12), 30.0, s, 1.0, False, True)
    assert d.step(later + timedelta(hours=12, minutes=5), 31.0, s, 1.0, False, False).request is False


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
    assert d.setpoint_raw <= 29.0                            # by day the efficient frequency (50 Hz) is the limit
    c = SmartController(); _fill(c)
    d = c.step(_inp(day, **dict(kw, room=18.9)))
    assert not d.freq_limited                                # clearly below the comfort band: the full range (80 Hz) is allowed
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


def test_floor_source_is_reported_and_the_estimate_follows_the_floor_sensor():
    c = SmartController()
    t = datetime(2026, 11, 13, 12, 0, tzinfo=TZ)
    d = c.step(_inp(t, ret=27.0))
    assert d.diag["vloer_bron"] == "retour" and d.diag["vloer_gemeten"] == 27.0
    for i in range(1, 6):
        d = c.step(_inp(t + timedelta(minutes=i), ret=27.0, floor=24.0, switch_state="on"))
    assert d.diag["vloer_bron"] == "vloersensor" and d.diag["vloer_gemeten"] == 24.0
    assert abs(d.diag["vloer_geschat"] - 24.0) < 0.5


# ---------------------------------------------------------------- usage statistics
def _usage_run(u, start, minutes, *, outside=8.0, heating=True, defrost=False, price=0.23, reg=True,
               el_kw=1.0, step=1.0, base=18.0):
    t = start
    for _ in range(int(minutes / step)):
        dt = step / 60.0
        u.update(t, dt_h=dt, e_dt=dt, outside=outside, base=base, el_kwh=el_kw * dt, th_kwh=3 * el_kw * dt,
                 price=price, heating=heating, defrost=defrost, regeling_actief=reg)
        t += timedelta(minutes=step)
    return t


def test_usage_degree_days_cost_and_run_time():
    from engine.usage import UsageStats
    u = UsageStats()
    _usage_run(u, datetime(2026, 11, 16, 0, 0, tzinfo=TZ), 24 * 60)             # 8 °C all day, 1 kW
    s = u.summary(starts_today=4)
    assert s["graaddagen_dag"] == pytest.approx(10.0, abs=0.05)                 # 18 - 8 for one day
    assert s["kosten_dag"] == pytest.approx(24 * 0.23, abs=0.05)
    assert s["draaitijd_vandaag"] == 1440 and s["draaitijd_per_start"] == 360
    assert s["kwh_per_graaddag_dag"] == pytest.approx(2.4, abs=0.05)
    assert s["graaddagen_week"] == s["graaddagen_dag"] and s["kosten_jaar"] == s["kosten_dag"]


def test_usage_mild_day_has_no_kwh_per_degree_day_and_base_is_adjustable():
    from engine.usage import UsageStats
    u = UsageStats()
    _usage_run(u, datetime(2026, 11, 16, 0, 0, tzinfo=TZ), 60, outside=19.0)
    assert u.summary()["graaddagen_dag"] == 0.0 and u.summary()["kwh_per_graaddag_dag"] is None
    u2 = UsageStats()
    _usage_run(u2, datetime(2026, 11, 16, 0, 0, tzinfo=TZ), 24 * 60, outside=19.0, base=20.0)
    assert u2.summary()["graaddagen_dag"] == pytest.approx(1.0, abs=0.02)


def test_usage_counts_defrosts_with_debounce_and_resets_per_period():
    from engine.usage import UsageStats
    u = UsageStats()
    t = datetime(2026, 11, 16, 6, 0, tzinfo=TZ)
    for flag in (False, True, True, False, True, False):                        # flicker inside 5 min = one
        t = _usage_run(u, t, 1, defrost=flag)
    assert u.summary()["ontdooien_vandaag"] == 1
    t = _usage_run(u, t + timedelta(minutes=10), 1, defrost=True)
    assert u.summary()["ontdooien_vandaag"] == 2 and u.summary()["ontdooien_7_dagen"] == 2
    _usage_run(u, datetime(2026, 11, 17, 0, 5, tzinfo=TZ), 1)
    s = u.summary()
    assert s["ontdooien_vandaag"] == 0 and s["ontdooien_7_dagen"] == 2 and s["graaddagen_dag"] < 0.1


def test_usage_compares_smart_control_on_and_off_and_persists():
    from engine.usage import UsageStats
    u = UsageStats()
    t = datetime(2026, 11, 1, 0, 0, tzinfo=TZ)
    for day in range(6):
        reg = day % 2 == 0
        _usage_run(u, t + timedelta(days=day), 24 * 60, reg=reg, el_kw=1.0 if reg else 1.5, step=10.0)
    _usage_run(u, t + timedelta(days=6), 10, step=10.0)                         # closes day 6
    s = u.summary()
    assert s["dagen_regeling"] == 3 and s["dagen_schaduw"] == 3
    assert s["kwh_per_graaddag_regeling"] < s["kwh_per_graaddag_schaduw"]
    v = UsageStats(); v.from_dict(u.to_dict())
    assert v.summary() == s


def test_usage_in_controller_uses_fixed_price_unless_sensor_price_is_chosen():
    c = SmartController()
    t = datetime(2026, 11, 16, 12, 0, tzinfo=TZ)
    for i in range(30):
        d = c.step(_inp(t + timedelta(minutes=i), freq=40.0, flow=30.0, ret=27.0, power_w=1000.0, price_now=1.0))
    fixed = d.diag["kosten_dag"]
    c2 = SmartController()
    for i in range(30):
        d2 = c2.step(_inp(t + timedelta(minutes=i), freq=40.0, flow=30.0, ret=27.0, power_w=1000.0, price_now=1.0,
                          cost_fixed_price=False))
    assert d2.diag["kosten_dag"] > fixed * 3                                    # sensor price 1.0 against 0.23
    assert d.diag["graaddagen_dag"] > 0 and d.diag["draaitijd_vandaag"] > 0


def test_full_state_survives_restart_including_defrosts_and_ice_warning():
    """Everything the integration learns or counts must come back after a restart (via JSON, like HA storage)."""
    import json, math
    c = SmartController()
    t0 = datetime(2026, 11, 10, 0, 0, tzinfo=TZ)
    room = 20.5
    for i in range(24 * 60):
        now = t0 + timedelta(minutes=i)
        defr = (i % 90) in (50, 51, 52, 53)
        run = (i % 240) < 200
        out = 3 + 3 * math.sin(i / 200)
        c.step(_inp(now, room=room, outside=out, flow=18 if defr else 31, ret=17 if defr else 26, floor=24.0,
                    freq=45.0 if run else 0.0, power_w=1100 if run else 0, price_now=0.2,
                    coil_temp=(14 if defr else -6) if run else out, unit_outside=out))
        room = min(22.5, max(19, room + (0.004 if run else -0.003)))
    c.ice.level, c.ice.reasons = "let_op", ["test"]
    s1 = json.loads(json.dumps(c.export_state()))
    assert c.usage.summary()["ontdooien_vandaag"] >= 5 and c.defl.n >= 5 and c.coil.n >= 5
    c2 = SmartController()
    c2.import_state(s1)
    assert json.loads(json.dumps(c2.export_state())) == s1
    assert c2.usage.summary(c2.today["starts"]) == c.usage.summary(c.today["starts"])
    assert c2.today == c.today and c2.defl.n == c.defl.n and c2.coil.n == c.coil.n
    assert c2.ice.level == "let_op" and c2.defl._pre_dtw == c.defl._pre_dtw
    # a restored warning must still be releasable once the conditions are gone
    now = t0 + timedelta(days=2)
    c2.ice.update(now, cop=3.5, heating=False, settling=False, defrost=False, unit_diff=None, outside=5.0,
                  freq_running=False, last_end=None, last_interval=None, mean_interval=None,
                  n_defrosts=0, since_last_min=None)
    assert c2.ice.level == "ok"


def test_coasting_setpoint_is_low_enough_for_the_compressor_to_stop():
    """Real history: the pump stops its compressor at return >= setpoint + 2 K. Coasting must ask for
    clearly less than that, otherwise the compressor keeps running at minimum frequency."""
    c = SmartController()
    c.step(_inp(_t(-90), room=22.5, ret=26.4, flow=30.0))
    d = c.step(_inp(_t(0), room=22.5, ret=26.4, flow=30.0, outside=22.0, freq=30.0))   # over temperature -> coast
    assert d.coasting
    assert 26.4 - d.setpoint_raw >= 2.5 and 26.4 - d.setpoint >= 2.0


def _boost_run(c, start_min, minutes, **kw):
    d = None
    for m in range(start_min, start_min + minutes):
        d = c.step(_inp(_t(m), switch_state="on", target_current=23.0, **kw))
    return d


def test_shortfall_boost_pushes_water_up_then_holds_minimum_frequency():
    c = SmartController()
    base = dict(room=19.9, outside=6.0, flow=27.0, ret=24.5, freq=30.0, settings={"setpoint_dag": 20.4})
    d = _boost_run(c, 0, 20, **base)
    assert not d.boosting                                     # shortfall not yet long enough
    d = _boost_run(c, 20, 20, **base)                         # 0.5 K short for > 30 min
    assert d.boost == "boost" and d.boosting and d.reason.startswith("tekort_boost")
    assert "gaat voor" in d.diag["plan_reden"]
    assert d.setpoint_raw >= 24.5 + 2.8 and not d.coasting     # gap that makes the pump ramp up
    d = _boost_run(c, 40, 5, **{**base, "ret": 30.5, "flow": 33.0})          # target return reached
    assert d.boost == "hold" and d.reason == "tekort_aanhouden"
    assert 28.0 <= d.setpoint_raw <= 30.5                      # just below the return: stays at minimum frequency
    d = _boost_run(c, 45, 3, **{**base, "ret": 30.5, "flow": 33.0, "room": 20.5})  # room recovered
    assert d.boost is None


def test_shortfall_boost_needs_switch_and_is_less_eager_at_night():
    c = SmartController()
    base = dict(room=19.9, outside=6.0, flow=27.0, ret=24.5, freq=30.0, settings={"setpoint_dag": 20.4})
    c.step(_inp(_t(0), switch_state="on", boost_enabled=False, **base))
    for m in range(1, 45):
        d = c.step(_inp(_t(m), switch_state="on", boost_enabled=False, **base))
    assert not d.boosting
    n = SmartController()                                     # 23:00, 0.4 K short: below the night threshold (2 x 0.4)
    for m in range(0, 45):
        d = n.step(_inp(_t(9 * 60 + m), switch_state="on", room=20.0, outside=3.0, flow=27.0, ret=24.5,
                        freq=30.0, settings={"setpoint_nacht": 20.4}))
    assert not d.boosting


def test_start_kick_when_room_is_cold_but_compressor_idle():
    """Screenshot case: room 1 K under target, setpoint 24 but return 22.5 -> pump never starts (needs ~2.5 K gap)."""
    c = SmartController()
    kw = dict(room=19.4, outside=5.7, flow=22.6, ret=22.5, freq=0.0, switch_state="on", target_current=24.0,
              settings={"setpoint_dag": 20.4})
    d = None
    for m in range(0, 6):
        d = c.step(_inp(_t(m), **kw))
    assert d.setpoint >= 22.5 + 2.5 and not d.coasting


def test_minimum_heating_setpoint_raises_low_curve_but_follows_frequency_gap():
    kw = dict(room=19.4, outside=5.7, switch_state="on", target_current=24.0, freq=40.0,
              settings={"setpoint_dag": 20.4})
    base = SmartController()
    b = None
    for m in range(6):
        b = base.step(_inp(_t(m), flow=27.0, ret=24.0, **kw))
    c = SmartController()
    for m in range(6):
        d = c.step(_inp(_t(m), flow=27.0, ret=24.0, **{**kw, "settings": {**kw["settings"], "stook_min": 31.0}}))
    assert d.setpoint_raw >= 24.0 + 2.8 and d.setpoint_raw <= 31.0     # climbs with the return, no jump to 31 at once
    e = SmartController()
    for m in range(6):
        f = e.step(_inp(_t(m), flow=32.0, ret=30.0, **{**kw, "settings": {**kw["settings"], "stook_min": 31.0}}))
    assert f.setpoint_raw >= 30.9                                       # return near 30: setpoint is the 31 minimum
    g = SmartController()
    for m in range(6):                                                  # room above target: minimum not applied
        h = g.step(_inp(_t(m), flow=27.0, ret=24.0, **{**kw, "room": 20.6, "settings": {**kw["settings"], "stook_min": 31.0}}))
    assert h.setpoint_raw < 31.0


def test_persistent_shortfall_raises_setpoint_by_itself_beyond_old_limit():
    """Real history: room 0.8-0.9 K under target all day while the setpoint stayed at 23-25."""
    kw = dict(room=19.6, outside=6.0, flow=27.0, ret=24.5, switch_state="on", target_current=24.0, freq=35.0,
              settings={"setpoint_dag": 20.4, "boost_tekort": 2.0})      # boost off here: only the integrator acts
    c = SmartController()
    first = c.step(_inp(_t(0), **kw))
    for m in range(1, 240):
        d = c.step(_inp(_t(m), **kw))
    assert c.pi_i > 2.0 and c.pi_i <= 6.0                       # old limit was 2 K
    assert d.setpoint_raw > first.setpoint_raw + 1.5
    r = SmartController()                                         # room already recovering: no extra push
    for m in range(0, 120):
        r.step(_inp(_t(m), **{**kw, "room": 19.4 + 0.004 * m}))
    assert r.pi_i < c.pi_i


def test_heating_curve_learns_a_lasting_correction_and_keeps_it():
    import json
    kw = dict(room=19.6, outside=6.0, flow=27.0, ret=24.5, switch_state="on", target_current=24.0, freq=35.0,
              settings={"setpoint_dag": 20.4, "boost_tekort": 2.0})
    c = SmartController()
    for m in range(0, 1440):                                    # 24 h with a constant 0.8 K shortfall
        d = c.step(_inp(_t(m), **kw))
    assert c.trim_at(6.0) > 1.0                                  # the curve itself moved up
    assert d.diag["stooklijn_correctie"] > 1.0
    again = SmartController()
    again.import_state(json.loads(json.dumps(c.export_state())))
    assert abs(again.trim_at(6.0) - c.trim_at(6.0)) < 0.01       # survives a restart
    # correction learned at 6 degrees also acts nearby, and nothing is invented far away without data
    assert again.trim_at(5.0) > 0.0
    fresh = SmartController()
    assert fresh.trim_at(6.0) == 0.0
    # too warm for a long time pulls it back down
    w = SmartController()
    w.import_state(json.loads(json.dumps(c.export_state())))
    before = w.trim_at(6.0)
    for m in range(1440, 2880):
        w.step(_inp(_t(m), **{**kw, "room": 22.2}))
    assert w.trim_at(6.0) < before


def test_boost_follows_measured_floor_heat():
    base = dict(outside=6.0, flow=27.0, ret=24.5, freq=30.0, settings={"setpoint_dag": 20.4})
    cold = SmartController()                                      # floor sensor reads low: floor lacks heat -> boost
    d = _boost_run(cold, 0, 40, floor=19.0, room=19.9, **base)
    assert d.boost == "boost" and cold._floor_gap is not None and cold._floor_gap >= 0.5
    warm = SmartController()                                      # floor warm AND room responding: no push
    for m in range(40):
        d = warm.step(_inp(_t(m), switch_state="on", target_current=23.0, floor=30.0, room=19.7 + 0.01 * m, **base))
    assert d.boost is None and warm._floor_gap is not None and warm._floor_gap < 0.5
    d = _boost_run(cold, 40, 5, floor=30.0, room=19.9, **base)    # floor warm but the room does not respond: stays on
    assert d.boost == "boost"
    flat = SmartController()                                      # model says full, room stays cold: do not trust it
    d = _boost_run(flat, 0, 40, floor=30.0, room=19.9, **base)
    assert d.boost == "boost"



def test_boost_target_is_calculated_with_floor_model_not_fixed_30():
    base = dict(room=19.9, outside=6.0, flow=37.0, ret=33.0, freq=30.0, settings={"setpoint_dag": 20.4})
    c = SmartController()
    d = _boost_run(c, 0, 40, floor=19.0, **{**base, "ret": 24.5, "flow": 27.0})
    assert d.boost == "boost"
    d = _boost_run(c, 40, 5, floor=19.0, **base)                  # return above 30 but the floor is still cold
    assert d.boost == "boost"                                      # fixed 30 does not end it


def test_room_prediction_has_no_gap_at_night():
    """After bedtime no bedtime is in the horizon: the check moves to the next rise of the comfort setpoint."""
    m = HouseModel()
    now = datetime(2026, 11, 12, 23, 0, tzinfo=TZ)
    f_eq = m.floor_equilibrium(20.0, 4.0, 0.0)
    inp = _plan_input(m, lambda t: 4.0, now, 20.0, f_eq, bedtime=False)
    inp.sp_fn = lambda t: 20.4 if 9 <= t.hour < 21 else 20.0
    res = plan(inp)
    assert res.tr_check is not None
    evening = plan(_plan_input(m, lambda t: 4.0, datetime(2026, 11, 12, 15, 0, tzinfo=TZ), 20.0, f_eq))
    assert evening.tr_check is not None                          # unchanged: one hour after bedtime


def test_partial_relearn_keeps_the_share_that_was_not_reset():
    import json
    c = SmartController()
    kw = dict(room=19.6, outside=6.0, flow=27.0, ret=24.5, switch_state="on", target_current=24.0, freq=35.0,
              settings={"setpoint_dag": 20.4, "boost_tekort": 2.0})
    for m in range(0, 1440):
        c.step(_inp(_t(m), **kw))
    # feed the model a little so there is something to forget
    for i in range(400):
        c.model.learn_room(0.05, 2.0 + 0.001 * i, 14.0, 0.2)
        c.model.learn_floor(0.3, 1.0 + 0.001 * i, 2.0)
    conf0, trim0, pi0 = c.model.confidence(), c.trim_at(6.0), c.pi_i
    c.tracker.bias = 0.4
    assert trim0 != 0.0 and conf0 > 0.2
    c.reset_model(0.5)
    assert 0.0 < c.model.confidence() < conf0
    assert abs(c.trim_at(6.0) - 0.5 * trim0) < 1e-6 and abs(c.pi_i - 0.5 * pi0) < 1e-6
    assert abs(c.tracker.bias - 0.2) < 1e-9
    json.dumps(c.export_state())                                 # still serialisable
    c.reset_model(1.0)                                           # full reset as before
    assert c.model.confidence() == 0.0 or c.model.confidence() < 0.01
    assert c.trim == {} and c.pi_i == 0.0 and c.tracker.bias == 0.0


def test_planner_may_not_coast_while_room_is_below_comfort_band():
    # history: room 19.5 for hours against a setpoint of 20.0 (tolerance 0.2) while the plan said "uitlopen"
    c = SmartController()
    t = datetime(2026, 11, 12, 14, 0, tzinfo=TZ)
    d = None
    for i in range(12):
        d = c.step(_inp(t + timedelta(minutes=10 * i), room=19.6, ret=22.0, outside=9.0, switch_state="on"))
    assert d.reason != "uitlopen"


def test_frequency_table_is_monotonic_and_relearn_shrinks_it():
    from engine.modulation import ModulationLearner
    m = ModulationLearner()
    for _ in range(12):
        m.observe(2.0, True, 54.0, 3.0); m.observe(3.5, True, 50.0, 3.5); m.observe(8.0, True, 70.0, 6.0)
    freqs = [f for _, f, _ in m.trusted()]
    assert freqs == sorted(freqs)               # a larger gap never shows a lower frequency
    m.shrink(0.5)
    assert m.table() == {} or all(v > 0 for v in m.table().values())
    m.shrink(0.0)
    assert m.table() == {}


def test_floor_table_is_published_per_outdoor_temperature():
    c = SmartController(); _fill(c)
    d = c.step(_inp(_t(0), room=21.0))
    t = d.diag.get("vloer_setpoint_tabel")
    assert t is None or (set(t) == {"-5", "0", "5", "10", "15"} and t["0"]["setpoint"] >= DEFAULTS["min_setpoint"]
                         and len(t["0"]["kamer"]) == 3)


def test_warm_floor_keeps_the_frequency_limit_even_when_room_is_far_below_band():
    c = SmartController(); _fill(c)
    c._floor_gap, c._tr_rate = 0.4, 0.05          # floor at the needed level, room not getting colder
    day = datetime(2026, 11, 12, 14, 0, tzinfo=TZ)
    d = c.step(_inp(day, room=18.9, ret=24.0, flow=28.0, freq=70.0, target_current=29.0, floor=24.5))
    assert d.setpoint_raw <= 24.0 + 3.0


def test_coil_tracker_detects_a_defrost_with_the_two_minute_sampling_of_the_integration():
    from engine.coil import CoilTracker
    tr = CoilTracker()
    t = _t(0)
    for i in range(8):                                  # drift, one sample every 2 minutes
        tr.update(t, -5.0 + 0.1 * (i % 2), True); t += timedelta(minutes=2)
    for v in (24.0, 38.0, 12.0, 2.0, -3.0, -4.0):       # the defrost rises ~30 K between two samples
        tr.update(t, v, True); t += timedelta(minutes=2)
    assert tr.last_peak == pytest.approx(38.0)

def test_cold_floor_keeps_pump_running_softly_while_room_is_warm_from_the_slab():
    base = dict(outside=6.0, flow=27.0, ret=24.5, freq=30.0, settings={"setpoint_dag": 20.4}, room=21.0)
    cold = SmartController()                         # room 21.0 (over), but the floor already cooled far below need
    for m in range(40):
        d = cold.step(_inp(_t(m), switch_state="on", target_current=23.0, floor=19.0, **base))
    assert cold._floor_hold and not d.coasting
    warm = SmartController()                         # floor still warm: coasting as before
    for m in range(40):
        d = warm.step(_inp(_t(m), switch_state="on", target_current=23.0, floor=30.0, **base))
    assert not warm._floor_hold and d.coasting


def test_expected_setpoint_table_covers_the_coming_hours():
    c = SmartController()
    for m in range(5):
        d = c.step(_inp(_t(m), room=20.5, floor=22.0, ret=24.0, freq=0.0))
    f = d.diag.get("verwacht_setpoint")
    assert f is None or (len(f) == 7 and all(r["setpoint"] >= DEFAULTS["min_setpoint"] for r in f))


def test_event_driven_coil_samples_give_the_real_defrost_peak():
    c = SmartController()
    t0 = _t(0)
    for i in range(6):
        c.step(_inp(t0 + timedelta(minutes=2 * i), coil_temp=-5.0, freq=40.0, flow=30.0, ret=27.0))
    t = t0 + timedelta(minutes=12)
    fast = tuple((t - timedelta(seconds=110 - s), v) for s, v in
                 ((5, -2.0), (15, 8.0), (30, 24.0), (45, 41.0), (60, 33.0), (80, 20.0)))   # 41 is the real peak
    c.step(_inp(t, coil_temp=15.0, coil_samples=fast, freq=40.0, flow=30.0, ret=27.0))       # poll only sees 15
    for k in range(1, 5):
        c.step(_inp(t + timedelta(minutes=2 * k), coil_temp=-3.0, freq=40.0, flow=30.0, ret=27.0))
    assert c.coil.last_peak == pytest.approx(41.0)


def test_plan_values_stay_visible_during_a_defrost_cycle():
    c = SmartController()
    for m in range(6):
        d = c.step(_inp(_t(m * 2), room=20.5, floor=22.0, ret=24.0, freq=40.0, flow=30.0, switch_state="on"))
    assert "plan" in d.diag and "verwacht_buiten" in d.diag
    d = c.step(_inp(_t(14), room=20.5, floor=22.0, ret=29.0, freq=40.0, flow=24.0, switch_state="on"))   # flow < return
    assert d.defrost and d.reason == "ontdooien"
    assert d.diag["plan"] == c._plan_diag["plan"] and d.diag["verwacht_buiten"] == c._plan_diag["verwacht_buiten"]


def test_frost_protection_still_works_when_the_room_sensor_is_missing():
    c = SmartController()
    d = c.step(_inp(_t(0), room=None, outside=-4.0, ret=6.0, switch_state="off", hvac_on=False))
    assert d.sensor_problem and d.frost and d.switch == "on" and d.frost_forced


def test_thermostat_off_without_power_switch_drops_the_setpoint_to_the_minimum():
    c = SmartController()
    d = c.step(_inp(_t(0), room=20.0, outside=8.0, switch_state=None, hvac_on=False, target_current=33.0))
    assert d.reason == "uit" and d.setpoint == DEFAULTS["min_setpoint"]


def test_one_damaged_stored_part_does_not_wipe_the_house_model():
    src = SmartController()
    for m in range(30):
        src.step(_inp(_t(m * 2), room=20.0, floor=22.0, ret=24.0, freq=40.0, flow=30.0))
    state = src.export_state()
    k0 = state["model"]["params"]["k"] if "params" in state["model"] else None
    state["usage"] = "kapot"
    dst = SmartController(); dst.import_state(state)
    assert dst.model.to_dict() == src.model.to_dict()


def test_dhw_run_survives_a_restart_and_is_still_ended_by_max_run_time():
    from engine.dhw import DhwController
    a = DhwController(); t = _t(0)
    a._start(t, "normal", 50.0, "onder_minimum")
    b = DhwController(); b.from_dict(a.to_dict())
    assert b.active and b.started == t


def test_shadow_mode_does_not_report_a_frost_switch_on():
    c = SmartController()
    d = c.step(_inp(_t(0), room=20.0, outside=-6.0, ret=6.0, switch_state="off", hvac_on=False, regeling_actief=False))
    assert not d.frost_forced and d.switch is None



def test_setpoint_restarts_from_the_water_after_coasting_and_follows_the_kick():
    c = SmartController()
    kw = dict(outside=4.0, flow=24.0, ret=24.0, freq=0.0, room=19.0, switch_state="on", target_current=21.0)
    for m in range(20):                                   # coasting: prev setpoint anchor must not survive
        c.step(_inp(_t(m * 2), **dict(kw, room=22.8)))
    assert c._prev_s is None
    d = c.step(_inp(_t(60), **kw))                        # room 1 K too cold, pump idle: kick, not a 0.5 K crawl
    assert d.setpoint >= 24.0 + 2.0



# ---------- v2.17: pump profile and complete frequency table ----------

def _learner(points, n=12):
    from engine.modulation import ModulationLearner
    m = ModulationLearner()
    for _ in range(n):
        for gap, hz, kw in points:
            m.observe(gap, True, hz, kw)
    return m


def test_frequency_table_stops_at_the_maximum_frequency():
    # the history case: +5 K already gives 70 Hz, +9 K showed 69 Hz -> nothing above +5 K may remain
    m = _learner([(2.5, 30.0, 1.5), (3.5, 45.0, 2.5), (5.0, 70.0, 4.0), (9.0, 69.0, 4.2)])
    rows = m.curve(30, 70)
    assert rows[-1]["verschil"] == 5.0 and rows[-1]["frequentie"] == 70
    assert all(r["frequentie"] <= 70 for r in rows)
    assert not [r for r in rows if r["verschil"] > 5.0]
    t = m.table(30, 70, full=True)
    assert t["+5.0"] == 70 and "+6.0" not in t and "+9.0" not in t


def test_frequency_table_is_filled_between_min_and_max_hz():
    m = _learner([(2.5, 30.0, 1.5), (5.0, 70.0, 4.0)])
    rows = m.curve(30, 70)
    assert [r["verschil"] for r in rows] == [2.5, 3.0, 3.5, 4.0, 4.5, 5.0]
    assert [r["bron"] for r in rows] == ["gemeten"] + ["interpolatie"] * 4 + ["gemeten"]
    hz = [r["frequentie"] for r in rows]
    assert hz == sorted(hz) and hz[0] == 30 and hz[-1] == 70


def test_frequency_table_is_clipped_to_the_configured_range():
    m = _learner([(2.5, 25.0, 1.0), (4.0, 60.0, 3.0), (6.0, 80.0, 5.0)])
    rows = m.curve(30, 60)                                  # pump limited to 30..60 Hz
    assert rows[0]["frequentie"] == 30                      # below the minimum -> the minimum
    assert rows[-1]["frequentie"] == 60 and rows[-1]["verschil"] == 4.0   # 60 Hz reached at +4 K: nothing above


def test_frequency_table_extrapolates_until_the_maximum_when_not_yet_seen():
    m = _learner([(2.5, 30.0, 1.5), (4.0, 50.0, 3.0)])
    rows = m.curve(0, 70)                                   # max configured, never seen
    assert rows[-1]["frequentie"] == 70 and rows[-1]["bron"] == "schatting"
    assert [r["bron"] for r in rows if r["verschil"] <= 4.0] == ["gemeten", "interpolatie", "interpolatie", "gemeten"]
    assert m.curve(0, 0)[-1]["bron"] == "gemeten"           # unknown maximum: only what was measured


def test_frequency_range_is_learned_when_not_configured():
    m = _learner([(2.5, 30.0, 1.5), (5.0, 70.0, 4.0)])
    assert m.f_range() == (30, 70)
    assert m.f_range(35, 0) == (35, 70)
    assert m.f_range(0, 65) == (30, 65)
    from engine.modulation import ModulationLearner
    m2 = ModulationLearner(); m2.from_dict(m.to_dict())
    assert m2.f_range() == (30, 70) and m2.table() == m.table()
    m.observe(3.0, True, 400.0, 1.0)                       # sensor glitch is ignored
    assert m.f_range()[1] == 70


def test_old_saved_modulation_state_without_range_still_loads():
    from engine.modulation import ModulationLearner
    m = ModulationLearner(); m.from_dict({"6": [20.0, 1.0, 50.0, 3.0]})
    assert m.table() == {"+3.0": 50} and m.f_range() == (0, 0)


def test_diag_publishes_complete_table_and_frequency_range():
    c = SmartController(); _fill(c)
    d = c.step(_inp(_t(0), room=21.0))
    assert d.diag["pomp_max_frequentie"] == 80 and d.diag["pomp_min_frequentie"] == 30
    assert d.diag["verschil_voor_max_frequentie"] == 5.0
    assert d.diag["frequentie_tabel"]["+5.0"] == 80
    assert "+6.0" not in d.diag["frequentie_tabel"]
    assert set(d.diag["frequentie_tabel_bron"].values()) <= {"gemeten", "interpolatie", "schatting"}


def test_pump_profile_start_gap_is_used_for_start_kick():
    def run(start):
        c = SmartController()
        d = c.step(_inp(_t(0), room=20.3, outside=12.0, ret=24.0, flow=24.0, freq=0.0, power_w=0.0,
                        settings={"pomp_start_verschil": start}))
        return d.setpoint
    assert run(4.0) >= run(2.0) + 1.5      # idle compressor, cold room: the setpoint sits one start gap above the water


def test_glycol_lowers_the_computed_heat_output():
    def kw(pct):
        c = SmartController()
        d = c.step(_inp(_t(0), room=20.0, ret=28.0, flow=33.0, flow_lh=1000.0, freq=45.0, power_w=1500.0,
                        settings={"glycol": pct}))
        return d.thermal_kw
    assert kw(0) > kw(30) > 0
    assert kw(30) == pytest.approx(kw(0) * (1 - 0.0032 * 30), rel=0.02)


def test_minimum_power_decides_heating_when_there_is_no_frequency():
    from engine.controller import SmartController as SC
    inp = _inp(_t(0), power_w=180.0, freq=None)
    assert not SC._heating(inp, 2.0)                       # default 250 W
    assert SC._heating(inp, 2.0, 100.0)                    # small pump: 180 W is heating


def test_pv_surplus_needs_the_house_not_to_import():
    def surplus(**kw):
        c = SmartController()
        return c.step(_inp(_t(0), pv_w=3000.0, **kw)).pv_surplus
    assert surplus()                                  # no grid sensor: production above the threshold counts
    assert surplus(grid_import_w=-800.0)              # exporting: clear surplus
    assert surplus(grid_import_w=60.0)                # within the tolerance
    assert not surplus(grid_import_w=900.0)           # the house itself uses it all and imports more
    c = SmartController()
    assert not c.step(_inp(_t(0), pv_w=300.0, grid_import_w=-800.0)).pv_surplus     # panels below the threshold


def test_manual_curve_corrections_are_interpolated_and_shift_the_setpoint():
    c = SmartController()
    c.step(_inp(_t(0), settings={"stooklijn_corr_min5": 2.0, "stooklijn_corr_5": 0.0, "stooklijn_corr_15": -1.0}))
    assert c.curve_corr(-5.0) == pytest.approx(2.0) and c.curve_corr(-10.0) == pytest.approx(2.0)     # flat outside the anchors
    assert c.curve_corr(0.0) == pytest.approx(1.0) and c.curve_corr(5.0) == pytest.approx(0.0)
    assert c.curve_corr(10.0) == pytest.approx(-0.5) and c.curve_corr(20.0) == pytest.approx(-1.0)

    def raw(corr):
        c = SmartController()
        return c.step(_inp(_t(0), room=20.4, outside=5.0, ret=24.0, flow=27.0, freq=40.0,
                           settings={"stooklijn_corr_5": corr})).setpoint_raw
    assert raw(3.0) == pytest.approx(raw(0.0) + 3.0, abs=0.6)
    c = SmartController(); d = c.step(_inp(_t(0)))
    assert d.diag["stooklijn_handmatig"] == 0.0


# ---------- v2.18: several rooms ----------

def test_rooms_main_room_leads_and_guard_rooms_only_have_a_minimum():
    from engine.rooms import combine
    v, info = combine(21.0, [("sensor.slaapkamer", 18.0)], "hoofd", 17.0)
    assert v == 21.0 and info["tekort_bewaakt"] == 0.0              # guard room above its minimum: the main room decides
    v, info = combine(21.0, [("sensor.slaapkamer", 15.5)], "hoofd", 17.0)
    assert v == 21.0 and info["tekort_bewaakt"] == pytest.approx(1.5)   # the main room keeps its real temperature; the shortfall is reported apart
    v, info = combine(21.0, [("a", 10.0)], "hoofd", 17.0)
    assert v == 21.0 and info["tekort_bewaakt"] == pytest.approx(3.0)   # capped at 3 K: one cold room cannot run the house wild


def test_rooms_average_and_coldest():
    from engine.rooms import combine
    assert combine(21.0, [("a", 19.0), ("b", 20.0)], "gemiddelde", 17.0)[0] == pytest.approx(20.0)
    assert combine(21.0, [("a", 19.0), ("b", 20.0)], "koudste", 17.0)[0] == 19.0


def test_rooms_survive_a_dropped_sensor():
    from engine.rooms import combine
    for mode in ("hoofd", "gemiddelde", "koudste"):                    # main room gone: the others must not take its place
        assert combine(None, [("a", 18.0), ("b", 19.0)], mode, 17.0)[0] is None
    assert combine(21.0, [("a", None)], "koudste", 17.0)[0] == 21.0                                 # guard room gone
    assert combine(None, [("a", None)], "gemiddelde", 17.0)[0] is None
    assert combine(20.5, [], "koudste", 17.0)[0] == 20.5                                            # no extra rooms: unchanged
    assert combine(20.5, [("a", 19.0)], "onzin", 17.0)[0] == 20.5                                   # unknown mode -> main room


# ---------- v2.18: sensor health, report data, messages ----------

def _readings(**over):
    base = {"kamer": {"entity": "sensor.room", "state": "20.5", "value": 20.5, "age_h": 0.1},
            "buiten": {"entity": "sensor.out", "state": "5", "value": 5.0, "age_h": 0.1},
            "retour": {"entity": "sensor.ret", "state": "27", "value": 27.0, "age_h": 0.1}}
    base.update(over)
    return base


def test_health_reports_only_problems_that_last_and_clears_them():
    from engine.health import SensorHealth
    h, t0 = SensorHealth(), _t(0)
    gone = _readings(retour={"entity": "sensor.ret", "state": "unavailable", "value": None, "age_h": None})
    assert h.check(t0, gone) == []                                           # one missing reading is normal
    assert h.check(t0 + timedelta(minutes=29), gone) == []
    pr = h.check(t0 + timedelta(minutes=31), gone)
    assert [p.key for p in pr] == ["unavailable_retour"] and pr[0].entity == "sensor.ret"
    assert h.check(t0 + timedelta(minutes=40), _readings()) == []            # fixed: gone again
    assert h.check(t0 + timedelta(minutes=80), gone) == []                   # and the timer restarts


def test_health_stale_and_implausible_readings():
    from engine.health import SensorHealth
    h = SensorHealth()
    stale = _readings(kamer={"entity": "sensor.room", "state": "20", "value": 20.0, "age_h": 7.0})
    assert [p.kind for p in h.check(_t(0), stale)] == ["stale"]
    wrong = _readings(buiten={"entity": "sensor.out", "state": "85", "value": 85.0, "age_h": 0.1})
    assert h.check(_t(0), wrong) == []
    assert [p.key for p in h.check(_t(11), wrong)] == ["implausible_buiten"]


def test_health_outdoor_sensors_that_disagree():
    from engine.health import SensorHealth
    h = SensorHealth()
    r = _readings(buiten={"entity": "sensor.out", "state": "-2", "value": -2.0, "age_h": 0.1})
    assert h.check(_t(0), r, unit_outside=9.7) == []
    pr = h.check(_t(125), r, unit_outside=9.7)
    assert [p.key for p in pr] == ["outside_mismatch"] and round(pr[0].data["diff"]) == 12
    assert h.check(_t(130), r, unit_outside=-1.0) == []                      # they agree again


def test_usage_report_and_comfort_share():
    from engine.usage import UsageStats
    u = UsageStats()
    t = datetime(2026, 11, 2, 0, 0, tzinfo=TZ)
    for day in range(8):                                                       # 8 days, hourly
        for h in range(24):
            now = t + timedelta(days=day, hours=h)
            u.update(now, dt_h=1.0, e_dt=1.0, outside=5.0, base=18.0, el_kwh=0.5, th_kwh=1.5, price=0.25,
                     heating=True, defrost=False, regeling_actief=True, in_band=(h < 18))
    rep = u.report(t + timedelta(days=7, hours=9), 7)
    assert rep["days"] == 7 and rep["kwh"] == pytest.approx(7 * 24 * 0.5)
    assert rep["comfort"] == pytest.approx(18 / 24) and rep["kwh_th"] / rep["kwh"] == pytest.approx(3.0)
    assert UsageStats().report(t, 7) is None
    # state saved before v2.18 (no comfort fields) still loads
    old = UsageStats(); old.from_dict({"cur": {"day": {"key": "2026-11-02", "kwh": 1.0}}, "history": {"2026-11-01": {"kwh": 2.0, "tot_s": 86400}}})
    assert old.report(t + timedelta(days=1), 7)["comfort"] is None


def test_messages_follow_the_home_assistant_language():
    from engine.i18n import msg, lang, role_name
    assert lang("nl") == "nl" and lang("nl-NL") == "nl" and lang("de") == "en" and lang(None) == "en" and lang("en-GB") == "en"
    assert "vorstbeveiliging" in msg("nl", "frost_title").lower() and "frost protection" in msg("en", "frost_title").lower()
    from engine.i18n import MESSAGES
    assert set(MESSAGES["nl"]) == set(MESSAGES["en"])                         # no message missing in a language
    assert role_name("en", "retour") == "return temperature" and role_name("nl", "retour") == "retourtemperatuur"


# ---------- v2.18: suggestions for the setup wizard ----------

def _cands():
    from engine.suggest import Candidate as C
    return [
        C("sensor.warmtepomp_retour_temp", "Warmtepomp Retour Temp", "°C", "temperature", "localtuya"),
        C("sensor.warmtepomp_aanvoer_temp", "Warmtepomp Aanvoer Temp", "°C", "temperature", "localtuya"),
        C("sensor.warmtepomp_buiten_temp", "Warmtepomp Buiten Temp", "°C", "temperature", "localtuya"),
        C("sensor.warmtepomp_pg_temp", "Warmtepomp Coil (PG) temperatuur", "°C", "temperature", "localtuya"),
        C("sensor.warmtepomp_compressor_frequentie", "Compressor frequentie", "Hz", None, "localtuya"),
        C("sensor.warmtepomp_compressor_stroom", "Compressor stroom", "A", None, "localtuya"),
        C("sensor.warmtepomp_spanning", "Spanning", "V", None, "localtuya"),
        C("sensor.warmtepomp_dc_spanning", "DC-spanning", "V", None, "localtuya"),
        C("number.warmtepomp_setpoint", "Setpoint verwarmen", None, None, "localtuya"),
        C("number.warmtepomp_defrost_interval_tijd", "Defrost interval", None, None, "localtuya"),
        C("switch.warmtepomp_schakelaar", "Warmtepomp aan/uit", None, None, "localtuya"),
        C("sensor.wp_elektrisch_vermogen_w", "WP elektrisch vermogen", "W", "power", "template"),
        C("sensor.wp_totaal_thermisch_vermogen_kw", "WP totaal thermisch vermogen", "kW", "power", "template"),
        C("sensor.flowsensing_belimo_flow_rate_lph", "Belimo flow rate", "l/h", None, "belimo"),
        C("sensor.flowsensing_belimo_2_flow_rate_lph", "Belimo 2 flow rate", "l/h", None, "belimo"),
        C("sensor.flowsensor_temp_tt101", "Flowsensor temp TT101", "°C", "temperature", "mqtt"),
        C("sensor.vloer_dekvloer_temperatuur", "Dekvloer temperatuur", "°C", "temperature", "mqtt"),
        C("sensor.woonkamer_temperatuur", "Woonkamer temperatuur", "°C", "temperature", "zha"),
        C("sensor.slaapkamer_temperatuur", "Slaapkamer temperatuur", "°C", "temperature", "zha"),
        C("sensor.tuin_buitentemperatuur", "Tuin buiten temperatuur", "°C", "temperature", "zha"),
    ]


def test_suggestions_find_the_right_sensor_for_each_role():
    from engine.suggest import suggest
    s = suggest(_cands(), pump_platform="localtuya")
    assert s["retour"] == "sensor.warmtepomp_retour_temp" and s["aanvoer"] == "sensor.warmtepomp_aanvoer_temp"
    assert s["frequentie"] == "sensor.warmtepomp_compressor_frequentie" and s["stroom"] == "sensor.warmtepomp_compressor_stroom"
    assert s["spanning"] == "sensor.warmtepomp_spanning"                      # not the DC voltage
    assert s["coil"] == "sensor.warmtepomp_pg_temp"
    assert s["pomp_setpoint"] == "number.warmtepomp_setpoint"                 # not the defrost interval
    assert s["pomp_schakelaar"] == "switch.warmtepomp_schakelaar"
    assert s["vermogen"] == "sensor.wp_elektrisch_vermogen_w"                 # not the thermal power
    assert s["vloer"] == "sensor.vloer_dekvloer_temperatuur"
    assert sorted(s["debiet"]) == ["sensor.flowsensing_belimo_2_flow_rate_lph", "sensor.flowsensing_belimo_flow_rate_lph"]


def test_suggestions_keep_the_pumps_own_outdoor_sensor_apart_from_the_controllers():
    from engine.suggest import suggest
    s = suggest(_cands(), pump_platform="localtuya")
    assert s["buiten_unit"] == "sensor.warmtepomp_buiten_temp"                # the pump's own sensor -> the "unit" role
    assert s["buiten"] == "sensor.tuin_buitentemperatuur"                     # the controller's own outdoor sensor is not the pump's
    assert s["kamer"] == "sensor.woonkamer_temperatuur"


def test_suggestions_without_a_chosen_integration_and_with_nothing_to_find():
    from engine.suggest import suggest, Candidate
    s = suggest(_cands())
    assert s["retour"] == "sensor.warmtepomp_retour_temp"
    assert suggest([]) == {} and suggest([Candidate("sensor.x", "Iets", "lux")]) == {}


# ---------- v2.18.1: review points ----------

def test_shadow_mode_is_respected_when_the_room_sensor_is_missing_during_frost():
    c = SmartController()
    d = c.step(_inp(_t(0), room=None, outside=-4.0, ret=6.0, switch_state="off", hvac_on=False, regeling_actief=False))
    assert d.sensor_problem and d.shadow and d.frost
    assert d.switch is None and not d.frost_forced                      # computed and visible, but nothing is sent


def test_a_cold_guard_room_asks_for_heat_without_teaching_the_house_model():
    ref, guard = SmartController(), SmartController()
    for m in range(0, 40, 2):
        kw = dict(room=20.5, floor=22.0, ret=24.0, freq=40.0, flow=28.0, switch_state="on")
        d_ref = ref.step(_inp(_t(m), **kw))
        d_guard = guard.step(_inp(_t(m), room_deficit=2.0, **kw))
    assert d_guard.setpoint_raw > d_ref.setpoint_raw                    # the shortfall is extra heat demand
    # ... but everything that is learned or predicted still sees the real temperature of the main room
    assert guard._win and guard._win[-1][1] == 20.5 and guard._tr_win[-1][1] == 20.5
    assert guard.tracker.bias == pytest.approx(ref.tracker.bias)
    assert guard.model.to_dict() == ref.model.to_dict()
    assert guard.f_est == pytest.approx(ref.f_est)


def test_health_does_not_cry_wolf_about_a_steady_frequency_or_a_pump_that_stands_still():
    from engine.health import SensorHealth
    h = SensorHealth()
    quiet = _readings(frequentie={"entity": "sensor.hz", "state": "0", "value": 0.0, "age_h": 9.0},
                      vermogen={"entity": "sensor.w", "state": "0", "value": 0.0, "age_h": 9.0},
                      retour={"entity": "sensor.ret", "state": "21", "value": 21.0, "age_h": 9.0})
    assert h.check(_t(0), quiet) == []                                           # pump off for 9 h: nothing is wrong
    steady = _readings(frequentie={"entity": "sensor.hz", "state": "70", "value": 70.0, "age_h": 9.0},
                       vermogen={"entity": "sensor.w", "state": "2400", "value": 2400.0, "age_h": 0.1})
    assert h.check(_t(0), steady) == []                                          # the frequency may stay on 70 Hz for hours
    frozen = _readings(frequentie={"entity": "sensor.hz", "state": "50", "value": 50.0, "age_h": 0.1},
                       vermogen={"entity": "sensor.w", "state": "1500", "value": 1500.0, "age_h": 8.0})
    assert [p.key for p in h.check(_t(0), frozen)] == ["stale_vermogen"]         # a power meter that froze while running is real
    dead_room = _readings(kamer={"entity": "sensor.room", "state": "20", "value": 20.0, "age_h": 8.0})
    assert [p.key for p in h.check(_t(0), dead_room)] == ["stale_kamer"]         # a room sensor must always keep reporting


def test_health_checks_the_extra_rooms_too():
    from engine.health import SensorHealth
    from engine.i18n import role_name
    h = SensorHealth()
    r = _readings(kamer_2={"entity": "sensor.slaap", "state": "unavailable", "value": None, "age_h": None},
                  kamer_3={"entity": "sensor.baby", "state": "55", "value": 55.0, "age_h": 0.1})
    assert h.check(_t(0), r) == []
    pr = h.check(_t(31), r)
    assert sorted(p.key for p in pr) == ["implausible_kamer_3", "unavailable_kamer_2"]
    assert role_name("nl", "kamer_2") == "kamertemperatuur 2" and role_name("en", "kamer_3") == "room temperature 3"
    assert role_name("nl", "pomp_setpoint") == "setpoint van de pomp"


def test_next_defrost_counts_compressor_run_time_not_the_clock():
    from engine.defrost import DefrostLearner
    t0 = datetime(2026, 11, 12, 6, 0, tzinfo=TZ)
    dl = DefrostLearner()
    dl.n, dl.interval, dl.last_start = 5, 54.0, t0
    assert dl.minutes_until_next(t0 + timedelta(hours=4)) == pytest.approx(54.0 - 240.0)        # clock: "overdue" after a standstill
    assert dl.minutes_until_next(t0 + timedelta(hours=4), run_min=10.0) == pytest.approx(44.0)  # run time: still 44 minutes to go
    # the interval is learned from run time too: a 7-hour clock gap with 50 minutes of running is a 50-minute interval
    dl2 = DefrostLearner()
    dl2.update(t0, True, None, True)
    dl2.update(t0 + timedelta(minutes=3), False, 4.0, True)
    dl2.update(t0 + timedelta(hours=7), True, None, True, run_min=50.0)
    assert dl2.interval == pytest.approx(50.0)


def test_a_hot_water_run_that_never_reaches_its_target_waits_before_trying_again():
    s = {**DEFAULTS}
    d = DhwController()
    t = datetime(2026, 11, 12, 13, 0, tzinfo=TZ)
    d.last_legionella = t - timedelta(days=7, hours=12)                    # legionella is due (60 C target)
    assert d.step(t, 50.0, s, 1.0, False, True).mode == "legionella"
    r = d.step(t + timedelta(minutes=50), 55.0, s, 1.0, False, True)       # the boiler tops out at 55 C
    assert r.request is True
    r = d.step(t + timedelta(minutes=95), 55.0, s, 1.0, False, True)       # maximum run time (90 min) is over
    assert r.request is False and r.reason == "max_looptijd" and d.timeouts == 1
    assert d.last_timeout["mode"] == "legionella" and d.last_timeout["tank"] == 55.0 and d.last_timeout["target"] == 60.0
    # it used to start again at once and keep the pump on hot water around the clock; now the house gets its turn
    for minutes in (100, 200, 600, 1300):
        r = d.step(t + timedelta(minutes=minutes), 55.0, s, 0.5, False, True)
        assert r.request is None and not r.active and r.reason == "wachten_na_timeout"
    r = d.step(t + timedelta(minutes=95 + 24 * 60 + 1), 55.0, s, 1.0, False, True)          # a day later it tries again
    assert r.mode == "legionella" and r.request is True


def test_a_normal_hot_water_run_that_times_out_waits_six_hours():
    s = {**DEFAULTS}
    d = DhwController()
    t = datetime(2026, 11, 12, 6, 0, tzinfo=TZ)
    assert d.step(t, 30.0, s, 1.0, False, True).mode == "normal"           # below the minimum, but the target is never reached
    assert d.step(t + timedelta(minutes=95), 40.0, s, 1.0, False, True).reason == "max_looptijd"
    assert d.step(t + timedelta(hours=3), 38.0, s, 1.0, False, True).reason == "wachten_na_timeout"
    assert d.step(t + timedelta(hours=8), 38.0, s, 1.0, False, True).mode == "normal"
    # the wait survives a restart
    d2 = DhwController(); d2.from_dict(d.to_dict())
    assert d2.timeouts == 1 and d2.retry_after == d.retry_after and d2.last_timeout == d.last_timeout


def test_legionella_waits_for_the_afternoon_unless_it_is_cheap_sunny_or_overdue():
    s = {**DEFAULTS}
    day = datetime(2026, 11, 12, 0, 0, tzinfo=TZ)

    def start(hour, weight=1.0, pv=False, overdue=False):
        d = DhwController()
        d.last_legionella = day + timedelta(hours=hour) - (timedelta(days=9) if overdue else timedelta(days=7, hours=12))
        return d.step(day + timedelta(hours=hour), 50.0, s, weight, pv, True).mode

    assert start(3) == "idle"                      # no price sensor: not in the middle of the night
    assert start(13) == "legionella"               # ... but in the afternoon
    assert start(20) == "idle"
    assert start(3, weight=0.7) == "legionella"    # a cheap hour (price control) may be at night
    assert start(3, pv=True) == "legionella"       # a solar surplus too
    assert start(13, weight=1.6) == "idle"         # expensive: wait
    assert start(3, weight=1.6, overdue=True) == "legionella"      # a day overdue starts anyway


def test_a_cold_guard_room_does_not_wind_up_the_integrator_or_teach_the_heating_curve():
    ref, guard = SmartController(), SmartController()
    for m in range(0, 240, 2):
        kw = dict(room=20.4, floor=22.0, ret=24.0, freq=40.0, flow=28.0, switch_state="on")
        ref.step(_inp(_t(m), **kw))
        guard.step(_inp(_t(m), room_deficit=2.0, **kw))
    assert ref.pi_i > 0.05                                            # the test is meaningful: the room lacks 0.6 K
    assert guard.pi_i == pytest.approx(ref.pi_i)                      # the stored integrator only follows the real main room
    assert guard._e_ema == pytest.approx(ref._e_ema)                  # ... and so does the heating-curve learning
    assert guard.trim == ref.trim


def test_the_return_water_dip_must_last_five_minutes_without_a_break():
    c = SmartController()
    kw = dict(room=20.0, outside=8.0, flow=12.0, switch_state="on", hvac_on=True)
    c.step(_inp(_t(0), ret=7.0, **kw))                                 # below the limit (8 C): the timer starts
    c.step(_inp(_t(2), ret=8.5, **kw))                                 # back in the 8-9 C band: the dip ended
    d = c.step(_inp(_t(20), ret=7.0, **kw))                            # a new dip, much later: it starts counting from here
    assert not d.frost
    c.step(_inp(_t(23), ret=7.0, **kw))
    assert c.step(_inp(_t(26), ret=7.0, **kw)).frost                   # 6 minutes below the limit in a row
    assert c.step(_inp(_t(30), ret=8.5, **kw)).frost                   # released only 1 K above the limit
    assert not c.step(_inp(_t(32), ret=9.1, **kw)).frost


def test_price_units_are_turned_into_currency_per_kwh():
    from engine.prices import price_factor
    assert price_factor("EUR/kWh") == 1.0 and price_factor("€/kWh") == 1.0 and price_factor(None) == 1.0
    assert price_factor("ct/kWh") == pytest.approx(0.01) and price_factor("c/kWh") == pytest.approx(0.01)
    assert price_factor("€ct/kWh") == pytest.approx(0.01) and price_factor("øre/kWh") == pytest.approx(0.01)
    assert price_factor("EUR/MWh") == pytest.approx(0.001) and price_factor("€/MWh") == pytest.approx(0.001)
    assert price_factor("ct/MWh") == pytest.approx(0.00001)
    assert price_factor("kWh") == 1.0 and price_factor("zomaar") == 1.0       # unknown: taken as it is


def test_a_flat_price_list_stays_hourly_on_the_days_the_clock_changes():
    from engine.prices import parse_price_forecast
    for day, hours in ((datetime(2026, 10, 25, 12, 0, tzinfo=TZ), 25), (datetime(2026, 3, 29, 12, 0, tzinfo=TZ), 23),
                       (datetime(2026, 11, 12, 12, 0, tzinfo=TZ), 24)):
        slots = parse_price_forecast({"today": [round(0.1 + 0.01 * i, 2) for i in range(hours)]}, day)
        assert len(slots) == hours
        starts = [t.astimezone(timezone.utc) for t, _ in slots]
        assert all((b - a) == timedelta(hours=1) for a, b in zip(starts, starts[1:]))        # exactly hourly, real time
        assert all(t.astimezone(TZ).minute == 0 for t, _ in slots)                           # never 00:57 or 01:55
        assert [t.astimezone(TZ).hour for t, _ in slots][:4] == ([0, 1, 3, 4] if hours == 23 else [0, 1, 2, 2 if hours == 25 else 3])
