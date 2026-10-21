import json
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from loadlens.adapters.jmeter import read_jtl
from loadlens.cli import main
from loadlens.report.json_schema import verdict_json_schema, verdict_json_schema_text
from loadlens.report.junit import junit_xml
from loadlens.report.summary import markdown_summary
from loadlens.report.trend import History, add_run, load_history, trend_page, trend_run, worst
from loadlens.schema import Run, RunMetadata, Samples, Tool
from loadlens.verdict import (
    Level,
    Reason,
    Verdict,
    evaluate,
    inconclusive,
    load_config,
)

ROOT = Path(__file__).resolve().parents[1]
SHIPPED = ROOT / "config" / "slo.yaml"
COMMITTED_SCHEMA = ROOT / "schemas" / "verdict.schema.json"
META = RunMetadata(tool=Tool.JMETER, source_file="x", started_at=datetime(2026, 1, 1, tzinfo=UTC))


@pytest.fixture(scope="module")
def config():
    return load_config(SHIPPED)


def run_of(elapsed, transaction="t", step_ms=100):
    """Samples `step_ms` apart: 600 samples at 100 ms = 60 s = 12 windows of 5 s."""
    n = len(elapsed)
    return Run(
        metadata=META,
        samples=Samples(
            start_ms=[i * step_ms for i in range(n)],
            elapsed_ms=[int(e) for e in elapsed],
            transaction=[transaction] * n,
            success=[True] * n,
            response_code=["200"] * n,
        ),
    )


def latencies(mean, sd, seed, n=600):
    return np.clip(np.random.default_rng(seed).normal(mean, sd, n), 1, None).round()


def single(jmeter_fixture, name, config, **kwargs):
    path = jmeter_fixture(f"2026-10-17-{name}.jtl")
    return evaluate([read_jtl(path)], config, segment_names=[path.name], **kwargs)


@pytest.fixture
def verdicts(config, jmeter_fixture):
    """One verdict of each shape the report has to carry."""
    healthy = [run_of(latencies(50, 5, seed)) for seed in (1, 2)]
    slower = [run_of(latencies(80, 5, seed)) for seed in (3, 4)]
    return {
        "warn_slo_only": single(
            jmeter_fixture,
            "nominal-short",
            config,
            target_rps={"get_statement": 6, "never_sent": 1},
        ),
        "fail_hard_slo": single(jmeter_fixture, "all-errors", config),
        "fail_regression": evaluate(slower, config, baseline=healthy, segment_names=["B1", "B2"]),
        "pass_compared": evaluate(
            healthy, config, baseline=[run_of(latencies(50, 5, s)) for s in (5, 6)]
        ),
        "inconclusive_windows": evaluate(
            [run_of(latencies(50, 5, 7, n=100))], config, baseline=[run_of(latencies(50, 5, 8))]
        ),
        "inconclusive_aggregates": evaluate(
            [run_of(latencies(50, 5, 9))],
            config,
            baseline=[Run(metadata=META, samples=None, aggregates=[])],
        ),
        "nothing_measured": inconclusive("A-B-B-A run unusable: no meta.json"),
    }


# --- JSON schema -----------------------------------------------------------------------------


def test_committed_schema_is_the_generated_one():
    """Regenerate with `loadlens schema schemas/verdict.schema.json` after changing the model."""
    assert COMMITTED_SCHEMA.read_text(encoding="utf-8") == verdict_json_schema_text()


def test_every_verdict_written_matches_the_schema(verdicts):
    validator = Draft202012Validator(verdict_json_schema())
    Draft202012Validator.check_schema(verdict_json_schema())
    for name, verdict in verdicts.items():
        written = json.loads(verdict.model_dump_json())
        errors = [e.message for e in validator.iter_errors(written)]
        assert not errors, (name, errors)
        assert written["schema_version"] == 1


def test_schema_rejects_an_unknown_level():
    validator = Draft202012Validator(verdict_json_schema())
    written = json.loads(inconclusive("x").model_dump_json())
    written["level"] = "MAYBE"
    assert not validator.is_valid(written)


def test_verdict_json_round_trips(verdicts):
    for verdict in verdicts.values():
        assert Verdict.model_validate_json(verdict.model_dump_json()) == verdict


def test_segment_names_must_differ(config):
    with pytest.raises(ValueError, match="segment names must differ"):
        evaluate([run_of([10] * 10)] * 2, config, segment_names=["run.jtl", "run.jtl"])


def test_cli_refuses_two_candidates_with_one_name(tmp_path, jmeter_fixture):
    path = jmeter_fixture("2026-10-17-nominal-short.jtl")
    copy = tmp_path / path.name
    copy.write_bytes(path.read_bytes())
    args = ["verdict", "--config", str(SHIPPED), "--candidate", str(path), "--candidate", str(copy)]
    assert main(args) == 4


# --- JUnit -----------------------------------------------------------------------------------


def parse(verdict):
    root = ET.fromstring(junit_xml(verdict).encode("utf-8"))
    cases = {
        (c.get("classname"), c.get("name")): next(
            (child.tag for child in c if child.tag in ("failure", "error", "skipped")), "passed"
        )
        for c in root.iter("testcase")
    }
    return root, cases


def test_junit_counts_match_the_cases(verdicts):
    for verdict in verdicts.values():
        root, cases = parse(verdict)
        outcomes = list(cases.values())
        for element in (root, root.find("testsuite")):
            assert element.get("tests") == str(len(outcomes))
            assert element.get("failures") == str(outcomes.count("failure"))
            assert element.get("errors") == str(outcomes.count("error"))
            assert element.get("skipped") == str(outcomes.count("skipped"))


def test_junit_fails_exactly_when_the_ci_job_fails(verdicts):
    """ADR-007: a case fails in JUnit (failure or error) when the verdict fails the CI job."""
    for name, verdict in verdicts.items():
        _, cases = parse(verdict)
        failing = any(outcome in ("failure", "error") for outcome in cases.values())
        assert failing == (not verdict.ci_passes), name


def test_junit_warn_passes_with_its_reason(verdicts):
    root, cases = parse(verdicts["warn_slo_only"])
    assert set(cases.values()) == {"passed"}
    # A declared rate never sent has no KPI row, but still a test case: the WARN one.
    case = next(c for c in root.iter("testcase") if c.get("name").startswith("never_sent"))
    assert case.find("system-out").text == "WARN soft_slo: no sample, target 1/s"
    assert case.get("name") == "never_sent [2026-10-17-nominal-short.jtl]"
    notes = root.find("testsuite").find("system-out").text
    assert "no baseline: SLO-only verdict" in notes


def test_junit_fail_is_a_failure_typed_by_its_check(verdicts):
    root, cases = parse(verdicts["fail_hard_slo"])
    case = next(c for c in root.iter("testcase") if c.get("name").startswith("all transactions"))
    failure = case.find("failure")
    assert failure.get("type") == "hard_slo"
    assert "error rate 100.00%" in failure.get("message")
    assert root.find("testsuite/properties/property").get("value") == "FAIL"


def test_junit_regression_cases_per_transaction(verdicts):
    _, cases = parse(verdicts["fail_regression"])
    assert cases[("loadlens.regression", "t")] == "failure"
    assert cases[("loadlens.slo", "t [B1]")] == "passed"
    _, cases = parse(verdicts["pass_compared"])
    assert cases[("loadlens.regression", "t")] == "passed"


def test_junit_inconclusive_is_skipped_unless_nothing_was_measured(verdicts):
    _, cases = parse(verdicts["inconclusive_windows"])
    assert cases[("loadlens.regression", "t")] == "skipped"
    _, cases = parse(verdicts["inconclusive_aggregates"])
    assert cases[("loadlens.regression", "all transactions")] == "skipped"
    _, cases = parse(verdicts["nothing_measured"])
    assert cases == {("loadlens.slo", "all transactions"): "error"}


def test_junit_escapes_markup():
    reason = Reason(
        level=Level.FAIL, check="hard_slo", transaction="<t&>", segment='"s"', detail="a < b"
    )
    verdict = Verdict(level=Level.FAIL, reasons=[reason], notes=[], segments={}, comparisons=[])
    root, cases = parse(verdict)
    assert cases == {("loadlens.slo", '<t&> ["s"]'): "failure"}
    assert "a < b" in root.find(".//failure").get("message")


# --- Markdown summary ------------------------------------------------------------------------


def test_summary_lists_level_reasons_kpis_and_notes(verdicts):
    verdict = verdicts["warn_slo_only"]
    text = markdown_summary(verdict)
    assert text.startswith("## loadlens verdict: ⚠️ WARN\n")
    assert (
        "| WARN | soft_slo | never_sent | 2026-10-17-nominal-short.jtl | no sample, target 1/s |"
        in text
    )
    assert "### KPIs, segment 2026-10-17-nominal-short.jtl" in text
    count = verdict.segments["2026-10-17-nominal-short.jtl"].overall.count
    assert f"| all transactions | {count} | 0 (0.00%) |" in text
    assert "- no baseline: SLO-only verdict, regressions not checked" in text
    assert "### Comparison with the baseline" not in text


def test_summary_of_a_comparison(verdicts):
    text = markdown_summary(verdicts["fail_regression"])
    assert "### KPIs, segment B1" in text and "### KPIs, segment B2" in text
    assert "### Comparison with the baseline" in text
    comparison = text[text.index("### Comparison with the baseline") :]
    row = next(line for line in comparison.splitlines() if line.startswith("| t |"))
    assert row.endswith("| 24 / 24 |")  # two 60 s segments per arm, 12 windows of 5 s each


def test_summary_without_reason_says_so(verdicts):
    assert "None: every check that could be made held." in markdown_summary(
        verdicts["pass_compared"]
    )


def test_summary_escapes_table_cells():
    reason = Reason(
        level=Level.WARN, check="soft_slo", transaction="a|b", segment=None, detail="x\ny | z"
    )
    verdict = Verdict(level=Level.WARN, reasons=[reason], notes=[], segments={}, comparisons=[])
    row = markdown_summary(verdict).splitlines()[6]
    assert row == "| WARN | soft_slo | a\\|b |  | x y \\| z |"


def test_unknown_kpis_are_written_unknown(verdicts):
    text = markdown_summary(verdicts["fail_hard_slo"])  # no successful sample: no latency
    row = next(line for line in text.splitlines() if line.startswith("| all transactions |"))
    assert "unknown" in row


# --- trend history and page ------------------------------------------------------------------


def entry(verdict, run_id, added_at, commit="0123456789abcdef"):
    return trend_run(verdict, run_id=run_id, commit=commit, added_at=added_at, url=None)


def test_add_run_appends_and_replaces_a_rerun(verdicts):
    history = History(runs=[])
    history = add_run(history, entry(verdicts["warn_slo_only"], "1", "2026-10-20T08:00Z"))
    history = add_run(history, entry(verdicts["fail_hard_slo"], "2", "2026-10-20T09:00Z"))
    history = add_run(history, entry(verdicts["pass_compared"], "1", "2026-10-20T10:00Z"))
    assert [(r.run_id, r.level) for r in history.runs] == [("1", Level.PASS), ("2", Level.FAIL)]


def test_trend_run_keeps_the_overall_kpis_of_each_segment(verdicts):
    run = entry(verdicts["fail_regression"], "1", "2026-10-20T08:00+02:00")
    assert set(run.segments) == {"B1", "B2"}
    assert run.added_at == datetime(2026, 10, 20, 6, tzinfo=UTC)
    p95 = [k.p95_ms for k in run.segments.values()]
    assert worst(run, "p95_ms") == max(p95)


def test_trend_run_needs_a_utc_offset(verdicts):
    with pytest.raises(ValueError, match="timezone"):
        entry(verdicts["pass_compared"], "1", "2026-10-20T08:00")


def test_page_is_deterministic_and_sorted_by_time(verdicts):
    history = History(
        runs=[
            entry(verdicts["warn_slo_only"], "late", "2026-10-21T08:00Z", commit="bbbbbbb1"),
            entry(verdicts["fail_hard_slo"], "early", "2026-10-20T08:00Z", commit="aaaaaaa1"),
        ]
    )
    page = trend_page(history)
    assert page == trend_page(History.model_validate_json(history.model_dump_json()))
    assert "2 runs" in page
    body = page[page.index("<tbody>") :]
    assert body.index("bbbbbbb") < body.index("aaaaaaa")  # newest first in the table
    assert page.count("<circle") == 3  # p95 of the all-errors run is unknown: not plotted
    assert "<script" not in page and "http://" not in page and "https://" not in page


def test_page_escapes_what_it_shows(verdicts):
    run = trend_run(
        verdicts["pass_compared"],
        run_id="<script>alert(1)</script>",
        commit='"><img>',
        added_at="2026-10-20T08:00Z",
        url='https://example.invalid/?a=1&b="2"',
    )
    page = trend_page(History(runs=[run]))
    assert "<script>" not in page and "<img>" not in page
    assert 'href="https://example.invalid/?a=1&amp;b=&quot;2&quot;"' in page


def test_page_without_runs():
    page = trend_page(History(runs=[]))
    assert "0 runs" in page and "No run yet." in page and "<svg" not in page


def axis_labels(page, title):
    """Y-axis labels of the chart titled `title`, bottom to top."""
    svg = page[page.index(f'aria-label="{title}"') :]
    return re.findall(r'text-anchor="end">([^<]*)</text>', svg[: svg.index("</svg>")])


@pytest.mark.parametrize(
    ("shapes", "labels"),
    [
        (["pass_compared"] * 3, ["0%", "0.5%", "1%"]),  # every error rate 0: the 1% span
        (["pass_compared", "fail_hard_slo"], ["0%", "50%", "100%"]),  # the data's own span
    ],
)
def test_page_error_rate_axis(verdicts, shapes, labels):
    """Seen on the live page on 2026-10-21, not by a test: every rate 0 gave a 0-400% axis."""
    runs = [entry(verdicts[s], str(i), f"2026-10-2{i}T08:00Z") for i, s in enumerate(shapes)]
    assert axis_labels(trend_page(History(runs=runs)), "Error rate per run") == labels


def test_page_error_rate_axis_has_a_1_percent_floor(config):
    """One error in 2,386 samples, the size of a CI run: 0.04% sits low on a 0-1% axis."""
    n = 2386
    run = Run(
        metadata=META,
        samples=Samples(
            start_ms=[i * 100 for i in range(n)],
            elapsed_ms=[50] * n,
            transaction=["t"] * n,
            success=[False] + [True] * (n - 1),
            response_code=["500"] + ["200"] * (n - 1),
        ),
    )
    runs = [entry(evaluate([run], config), str(i), f"2026-10-2{i}T08:00Z") for i in range(3)]
    page = trend_page(History(runs=runs))
    assert axis_labels(page, "Error rate per run") == ["0%", "0.5%", "1%"]


def test_page_p95_axis_when_every_p95_is_zero(config):
    verdict = evaluate([run_of([0] * 600)], config)  # every sample under 1 ms
    runs = [entry(verdict, str(i), f"2026-10-2{i}T08:00Z") for i in range(3)]
    page = trend_page(History(runs=runs))
    assert axis_labels(page, "p95 latency per run") == ["0 ms", "0.5 ms", "1 ms"]


# --- command line ----------------------------------------------------------------------------


def test_cli_verdict_writes_junit_and_appends_the_summary(tmp_path, jmeter_fixture):
    summary = tmp_path / "summary.md"
    summary.write_text("before\n", encoding="utf-8")
    junit = tmp_path / "verdict.xml"
    path = str(jmeter_fixture("2026-10-17-all-errors.jtl"))
    args = ["verdict", "--config", str(SHIPPED), "--candidate", path]
    for _ in range(2):
        assert main([*args, "--junit", str(junit), "--summary", str(summary)]) == 2
    text = summary.read_text(encoding="utf-8")
    assert text.startswith("before\n") and text.count("## loadlens verdict: ❌ FAIL") == 2
    assert ET.parse(junit).getroot().get("failures") != "0"


def test_cli_schema_to_a_file(tmp_path, capsys):
    out = tmp_path / "schema.json"
    assert main(["schema", str(out)]) == 0
    assert out.read_bytes() == verdict_json_schema_text().encode("utf-8")
    assert main(["schema"]) == 0
    assert json.loads(capsys.readouterr().out)["title"] == "Verdict"


def test_cli_trend_starts_adds_and_writes_the_page(tmp_path, verdicts):
    verdict = tmp_path / "verdict.json"
    verdict.write_text(verdicts["warn_slo_only"].model_dump_json(), encoding="utf-8")
    history, page = tmp_path / "history.json", tmp_path / "index.html"
    add = ["--add", str(verdict), "--commit", "abc1234", "--added-at", "2026-10-20T08:00Z"]
    assert main(["trend", str(history), "--start", *add, "--run-id", "1"]) == 0
    assert main(["trend", str(history), *add, "--run-id", "2", "--page", str(page)]) == 0
    assert [r.run_id for r in load_history(history).runs] == ["1", "2"]
    assert "2 runs" in page.read_text(encoding="utf-8")
    assert b"\r" not in history.read_bytes() + page.read_bytes()


@pytest.mark.parametrize(
    "args",
    [
        ["--start"],  # the history exists: never overwritten
        ["--page", "P"],  # fine
        ["--add", "V", "--run-id", "3"],  # no commit, no time
        ["--run-id", "3", "--page", "P"],  # run fields without --add
        [],  # nothing to do
        ["--add", "V", "--run-id", "3", "--commit", "c", "--added-at", "2026-10-20T08:00"],
    ],
)
def test_cli_trend_arguments(tmp_path, verdicts, args):
    verdict = tmp_path / "verdict.json"
    verdict.write_text(verdicts["pass_compared"].model_dump_json(), encoding="utf-8")
    history = tmp_path / "history.json"
    history.write_text(History(runs=[]).model_dump_json(), encoding="utf-8")
    before = history.read_bytes()
    args = [str(verdict) if a == "V" else str(tmp_path / "p.html") if a == "P" else a for a in args]
    code = main(["trend", str(history), *args])
    assert code == (0 if args[:1] == ["--page"] else 4)
    assert history.read_bytes() == before


def test_cli_trend_needs_an_existing_history_without_start(tmp_path):
    assert main(["trend", str(tmp_path / "missing.json"), "--page", str(tmp_path / "p")]) == 4
