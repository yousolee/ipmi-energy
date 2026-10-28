"""Synthetic HPL-like node power traces for testing and error analysis.

Shape: idle -> ramp up -> noisy plateau (with the periodic dips HPL shows
between panel factorisations) -> ramp down -> idle.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .series import Series, as_series


@dataclass(frozen=True)
class HplProfile:
    idle_w: float = 180.0       # dual-socket high-mem node at idle (assumed)
    peak_w: float = 620.0       # plateau under HPL (assumed)
    ramp_s: float = 8.0         # time to reach plateau
    noise_w: float = 12.0       # std-dev of per-second noise on the plateau
    dip_w: float = 60.0         # depth of periodic dips
    dip_period_s: float = 23.0  # roughly one HPL panel iteration
    dip_len_s: float = 3.0
    decay: float = 0.12         # plateau sags this fraction as the matrix shrinks


def hpl_power(t: np.ndarray, job_start: float, job_end: float,
              profile: HplProfile = HplProfile(),
              rng: np.random.Generator | None = None) -> np.ndarray:
    """Power (W) at times ``t`` for a job running over [job_start, job_end]."""
    rng = rng if rng is not None else np.random.default_rng(0)
    p = profile
    length = job_end - job_start
    ramp = min(p.ramp_s, 0.2 * length)
    since = t - job_start
    until = job_end - t

    level = np.clip(np.minimum(since, until) / ramp, 0.0, 1.0) if ramp > 0 else \
        ((since >= 0) & (until >= 0)).astype(float)
    frac = np.clip(since / length, 0.0, 1.0)
    plateau = p.peak_w - p.decay * (p.peak_w - p.idle_w) * frac
    in_dip = (np.mod(since, p.dip_period_s) < p.dip_len_s) & (since > ramp)
    plateau = plateau - p.dip_w * in_dip
    noise = rng.normal(0.0, p.noise_w, size=t.shape) * level
    return np.maximum(p.idle_w + level * (plateau - p.idle_w) + noise, 0.0)


def hpl_trace(job_len_s: float, dt: float = 1.0, pre_idle_s: float = 60.0,
              post_idle_s: float = 60.0, profile: HplProfile = HplProfile(),
              seed: int = 0) -> tuple[Series, float, float]:
    """A sampled trace and its job window ``(series, job_start, job_end)``.

    Times start at 0; the job runs from ``pre_idle_s`` to
    ``pre_idle_s + job_len_s``.
    """
    rng = np.random.default_rng(seed)
    start, end = pre_idle_s, pre_idle_s + job_len_s
    t = np.arange(0.0, end + post_idle_s + dt / 2, dt)
    w = hpl_power(t, start, end, profile, rng)
    return as_series(np.column_stack([t, w])), start, end


def downsample(series: Series, every_s: float, phase_s: float = 0.0) -> Series:
    """Readings a poller would see every ``every_s`` seconds, first at ``phase_s``."""
    targets = np.arange(series.t[0] + phase_s, series.t[-1] + 1e-9, every_s)
    idx = np.searchsorted(series.t, targets - 1e-9)
    idx = np.unique(np.clip(idx, 0, len(series) - 1))
    return Series(series.t[idx].copy(), series.w[idx].copy())
