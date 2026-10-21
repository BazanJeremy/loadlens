"""Markdown summary of a verdict, for `$GITHUB_STEP_SUMMARY`: the level, every reason, the KPIs of
each candidate segment, the comparison with the baseline, and what was not checked."""

from loadlens.kpi import Kpis
from loadlens.verdict import OVERALL, Level, Verdict

MARKS = {Level.PASS: "✅", Level.WARN: "⚠️", Level.FAIL: "❌", Level.INCONCLUSIVE: "❔"}
UNKNOWN = "unknown"


def _cell(text: str) -> str:
    """A Markdown table cell: a pipe would end it, a line break would end the row."""
    return " ".join(text.split()).replace("|", "\\|")


def _ms(value: float | None) -> str:
    return UNKNOWN if value is None else f"{value:g} ms"


def _rate(value: float | None) -> str:
    return UNKNOWN if value is None else f"{value:.2%}"


def _number(value: float | None, spec: str, suffix: str = "") -> str:
    return UNKNOWN if value is None else f"{value:{spec}}{suffix}"


def _kpi_row(name: str, k: Kpis) -> str:
    cells = [
        name,
        str(k.count),
        f"{k.error_count} ({_rate(k.error_rate)})",
        _ms(k.p50_ms),
        _ms(k.p95_ms),
        _ms(k.p99_ms),
        _number(k.throughput_rps, ".2f", "/s"),
        _number(k.apdex, ".3f"),
    ]
    return "| " + " | ".join(_cell(c) for c in cells) + " |"


def markdown_summary(verdict: Verdict) -> str:
    lines = [f"## loadlens verdict: {MARKS[verdict.level]} {verdict.level}", ""]

    lines += ["### Reasons", ""]
    if verdict.reasons:
        lines += ["| Level | Check | Transaction | Segment | Detail |", "|---|---|---|---|---|"]
        for r in verdict.reasons:
            cells = [r.level, r.check, r.transaction or OVERALL, r.segment or "", r.detail]
            lines.append("| " + " | ".join(_cell(str(c)) for c in cells) + " |")
    else:
        lines.append("None: every check that could be made held.")
    lines.append("")

    for segment, kpis in verdict.segments.items():
        duration = _number(kpis.duration_s, ".0f", " s")
        lines += [
            f"### KPIs, segment {_cell(segment)}",
            "",
            f"Warm-up left out, measured duration {duration}, Apdex T = {kpis.apdex_t_ms} ms.",
            "",
            "| Transaction | Samples | Errors | p50 | p95 | p99 | Throughput | Apdex |",
            "|---|--:|--:|--:|--:|--:|--:|--:|",
            _kpi_row(OVERALL, kpis.overall),
            *(_kpi_row(name, k) for name, k in kpis.transactions.items()),
            "",
        ]

    if verdict.comparisons:
        lines += [
            "### Comparison with the baseline",
            "",
            "| Transaction | p95 baseline → candidate | Change | Windowed p | Cliff's δ "
            "| Windows (baseline / candidate) |",
            "|---|--:|--:|--:|--:|--:|",
        ]
        for c in verdict.comparisons:
            cells = [
                c.transaction,
                f"{_ms(c.p95_baseline_ms)} → {_ms(c.p95_candidate_ms)}",
                _number(c.delta_p95_rel, "+.0%"),
                _number(c.windowed_p_value, ".2g"),
                _number(c.windowed_cliffs_delta, ".2f"),
                f"{c.windows_baseline} / {c.windows_candidate}",
            ]
            lines.append("| " + " | ".join(_cell(x) for x in cells) + " |")
        lines.append("")

    if verdict.notes:
        lines += ["### Not checked", "", *(f"- {' '.join(n.split())}" for n in verdict.notes), ""]
    return "\n".join(lines)
