"""Learns how low the water setpoint can sit above the return temperature while the
compressor still keeps running (and therefore runs slowly).

The heat pump decides its own frequency from the gap between the setpoint it is given and
the return temperature: a large gap means high frequency, a gap near zero means the
compressor idles down or stops. We cannot command the frequency, but we can choose the gap.
Observations are binned by gap (0.5 K); for every bin we keep exponentially weighted
averages of "was the compressor running" and its frequency. The *floor* is the smallest gap
that was seen to keep the compressor running.
"""
from __future__ import annotations

BIN = 0.5
LO, HI = -3.0, 9.0
MIN_N = 8          # samples before a bin is trusted
RUN_OK = 0.8       # fraction of samples that must show a running compressor
ALPHA = 0.05       # weight of a new sample


def _bin(delta: float) -> int:
    return int(round(max(LO, min(HI, delta)) / BIN))


class ModulationLearner:
    def __init__(self) -> None:
        # bin -> [n, run_fraction, mean_freq, mean_kw]
        self.bins: dict[int, list[float]] = {}

    def reset(self) -> None:
        self.bins = {}

    def observe(self, delta: float, running: bool, freq: float | None, kw: float | None) -> None:
        b = self.bins.setdefault(_bin(delta), [0.0, 1.0 if running else 0.0, freq or 0.0, kw or 0.0])
        b[0] += 1.0
        a = max(ALPHA, 1.0 / b[0])
        b[1] += a * ((1.0 if running else 0.0) - b[1])
        if running and freq is not None:
            b[2] += a * (freq - b[2])
        if running and kw is not None:
            b[3] += a * (kw - b[3])

    def floor(self) -> float | None:
        """Smallest gap (K) with a trusted bin that kept the compressor running."""
        ok = [k for k, v in self.bins.items() if v[0] >= MIN_N and v[1] >= RUN_OK]
        return min(ok) * BIN if ok else None

    def needs_probe(self) -> bool:
        """True when the bin just below the floor has too little data to judge."""
        f = self.floor()
        if f is None:
            return False
        below = self.bins.get(_bin(f) - 1)
        return f > LO + BIN and (below is None or below[0] < MIN_N)

    def freq_at_floor(self) -> float | None:
        f = self.floor()
        return None if f is None else round(self.bins[_bin(f)][2], 1)

    def to_dict(self) -> dict:
        return {str(k): [round(x, 4) for x in v] for k, v in self.bins.items()}

    def from_dict(self, d: dict) -> None:
        self.bins = {}
        for k, v in (d or {}).items():
            n, run, fr, kw = (float(x) for x in v)
            self.bins[int(k)] = [n, run, fr, kw]
