# Reporting

A verdict is turned into four outputs: a Markdown summary for people, a JSON file and a JUnit XML
report for other tools, and a trend page across runs. The choices behind them are recorded in
[ADR-007](adr/ADR-007-verdict-outputs-and-trend-history.md).

```bash
loadlens verdict --config config/slo.yaml --abba results/run \
  --json verdict.json --junit verdict.xml --summary summary.md
loadlens trend history.json --add verdict.json --run-id 42 --commit "$SHA" \
  --added-at 2026-10-20T08:00Z --page index.html
```

## Job summary

`--summary PATH` **appends** to the file, so it can be pointed at `$GITHUB_STEP_SUMMARY`: the
level, every reason, the KPIs of each candidate segment (warm-up left out), the comparison with
the baseline when there is one, and what was not checked. A KPI that is not known is written
`unknown`. In CI, the `jmeter`, `gate` and `proof` jobs write it.

## Verdict JSON

`--json PATH` writes the verdict as JSON. Its schema, [JSON Schema draft
2020-12](https://json-schema.org/draft/2020-12/schema), is
[`schemas/verdict.schema.json`](../schemas/verdict.schema.json). It is generated from the model by
`loadlens schema schemas/verdict.schema.json`, never written by hand; a test checks that the
committed file is the generated one, and that verdicts of every shape match it.

| Field | Content |
|---|---|
| `schema_version` | `1`. Raised when a field is renamed, removed or changes meaning; adding a field does not raise it. |
| `level` | `PASS`, `WARN`, `FAIL` or `INCONCLUSIVE` ([verdict.md](verdict.md)) |
| `reasons` | every broken or unchecked rule: `level`, `check`, `transaction` (`null`: the run as a whole), `segment` (`null`: not tied to one), `detail` |
| `notes` | what was not checked, and why |
| `segments` | per candidate segment name: KPIs overall and per transaction, measured duration, Apdex T ([kpi.md](kpi.md)) |
| `comparisons` | per transaction, when a baseline was given: p95 of each arm, windows, windowed p-value and Cliff's δ |

`check` is one of `hard_slo`, `soft_slo`, `regression`, `weak_regression`, `comparison`,
`sample_size`, `no_measurement`. A reader that has to decide like the CI job does: the job fails
when `level` is `FAIL`, or when a reason has the check `no_measurement` (ADR-005).

## JUnit XML

`--junit PATH` writes one test case per check target, under one suite named `loadlens verdict`:

| Test case | `classname` | `name` |
|---|---|---|
| SLOs of a transaction in a candidate segment | `loadlens.slo` | `get_payment [B1]`, `all transactions [B1]` |
| Comparison of a transaction with the baseline | `loadlens.regression` | `get_payment` |
| A rule about the whole comparison, or a run that could not be read | as above | `all transactions` |

A test case fails in JUnit exactly when its reasons fail the CI job:

| Reasons of the test case | JUnit outcome |
|---|---|
| none | passed |
| WARN only | passed, the reason in `<system-out>` |
| a FAIL | `<failure>`, typed with its check |
| nothing measured (`no_measurement`) | `<error>`: the check did not take place |
| any other INCONCLUSIVE | `<skipped>`: the check could not be made |

The suite carries the level as a property (`level`) and the notes in its `<system-out>`. A test
case lists each of its reasons as `LEVEL check: detail`.

## Trend page

`loadlens trend HISTORY_JSON` keeps one JSON history and rebuilds the page from it:

- `--add VERDICT_JSON` with `--run-id`, `--commit` and `--added-at` (ISO 8601 with a UTC offset)
  adds one run, and `--url` links it. A run added again with the same id replaces its entry.
- `--start` begins a new history; it refuses a file that already exists. Without it, a missing
  history is an error: a history cannot be rebuilt, so it is never started by accident.
- `--page HTML` writes the page: p95 and error rate per run, and a table of the runs. A run with
  several candidate segments shows its worst one (the highest p95, p99 and error rate). Runs are
  ordered by the time they were added. A value that is not known is not plotted.

The page is plain HTML with inline SVG: no script, no external resource, the same bytes for the
same history. It follows the reader's light or dark theme.

Each run of a history ran on its own machine: the page shows their values side by side and
compares nothing. A regression is only measured against a baseline run on the same machine
([ADR-003](adr/ADR-003-abba-protocol-on-one-machine.md)).

### In CI

The `trend page (main)` job runs after the `jmeter` job, on `main` only (pushes and manual runs of
the CI workflow), whether the verdict passed or failed:

1. it fetches `history.json` from the `gh-pages` branch, or starts it when the branch does not
   exist yet;
2. it adds the run (`--added-at` is the time of the job, `--url` the workflow run);
3. it pushes `history.json` and `index.html` to `gh-pages`;
4. it deploys them with GitHub Pages, through Actions: a commit pushed with the `GITHUB_TOKEN` does
   not start a Pages build from a branch.

GitHub Pages must be enabled in the repository settings with **GitHub Actions** as its source.
The page is served at <https://bazanjeremy.github.io/loadlens/>.
