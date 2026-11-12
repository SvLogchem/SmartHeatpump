"""Small exponentially weighted ridge regression with a prior (pure Python)."""
from __future__ import annotations


class RidgeEW:
    """Online least squares: min sum w*(y - x.theta)^2 + sum lam_i (theta_i - prior_i)^2.

    Old samples fade with factor ``forget`` per update. The prior keeps the
    solution sane while there is little or poorly exciting data, and the
    bounds keep it physical.
    """

    def __init__(self, prior, lam, lo, hi, forget: float = 0.9985):
        self.n = len(prior)
        self.prior = list(prior)
        self.lam = list(lam)
        self.lo = list(lo)
        self.hi = list(hi)
        self.forget = forget
        self.reset()

    def reset(self) -> None:
        n = self.n
        self.A = [[0.0] * n for _ in range(n)]
        self.b = [0.0] * n
        self.weight = 0.0

    def update(self, x, y: float, w: float = 1.0) -> None:
        f = self.forget
        n = self.n
        for i in range(n):
            self.b[i] = f * self.b[i] + w * x[i] * y
            row = self.A[i]
            for j in range(n):
                row[j] = f * row[j] + w * x[i] * x[j]
        self.weight = f * self.weight + w

    def solve(self) -> list[float]:
        n = self.n
        m = [
            [self.A[i][j] + (self.lam[i] if i == j else 0.0) for j in range(n)]
            + [self.b[i] + self.lam[i] * self.prior[i]]
            for i in range(n)
        ]
        for col in range(n):
            piv = max(range(col, n), key=lambda r: abs(m[r][col]))
            if abs(m[piv][col]) < 1e-12:
                return list(self.prior)
            m[col], m[piv] = m[piv], m[col]
            p = m[col][col]
            for j in range(col, n + 1):
                m[col][j] /= p
            for r in range(n):
                if r != col:
                    fac = m[r][col]
                    if fac:
                        for j in range(col, n + 1):
                            m[r][j] -= fac * m[col][j]
        theta = [m[i][n] for i in range(n)]
        return [min(max(theta[i], self.lo[i]), self.hi[i]) for i in range(n)]

    def confidence(self, idx=None) -> float:
        """0..1: how much the data (not the prior) determines the weakest parameter."""
        idx = range(self.n) if idx is None else idx
        return min(self.A[i][i] / (self.A[i][i] + self.lam[i]) for i in idx)

    def to_dict(self) -> dict:
        return {"A": self.A, "b": self.b, "weight": self.weight}

    def from_dict(self, d: dict) -> None:
        try:
            A, b = d["A"], d["b"]
            if len(A) == self.n and len(b) == self.n and all(len(r) == self.n for r in A):
                self.A = [[float(v) for v in r] for r in A]
                self.b = [float(v) for v in b]
                self.weight = float(d.get("weight", 0.0))
        except (KeyError, TypeError, ValueError):
            self.reset()
