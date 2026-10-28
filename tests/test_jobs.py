import pytest

from energy_calc import Job, as_series, job_energy


def flat(watts, t0=0, t1=100, step=10):
    return as_series([(t, watts) for t in range(t0, t1 + 1, step)])


def job(nodes=("a",), start=0, end=100, alloc=64, total=64):
    return Job("1", tuple(nodes), start, end, alloc, total)


def test_multi_node_job_sums_nodes():
    samples = {"a": flat(100.0), "b": flat(200.0)}
    r = job_energy(job(("a", "b")), samples)
    assert r["total_J"] == pytest.approx(30000)
    assert r["avg_W"] == pytest.approx(300)
    assert r["per_node"]["a"]["energy_J"] == pytest.approx(10000)
    assert r["per_node"]["b"]["energy_J"] == pytest.approx(20000)
    assert r["total_kWh"] == pytest.approx(30000 / 3.6e6)
    assert r["complete"]


def test_idle_subtraction():
    r = job_energy(job(), {"a": flat(300.0)}, idle={"a": 100.0})
    assert r["total_J"] == pytest.approx(30000)
    assert r["dynamic_J"] == pytest.approx(20000)


def test_no_idle_means_no_dynamic():
    r = job_energy(job(), {"a": flat(300.0)})
    assert r["dynamic_J"] is None


def test_cpu_share_attribution():
    r = job_energy(job(alloc=16, total=64), {"a": flat(300.0)},
                   idle={"a": 100.0}, attribution="cpu_share")
    assert r["share"] == pytest.approx(0.25)
    assert r["total_J"] == pytest.approx(7500)
    assert r["dynamic_J"] == pytest.approx(5000)


def test_exclusive_ignores_cpu_counts():
    r = job_energy(job(alloc=16, total=64), {"a": flat(300.0)})
    assert r["total_J"] == pytest.approx(30000)


def test_missing_node_is_flagged():
    r = job_energy(job(("a", "b")), {"a": flat(100.0)}, idle={"a": 50.0, "b": 50.0})
    assert not r["complete"]
    assert any("b: no samples" in w for w in r["warnings"])
    assert r["total_J"] == pytest.approx(10000)
    assert r["dynamic_J"] is None  # can't be trusted with a node missing


def test_missing_idle_baseline_is_flagged():
    r = job_energy(job(), {"a": flat(100.0)}, idle={})
    assert r["dynamic_J"] is None
    assert any("no idle baseline" in w for w in r["warnings"])


def test_partial_coverage_and_gap_warnings():
    samples = {"a": as_series([(0, 100.0), (10, 100.0), (60, 100.0)])}
    r = job_energy(job(end=100), samples, max_gap_s=20)
    assert not r["complete"]
    assert any("cover" in w for w in r["warnings"])
    assert any("gap" in w for w in r["warnings"])


def test_bad_attribution():
    with pytest.raises(ValueError):
        job_energy(job(), {"a": flat(1.0)}, attribution="even")
