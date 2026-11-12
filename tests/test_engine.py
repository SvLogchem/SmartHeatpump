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
