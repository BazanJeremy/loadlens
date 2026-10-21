"""Trend history and its static HTML page (ADR-007).

The history is one JSON file, `history.json`, kept on the `gh-pages` branch: one entry per run
added, with the verdict level and the overall KPIs of each candidate segment. The page is
rebuilt from it in full each time: inline SVG charts, no script, no external resource, and the
same bytes for the same history.

Runs of a history ran on different machines; the page shows their values side by side and
compares nothing (ADR-003: absolute latencies of different runs are not compared).
"""

import json
import math
from collections.abc import Callable
from datetime import UTC
from html import escape
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from loadlens.kpi import Kpis
from loadlens.verdict import Level, Verdict

HISTORY_SCHEMA_VERSION = 1


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TrendRun(_Strict):
    run_id: str = Field(min_length=1)  # a run added again replaces the earlier entry
    commit: str = Field(min_length=1)
    added_at: AwareDatetime  # when the run was added to the history
    url: str | None  # link to the run
    level: Level
    segments: dict[str, Kpis]  # overall KPIs of each candidate segment


class History(_Strict):
    schema_version: Literal[1] = HISTORY_SCHEMA_VERSION
    runs: list[TrendRun]


def load_history(path: str | Path) -> History:
    return History.model_validate_json(Path(path).read_text(encoding="utf-8"))


def history_text(history: History) -> str:
    return json.dumps(history.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def trend_run(
    verdict: Verdict, *, run_id: str, commit: str, added_at: str, url: str | None
) -> TrendRun:
    return TrendRun.model_validate(
        {
            "run_id": run_id,
            "commit": commit,
            "added_at": added_at,
            "url": url,
            "level": verdict.level,
            "segments": {name: k.overall for name, k in verdict.segments.items()},
        }
    )


def add_run(history: History, run: TrendRun) -> History:
    """Appends the run, or replaces the entry of the same run id where it stands (a re-run)."""
    runs = list(history.runs)
    for i, existing in enumerate(runs):
        if existing.run_id == run.run_id:
            runs[i] = run
            break
    else:
        runs.append(run)
    return History(runs=runs)


def worst(run: TrendRun, kpi: str) -> float | None:
    """Highest value of a KPI over the run's segments, unknown ones left out."""
    values = [v for k in run.segments.values() if (v := getattr(k, kpi)) is not None]
    return max(values) if values else None


# --- page ------------------------------------------------------------------------------------

LEVEL_CLASS = {lv: lv.value.lower() for lv in Level}
WIDTH, HEIGHT = 720, 220
LEFT, RIGHT, TOP, BOTTOM = 64, 16, 12, 28

CSS = """
:root { color-scheme: light dark;
  --bg: #ffffff; --fg: #1f2328; --muted: #59636e; --grid: #d1d9e0; --line: #8c959f;
  --pass: #1a7f37; --warn: #9a6700; --fail: #cf222e; --inconclusive: #6e7781; }
@media (prefers-color-scheme: dark) { :root {
  --bg: #0d1117; --fg: #e6edf3; --muted: #9198a1; --grid: #30363d; --line: #6e7681;
  --pass: #3fb950; --warn: #d29922; --fail: #f85149; --inconclusive: #9198a1; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 760px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 1.5rem; margin: 0 0 4px; }
h2 { font-size: 1.1rem; margin: 32px 0 8px; }
p { margin: 8px 0; }
.muted { color: var(--muted); }
svg { display: block; width: 100%; height: auto; }
svg text { fill: var(--muted); font-size: 13px; }
.grid { stroke: var(--grid); stroke-width: 1; }
.trace { fill: none; stroke: var(--line); stroke-width: 1.5; }
.pass { fill: var(--pass); color: var(--pass); }
.warn { fill: var(--warn); color: var(--warn); }
.fail { fill: var(--fail); color: var(--fail); }
.inconclusive { fill: var(--inconclusive); color: var(--inconclusive); }
.legend span { margin-right: 16px; white-space: nowrap; }
.table { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { padding: 6px 8px; border-bottom: 1px solid var(--grid); text-align: right;
  white-space: nowrap; }
th:nth-child(-n+4), td:nth-child(-n+4) { text-align: left; }
.level { font-weight: 600; }
a { color: inherit; }
""".strip()


def _nice_step(span: float) -> float:
    """1, 2 or 5 times a power of ten, about a quarter of the span."""
    raw = span / 4
    power = 10 ** math.floor(math.log10(raw))
    return next(m * power for m in (1, 2, 5, 10) if m * power >= raw)


def _chart(
    title: str, runs: list[TrendRun], values: list[float | None], fmt: Callable[[float], str]
) -> str:
    known = [v for v in values if v is not None]
    if not known:
        return f'<p class="muted">{escape(title)}: no known value yet.</p>'
    top = max(known)
    step = _nice_step(top) if top > 0 else 1.0
    y_max = step * math.ceil(top / step) if top > 0 else step * 4
    plot_w, plot_h = WIDTH - LEFT - RIGHT, HEIGHT - TOP - BOTTOM

    def x(i: int) -> float:
        return LEFT + (i + 0.5) * plot_w / len(values)

    def y(v: float) -> float:
        return TOP + plot_h * (1 - v / y_max)

    parts = [
        f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="{escape(title)}">',
    ]
    ticks = round(y_max / step)
    for t in range(ticks + 1):
        v = t * step
        parts.append(
            f'<line class="grid" x1="{LEFT}" x2="{WIDTH - RIGHT}" y1="{y(v):.1f}" '
            f'y2="{y(v):.1f}"/>'
            f'<text x="{LEFT - 8}" y="{y(v) + 4:.1f}" text-anchor="end">{escape(fmt(v))}</text>'
        )
    trace: list[str] = []
    for i, v in enumerate(values):  # an unknown value breaks the line
        if v is None:
            if len(trace) > 1:
                parts.append(f'<polyline class="trace" points="{" ".join(trace)}"/>')
            trace = []
        else:
            trace.append(f"{x(i):.1f},{y(v):.1f}")
    if len(trace) > 1:
        parts.append(f'<polyline class="trace" points="{" ".join(trace)}"/>')
    every = math.ceil(len(runs) / 8)
    for i, (run, v) in enumerate(zip(runs, values, strict=True)):
        if i % every == 0 or i == len(runs) - 1:
            parts.append(
                f'<text x="{x(i):.1f}" y="{HEIGHT - 8}" text-anchor="middle">'
                f"{run.added_at:%m-%d}</text>"
            )
        if v is not None:
            label = f"{run.added_at:%Y-%m-%d %H:%M} UTC, {run.commit[:7]}: {fmt(v)}, {run.level}"
            parts.append(
                f'<circle class="{LEVEL_CLASS[run.level]}" cx="{x(i):.1f}" cy="{y(v):.1f}" r="4">'
                f"<title>{escape(label)}</title></circle>"
            )
    parts.append("</svg>")
    return "\n".join(parts)


def _ms(v: float | None) -> str:
    return "unknown" if v is None else f"{v:g} ms"


def _pct(v: float | None) -> str:
    return "unknown" if v is None else f"{v:.2%}"


def trend_page(history: History) -> str:
    runs = sorted(  # by time, whatever the order they were added in; stable for equal times
        (r.model_copy(update={"added_at": r.added_at.astimezone(UTC)}) for r in history.runs),
        key=lambda r: r.added_at,
    )
    count = f"{len(runs)} run{'s' if len(runs) != 1 else ''}"
    body = [
        "<h1>loadlens performance trend</h1>",
        f'<p class="muted">{count} in <a href="history.json">history.json</a>, oldest first in '
        "the charts. A run with several candidate segments shows its worst one: the highest "
        "p95, p99 and error rate.</p>",
        "<p>Each point is one load test checked against its SLOs. Runs ran on different "
        "machines, so their latencies are shown side by side, not compared: a regression is "
        "only measured against a baseline run on the same machine.</p>",
        '<p class="legend">'
        + "".join(f'<span class="{LEVEL_CLASS[lv]}">● {lv}</span>' for lv in Level)
        + "</p>",
    ]
    if not runs:
        body.append('<p class="muted">No run yet.</p>')
    else:
        body += [
            "<h2>p95 latency</h2>",
            _chart("p95 latency per run", runs, [worst(r, "p95_ms") for r in runs], _ms_axis),
            "<h2>Error rate</h2>",
            _chart("Error rate per run", runs, [worst(r, "error_rate") for r in runs], _pct_axis),
            "<h2>Runs, newest first</h2>",
            '<div class="table"><table>',
            "<thead><tr><th>Added (UTC)</th><th>Run</th><th>Commit</th><th>Verdict</th>"
            "<th>p95</th><th>p99</th><th>Error rate</th><th>Samples</th></tr></thead><tbody>",
        ]
        for run in reversed(runs):
            link = (
                f'<a href="{escape(run.url)}">{escape(run.run_id)}</a>'
                if run.url
                else escape(run.run_id)
            )
            samples = sum(k.count for k in run.segments.values())
            body.append(
                f"<tr><td>{run.added_at:%Y-%m-%d %H:%M}</td><td>{link}</td>"
                f"<td><code>{escape(run.commit[:7])}</code></td>"
                f'<td class="level {LEVEL_CLASS[run.level]}">{run.level}</td>'
                f"<td>{_ms(worst(run, 'p95_ms'))}</td><td>{_ms(worst(run, 'p99_ms'))}</td>"
                f"<td>{_pct(worst(run, 'error_rate'))}</td><td>{samples}</td></tr>"
            )
        body.append("</tbody></table></div>")
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>loadlens trend</title>\n"
        f"<style>\n{CSS}\n</style>\n</head>\n<body>\n<main>\n"
        + "\n".join(body)
        + "\n</main>\n</body>\n</html>\n"
    )


def _ms_axis(v: float) -> str:
    return f"{v:g} ms"


def _pct_axis(v: float) -> str:
    return f"{v * 100:g}%"
