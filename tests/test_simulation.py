"""Closed-loop tests against a synthetic floor-heating house (see sim_house.py).

The simulated house has a three-node floor while the controller learns a
two-node model, so these tests check robustness, not just self-consistency.
"""
import pytest

from engine.controller import SmartController
from sim_house import HouseParams, Sim, V1Baseline, kpis


def _after(log, days):
    return [r for r in log if (r["t"] - log[0]["t"]).days >= days]


@pytest.fixture(scope="module")
def run_v2():
    ctrl = SmartController()
    sim = Sim(ctrl, seed=1)
    return ctrl, sim.run(16)


@pytest.fixture(scope="module")
def run_v1():
    b = Sim(V1Baseline(), seed=1)
    return b.run(16, apply=b.ctrl.step)


def test_learning_converges_and_is_plausible(run_v2):
    ctrl, _ = run_v2
    p = ctrl.model.params
    assert ctrl.model.plausible()
    assert ctrl.model.confidence() > 0.7
    # true loss coefficient of the simulated house is 0.06 /h
    assert p.k == pytest.approx(0.06, rel=0.25)
    # dT between supply and return is learned from the data (sim uses 3.5 K)
    assert 2.5 < ctrl.dT_sup < 5.5


def test_comfort_not_worse_than_v1_logic(run_v2, run_v1):
    new = kpis(_after(run_v2[1], 5), 0)
    old = kpis(_after(run_v1, 5), 0)
    assert new["cold_h"] <= old["cold_h"] + 0.5
    assert new["room_2200"] > -0.25            # room one hour after bedtime is at setpoint
    assert new["night_min"] > -0.35


def test_energy_not_worse_than_v1_logic(run_v2, run_v1):
    new = kpis(_after(run_v2[1], 5), 0)
    old = kpis(_after(run_v1, 5), 0)
    assert new["el_kwh"] <= old["el_kwh"] * 1.03


def test_no_hard_run_after_bedtime(run_v2, run_v1):
    """The reason for this project: no strong recovery run during the night."""
    new = kpis(_after(run_v2[1], 5), 0)
    old = kpis(_after(run_v1, 5), 0)
    assert new["night_peak_1h"] <= old["night_peak_1h"]


def test_floor_is_charged_at_bedtime(run_v2):
    k = kpis(_after(run_v2[1], 5), 0)
    assert k["floor_21"] > 25.5      # screed warm at 21:00 (steady-state value is ~26)


def test_works_in_aanvoer_mode():
    sim = Sim(SmartController(), seed=3, mode="aanvoer")
    k = kpis(_after(sim.run(12), 5), 0)
    assert k["cold_h"] < 6 and k["warm_h"] < 3


def test_dynamic_prices_lower_cost_within_comfort_band():
    """Same controller and weather; only the price forecast differs (cheap 01-06, peak 16-21)."""
    blind = kpis(_after(Sim(SmartController(), seed=2, prices=False).run(16), 6), 0)
    aware = kpis(_after(Sim(SmartController(), seed=2, prices=True).run(16), 6), 0)
    assert aware["cost"] < blind["cost"] * 0.97          # measured: about -5 %
    assert aware["night_min"] > -0.45                    # stays inside tolerance (0.3) + margin
    assert aware["cold_h"] < 6.0


def test_survives_sensor_dropout_and_reload():
    ctrl = SmartController()
    sim = Sim(ctrl, seed=4)
    sim.run(6)
    state = ctrl.export_state()
    fresh = SmartController()
    fresh.import_state(state)
    assert fresh.model.params == ctrl.model.params
    sim2 = Sim(fresh, seed=4)
    # a room-sensor outage must not crash or write nonsense setpoints
    def apply(inp):
        if 600 < len(sim2.log) < 700:
            inp.room = None
        return fresh.step(inp)
    sim2.run(1, apply=apply)
    assert all(15 < r["s"] < 45 for r in sim2.log)
