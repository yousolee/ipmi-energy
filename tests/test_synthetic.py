import numpy as np
import pytest

from energy_calc import energy
from energy_calc.synthetic import HplProfile, downsample, hpl_trace


def test_trace_shape_idle_then_plateau_then_idle():
    p = HplProfile()
    s, start, end = hpl_trace(600, profile=p, seed=1)
    before = s.w[s.t < start]
    after = s.w[s.t > end]
    middle = s.w[(s.t > start + 60) & (s.t < end - 60)]
    assert np.allclose(before, p.idle_w) and np.allclose(after, p.idle_w)
    assert p.idle_w + 0.6 * (p.peak_w - p.idle_w) < middle.mean() < p.peak_w + 3 * p.noise_w


def test_trace_is_reproducible():
    a, _, _ = hpl_trace(120, seed=3)
    b, _, _ = hpl_trace(120, seed=3)
    assert np.array_equal(a.w, b.w)


def test_downsample_picks_every_kth_reading():
    s, _, _ = hpl_trace(120)
    d = downsample(s, 10, phase_s=3)
    assert d.t[0] == 3 and np.all(np.diff(d.t) == 10)
    assert np.array_equal(d.w, s.w[np.isin(s.t, d.t)])


def test_one_second_downsample_matches_original():
    s, start, end = hpl_trace(300)
    assert energy(downsample(s, 1), start, end) == pytest.approx(energy(s, start, end))
