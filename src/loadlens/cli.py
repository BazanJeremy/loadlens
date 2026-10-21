"""Command-line interface.

    loadlens kpi RESULT_FILE [options]    KPIs of a JMeter result file, as JSON on stdout
    loadlens verdict --config SLO_YAML (--abba RUN_DIR | --candidate JTL ...) [options]
                                          PASS / WARN / FAIL / INCONCLUSIVE, with the reasons
    loadlens schema                       JSON schema of the verdict, on stdout
    loadlens trend HISTORY_JSON [--add VERDICT_JSON ...] [--page HTML]
                                          trend history and its HTML page

Exit codes: 0 success or PASS, 1 WARN, 2 FAIL, 3 INCONCLUSIVE, 4 unusable input (missing or
malformed file, invalid argument). With `verdict --ci-status`, the exit code is a CI job status
instead: 0 pass, 1 fail, 4 unusable input.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from loadlens.adapters.jmeter import JtlFormatError, read_jtl
from loadlens.calibration import UnusableRun, load_abba
from loadlens.kpi import DEFAULT_APDEX_T_MS, compute, drop_warmup
from loadlens.report.json_schema import verdict_json_schema_text
from loadlens.report.junit import junit_xml
from loadlens.report.summary import markdown_summary
from loadlens.report.trend import (
    History,
    add_run,
    history_text,
    load_history,
    trend_page,
    trend_run,
)
from loadlens.schema import Machine
from loadlens.verdict import Level, Verdict, evaluate, inconclusive, load_config

EXIT_OK = 0
EXIT_INPUT_ERROR = 4


class _Parser(argparse.ArgumentParser):
    """argparse exits with 2 on a usage error; 2 is reserved for FAIL, so use 4."""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(EXIT_INPUT_ERROR, f"{self.prog}: error: {message}\n")


def _key_value(text: str) -> tuple[str, str]:
    key, sep, value = text.partition("=")
    if not sep or not key:
        raise argparse.ArgumentTypeError(f"expected KEY=VALUE, got {text!r}")
    return key, value


def _target(text: str) -> tuple[str, float]:
    key, value = _key_value(text)
    try:
        rate = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected TRANSACTION=RATE, got {text!r}") from None
    if not rate > 0:
        raise argparse.ArgumentTypeError(f"rate must be > 0, got {text!r}")
    return key, rate


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="loadlens", description="Readable, statistically defensible load-test KPIs."
    )
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    kpi = commands.add_parser("kpi", help="KPIs of a JMeter result file (JTL), as JSON")
    kpi.add_argument("result_file", help="JTL (CSV) file written by JMeter")
    kpi.add_argument("--tool-version", help="JMeter version (a JTL does not record it)")
    kpi.add_argument(
        "--profile",
        type=_key_value,
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="load profile entry to record, repeatable",
    )
    kpi.add_argument("--os", help="operating system of the load generator")
    kpi.add_argument("--cpu-model", help="CPU model of the load generator")
    kpi.add_argument("--cpu-count", type=int, help="CPU count of the load generator")
    kpi.add_argument("--apdex-t-ms", type=int, default=DEFAULT_APDEX_T_MS, help="Apdex threshold T")
    kpi.add_argument(
        "--warmup-s",
        type=float,
        default=0.0,
        help="leave out samples started during the first N seconds",
    )

    verdict = commands.add_parser(
        "verdict", help="PASS / WARN / FAIL / INCONCLUSIVE of a candidate, with the reasons"
    )
    verdict.add_argument("--config", required=True, help="thresholds file (config/slo.yaml)")
    source = verdict.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--abba",
        metavar="RUN_DIR",
        help="output of load/abba.sh; meta.json gives the segments, warm-up and target rates",
    )
    source.add_argument(
        "--candidate", action="append", metavar="JTL", help="candidate segment, repeatable"
    )
    verdict.add_argument(
        "--baseline",
        action="append",
        metavar="JTL",
        help="baseline segment, repeatable; without one the verdict rests on SLOs alone",
    )
    verdict.add_argument(
        "--warmup-s", type=float, help="leave out samples started during the first N seconds"
    )
    verdict.add_argument(
        "--target-rps",
        type=_target,
        action="append",
        metavar="TRANSACTION=RATE",
        help="declared arrival rate of a transaction, repeatable",
    )
    verdict.add_argument("--json", metavar="PATH", help="also write the verdict as JSON here")
    verdict.add_argument("--junit", metavar="PATH", help="also write a JUnit XML report here")
    verdict.add_argument(
        "--summary",
        metavar="PATH",
        help="also append a Markdown summary to this file, e.g. $GITHUB_STEP_SUMMARY",
    )
    verdict.add_argument(
        "--annotations",
        action="store_true",
        help="also print a GitHub Actions annotation: an error when the CI job should fail, "
        "a warning for any other verdict but PASS",
    )
    verdict.add_argument(
        "--ci-status",
        action="store_true",
        help="exit with a CI job status instead of the verdict code: 1 for FAIL, or for an "
        "INCONCLUSIVE where nothing was measured; 0 otherwise",
    )

    schema = commands.add_parser(
        "schema", help="JSON schema of the verdict that verdict --json writes"
    )
    schema.add_argument("output", nargs="?", help="write it to this file instead of stdout")

    trend = commands.add_parser("trend", help="add a verdict to a trend history, write its page")
    trend.add_argument("history", help="history JSON file, rewritten in place by --add")
    trend.add_argument(
        "--start", action="store_true", help="start a new history; the file must not exist yet"
    )
    trend.add_argument("--add", metavar="VERDICT_JSON", help="verdict written by verdict --json")
    trend.add_argument("--run-id", help="identifier of the run; added again, it replaces the entry")
    trend.add_argument("--commit", help="commit the run measured")
    trend.add_argument("--added-at", help="ISO 8601 time with a UTC offset, e.g. 2026-10-20T08:00Z")
    trend.add_argument("--url", help="link to the run")
    trend.add_argument("--page", metavar="HTML", help="write the trend page here")
    return parser


def _kpi(args: argparse.Namespace) -> int:
    try:
        machine = None
        if args.os or args.cpu_model or args.cpu_count is not None:
            machine = Machine(os=args.os, cpu_model=args.cpu_model, cpu_count=args.cpu_count)
        run = read_jtl(
            args.result_file,
            tool_version=args.tool_version,
            profile=dict(args.profile),
            machine=machine,
        )
        run = drop_warmup(run, args.warmup_s)
        kpis = compute(run, apdex_t_ms=args.apdex_t_ms)
    except (OSError, JtlFormatError, ValidationError, ValueError) as exc:
        print(f"loadlens: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    report = {
        "metadata": run.metadata.model_dump(mode="json"),
        "warmup_s": args.warmup_s,
        "kpis": kpis.model_dump(mode="json"),
    }
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return EXIT_OK


def _load_verdict(args: argparse.Namespace) -> Verdict:
    config = load_config(args.config)
    if args.abba:
        directory = Path(args.abba)
        if not directory.is_dir():
            raise OSError(f"no such directory: {directory}")
        try:
            meta, baseline, candidate = load_abba(directory)
        except UnusableRun as reason:
            return inconclusive(f"A-B-B-A run unusable: {reason}")
        targets = {name: float(rate) for name, rate in meta.get("rates", {}).items()}
        return evaluate(
            candidate,
            config,
            baseline=baseline,
            segment_names=meta["candidate_segments"],
            target_rps=targets,
        )

    def load(paths: Sequence[str]) -> list:
        return [drop_warmup(read_jtl(path), args.warmup_s or 0.0) for path in paths]

    return evaluate(
        load(args.candidate),
        config,
        baseline=load(args.baseline) if args.baseline else None,
        segment_names=[Path(path).name for path in args.candidate],
        target_rps=dict(args.target_rps or []),
    )


def _print_verdict(verdict: Verdict) -> None:
    print(f"loadlens verdict: {verdict.level}")
    for r in verdict.reasons:
        where = ", ".join(x for x in (r.transaction, r.segment) if x) or "run"
        print(f"  {r.level:<12} {r.check:<15} {where}: {r.detail}")
    for note in verdict.notes:
        print(f"  note: {note}")


def github_annotation(verdict: Verdict) -> str | None:
    """GitHub Actions workflow command for a verdict: an error when the job should fail (FAIL,
    nothing measured), a warning for WARN and any other INCONCLUSIVE, none for PASS. Data is
    escaped as the workflow-command syntax requires."""
    if verdict.level is Level.PASS:
        return None
    lines = [
        f"{r.transaction or 'run'}{f' in {r.segment}' if r.segment else ''}: {r.detail}"
        for r in verdict.reasons
    ]
    message = "; ".join(lines).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    command = "warning" if verdict.ci_passes else "error"
    return f"::{command} title=loadlens verdict {verdict.level}::{message}"


def _verdict(args: argparse.Namespace) -> int:
    if args.abba and (args.baseline or args.warmup_s is not None or args.target_rps):
        print(
            "loadlens: --abba takes the baseline, warm-up and target rates from meta.json",
            file=sys.stderr,
        )
        return EXIT_INPUT_ERROR
    try:
        verdict = _load_verdict(args)
        if args.json:
            Path(args.json).write_text(
                verdict.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
            )
        if args.junit:
            Path(args.junit).write_text(junit_xml(verdict), encoding="utf-8", newline="\n")
        if args.summary:
            with open(args.summary, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(markdown_summary(verdict) + "\n")
    except (OSError, JtlFormatError, ValidationError, ValueError, KeyError) as exc:
        print(f"loadlens: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    _print_verdict(verdict)
    if args.annotations and (annotation := github_annotation(verdict)):
        print(annotation)
    if args.ci_status:
        return EXIT_OK if verdict.ci_passes else 1
    return verdict.exit_code


def _trend(args: argparse.Namespace) -> int:
    run_fields = (args.run_id, args.commit, args.added_at)
    if args.add and not all(run_fields):
        print("loadlens: --add needs --run-id, --commit and --added-at", file=sys.stderr)
        return EXIT_INPUT_ERROR
    if not args.add and (any(run_fields) or args.url):
        print("loadlens: --run-id, --commit, --added-at and --url go with --add", file=sys.stderr)
        return EXIT_INPUT_ERROR
    if not (args.add or args.page or args.start):
        print("loadlens: nothing to do: give --add, --page or --start", file=sys.stderr)
        return EXIT_INPUT_ERROR
    path = Path(args.history)
    try:
        if args.start:
            if path.exists():  # never overwrite a history: it cannot be rebuilt
                raise OSError(f"{path} exists; --start only begins a new history")
            history = History(runs=[])
        else:
            history = load_history(path)
        if args.add:
            verdict = Verdict.model_validate_json(Path(args.add).read_text(encoding="utf-8"))
            run = trend_run(
                verdict,
                run_id=args.run_id,
                commit=args.commit,
                added_at=args.added_at,
                url=args.url,
            )
            history = add_run(history, run)
        if args.add or args.start:
            path.write_text(history_text(history), encoding="utf-8", newline="\n")
        if args.page:
            Path(args.page).write_text(trend_page(history), encoding="utf-8", newline="\n")
    except (OSError, ValidationError, ValueError) as exc:
        print(f"loadlens: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    print(f"loadlens trend: {len(history.runs)} run(s) in {path}")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "kpi":
        return _kpi(args)
    if args.command == "verdict":
        return _verdict(args)
    if args.command == "schema":  # a file, not a redirection: PowerShell 5.1 writes UTF-16
        if args.output:
            Path(args.output).write_text(verdict_json_schema_text(), encoding="utf-8", newline="\n")
        else:
            sys.stdout.write(verdict_json_schema_text())
        return EXIT_OK
    if args.command == "trend":
        return _trend(args)
    raise AssertionError(f"unhandled command {args.command}")  # argparse rejects unknown ones


if __name__ == "__main__":
    sys.exit(main())
