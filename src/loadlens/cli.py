"""Command-line interface.

    loadlens kpi RESULT_FILE [options]    KPIs of a JMeter result file, as JSON on stdout

Exit codes: 0 success, 4 unusable input (missing or malformed file, invalid argument).
Codes 1 to 3 are reserved for verdicts (WARN, FAIL, INCONCLUSIVE).
"""

import argparse
import json
import sys
from collections.abc import Sequence

from pydantic import ValidationError

from loadlens.adapters.jmeter import JtlFormatError, read_jtl
from loadlens.kpi import DEFAULT_APDEX_T_MS, compute, drop_warmup
from loadlens.schema import Machine

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


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "kpi":
        return _kpi(args)
    raise AssertionError(f"unhandled command {args.command}")  # argparse rejects unknown ones


if __name__ == "__main__":
    sys.exit(main())
