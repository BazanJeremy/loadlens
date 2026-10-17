"""Calibration of candidate regression detectors on A-B-B-A runs (docs/calibration.md).

    python -m loadlens.calibration RUN_DIR [RUN_DIR ...] [--json report.json]

Each RUN_DIR is the output of load/abba.sh: A1/B1/B2/A2 JTL files and meta.json. A/A runs
(candidate "none") measure false positives; runs with a regression switched on measure power on
the transactions that regression is expected to slow down.
"""

import argparse
import json
import statistics
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from scipy.stats import beta

from loadlens.adapters.jmeter import read_jtl
from loadlens.compare import TransactionComparison, compare_runs, window_p95
from loadlens.kpi import drop_warmup
from loadlens.schema import Run

EFFECT_THRESHOLD = 0.10  # relative p95 increase (mission default)
DELTA_THRESHOLD = 0.147  # |Cliff's delta| "small" boundary (Romano et al. 2006)
ALPHA = 0.05

# Transactions each regression is expected to slow down (sut/README.en.md).
EXPECTED = {
    "N_PLUS_ONE": {"get_statement"},
    "LOCK": {"create_payment"},
    "POOL": {"create_payment", "get_payment", "get_statement"},
}


def _lt(value: float | None, threshold: float) -> bool:
    return value is not None and value < threshold


def _gt(value: float | None, threshold: float) -> bool:
    return value is not None and value > threshold


def _ge(value: float | None, threshold: float) -> bool:
    return value is not None and value >= threshold


DETECTORS: dict[str, Callable[[TransactionComparison], bool]] = {
    "mission: raw p<0.05 & dp95>+10% & delta>=0.147": lambda c: (
        _lt(c.raw_p_value, ALPHA)
        and _gt(c.delta_p95_rel, EFFECT_THRESHOLD)
        and _ge(c.raw_cliffs_delta, DELTA_THRESHOLD)
    ),
    "windowed: p<0.05 & dp95>+10% & delta>=0.147": lambda c: (
        _lt(c.windowed_p_value, ALPHA)
        and _gt(c.delta_p95_rel, EFFECT_THRESHOLD)
        and _ge(c.windowed_cliffs_delta, DELTA_THRESHOLD)
    ),
    "bootstrap: 5th pct of dp95 > +10%": lambda c: _gt(c.bootstrap_delta_p95_low, EFFECT_THRESHOLD),
    "bootstrap: 5th pct > 0 & dp95 > +10%": lambda c: (
        _gt(c.bootstrap_delta_p95_low, 0.0) and _gt(c.delta_p95_rel, EFFECT_THRESHOLD)
    ),
    # Single conditions, to see which one carries the false positives.
    "component: raw p<0.05": lambda c: _lt(c.raw_p_value, ALPHA),
    "component: dp95 > +10%": lambda c: _gt(c.delta_p95_rel, EFFECT_THRESHOLD),
    "component: raw delta>=0.147": lambda c: _ge(c.raw_cliffs_delta, DELTA_THRESHOLD),
    "component: windowed p<0.05": lambda c: _lt(c.windowed_p_value, ALPHA),
}


def clopper_pearson_upper(events: int, trials: int, confidence: float = 0.95) -> float:
    """One-sided exact upper bound of a proportion (3/n "rule of three" territory at 0 events)."""
    if trials <= 0:
        raise ValueError("no trials")
    if events >= trials:
        return 1.0
    return float(beta.ppf(confidence, events + 1, trials - events))


SEGMENT_SLACK_S = 30  # a segment may run this much longer than its schedule before it is suspect


class UnusableRun(Exception):
    """The directory does not hold a complete, undisturbed A-B-B-A run. Message = reason."""


def load_abba(directory: Path) -> tuple[dict, list[Run], list[Run]]:
    meta_path = directory / "meta.json"
    if not meta_path.is_file():
        raise UnusableRun("no meta.json (the run did not finish)")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    warmup = float(meta["ramp_s"])
    schedule_s = warmup + float(meta["hold_s"]) if "hold_s" in meta else None
    # Host wall clock per segment (load/abba.sh): catches a suspended host, which the JTL's own
    # timestamps do not show.
    for name, wall in meta.get("segment_wall_s", {}).items():
        if schedule_s is not None and wall > schedule_s + SEGMENT_SLACK_S:
            raise UnusableRun(
                f"segment {name} took {wall} s of wall clock for a {schedule_s:.0f} s schedule"
            )

    def runs(names: Sequence[str]) -> list[Run]:
        loaded = []
        for name in names:
            run = read_jtl(directory / f"{name}.jtl")
            s = run.samples
            if s is None or not len(s):
                raise UnusableRun(f"segment {name} has no sample")
            span_s = (
                max(a + e for a, e in zip(s.start_ms, s.elapsed_ms, strict=True)) - min(s.start_ms)
            ) / 1000
            if schedule_s is not None and span_s > schedule_s + SEGMENT_SLACK_S:
                raise UnusableRun(
                    f"segment {name} spans {span_s:.0f} s for a {schedule_s:.0f} s schedule"
                )
            loaded.append(drop_warmup(run, warmup))
        return loaded

    return meta, runs(meta["baseline"]), runs(meta["candidate_segments"])


def _stability(runs: Sequence[Run], window_s: float) -> dict[str, list[float]]:
    """Per transaction and segment: raw-latency CV and CV of the per-window p95."""
    raw_cv: list[float] = []
    window_cv: list[float] = []
    for run in runs:
        s = run.samples
        assert s is not None
        for name in set(s.transaction):
            ok = [
                e
                for e, n, f in zip(s.elapsed_ms, s.transaction, s.success, strict=True)
                if f and n == name
            ]
            if len(ok) >= 2 and statistics.fmean(ok):
                raw_cv.append(statistics.pstdev(ok) / statistics.fmean(ok))
            rows = sorted(
                (t, e)
                for t, e, n, f in zip(
                    s.start_ms, s.elapsed_ms, s.transaction, s.success, strict=True
                )
                if f and n == name
            )
            windows = window_p95(rows, window_s, 5)
            if len(windows) >= 2 and statistics.fmean(windows):
                window_cv.append(statistics.pstdev(windows) / statistics.fmean(windows))
    return {"raw_cv": raw_cv, "window_p95_cv": window_cv}


def _both_ways(arm: Sequence[Run], options: dict) -> list[list[TransactionComparison]]:
    """The arm's second segment against its first, then the reverse."""
    return [
        compare_runs([arm[0]], [arm[1]], **options),
        compare_runs([arm[1]], [arm[0]], **options),
    ]


def analyze(directories: Sequence[Path], *, window_s: float = 5.0, replicates: int = 2000) -> dict:
    runs = []
    excluded = []
    for directory in directories:
        try:
            meta, baseline, candidate = load_abba(directory)
        except UnusableRun as reason:
            excluded.append({"directory": directory.name, "reason": str(reason)})
            continue
        options = {"window_s": window_s, "replicates": replicates}
        comparisons = compare_runs(baseline, candidate, **options)

        # Self-check: the two baseline segments should not differ. A detector that fires between
        # A1 and A2, in either direction, finds the run too unstable to conclude — a data-driven
        # candidate stand-in for a fixed CV threshold. B1 versus B2 is recorded for information.
        within = {
            "baseline": _both_ways(baseline, options),
            "candidate": _both_ways(candidate, options),
        }
        stability = _stability([*baseline, *candidate], window_s)
        runs.append(
            {
                "directory": directory.name,
                "candidate": meta["candidate"],
                "cpu_count": meta.get("cpu_count"),
                "comparisons": [c.model_dump() for c in comparisons],
                "flags": {
                    name: sorted(c.transaction for c in comparisons if detector(c))
                    for name, detector in DETECTORS.items()
                },
                # Measured on the local pilot (2026-10-17): checking the candidate arm too turned
                # the N+1 run inconsistent, because two regressed segments differ from each other.
                "inconsistent": {
                    name: any(detector(c) for pair in within["baseline"] for c in pair)
                    for name, detector in DETECTORS.items()
                },
                "candidate_inconsistent": {
                    name: any(detector(c) for pair in within["candidate"] for c in pair)
                    for name, detector in DETECTORS.items()
                },
                "stability": stability,
            }
        )

    aa = [r for r in runs if r["candidate"] == "none"]
    detectors = {}
    for name in DETECTORS:
        entry: dict = {}
        if aa:
            flagged = sum(1 for r in aa if r["flags"][name])
            entry["false_positive_runs"] = flagged
            entry["aa_runs"] = len(aa)
            entry["false_positive_rate_upper_95"] = clopper_pearson_upper(flagged, len(aa))
            # With the self-check gate, an inconsistent run ends INCONCLUSIVE, never FAIL.
            entry["aa_inconsistent_runs"] = sum(1 for r in aa if r["inconsistent"][name])
            entry["false_positive_runs_when_consistent"] = sum(
                1 for r in aa if r["flags"][name] and not r["inconsistent"][name]
            )
        for mode, expected in EXPECTED.items():
            mode_runs = [r for r in runs if r["candidate"] == mode]
            if mode_runs:
                detected = sum(1 for r in mode_runs if expected & set(r["flags"][name]))
                inconsistent = sum(1 for r in mode_runs if r["inconsistent"][name])
                entry[f"detected_{mode}"] = f"{detected}/{len(mode_runs)}"
                entry[f"inconsistent_{mode}"] = inconsistent
        detectors[name] = entry

    aa_stability = {
        key: sorted(v for r in aa for v in r["stability"][key])
        for key in ("raw_cv", "window_p95_cv")
    }
    return {
        "runs": runs,
        "excluded": excluded,
        "detectors": detectors,
        "aa_stability": aa_stability,
    }


def _quantiles(values: Sequence[float]) -> str:
    if not values:
        return "n/a"
    qs = statistics.quantiles(values, n=20, method="inclusive") if len(values) > 1 else [values[0]]
    return (
        f"min {min(values):.3f} | median {statistics.median(values):.3f}"
        f" | p95 {qs[-1]:.3f} | max {max(values):.3f}"
    )


def render_markdown(report: dict) -> str:
    modes = [m for m in EXPECTED if any(r["candidate"] == m for r in report["runs"])]
    header = (
        "| Detector | A/A runs flagged | FPR upper bound (95%) | A/A self-check inconsistent | "
        "A/A flagged and consistent | "
        + " | ".join(f"{m} detected (inconsistent)" for m in modes)
        + " |"
    )
    lines = [
        "## Regression detectors",
        "",
        "A run is *inconsistent* when the detector also fires between its two baseline segments",
        "(A1 against A2, both ways): with the self-check gate it would end INCONCLUSIVE.",
        "",
        header,
        "|" + "---|" * (5 + len(modes)),
    ]
    for name, entry in report["detectors"].items():
        if "aa_runs" in entry:
            aa_cells = [
                f"{entry['false_positive_runs']}/{entry['aa_runs']}",
                f"{entry['false_positive_rate_upper_95']:.0%}",
                f"{entry['aa_inconsistent_runs']}/{entry['aa_runs']}",
                f"{entry['false_positive_runs_when_consistent']}/{entry['aa_runs']}",
            ]
        else:
            aa_cells = ["n/a"] * 4
        cells = [
            f"{entry[f'detected_{m}']} ({entry[f'inconsistent_{m}']})"
            if f"detected_{m}" in entry
            else "n/a"
            for m in modes
        ]
        lines.append(f"| {name} | " + " | ".join(aa_cells + cells) + " |")
    if report["excluded"]:
        lines += ["", "## Excluded runs", ""]
        lines += [f"- {e['directory']}: {e['reason']}" for e in report["excluded"]]
    lines += [
        "",
        "## Stability indicators on A/A runs (per transaction and segment)",
        "",
        f"- raw-latency CV: {_quantiles(report['aa_stability']['raw_cv'])}",
        f"- CV of the 5 s window p95: {_quantiles(report['aa_stability']['window_p95_cv'])}",
        "",
        "## Runs",
        "",
        "| Run | Candidate | CPUs | Transaction | p95 A -> B (ms) | dp95 | raw p | raw delta | "
        "windowed p | bootstrap 5th-95th pct |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for run in report["runs"]:
        for c in run["comparisons"]:

            def fmt(v, spec):
                return "n/a" if v is None else format(v, spec)

            lines.append(
                f"| {run['directory']} | {run['candidate']} | {run['cpu_count']} | "
                f"{c['transaction']} | {fmt(c['p95_baseline_ms'], '.0f')} -> "
                f"{fmt(c['p95_candidate_ms'], '.0f')} | {fmt(c['delta_p95_rel'], '+.0%')} | "
                f"{fmt(c['raw_p_value'], '.2g')} | {fmt(c['raw_cliffs_delta'], '+.3f')} | "
                f"{fmt(c['windowed_p_value'], '.2g')} | "
                f"{fmt(c['bootstrap_delta_p95_low'], '+.0%')} ... "
                f"{fmt(c['bootstrap_delta_p95_high'], '+.0%')} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m loadlens.calibration")
    parser.add_argument("directories", nargs="+", type=Path)
    parser.add_argument("--json", type=Path, help="also write the full report as JSON")
    parser.add_argument("--replicates", type=int, default=2000)
    args = parser.parse_args(argv)
    report = analyze(args.directories, replicates=args.replicates)
    if args.json:
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    sys.stdout.write(render_markdown(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
