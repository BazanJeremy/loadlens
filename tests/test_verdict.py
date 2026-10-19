import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from loadlens import calibration, compare
from loadlens.cli import main
from loadlens.compare import TransactionComparison
from loadlens.schema import Run, RunMetadata, Samples, Tool, TransactionAggregate
from loadlens.verdict import (
    EXIT_CODES,
    Level,
    RegressionRule,
    _check_regression,
    evaluate,
    load_config,
)

SHIPPED = Path(__file__).resolve().parents[1] / "config" / "slo.yaml"
META = RunMetadata(tool=Tool.JMETER, source_file="x", started_at=datetime(2026, 1, 1, tzinfo=UTC))


@pytest.fixture(scope="module")
def config():
    return load_config(SHIPPED)


def run_of(elapsed, transaction="t", step_ms=100, success=None):
    """Samples `step_ms` apart: 600 samples at 100 ms = 60 s = 12 windows of 5 s."""
    n = len(elapsed)
    return Run(
        metadata=META,
        samples=Samples(
            start_ms=[i * step_ms for i in range(n)],
            elapsed_ms=[int(e) for e in elapsed],
            transaction=[transaction] * n,
            success=success or [True] * n,
            response_code=["200"] * n,
        ),
    )


def latencies(mean, sd, n=600, seed=0):
    return np.clip(np.random.default_rng(seed).normal(mean, sd, n), 1, None).round()


def levels(verdict):
    return [(r.level, r.check) for r in verdict.reasons]


# --- configuration ---------------------------------------------------------------------------


def test_shipped_regression_rule_is_the_calibrated_detector(config):
    """config/slo.yaml must hold the detector ADR-004 measured, not a retuned one."""
    rule = config.regression
    assert rule.window_s == compare.DEFAULT_WINDOW_S
    assert rule.min_window_samples == compare.DEFAULT_MIN_WINDOW_SAMPLES
    assert rule.alpha == calibration.ALPHA
    assert rule.min_delta_p95_rel == calibration.EFFECT_THRESHOLD
    assert rule.min_cliffs_delta == calibration.DELTA_THRESHOLD


def test_shipped_slos_are_the_mission_defaults(config):
    assert (config.hard.p99_ms, config.hard.error_rate) == (800, 0.005)
    assert (config.soft.p95_ms, config.soft.apdex, config.soft.throughput_tolerance) == (
        300,
        0.90,
        0.05,
    )
    assert config.apdex_t_ms == 300


def test_unknown_or_missing_keys_are_rejected(tmp_path):
    text = SHIPPED.read_text(encoding="utf-8")
    extra = tmp_path / "extra.yaml"
    extra.write_text(text + "\nunexpected: 1\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(extra)
    missing = tmp_path / "missing.yaml"
    missing.write_text(text.replace("apdex_t_ms: 300", ""), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(missing)


def test_invalid_yaml_is_a_value_error(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("hard: [unclosed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid YAML"):
        load_config(bad)


# --- SLOs ------------------------------------------------------------------------------------


def test_healthy_run_without_baseline_passes_and_says_so(config):
    verdict = evaluate([run_of(latencies(10, 1))], config, target_rps={"t": 10})
    assert verdict.level is Level.PASS
    assert verdict.reasons == []
    assert "no baseline: SLO-only verdict, regressions not checked" in verdict.notes
    assert verdict.comparisons == []


@pytest.mark.parametrize(
    ("p99", "expected"),
    [(799, Level.PASS), (800, Level.FAIL)],  # "p99 < 800 ms": 800 is a breach
)
def test_p99_is_a_hard_slo_with_a_strict_limit(config, p99, expected):
    values = [10] * 98 + [p99, p99]  # nearest-rank p99 of 100 values is the 99th
    assert evaluate([run_of(values)], config).level is expected


@pytest.mark.parametrize(
    ("errors", "count", "expected"), [(1, 201, Level.PASS), (1, 200, Level.FAIL)]
)
def test_error_rate_is_a_hard_slo_with_a_strict_limit(config, errors, count, expected):
    success = [False] * errors + [True] * (count - errors)
    verdict = evaluate([run_of([10] * count, success=success)], config)
    assert verdict.level is expected


def test_p95_and_apdex_are_soft_slos(config):
    slow = [10] * 90 + [400] * 10  # p95 = 400 ms; Apdex = (90 + 10/2) / 100 = 0.95
    verdict = evaluate([run_of(slow)], config)
    assert verdict.level is Level.WARN
    assert {r.detail.split(" ")[0] for r in verdict.reasons} == {"p95"}
    frustrated = [10] * 80 + [1300] * 20  # Apdex 0.80, p95 1300 but p99 1300 too: hard FAIL
    assert evaluate([run_of(frustrated)], config).level is Level.FAIL


def test_throughput_below_tolerance_warns_and_no_target_is_a_note(config):
    run = run_of(latencies(10, 1), step_ms=100)  # 600 samples over 59.9 s: about 10.02/s
    assert evaluate([run], config, target_rps={"t": 10.5}).level is Level.PASS  # floor 9.975
    low = evaluate([run], config, target_rps={"t": 11})  # floor 10.45
    assert levels(low) == [(Level.WARN, "soft_slo")]
    assert "throughput" in low.reasons[0].detail
    assert "throughput of t not checked: no target" in evaluate([run], config).notes


def test_a_declared_transaction_without_samples_warns(config):
    verdict = evaluate([run_of(latencies(10, 1))], config, target_rps={"t": 10, "other": 4})
    assert levels(verdict) == [(Level.WARN, "soft_slo")]
    assert verdict.reasons[0].transaction == "other"


def test_every_candidate_segment_is_checked(config):
    healthy, slow = run_of([10] * 100), run_of([10] * 90 + [400] * 10)
    verdict = evaluate([healthy, slow], config, segment_names=["B1", "B2"])
    assert {r.segment for r in verdict.reasons} == {"B2"}


def test_a_segment_without_samples_is_inconclusive_not_pass(config):
    empty = run_of([])
    verdict = evaluate([empty], config)
    assert levels(verdict) == [(Level.INCONCLUSIVE, "no_measurement")]
    assert not verdict.measured
    assert not verdict.ci_passes  # nothing was measured: the CI job must not pass


@pytest.mark.parametrize(
    ("make", "passes"),
    [
        (lambda c: evaluate([run_of(latencies(10, 1))], c), True),  # PASS
        (lambda c: evaluate([run_of([10] * 90 + [400] * 10)], c), True),  # WARN
        (lambda c: evaluate([run_of(latencies(10, 1))], c, baseline=[]), True),  # INCONCLUSIVE
        (lambda c: evaluate([run_of([10] * 98 + [900, 900])], c), False),  # FAIL
    ],
)
def test_ci_passes_unless_fail_or_nothing_measured(config, make, passes):
    assert make(config).ci_passes is passes


def test_aggregates_without_percentiles_leave_notes_not_breaches(config):
    run = Run(
        metadata=META.model_copy(update={"started_at": None}),
        aggregates=[TransactionAggregate(transaction="t", count=100, error_count=0)],
    )
    verdict = evaluate([run], config)
    assert verdict.level is Level.PASS
    assert any(n.startswith("p99 of t") for n in verdict.notes)


# --- regression ------------------------------------------------------------------------------


def test_clear_regression_fails(config):
    baseline = [run_of(latencies(10, 1, seed=1)), run_of(latencies(10, 1, seed=2))]
    candidate = [run_of(latencies(30, 3, seed=3)), run_of(latencies(30, 3, seed=4))]
    verdict = evaluate(candidate, config, baseline=baseline)
    assert levels(verdict) == [(Level.FAIL, "regression")]
    assert verdict.comparisons[0].windows_baseline == 24


def test_identical_arms_pass(config):
    arm = [run_of(latencies(10, 1, seed=1)), run_of(latencies(10, 1, seed=2))]
    verdict = evaluate(arm, config, baseline=arm)
    assert verdict.level is Level.PASS
    assert "no baseline: SLO-only verdict, regressions not checked" not in verdict.notes


def test_an_empty_baseline_is_inconclusive(config):
    verdict = evaluate([run_of(latencies(10, 1))], config, baseline=[])
    assert levels(verdict) == [(Level.INCONCLUSIVE, "comparison")]


def test_aggregates_cannot_be_compared(config):
    agg = Run(
        metadata=META.model_copy(update={"started_at": None}),
        aggregates=[TransactionAggregate(transaction="t", count=100, error_count=0)],
    )
    verdict = evaluate([run_of(latencies(10, 1))], config, baseline=[agg])
    assert levels(verdict) == [(Level.INCONCLUSIVE, "comparison")]


def test_too_few_windows_is_inconclusive(config):
    short = run_of(latencies(10, 1, n=200))  # 20 s: 4 windows per arm, 10 needed
    verdict = evaluate([short], config, baseline=[short])
    assert levels(verdict) == [(Level.INCONCLUSIVE, "sample_size")]
    assert verdict.ci_passes  # measured, but too little to conclude: green with a warning


def test_a_transaction_missing_from_the_baseline_is_inconclusive(config):
    baseline = run_of(latencies(10, 1), transaction="t")
    candidate = Run(
        metadata=META,
        samples=Samples(
            start_ms=[*range(0, 60000, 100), *range(0, 60000, 100)],
            elapsed_ms=[10] * 1200,
            transaction=["t"] * 600 + ["new"] * 600,
            success=[True] * 1200,
            response_code=["200"] * 1200,
        ),
    )
    verdict = evaluate([candidate], config, baseline=[baseline])
    assert [(r.level, r.transaction) for r in verdict.reasons] == [(Level.INCONCLUSIVE, "new")]


def comparison(p, rel, delta):
    return TransactionComparison(
        transaction="t",
        baseline_count=100,
        candidate_count=100,
        p95_baseline_ms=10,
        p95_candidate_ms=10 * (1 + rel),
        delta_p95_rel=rel,
        raw_p_value=None,
        raw_cliffs_delta=None,
        windows_baseline=24,
        windows_candidate=24,
        windowed_p_value=p,
        windowed_cliffs_delta=delta,
        bootstrap_delta_p95_low=None,
        bootstrap_delta_p95_high=None,
    )


RULE = RegressionRule(
    window_s=5,
    min_window_samples=5,
    alpha=0.05,
    min_delta_p95_rel=0.10,
    min_cliffs_delta=0.147,
    min_windows_per_arm=10,
)


@pytest.mark.parametrize(
    ("p", "rel", "delta", "expected"),
    [
        (0.01, 0.2, 0.5, (Level.FAIL, "regression")),
        (0.01, 0.2, 0.1, (Level.WARN, "weak_regression")),
        (0.01, 0.05, 0.5, (Level.WARN, "weak_regression")),
        (0.2, 0.2, 0.5, (Level.WARN, "weak_regression")),
        (0.01, 0.05, 0.1, None),
        (0.2, 0.2, 0.1, None),
        (0.05, 0.10, 0.147, None),  # at the limits only delta holds: p and rel are strict
    ],
)
def test_regression_conditions(p, rel, delta, expected):
    reason = _check_regression(comparison(p, rel, delta), RULE)
    assert (None if reason is None else (reason.level, reason.check)) == expected


# --- precedence ------------------------------------------------------------------------------


def test_fail_outranks_inconclusive(config):
    """An INCONCLUSIVE job stays green: it must not hide a broken hard SLO."""
    broken = run_of([10] * 98 + [900, 900])
    assert evaluate([broken], config, baseline=[]).level is Level.FAIL


def test_inconclusive_outranks_warn(config):
    slow = run_of([10] * 90 + [400] * 10)
    assert evaluate([slow], config, baseline=[]).level is Level.INCONCLUSIVE


def test_exit_codes():
    assert EXIT_CODES == {Level.PASS: 0, Level.WARN: 1, Level.FAIL: 2, Level.INCONCLUSIVE: 3}


# --- command line ----------------------------------------------------------------------------


def abba_dir(tmp_path, jmeter_fixture, *, ramp_s=2, hold_s=20, meta=True):
    directory = tmp_path / "run"
    directory.mkdir()
    for name in ("A1", "B1", "B2", "A2"):
        shutil.copy(jmeter_fixture("2026-10-17-nominal-short.jtl"), directory / f"{name}.jtl")
    if meta:
        (directory / "meta.json").write_text(
            json.dumps(
                {
                    "candidate": "none",
                    "baseline": ["A1", "A2"],
                    "candidate_segments": ["B1", "B2"],
                    "ramp_s": ramp_s,
                    "hold_s": hold_s,
                    "rates": {"create_payment": 4, "get_payment": 10, "get_statement": 6},
                }
            ),
            encoding="utf-8",
        )
    return directory


def test_cli_abba_takes_segments_and_targets_from_meta(capsys, tmp_path, jmeter_fixture):
    directory = abba_dir(tmp_path, jmeter_fixture)
    out = tmp_path / "verdict.json"
    code = main(["verdict", "--config", str(SHIPPED), "--abba", str(directory), "--json", str(out)])
    # A 20 s hold gives 4 windows per segment, 8 per arm: below the 10 the config asks for.
    assert code == EXIT_CODES[Level.INCONCLUSIVE]
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["level"] == "INCONCLUSIVE"
    assert {r["check"] for r in report["reasons"]} >= {"sample_size"}
    assert not any("no target" in n for n in report["notes"])
    assert {r["segment"] for r in report["reasons"] if r["segment"]} <= {"B1", "B2"}
    assert "loadlens verdict: INCONCLUSIVE" in capsys.readouterr().out


def test_cli_unusable_abba_run_is_inconclusive(capsys, tmp_path, jmeter_fixture):
    directory = abba_dir(tmp_path, jmeter_fixture, meta=False)
    code = main(["verdict", "--config", str(SHIPPED), "--abba", str(directory)])
    assert code == EXIT_CODES[Level.INCONCLUSIVE]
    assert "no meta.json" in capsys.readouterr().out


def test_ci_status_fails_an_unusable_run_with_an_error(capsys, tmp_path, jmeter_fixture):
    directory = abba_dir(tmp_path, jmeter_fixture, meta=False)
    args = ["verdict", "--config", str(SHIPPED), "--abba", str(directory)]
    assert main([*args, "--annotations", "--ci-status"]) == 1
    assert (
        capsys.readouterr()
        .out.splitlines()[-1]
        .startswith("::error title=loadlens verdict INCONCLUSIVE::run: A-B-B-A run unusable")
    )


def test_ci_status_keeps_a_measured_inconclusive_green(capsys, tmp_path, jmeter_fixture):
    directory = abba_dir(tmp_path, jmeter_fixture)  # 8 windows per arm: too few, but measured
    args = ["verdict", "--config", str(SHIPPED), "--abba", str(directory)]
    assert main([*args, "--annotations", "--ci-status"]) == 0
    assert "::warning title=loadlens verdict INCONCLUSIVE::" in capsys.readouterr().out


@pytest.mark.parametrize(("fixture", "status"), [("all-errors", 1), ("single-transaction", 0)])
def test_ci_status_of_single_runs(jmeter_fixture, fixture, status):
    path = str(jmeter_fixture(f"2026-10-17-{fixture}.jtl"))
    assert main(["verdict", "--config", str(SHIPPED), "--candidate", path, "--ci-status"]) == status


def test_cli_files_without_baseline(capsys, jmeter_fixture):
    path = str(jmeter_fixture("2026-10-17-all-errors.jtl"))
    assert main(["verdict", "--config", str(SHIPPED), "--candidate", path]) == 2
    assert "error rate 100.00%" in capsys.readouterr().out


def run_cli(args):
    """Exit code of `main`, including argparse errors (raised as SystemExit)."""
    try:
        return main(args)
    except SystemExit as exit_:
        return exit_.code


@pytest.mark.parametrize(
    "extra",
    [
        ["--abba", "RUN", "--baseline", "x.jtl"],
        ["--abba", "RUN", "--warmup-s", "0"],
        ["--abba", "RUN", "--target-rps", "t=1"],
        ["--abba", "does-not-exist"],
        ["--abba", "RUN", "--candidate", "x.jtl"],
        ["--candidate", "x.jtl", "--target-rps", "t=0"],
        ["--candidate", "x.jtl", "--target-rps", "t"],
        ["--candidate", "does-not-exist.jtl"],
    ],
)
def test_cli_input_errors(tmp_path, jmeter_fixture, extra):
    directory = abba_dir(tmp_path, jmeter_fixture)
    extra = [str(directory) if a == "RUN" else a for a in extra]
    assert run_cli(["verdict", "--config", str(SHIPPED), *extra]) == 4


def test_cli_needs_a_config(jmeter_fixture):
    path = str(jmeter_fixture("2026-10-17-nominal-short.jtl"))
    assert run_cli(["verdict", "--candidate", path]) == 4


def test_annotations_follow_the_level_and_escape_percent(capsys, jmeter_fixture):
    path = str(jmeter_fixture("2026-10-17-all-errors.jtl"))
    assert run_cli(["verdict", "--config", str(SHIPPED), "--candidate", path, "--annotations"]) == 2
    out = capsys.readouterr().out.splitlines()
    assert out[-1].startswith("::error title=loadlens verdict FAIL::run in ")
    assert "error rate 100.00%25 (70/70)" in out[-1]
    assert "%" not in out[-1].replace("%25", "")


def test_no_annotation_for_pass(config):
    from loadlens.cli import github_annotation

    healthy = evaluate([run_of(latencies(10, 1))], config)
    assert github_annotation(healthy) is None
    slow = evaluate([run_of([10] * 90 + [400] * 10)], config)
    assert github_annotation(slow).startswith("::warning title=loadlens verdict WARN::")
