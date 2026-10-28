import csv

import pytest

from energy_calc import InputError, load_jobs, load_samples, parse_timestamp
from energy_calc.cli import main


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("text,expected", [
    ("1700000000", 1700000000.0),
    ("1700000000.5", 1700000000.5),
    ("2023-11-14T22:13:20Z", 1700000000.0),
    ("2023-11-14T22:13:20", 1700000000.0),          # naive -> UTC
    ("2023-11-14T17:13:20-05:00", 1700000000.0),
])
def test_parse_timestamp(text, expected):
    assert parse_timestamp(text) == pytest.approx(expected)


def test_parse_timestamp_rejects_garbage():
    with pytest.raises(ValueError):
        parse_timestamp("yesterday")


def test_load_samples_groups_by_node(tmp_path):
    p = write(tmp_path / "s.csv", "timestamp,node,watts\n0,a,1\n10,b,2\n5,a,3\n")
    s = load_samples(p)
    assert list(s["a"].t) == [0, 5]
    assert list(s["b"].w) == [2]


def test_load_samples_missing_column(tmp_path):
    p = write(tmp_path / "s.csv", "time,node,watts\n0,a,1\n")
    with pytest.raises(InputError, match="missing column"):
        load_samples(p)


def test_load_samples_bad_value_names_line(tmp_path):
    p = write(tmp_path / "s.csv", "timestamp,node,watts\n0,a,1\n5,a,lots\n")
    with pytest.raises(InputError, match=":3:"):
        load_samples(p)


def test_load_jobs_quoted_nodes(tmp_path):
    p = write(tmp_path / "j.csv",
              'jobid,nodes,start,end,alloc_cpus,total_cpus\n7,"hm01,hm02",0,100,32,128\n')
    (j,) = load_jobs(p)
    assert j.nodes == ("hm01", "hm02") and j.duration == 100


@pytest.mark.parametrize("row", ['7,a,100,0,1,1', '7,a,0,100,9,4', '7,"",0,100,1,1'])
def test_load_jobs_rejects_invalid(tmp_path, row):
    p = write(tmp_path / "j.csv", "jobid,nodes,start,end,alloc_cpus,total_cpus\n" + row + "\n")
    with pytest.raises(InputError):
        load_jobs(p)


def test_cli_end_to_end(tmp_path):
    samples = "timestamp,node,watts\n" + "".join(
        f"{t},{n},{w}\n" for t in range(0, 101, 10) for n, w in (("a", 300), ("b", 200)))
    s = write(tmp_path / "s.csv", samples)
    j = write(tmp_path / "j.csv",
              'jobid,nodes,start,end,alloc_cpus,total_cpus\n1,"a,b",0,100,64,64\n'
              '2,a,50,100,16,64\n')
    i = write(tmp_path / "i.csv", "node,idle_watts\na,100\nb,100\n")
    out, per_node = tmp_path / "out.csv", tmp_path / "nodes.csv"

    rc = main(["--samples", str(s), "--jobs", str(j), "--idle", str(i),
               "--attribution", "cpu_share", "--out", str(out),
               "--per-node-out", str(per_node)])
    assert rc == 0
    rows = {r["jobid"]: r for r in csv.DictReader(out.open())}
    assert float(rows["1"]["total_J"]) == pytest.approx(50000)
    assert float(rows["1"]["dynamic_J"]) == pytest.approx(30000)
    assert float(rows["2"]["total_J"]) == pytest.approx(300 * 50 * 0.25)
    assert rows["1"]["complete"] == "True"
    assert len(list(csv.DictReader(per_node.open()))) == 3


def test_cli_reports_input_errors(tmp_path, capsys):
    rc = main(["--samples", str(tmp_path / "nope.csv"), "--jobs", str(tmp_path / "j.csv")])
    assert rc == 2
    assert "error" in capsys.readouterr().err
