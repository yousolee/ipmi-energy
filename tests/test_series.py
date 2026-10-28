import numpy as np
import pytest

from energy_calc import as_series, average_power, energy, energy_detail, joules_to_kwh


def ramp(t0=0, t1=100, step=10, a=100.0, b=2.0):
    t = np.arange(t0, t1 + step, step, dtype=float)
    return as_series(np.column_stack([t, a + b * t]))


@pytest.mark.parametrize("method", ["trapezoid", "rectangle"])
def test_constant_power_is_exact(method):
    s = as_series([(t, 250.0) for t in range(0, 61, 5)])
    assert energy(s, 0, 60, method) == pytest.approx(250 * 60)
    assert average_power(s, 0, 60, method) == pytest.approx(250)


def test_linear_ramp_trapezoid_exact():
    # P = 100 + 2t over [0, 100]: E = 100*100 + 100^2 = 20000 J
    assert energy(ramp(), 0, 100, "trapezoid") == pytest.approx(20000)


def test_linear_ramp_rectangle_error_is_b_T_dt_over_2():
    # Left Riemann sum under-reads a rising ramp by b*T*dt/2 = 2*100*10/2
    assert energy(ramp(), 0, 100, "rectangle") == pytest.approx(20000 - 1000)


def test_window_not_aligned_to_samples():
    s = ramp(0, 20, 10)  # samples at 0, 10, 20
    # exact: integral of 100+2t over [5, 15] = 1000 + (225 - 25) = 1200
    assert energy(s, 5, 15, "trapezoid") == pytest.approx(1200)
    # hold-last-value: 100 W on [5,10] + 120 W on [10,15]
    assert energy(s, 5, 15, "rectangle") == pytest.approx(500 + 600)


def test_window_inside_one_interval():
    s = ramp(0, 20, 10)
    assert energy(s, 2, 4, "trapezoid") == pytest.approx(2 * (100 + 2 * 3))


@pytest.mark.parametrize("method", ["trapezoid", "rectangle"])
def test_gap_is_bridged_and_reported(method):
    pts = [(t, 200.0) for t in range(0, 11)] + [(60, 200.0), (70, 200.0)]
    d = energy_detail(pts, 0, 70, method)
    assert d.energy_J == pytest.approx(200 * 70)
    assert d.max_gap_s == pytest.approx(50)
    assert d.coverage == pytest.approx(1.0)


def test_window_beyond_data_is_not_extrapolated():
    s = as_series([(t, 100.0) for t in range(0, 101, 10)])
    d = energy_detail(s, -50, 100)
    assert d.energy_J == pytest.approx(100 * 100)
    assert d.coverage == pytest.approx(100 / 150)


def test_window_with_no_overlap():
    s = as_series([(0, 100.0), (10, 100.0)])
    d = energy_detail(s, 20, 30)
    assert d.energy_J == 0 and d.coverage == 0


def test_unsorted_and_duplicate_samples():
    s = as_series([(10, 100.0), (0, 100.0), (5, 999.0), (5, 100.0)])
    assert list(s.t) == [0, 5, 10]
    assert energy(s, 0, 10) == pytest.approx(1000)


def test_input_is_not_mutated():
    arr = np.array([[10.0, 1.0], [0.0, 2.0]])
    as_series(arr)
    assert arr[0, 0] == 10.0


@pytest.mark.parametrize("bad", [[(0, -1.0), (1, 5.0)], [(0, float("nan")), (1, 5.0)]])
def test_rejects_bad_samples(bad):
    with pytest.raises(ValueError):
        as_series(bad)


def test_rejects_bad_window_and_method():
    s = ramp()
    with pytest.raises(ValueError):
        energy(s, 10, 10)
    with pytest.raises(ValueError):
        energy(s, 0, 10, "simpson")


def test_kwh_conversion():
    assert joules_to_kwh(3.6e6) == pytest.approx(1.0)
