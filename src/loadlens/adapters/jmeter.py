"""Apache JMeter JTL (CSV) adapter.

Format reference: JMeter user manual, section 12.4 "CSV Log format"
(https://jmeter.apache.org/usermanual/listeners.html). Column order is fixed but each column is
optional, so columns are read by header name. Required here: `timeStamp` (epoch milliseconds),
`elapsed`, `label`, `responseCode`, `success`. loadlens runs pin the settings this relies on
(header line, millisecond timestamps, start-of-sample timestamps, no sub-results) in
`load/jmeter/loadlens.properties`.

Every row becomes one sample. Files are read as UTF-8 (JMeter writes the platform encoding,
UTF-8 in the Linux container loadlens uses).
"""

import csv
from datetime import UTC, datetime
from pathlib import Path

from loadlens.schema import Machine, Run, RunMetadata, Samples, Tool

REQUIRED_COLUMNS = ("timeStamp", "elapsed", "label", "responseCode", "success")
_BOOLEANS = {"true": True, "false": False}


class JtlFormatError(ValueError):
    """The file is not a JTL CSV this adapter can read. The message names the line."""


def read_jtl(
    path: str | Path,
    *,
    tool_version: str | None = None,
    profile: dict[str, str] | None = None,
    machine: Machine | None = None,
) -> Run:
    path = Path(path)
    start_ms: list[int] = []
    elapsed_ms: list[int] = []
    transaction: list[str] = []
    success: list[bool] = []
    response_code: list[str] = []

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            raise JtlFormatError(f"{path}: empty file, expected a header line")
        missing = [name for name in REQUIRED_COLUMNS if name not in header]
        if missing:
            raise JtlFormatError(
                f"{path}: line 1: missing columns {missing}"
                " (expected a header line: jmeter.save.saveservice.print_field_names=true)"
            )
        col = {name: header.index(name) for name in REQUIRED_COLUMNS}

        for line_no, row in enumerate(reader, start=2):
            if len(row) != len(header):
                raise JtlFormatError(
                    f"{path}: line {line_no}: {len(row)} fields, header has {len(header)}"
                )
            try:
                start = int(row[col["timeStamp"]])
            except ValueError:
                raise JtlFormatError(
                    f"{path}: line {line_no}: timeStamp {row[col['timeStamp']]!r} is not epoch"
                    " milliseconds (expected jmeter.save.saveservice.timestamp_format=ms)"
                ) from None
            try:
                elapsed = int(row[col["elapsed"]])
            except ValueError:
                raise JtlFormatError(
                    f"{path}: line {line_no}: elapsed {row[col['elapsed']]!r} is not an integer"
                ) from None
            if elapsed < 0:
                raise JtlFormatError(f"{path}: line {line_no}: negative elapsed {elapsed}")
            flag = _BOOLEANS.get(row[col["success"]])
            if flag is None:
                raise JtlFormatError(
                    f"{path}: line {line_no}: success {row[col['success']]!r}"
                    " is neither 'true' nor 'false'"
                )
            start_ms.append(start)
            elapsed_ms.append(elapsed)
            transaction.append(row[col["label"]])
            success.append(flag)
            response_code.append(row[col["responseCode"]])

    started_at = datetime.fromtimestamp(min(start_ms) / 1000, tz=UTC) if start_ms else None
    return Run(
        metadata=RunMetadata(
            tool=Tool.JMETER,
            tool_version=tool_version,
            source_file=path.name,
            started_at=started_at,
            profile=profile or {},
            machine=machine,
        ),
        samples=Samples(
            start_ms=start_ms,
            elapsed_ms=elapsed_ms,
            transaction=transaction,
            success=success,
            response_code=response_code,
        ),
    )
