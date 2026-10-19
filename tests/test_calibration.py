import csv
import json
import shutil

import pytest

from loadlens.calibration import (
    DETECTORS,
    FLOOR_MS,
    FLOORED,
    WINDOWED,
    analyze,
    clopper_pearson_lower,
    clopper_pearson_upper,
    render_markdown,
)
from loadlens.compare import TransactionComparison

NOMINAL = "2026-10-17-nominal-short.jtl"
FLOORED_2_OF_3 = "windowed + floor: at least 2 of its 3 conditions"


def abba_dir(tmp_path, jmeter_fixture, name, candidate, scale_b=1.0, shift_b_ms=0):
    """A-B-B-A directory built from one real JTL. The B segments are a derived copy with every
    latency multiplied by `scale_b`, then raised by `shift_b_ms` (synthetic, to give the detectors
    a known effect)."""
    directory = tmp_path / name
    directory.mkdir()
    source = jmeter_fixture(NOMINAL)
    for segment in ("A1", "A2"):
        shutil.copy(source, directory / f"{segment}.jtl")
    with source.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    elapsed = rows[0].index("elapsed")
    for row in rows[1:]:
        row[elapsed] = str(round(int(row[elapsed]) * scale_b) + shift_b_ms)
    for segment in ("B1", "B2"):
        with (directory / f"{segment}.jtl").open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle, lineterminator="\n").writerows(rows)
    meta = {
        "candidate": candidate,
        "baseline": ["A1", "A2"],
        "candidate_segments": ["B1", "B2"],
        "ramp_s": 2,
        "cpu_count": 2,
    }
    (directory / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return directory


@pytest.mark.parametrize("trials", [10, 30, 60])
def test_clopper_pearson_upper_bound_at_zero_events_has_a_closed_form(trials):
    assert clopper_pearson_upper(0, trials) == pytest.approx(1 - 0.05 ** (1 / trials))


def test_clopper_pearson_upper_bound_grows_with_events():
    assert (
        clopper_pearson_upper(0, 10) < clopper_pearson_upper(1, 10) < clopper_pearson_upper(5, 10)
    )
    assert clopper_pearson_upper(10, 10) == 1.0
    with pytest.raises(ValueError):
        clopper_pearson_upper(0, 0)


@pytest.mark.parametrize("trials", [5, 10])
def test_clopper_pearson_lower_bound_at_all_events_has_a_closed_form(trials):
    assert clopper_pearson_lower(trials, trials) == pytest.approx(0.05 ** (1 / trials))
    assert clopper_pearson_lower(0, trials) == 0.0
    with pytest.raises(ValueError):
        clopper_pearson_lower(0, 0)


def comparison(p95_baseline_ms, p95_candidate_ms, p_value=0.001, cliffs_delta=0.5):
    """A comparison whose windowed test and Cliff's delta both pass by default."""
    rel = (p95_candidate_ms - p95_baseline_ms) / p95_baseline_ms
    return TransactionComparison(
        transaction="t",
        baseline_count=100,
        candidate_count=100,
        p95_baseline_ms=p95_baseline_ms,
        p95_candidate_ms=p95_candidate_ms,
        delta_p95_rel=rel,
        raw_p_value=None,
        raw_cliffs_delta=None,
        windows_baseline=24,
        windows_candidate=24,
        windowed_p_value=p_value,
        windowed_cliffs_delta=cliffs_delta,
        bootstrap_delta_p95_low=None,
        bootstrap_delta_p95_high=None,
    )


@pytest.mark.parametrize(
    ("p95_a", "p95_b", "windowed", "floored"),
    [
        (6, 7, True, False),  # +17%, one millisecond: the step of the known false positives
        (6, 8, True, True),  # +33%, two milliseconds
        (10, 12, True, True),  # +20%, two milliseconds
        (30, 32, False, False),  # two milliseconds but +7%: the relative condition still holds
    ],
)
def test_floor_needs_two_milliseconds_on_top_of_ten_percent(p95_a, p95_b, windowed, floored):
    assert FLOOR_MS == 2
    c = comparison(p95_a, p95_b)
    assert DETECTORS[WINDOWED](c) is windowed
    assert DETECTORS[FLOORED](c) is floored


def test_a_significant_one_millisecond_step_meets_two_of_the_floored_conditions():
    # In the verdict this is WARN (weak regression), no longer FAIL.
    assert DETECTORS[FLOORED_2_OF_3](comparison(6, 7)) is True
    assert DETECTORS[FLOORED_2_OF_3](comparison(6, 7, p_value=0.5)) is False


def test_floor_without_a_p95_flags_nothing():
    c = comparison(6, 8).model_copy(update={"p95_candidate_ms": None})
    assert DETECTORS[FLOORED](c) is False


def test_identical_aa_run_flags_nothing(tmp_path, jmeter_fixture):
    report = analyze([abba_dir(tmp_path, jmeter_fixture, "aa", "none")], replicates=200)
    for name, entry in report["detectors"].items():
        assert entry["false_positive_runs"] == 0, name
        assert entry["aa_runs"] == 1


def test_doubled_latency_is_detected_on_the_expected_transaction(tmp_path, jmeter_fixture):
    run = abba_dir(tmp_path, jmeter_fixture, "n1", "N_PLUS_ONE", scale_b=2.0)
    report = analyze([run], replicates=200)
    entry = report["detectors"]["mission: raw p<0.05 & dp95>+10% & delta>=0.147"]
    assert entry["detected_N_PLUS_ONE"] == "1/1"
    assert "aa_runs" not in entry  # no A/A run: no false-positive figure, not a zero


def test_self_check_flags_a_run_whose_baseline_segments_disagree(tmp_path, jmeter_fixture):
    mission = "mission: raw p<0.05 & dp95>+10% & delta>=0.147"
    steady = abba_dir(tmp_path, jmeter_fixture, "steady", "none")
    drifting = abba_dir(tmp_path, jmeter_fixture, "drifting", "none")
    # Derived A2: the same rows, every latency doubled, so A1 and A2 disagree.
    with (drifting / "A2.jtl").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    elapsed = rows[0].index("elapsed")
    for row in rows[1:]:
        row[elapsed] = str(int(row[elapsed]) * 2)
    with (drifting / "A2.jtl").open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)

    runs = {r["directory"]: r for r in analyze([steady, drifting], replicates=50)["runs"]}
    assert runs["steady"]["inconsistent"][mission] is False
    assert runs["drifting"]["inconsistent"][mission] is True


def test_unfinished_run_is_excluded_with_its_reason(tmp_path, jmeter_fixture):
    done = abba_dir(tmp_path, jmeter_fixture, "done", "none")
    unfinished = tmp_path / "unfinished"
    unfinished.mkdir()
    report = analyze([done, unfinished], replicates=50)
    assert [r["directory"] for r in report["runs"]] == ["done"]
    assert report["excluded"] == [
        {"directory": "unfinished", "reason": "no meta.json (the run did not finish)"}
    ]


def test_segment_far_longer_than_its_schedule_is_excluded(tmp_path, jmeter_fixture):
    # Observed on 2026-10-17: the host slept during a segment, which then spanned 4.5 hours.
    run = abba_dir(tmp_path, jmeter_fixture, "slept", "POOL")
    meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
    meta["hold_s"] = 20  # the fixture spans about 22 s, within 2 + 20 + 30 s
    (run / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    assert analyze([run], replicates=20)["excluded"] == []

    with (run / "B2.jtl").open(encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    first, rest = lines[-1].split(",", 1)
    lines[-1] = f"{int(first) + 4 * 3600 * 1000},{rest}"  # last sample 4 hours later
    (run / "B2.jtl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = analyze([run], replicates=20)
    assert report["runs"] == []
    assert report["excluded"][0]["reason"].startswith("segment B2 spans 14422 s")


def test_segment_with_too_much_wall_clock_is_excluded(tmp_path, jmeter_fixture):
    # The JTL of a segment the host slept through spanned 64 s; only the host clock showed it.
    run = abba_dir(tmp_path, jmeter_fixture, "suspended", "POOL")
    meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
    meta |= {"hold_s": 60, "segment_wall_s": {"A1": 73, "B1": 72, "B2": 16366, "A2": 73}}
    (run / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    report = analyze([run], replicates=20)
    assert report["excluded"] == [
        {
            "directory": "suspended",
            "reason": "segment B2 took 16366 s of wall clock for a 62 s schedule",
        }
    ]


def test_report_lists_every_detector_and_renders(tmp_path, jmeter_fixture):
    runs = [
        abba_dir(tmp_path, jmeter_fixture, "aa", "none"),
        abba_dir(tmp_path, jmeter_fixture, "lock", "LOCK", scale_b=1.5),
    ]
    report = analyze(runs, replicates=100)
    assert set(report["detectors"]) == set(DETECTORS)
    assert len(report["runs"]) == 2
    assert report["aa_stability"]["raw_cv"]  # one value per transaction and segment
    text = render_markdown(report)
    assert (
        "| Detector | A/A runs flagged | FPR upper bound (95%) | A/A self-check inconsistent | "
        "A/A flagged and consistent | LOCK detected (inconsistent) |"
    ) in text
    assert text.isascii()  # printable on a cp1252 Windows console


def test_run_with_another_cpu_count_is_excluded_when_one_is_expected(tmp_path, jmeter_fixture):
    run = abba_dir(tmp_path, jmeter_fixture, "two-cpus", "none")  # meta.json: cpu_count 2
    assert analyze([run], replicates=20, expected_cpus=2)["excluded"] == []
    report = analyze([run], replicates=20, expected_cpus=4)
    assert report["excluded"] == [{"directory": "two-cpus", "reason": "cpu_count 2, expected 4"}]
    assert "1 of 1 runs." in render_markdown(report)


def test_report_lists_the_one_millisecond_steps_the_floor_removes(tmp_path, jmeter_fixture):
    # Every B latency raised by 1 ms: get_payment, p95 6 ms in this fixture, rises by 17%.
    run = abba_dir(tmp_path, jmeter_fixture, "step", "none", shift_b_ms=1)
    report = analyze([run], replicates=50)
    flags = report["runs"][0]["flags"]
    assert "get_payment" in flags[WINDOWED]
    assert flags[FLOORED] == []
    removed = report["floor_removed"]
    assert {f["transaction"] for f in removed} == set(flags[WINDOWED])
    assert all(f["p95_candidate_ms"] - f["p95_baseline_ms"] == 1 for f in removed)
    assert "| step | none | get_payment | 6 -> 7 |" in render_markdown(report)

    # Raised by 2 ms instead, the floor keeps what the windowed detector flags.
    run = abba_dir(tmp_path, jmeter_fixture, "two-steps", "none", shift_b_ms=2)
    report = analyze([run], replicates=50)
    assert report["floor_removed"] == []
    assert "get_payment" in report["runs"][0]["flags"][FLOORED]
