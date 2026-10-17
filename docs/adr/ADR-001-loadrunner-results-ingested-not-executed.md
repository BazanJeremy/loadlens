# ADR-001: LoadRunner results are ingested, not executed, in CI

- **Status:** Proposed
- **Date:** 2026-10-17
- **Deciders:** Jérémy Bazan

## Context

loadlens must produce a verdict from LoadRunner-family results as well as from JMeter, and its
CI must stay green with zero proprietary binaries and zero credentials.

The free LoadRunner-family tool is OpenText Performance Engineering for Developers (formerly
LoadRunner Developer). What its licence says (source: OpenText Additional License Authorizations
for Performance Engineering software, document 5200-1957 of 2025-01-20, read on 2026-10-16):

- a community licence allowing one test at a time, 50 virtual users and the DevWeb protocol
  only, "limited in use for test development and proof-of-concept execution";
- "Any commercial use is strictly prohibited";
- clause C of the additional terms: results of benchmarks of the software itself, and "specific
  detailed comparisons" between the software and third-party products, may not be disclosed
  without written consent.

Unknown: whether downloading the tool requires an OpenText account (the marketplace page shows a
download button, older third-party guides say an account is needed), and whether a more recent
version of the licence document exists.

## Decision

LoadRunner never runs in CI. Its results are produced locally by the maintainer, committed as
dated fixtures, and ingested by an adapter built only from those real files or from cited
official documentation. JMeter/LoadRunner parity is a verdict parity — both chains reach the
same verdict on the same regression — never a published table of figures comparing the tools.

## Options Considered

1. **Ingest committed fixtures (chosen)** — CI stays free of proprietary binaries and
   credentials; the licence is respected. Cost: LoadRunner results are not reproduced by CI.
2. **Download and run the tool in CI** — reproducible, but needs a binary that cannot be
   redistributed, possibly an account in CI secrets, and runs against the licence's intent.
3. **Leave LoadRunner out** — simplest, but drops half of the problem loadlens addresses.

## Consequences

- Every LoadRunner fixture is dated and states the tool version and how it was produced.
- An adapter without a real file or an official format description is not written: work stops
  and the maintainer is asked.
- No README, test report or ADR publishes JMeter and LoadRunner figures side by side.
- The 50-virtual-user limit is a documented limitation of the LoadRunner path.

## Sources

- OpenText, Additional License Authorizations for Performance Engineering software, 5200-1957:
  https://www.opentext.com/media/documentation/additional-license-authorizations-for-performance-engineering-software-products-documentation-en.pdf
- DevWeb FAQ (50 Vusers): https://admhelp.microfocus.com/lrd/en/26.1-26.3/help/Content/DevWeb/DW-FAQ.htm
