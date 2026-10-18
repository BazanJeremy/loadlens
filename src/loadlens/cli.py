"""Command-line interface.

    loadlens kpi RESULT_FILE [options]    KPIs of a JMeter result file, as JSON on stdout
    loadlens verdict --config SLO_YAML (--abba RUN_DIR | --candidate JTL ...) [options]
                                          PASS / WARN / FAIL / INCONCLUSIVE, with the reasons

Exit codes: 0 success or PASS, 1 WARN, 2 FAIL, 3 INCONCLUSIVE, 4 unusable input (missing or
malformed file, invalid argument).
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
    verdict.add_argument(
        "--annotations",
        action="store_true",
        help="also print a GitHub Actions annotation (error for FAIL, warning for WARN and "
        "INCONCLUSIVE)",
    )
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
    """GitHub Actions workflow command for a verdict: an error for FAIL, a warning for WARN and
    INCONCLUSIVE, none for PASS. Data is escaped as the workflow-command syntax requires."""
    if verdict.level is Level.PASS:
        return None
    lines = [
        f"{r.transaction or 'run'}{f' in {r.segment}' if r.segment else ''}: {r.detail}"
        for r in verdict.reasons
    ]
    message = "; ".join(lines).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    command = "error" if verdict.level is Level.FAIL else "warning"
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
    except (OSError, JtlFormatError, ValidationError, ValueError, KeyError) as exc:
        print(f"loadlens: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    _print_verdict(verdict)
    if args.annotations and (annotation := github_annotation(verdict)):
        print(annotation)
    return verdict.exit_code


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "kpi":
        return _kpi(args)
    if args.command == "verdict":
        return _verdict(args)
    raise AssertionError(f"unhandled command {args.command}")  # argparse rejects unknown ones


if __name__ == "__main__":
    sys.exit(main())
