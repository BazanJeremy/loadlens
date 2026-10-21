"""JUnit XML report of a verdict, for tools that read test results (ADR-007).

One test case per check target: the SLOs of a transaction in a candidate segment
(`loadlens.slo`, "get_payment [B1]"), and the comparison of a transaction with the baseline
(`loadlens.regression`, "get_payment"). A test case fails in JUnit when it fails the CI job:

- FAIL: `<failure>`;
- INCONCLUSIVE because nothing was measured: `<error>`, the check did not take place;
- any other INCONCLUSIVE: `<skipped>`, the check could not be made;
- WARN: passed, with the reason in `<system-out>`: a WARN leaves the CI job green.

What was not checked (the verdict's notes) goes to the suite's `<system-out>`.
"""

import xml.etree.ElementTree as ET

from loadlens.verdict import NO_MEASUREMENT, OVERALL, Level, Reason, Verdict

SLO_CHECKS = frozenset({"hard_slo", "soft_slo", NO_MEASUREMENT})


def _case(check_family: str, transaction: str | None, segment: str | None) -> tuple[str, str]:
    name = transaction or OVERALL
    return f"loadlens.{check_family}", f"{name} [{segment}]" if segment else name


def _line(r: Reason) -> str:
    return f"{r.level} {r.check}: {r.detail}"


def junit_xml(verdict: Verdict) -> str:
    cases: dict[tuple[str, str], list[Reason]] = {}
    for segment, kpis in verdict.segments.items():
        for transaction in [None, *kpis.transactions]:
            cases.setdefault(_case("slo", transaction, segment), [])
    for c in verdict.comparisons:
        cases.setdefault(_case("regression", c.transaction, None), [])
    for r in verdict.reasons:  # also the targets no KPI lists, e.g. a declared rate never sent
        family = "slo" if r.check in SLO_CHECKS else "regression"
        cases.setdefault(_case(family, r.transaction, r.segment), []).append(r)

    suite = ET.Element("testsuite", name="loadlens verdict")
    properties = ET.SubElement(suite, "properties")
    ET.SubElement(properties, "property", name="level", value=str(verdict.level))
    counts = {"failure": 0, "error": 0, "skipped": 0}
    for (classname, name), reasons in cases.items():
        case = ET.SubElement(suite, "testcase", classname=classname, name=name)
        message = "; ".join(_line(r) for r in reasons)
        outcome = _outcome(reasons)
        if outcome is not None:
            tag, kind = outcome
            counts[tag] += 1
            element = ET.SubElement(case, tag, message=message)
            if kind:
                element.set("type", kind)
        elif reasons:  # WARN only: passed, the reason kept
            ET.SubElement(case, "system-out").text = message
    if verdict.notes:
        ET.SubElement(suite, "system-out").text = "\n".join(verdict.notes)

    attributes = {
        "tests": str(len(cases)),
        "failures": str(counts["failure"]),
        "errors": str(counts["error"]),
        "skipped": str(counts["skipped"]),
    }
    for key, value in attributes.items():
        suite.set(key, value)
    root = ET.Element("testsuites", name="loadlens", **attributes)
    root.append(suite)
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def _outcome(reasons: list[Reason]) -> tuple[str, str] | None:
    """JUnit element and type of a case that did not pass; None for a passed case."""
    for r in reasons:
        if r.level is Level.FAIL:
            return "failure", r.check
    for r in reasons:
        if r.check == NO_MEASUREMENT:
            return "error", r.check
    if any(r.level is Level.INCONCLUSIVE for r in reasons):
        return "skipped", ""
    return None
