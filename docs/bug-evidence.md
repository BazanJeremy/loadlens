# Bug Evidence Log

Bugs found in this project, documented before being fixed — never silently. Each
entry says what caught it (one of the project's tests, or not), the cause, the fix,
and the test that pins it.

## #1 — Error-rate axis labelled 0% to 400% when every rate was 0 (2026-10-21, step 5)

- **Caught by:** reading the live trend page (<https://bazanjeremy.github.io/loadlens/>)
  on 2026-10-21, with 3 runs on it — **not by a test**. No test rendered a chart whose
  values were all 0, and the local trial before the merge of the reporting step used a
  run with a 100% error rate, whose axis is right.
- **Symptom:** with every error rate at 0, the "Error rate" chart labelled its axis 0%,
  100%, 200%, 300%, 400%. A rate cannot pass 100%, and a series of zeros is the normal
  case for the error rate.
- **Cause:** when the highest value was 0, `_chart` (`src/loadlens/report/trend.py`)
  fell back to `step = 1.0` and `y_max = 4 × step`, a span in no chart's unit, and
  `_pct_axis` multiplied 0 to 4 by 100. The p95 chart shared that path (0 to 4 ms on a
  series of zeros; never seen on the page).
- **Fix:** `_chart` takes a span per chart, used only when every known value is 0: 1 ms
  for the p95 (sample times are whole milliseconds, so a p95 above 0 is at least 1 ms)
  and 1% for the error rate (the smallest round rate that keeps the shipped hard
  error-rate SLO, 0.5%, on the axis). A chart with a value above 0 keeps the span of its
  data, so a 100% rate still tops out at 100%.
- **Pinned by:** `tests/test_report.py::test_page_error_rate_axis` (every rate 0: labels
  0%, 0.5%, 1%; with a 100% run: 0%, 50%, 100%) and
  `tests/test_report.py::test_page_p95_axis_when_every_p95_is_zero` (0 ms, 0.5 ms, 1 ms).
  Both fail on the code before the fix.
