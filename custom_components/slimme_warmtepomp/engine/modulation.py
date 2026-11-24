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
FREQ_SANE = 150.0  # readings above this are sensor glitches, not a compressor frequency
REACH_HZ = 1.0     # a row within this many Hz of the maximum counts as "maximum reached"
SLOPE_MIN, SLOPE_MAX = 3.0, 25.0   # Hz per K used to extrapolate a table that has not reached the maximum yet
EXTRAPOLATE_K = 3.0                # never extrapolate further than this beyond the last measured gap


def _bin(delta: float) -> int:
    return int(round(max(LO, min(HI, delta)) / BIN))


class ModulationLearner:
    def __init__(self) -> None:
        # bin -> [n, run_fraction, mean_freq, mean_kw]
        self.bins: dict[int, list[float]] = {}
        # highest / lowest compressor frequency ever seen while running (the pump's real range)
        self.peak = 0.0
        self.lowest = 0.0

    def reset(self) -> None:
        self.bins = {}
        self.peak = 0.0
        self.lowest = 0.0

    def shrink(self, keep: float) -> None:
        """Forget part of the evidence: bins fall back below the trust threshold and are relearned."""
        for b in self.bins.values():
            b[0] = min(b[0], MIN_N * 3.0) * keep
        self.bins = {k: v for k, v in self.bins.items() if v[0] >= 1.0}

    def observe(self, delta: float, running: bool, freq: float | None, kw: float | None) -> None:
        if running and freq is not None and 5.0 <= freq <= FREQ_SANE:
            self.peak = max(self.peak, freq)
            self.lowest = freq if self.lowest <= 0 else min(self.lowest, freq)
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

    def trusted(self) -> list[tuple[float, float, float]]:
        """(gap K, mean frequency Hz, mean thermal kW) of every trusted bin where the compressor ran."""
        rows = sorted((k * BIN, v[2], v[3]) for k, v in self.bins.items()
                      if v[0] >= MIN_N and v[1] >= 0.5 and v[2] > 0)
        out, top = [], 0.0
        for g, f, kw in rows:        # the pump never runs slower at a larger gap: smooth out stale or polluted bins
            top = max(top, f)
            out.append((g, top, kw))
        return out

    def gap_cap(self, f_max: float, margin: float = 0.25) -> float | None:
        """Largest gap that keeps the compressor at or below ``f_max`` Hz.

        None when there is no evidence that the limit would be exceeded (no cap needed or
        not enough data yet): the controller then does not limit anything.
        """
        tb = self.trusted()
        if len(tb) < 2 or f_max <= 0:
            return None
        ok = None
        for gap, freq, _kw in tb:
            if freq > f_max:
                return max(0.0, (ok if ok is not None else gap) - margin)
            ok = gap
        return None

    def f_range(self, f_min: float = 0.0, f_max: float = 0.0) -> tuple[float, float]:
        """Minimum / maximum frequency of the pump: the setting when given, otherwise what was observed."""
        return (f_min if f_min > 0 else round(self.lowest)), (f_max if f_max > 0 else round(self.peak))

    def curve(self, f_min: float = 0.0, f_max: float = 0.0) -> list[dict]:
        """Complete frequency-per-gap table from the minimum to the maximum compressor frequency.

        Rows are 0.5 K apart. Measured bins are used as they are, gaps in between are interpolated and,
        while the maximum has not been seen yet, the table is extended with an estimate. The table stops
        at the first gap that reaches the maximum frequency: a larger gap gives no higher frequency
        ("+5 K = 70 Hz" says everything there is to say, "+9 K = 69 Hz" would only be noise).
        Every row carries its source: ``gemeten``, ``interpolatie`` or ``schatting``.
        """
        rows = self.trusted()
        lo, hi = self.f_range(f_min, f_max)
        if not rows:
            return []
        pts: list[tuple[int, float, float]] = []                       # (bin, Hz, kW) measured
        for g, f, kw in rows:
            f = max(lo, f) if lo > 0 else f
            if hi > 0:
                f = min(f, hi)
            pts.append((int(round(g / BIN)), f, kw))
            if hi > 0 and f >= hi - REACH_HZ:
                pts[-1] = (pts[-1][0], hi, kw)
                break
        reached = hi > 0 and pts[-1][1] >= hi - 1e-9
        measured = {b: (f, kw) for b, f, kw in pts}
        out: list[dict] = []
        first, last = pts[0][0], pts[-1][0]
        for b in range(first, last + 1):
            if b in measured:
                f, kw = measured[b]
                src = "gemeten"
            else:
                lo_p = max(p for p in pts if p[0] < b)
                hi_p = min(p for p in pts if p[0] > b)
                w = (b - lo_p[0]) / (hi_p[0] - lo_p[0])
                f, kw, src = lo_p[1] + w * (hi_p[1] - lo_p[1]), lo_p[2] + w * (hi_p[2] - lo_p[2]), "interpolatie"
            out.append({"verschil": round(b * BIN, 1), "frequentie": round(f), "vermogen_kw": round(kw, 2), "bron": src})
        if hi > 0 and not reached and len(pts) >= 2 and pts[-1][1] > pts[0][1]:
            slope = (pts[-1][1] - pts[0][1]) / ((pts[-1][0] - pts[0][0]) * BIN)
            slope = max(SLOPE_MIN, min(SLOPE_MAX, slope))
            f, kw, b = pts[-1][1], pts[-1][2], last
            kw_slope = (pts[-1][2] - pts[0][2]) / ((pts[-1][0] - pts[0][0]) * BIN)
            while f < hi - 1e-9 and (b - last) * BIN < EXTRAPOLATE_K and b * BIN < HI:
                b += 1
                f, kw = min(hi, f + slope * BIN), max(kw, kw + kw_slope * BIN)
                out.append({"verschil": round(b * BIN, 1), "frequentie": round(f), "vermogen_kw": round(kw, 2), "bron": "schatting"})
        return out

    def table(self, f_min: float = 0.0, f_max: float = 0.0, full: bool = False) -> dict:
        """{"+3.0": 50, ...}. Measured bins only (default) or the complete curve (``full``)."""
        if full:
            return {f"{r['verschil']:+.1f}": r["frequentie"] for r in self.curve(f_min, f_max)}
        return {f"{g:+.1f}": round(f) for g, f, _ in self.trusted()}

    def to_dict(self) -> dict:
        out = {str(k): [round(x, 4) for x in v] for k, v in self.bins.items()}
        if self.peak > 0:
            out["_range"] = [round(self.peak, 1), round(self.lowest, 1)]
        return out

    def from_dict(self, d: dict) -> None:
        self.bins = {}
        self.peak = self.lowest = 0.0
        for k, v in (d or {}).items():
            if k == "_range":
                try:
                    self.peak, self.lowest = float(v[0]), float(v[1])
                except (TypeError, ValueError, IndexError):
                    pass
                continue
            n, run, fr, kw = (float(x) for x in v)
            self.bins[int(k)] = [n, run, fr, kw]
