"""Verdict of a candidate: its SLOs, plus the windowed regression detector (ADR-004) when a
baseline is given. Rules and thresholds: docs/verdict.md and config/slo.yaml.

Levels and exit codes: PASS 0, WARN 1, FAIL 2, INCONCLUSIVE 3. The most severe reason sets the
level, in the order FAIL, INCONCLUSIVE, WARN. FAIL ranks first because a broken hard SLO or a
detected regression holds whatever else could not be checked, and an INCONCLUSIVE CI job stays
green.

Without a baseline the verdict rests on SLOs alone and says so in a note. INCONCLUSIVE means a
comparison was asked for and could not be made: no baseline run, a run without raw samples, a
transaction missing from one arm, or too few windows. It also means that nothing was measured:
a candidate segment without any sample, or an A-B-B-A run that cannot be used. Only that last
kind fails a CI job (`ci_passes`): the check did not take place at all.
"""

from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from loadlens.compare import TransactionComparison, compare_runs
from loadlens.kpi import Kpis, compute
from loadlens.schema import Run

OVERALL = "all transactions"
NO_MEASUREMENT = "no_measurement"


class Level(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


EXIT_CODES = {Level.PASS: 0, Level.WARN: 1, Level.FAIL: 2, Level.INCONCLUSIVE: 3}
SEVERITY = (Level.FAIL, Level.INCONCLUSIVE, Level.WARN)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HardSlo(_Strict):
    p99_ms: float = Field(gt=0)
    error_rate: float = Field(ge=0, le=1)


class SoftSlo(_Strict):
    p95_ms: float = Field(gt=0)
    apdex: float = Field(ge=0, le=1)
    throughput_tolerance: float = Field(ge=0, lt=1)


class RegressionRule(_Strict):
    window_s: float = Field(gt=0)
    min_window_samples: int = Field(ge=1)
    alpha: float = Field(gt=0, lt=1)
    min_delta_p95_rel: float = Field(ge=0)
    min_cliffs_delta: float = Field(ge=0, le=1)
    min_windows_per_arm: int = Field(ge=1)


class VerdictConfig(_Strict):
    """No default anywhere: config/slo.yaml is the one place thresholds are written."""

    apdex_t_ms: int = Field(gt=0)
    hard: HardSlo
    soft: SoftSlo
    regression: RegressionRule


def load_config(path: str | Path) -> VerdictConfig:
    with open(path, encoding="utf-8") as handle:
        try:
            content = yaml.safe_load(handle)
        except yaml.YAMLError as exc:
            raise ValueError(f"{path}: not valid YAML: {exc}") from None
    return VerdictConfig.model_validate(content)


class Reason(_Strict):
    level: Level
    # hard_slo, soft_slo, regression, weak_regression, comparison, sample_size, no_measurement
    check: str
    transaction: str | None  # None: the run as a whole
    segment: str | None  # candidate segment an SLO was broken in
    detail: str


class Verdict(_Strict):
    level: Level
    reasons: list[Reason]
    notes: list[str]  # what was not checked, and why
    comparisons: list[TransactionComparison]  # empty without a baseline

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.level]

    @property
    def measured(self) -> bool:
        return not any(r.check == NO_MEASUREMENT for r in self.reasons)

    @property
    def ci_passes(self) -> bool:
        """Whether a CI job should pass: WARN and INCONCLUSIVE stay green with an annotation,
        except an INCONCLUSIVE where nothing was measured."""
        return self.level is not Level.FAIL and self.measured


def _check_slos(
    name: str,
    kpis: Kpis,
    config: VerdictConfig,
    segment: str,
    target_rps: float | None,
    reasons: list[Reason],
    notes: list[str],
) -> None:
    def broken(level: Level, check: str, detail: str) -> None:
        transaction = None if name == OVERALL else name
        reasons.append(
            Reason(
                level=level, check=check, transaction=transaction, segment=segment, detail=detail
            )
        )

    def unknown(what: str) -> None:
        notes.append(f"{what} of {name} in {segment} not checked: unknown")

    hard, soft = config.hard, config.soft
    if kpis.p99_ms is None:
        unknown("p99")
    elif not kpis.p99_ms < hard.p99_ms:
        broken(Level.FAIL, "hard_slo", f"p99 {kpis.p99_ms:g} ms, limit < {hard.p99_ms:g} ms")
    if kpis.error_rate is None:
        unknown("error rate")
    elif not kpis.error_rate < hard.error_rate:
        broken(
            Level.FAIL,
            "hard_slo",
            f"error rate {kpis.error_rate:.2%} ({kpis.error_count}/{kpis.count}), "
            f"limit < {hard.error_rate:.2%}",
        )
    if kpis.p95_ms is None:
        unknown("p95")
    elif not kpis.p95_ms < soft.p95_ms:
        broken(Level.WARN, "soft_slo", f"p95 {kpis.p95_ms:g} ms, limit < {soft.p95_ms:g} ms")
    if kpis.apdex is None:
        unknown("Apdex")
    elif not kpis.apdex >= soft.apdex:
        broken(Level.WARN, "soft_slo", f"Apdex {kpis.apdex:.3f}, limit >= {soft.apdex:g}")
    if target_rps is not None:
        floor = target_rps * (1 - soft.throughput_tolerance)
        if kpis.throughput_rps is None:
            unknown("throughput")
        elif not kpis.throughput_rps >= floor:
            broken(
                Level.WARN,
                "soft_slo",
                f"throughput {kpis.throughput_rps:.2f}/s, limit >= {floor:.2f}/s "
                f"(target {target_rps:g}/s - {soft.throughput_tolerance:.0%})",
            )


def _check_regression(c: TransactionComparison, rule: RegressionRule) -> Reason | None:
    def reason(level: Level, check: str, detail: str) -> Reason:
        return Reason(
            level=level, check=check, transaction=c.transaction, segment=None, detail=detail
        )

    if c.baseline_count == 0 or c.candidate_count == 0:
        arm = "baseline" if c.baseline_count == 0 else "candidate"
        return reason(Level.INCONCLUSIVE, "comparison", f"no successful sample in the {arm}")
    fewest = min(c.windows_baseline, c.windows_candidate)
    if fewest < rule.min_windows_per_arm:
        return reason(
            Level.INCONCLUSIVE,
            "sample_size",
            f"{c.windows_baseline} baseline and {c.windows_candidate} candidate windows, "
            f"at least {rule.min_windows_per_arm} needed in each",
        )
    p, rel, delta = c.windowed_p_value, c.delta_p95_rel, c.windowed_cliffs_delta
    conditions = [
        p is not None and p < rule.alpha,
        rel is not None and rel > rule.min_delta_p95_rel,
        delta is not None and delta >= rule.min_cliffs_delta,
    ]
    met = sum(conditions)
    if met < 2:
        return None
    change = f"{rel:+.0%}" if rel is not None else "change unknown"
    detail = (
        f"p95 {c.p95_baseline_ms:g} -> {c.p95_candidate_ms:g} ms ({change}), "
        f"windowed p = {p:.2g}, Cliff's delta = {delta:.2f}"
    )
    if met == 3:
        return reason(Level.FAIL, "regression", detail)
    return reason(Level.WARN, "weak_regression", f"2 of 3 regression conditions: {detail}")


def evaluate(
    candidate: Sequence[Run],
    config: VerdictConfig,
    *,
    baseline: Sequence[Run] | None = None,
    segment_names: Sequence[str] | None = None,
    target_rps: Mapping[str, float] | None = None,
) -> Verdict:
    """`candidate`: the candidate segments, every SLO checked in each. `baseline`: None for an
    SLO-only verdict; a sequence, even empty, asks for a comparison. `target_rps`: declared rate
    per transaction; throughput is not checked for a transaction without one."""
    if not candidate:
        raise ValueError("no candidate run")
    names = (
        list(segment_names)
        if segment_names is not None
        else [f"segment {i}" for i in range(1, len(candidate) + 1)]
    )
    if len(names) != len(candidate):
        raise ValueError("one segment name per candidate run")
    targets = dict(target_rps or {})
    reasons: list[Reason] = []
    notes: list[str] = []

    for segment, run in zip(names, candidate, strict=True):
        kpis = compute(run, apdex_t_ms=config.apdex_t_ms)
        if kpis.overall.count == 0:  # nothing measured: no SLO can be said to hold
            reasons.append(
                Reason(
                    level=Level.INCONCLUSIVE,
                    check=NO_MEASUREMENT,
                    transaction=None,
                    segment=segment,
                    detail="no sample in this segment",
                )
            )
            continue
        _check_slos(OVERALL, kpis.overall, config, segment, None, reasons, notes)
        for transaction, values in kpis.transactions.items():
            _check_slos(
                transaction, values, config, segment, targets.get(transaction), reasons, notes
            )
        observed = set(kpis.transactions)
        for transaction in sorted(observed - set(targets)):
            note = f"throughput of {transaction} not checked: no target"
            if note not in notes:
                notes.append(note)
        for transaction in sorted(set(targets) - observed):  # declared, never sent: 0/s
            reasons.append(
                Reason(
                    level=Level.WARN,
                    check="soft_slo",
                    transaction=transaction,
                    segment=segment,
                    detail=f"no sample, target {targets[transaction]:g}/s",
                )
            )

    comparisons: list[TransactionComparison] = []
    if baseline is None:
        notes.append("no baseline: SLO-only verdict, regressions not checked")
    elif not baseline:
        reasons.append(
            Reason(
                level=Level.INCONCLUSIVE,
                check="comparison",
                transaction=None,
                segment=None,
                detail="no baseline run",
            )
        )
    elif any(run.samples is None for run in [*baseline, *candidate]):
        reasons.append(
            Reason(
                level=Level.INCONCLUSIVE,
                check="comparison",
                transaction=None,
                segment=None,
                detail="comparison needs raw samples; a run only has aggregates",
            )
        )
    else:
        rule = config.regression
        comparisons = compare_runs(
            baseline, candidate, window_s=rule.window_s, min_window_samples=rule.min_window_samples
        )
        reasons.extend(r for c in comparisons if (r := _check_regression(c, rule)) is not None)

    level = next((lv for lv in SEVERITY if any(r.level is lv for r in reasons)), Level.PASS)
    return Verdict(level=level, reasons=reasons, notes=notes, comparisons=comparisons)


def inconclusive(detail: str) -> Verdict:
    """Verdict of a run that could not even be loaded, e.g. an unusable A-B-B-A run: nothing was
    measured."""
    reason = Reason(
        level=Level.INCONCLUSIVE,
        check=NO_MEASUREMENT,
        transaction=None,
        segment=None,
        detail=detail,
    )
    return Verdict(level=Level.INCONCLUSIVE, reasons=[reason], notes=[], comparisons=[])
