"""Power time series and energy integration for a single node."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence, Union

import numpy as np

METHODS = ("trapezoid", "rectangle")
J_PER_KWH = 3.6e6


@dataclass(frozen=True)
class Series:
    """Power samples for one node: times in Unix seconds, power in watts.

    Construct with :func:`as_series`, which sorts, validates and removes
    duplicate timestamps.
    """

    t: np.ndarray
    w: np.ndarray

    def __len__(self) -> int:
        return len(self.t)


@dataclass(frozen=True)
class WindowEnergy:
    """Result of integrating one series over one window."""

    energy_J: float
    covered_s: float      # seconds of the window that have data on both sides
    requested_s: float    # t_end - t_start
    n_samples: int        # samples strictly inside the window
    max_gap_s: float      # largest spacing between points used

    @property
    def coverage(self) -> float:
        return self.covered_s / self.requested_s if self.requested_s > 0 else 0.0


SamplesLike = Union["Series", Iterable[Sequence[float]], np.ndarray]


def as_series(samples: SamplesLike) -> Series:
    """Build a validated, time-sorted :class:`Series`.

    Accepts an existing Series, an (N, 2) array, or an iterable of
    ``(timestamp, watts)`` pairs. Duplicate timestamps keep the last value.
    """
    if isinstance(samples, Series):
        return samples
    arr = np.asarray(list(samples) if not isinstance(samples, np.ndarray) else samples,
                     dtype=float)
    if arr.size == 0:
        return Series(np.empty(0), np.empty(0))
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError("samples must be (timestamp, watts) pairs")
    if not np.all(np.isfinite(arr)):
        raise ValueError("samples contain NaN or infinite values")
    if np.any(arr[:, 1] < 0):
        raise ValueError("samples contain negative watts")
    order = np.argsort(arr[:, 0], kind="stable")
    t, w = arr[order, 0], arr[order, 1]
    # keep the last of any duplicate timestamps
    keep = np.append(t[1:] != t[:-1], True)
    return Series(t[keep].copy(), w[keep].copy())


def _value_at(s: Series, x: float, method: str) -> float:
    """Power at time x, which must lie within [s.t[0], s.t[-1]].

    Trapezoid uses linear interpolation; rectangle uses hold-last-value
    (the reading in effect at x), which is what that method assumes.
    """
    if method == "trapezoid":
        return float(np.interp(x, s.t, s.w))
    idx = int(np.searchsorted(s.t, x, side="right")) - 1
    return float(s.w[max(idx, 0)])


def _check_method(method: str) -> None:
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}, got {method!r}")


def energy_detail(samples: SamplesLike, t_start: float, t_end: float,
                  method: str = "trapezoid") -> WindowEnergy:
    """Integrate power over [t_start, t_end], clipped to the data's time span.

    Boundary values are interpolated (see :func:`_value_at`), so a window that
    does not line up with sample times is handled exactly under each method's
    own assumption. Parts of the window before the first or after the last
    sample are *not* extrapolated; they show up as coverage < 1.
    """
    _check_method(method)
    if not (np.isfinite(t_start) and np.isfinite(t_end)):
        raise ValueError(f"window bounds must be finite, got ({t_start}, {t_end})")
    if t_end <= t_start:
        raise ValueError(f"t_end ({t_end}) must be after t_start ({t_start})")
    s = as_series(samples)
    requested = t_end - t_start
    if len(s) < 2:
        return WindowEnergy(0.0, 0.0, requested, len(s), float("inf"))

    a, b = max(t_start, s.t[0]), min(t_end, s.t[-1])
    if b <= a:
        return WindowEnergy(0.0, 0.0, requested, 0, float("inf"))

    inside = (s.t > a) & (s.t < b)
    t = np.concatenate(([a], s.t[inside], [b]))
    w = np.concatenate(([_value_at(s, a, method)], s.w[inside],
                        [_value_at(s, b, method)]))
    dt = np.diff(t)
    if method == "trapezoid":
        e = float(np.sum(0.5 * (w[:-1] + w[1:]) * dt))
    else:
        e = float(np.sum(w[:-1] * dt))
    return WindowEnergy(e, float(b - a), requested, int(inside.sum()), float(dt.max()))


def energy(samples: SamplesLike, t_start: float, t_end: float, method: str = "trapezoid") -> float:
    """Energy in joules over [t_start, t_end]. See :func:`energy_detail`."""
    return energy_detail(samples, t_start, t_end, method).energy_J


def average_power(samples: SamplesLike, t_start: float, t_end: float,
                  method: str = "trapezoid") -> float:
    """Mean power in watts over the covered part of [t_start, t_end]."""
    d = energy_detail(samples, t_start, t_end, method)
    return d.energy_J / d.covered_s if d.covered_s > 0 else float("nan")


def joules_to_kwh(joules: float) -> float:
    return joules / J_PER_KWH
