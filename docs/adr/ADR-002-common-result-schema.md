# ADR-002: Common result schema with one adapter per tool

- **Status:** Accepted
- **Date:** 2026-10-17
- **Deciders:** Jérémy Bazan

## Context

loadlens reads JMeter JTL files and LoadRunner-family results, then computes the same KPIs and
the same verdict on both. Two facts shape the model:

- Statistics (rank tests, effect sizes, tail percentiles) need raw samples. A JMeter JTL has one
  row per sample (`fixtures/jmeter/PROVENANCE.md`).
- Some sources only export summaries. DevWeb can write an aggregated `replay_summary.json`
  besides its raw SQLite results (source: DevWeb "Run scripts locally" help page, 26.x); what a
  real export contains is unknown until the maintainer supplies one.

## Decision

One pivot model, `loadlens.schema.Run`, produced by one adapter per tool. A run carries
**either** column-oriented raw samples **or** per-transaction aggregates — exactly one, so there
is a single source of truth per run. Unknown values are `None`, never estimated: for example a
JTL does not record the JMeter version, so `tool_version` is `None` unless the caller supplies it.

## Options Considered

1. **Samples or aggregates, exactly one (chosen)** — statistics run when samples exist, and an
   aggregate-only run degrades explicitly (no overall percentile, no Apdex, no comparison test)
   instead of failing late.
2. **Samples only** — simpler, but the first aggregate-only source would force a schema change
   after this ADR is accepted.
3. **Both at once** — two possibly inconsistent sources of truth in one run.

Samples are stored column by column (one list per field) rather than one object per sample.
Measured on 2026-10-17 (Python 3.14, the machine in `fixtures/jmeter/PROVENANCE.md`): reading a
200,000-row JTL takes 0.44 s and computing its KPIs 0.30 s.

## Consequences

- Each adapter only translates a format into `Run`; KPI and verdict code never sees a tool format.
- Overall percentiles of an aggregate-only run stay unknown: per-transaction percentiles cannot
  be merged (`docs/kpi.md`).
- Machine and load-profile metadata are optional and supplied by whoever launches the run.

## Sources

- JMeter user manual, 12.4 CSV Log format: https://jmeter.apache.org/usermanual/listeners.html
- DevWeb, Run scripts locally (26.x): https://admhelp.microfocus.com/lrd/en/26.1-26.3/help/Content/DevWeb/DW-run-scripts_CLI.htm
