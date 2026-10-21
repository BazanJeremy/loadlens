"""LoadRunner DevWeb raw results (`devWebDB.db`, SQLite) adapter.

Format reference: no official description of this file was found (the DevWeb "Run scripts
locally" help page, 26.x, names neither the file nor its tables). The adapter is built from real
files written by OpenText Performance Engineering for Developers 26.3, committed in
`fixtures/loadrunner/` with their provenance. What they show, and what is read here:

- table `Transactions (uid, timestamp, name, duration, thinkTime, status)`, one row per
  transaction; `duration` and `thinkTime` are integer milliseconds, `status` is `Passed` or
  `Failed`;
- `timestamp` is ISO 8601 local time without a UTC offset, with 1 to 3 fraction digits (trailing
  zeros dropped), so the caller gives the offset (DevWeb's `replay_summary.json` writes it in its
  `startTime`);
- `timestamp` marks the end of the transaction: every request (table `Hits`) falls within
  [timestamp - duration, timestamp] of a transaction of its Vuser, while many fall within no
  [timestamp, timestamp + duration] (both fixtures, checked by a test). A sample's start is
  therefore `timestamp - duration`;
- no HTTP status code per transaction (table `Hits` has codes, with nothing linking them to a
  transaction), so `response_code` is `None`.

Rows with a non-zero `thinkTime` or another status are refused: how DevWeb writes them was never
observed.
"""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from loadlens.schema import Machine, Run, RunMetadata, Samples, Tool

# First 16 bytes of every SQLite 3 database (https://www.sqlite.org/fileformat.html, 1.3).
SQLITE_MAGIC = b"SQLite format 3\x00"
COLUMNS = ("timestamp", "name", "duration", "thinkTime", "status")
_STATUSES = {"Passed": True, "Failed": False}
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MS = timedelta(milliseconds=1)


class DevWebFormatError(ValueError):
    """The file is not a DevWeb result database this adapter can read. The message names the
    row."""


def is_sqlite(path: str | Path) -> bool:
    with open(path, "rb") as handle:
        return handle.read(len(SQLITE_MAGIC)) == SQLITE_MAGIC


def read_devweb(
    path: str | Path,
    *,
    utc_offset: timedelta,
    tool_version: str | None = None,
    profile: dict[str, str] | None = None,
    machine: Machine | None = None,
) -> Run:
    path = Path(path)
    if not path.is_file():  # sqlite3 would create an empty database instead of failing
        raise FileNotFoundError(f"no such file: {path}")
    zone = timezone(utc_offset)
    try:
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
            present = {row[1] for row in db.execute("PRAGMA table_info(Transactions)")}
            missing = [name for name in COLUMNS if name not in present]
            if missing:
                raise DevWebFormatError(
                    f"{path}: table Transactions missing or without columns {missing}"
                )
            rows = db.execute(
                "SELECT rowid, timestamp, name, duration, thinkTime, status"
                " FROM Transactions ORDER BY rowid"
            ).fetchall()
    except sqlite3.Error as exc:
        raise DevWebFormatError(f"{path}: not a readable SQLite database: {exc}") from None

    start_ms: list[int] = []
    elapsed_ms: list[int] = []
    transaction: list[str] = []
    success: list[bool] = []
    for rowid, stamp, name, duration, think_time, status in rows:
        where = f"{path}: Transactions row {rowid}"
        try:
            local = datetime.fromisoformat(stamp)
        except (TypeError, ValueError):
            raise DevWebFormatError(f"{where}: timestamp {stamp!r} is not ISO 8601") from None
        if local.tzinfo is not None:
            raise DevWebFormatError(f"{where}: timestamp {stamp!r} has a UTC offset")
        if not isinstance(duration, int) or duration < 0:
            raise DevWebFormatError(f"{where}: duration {duration!r} is not milliseconds")
        if think_time != 0:
            raise DevWebFormatError(f"{where}: thinkTime {think_time!r} ms, only 0 is supported")
        flag = _STATUSES.get(status)
        if flag is None:
            raise DevWebFormatError(f"{where}: status {status!r} is neither Passed nor Failed")
        end = (local.replace(tzinfo=zone) - _EPOCH) // _MS
        start_ms.append(end - duration)
        elapsed_ms.append(duration)
        transaction.append(name)
        success.append(flag)

    started_at = datetime.fromtimestamp(min(start_ms) / 1000, tz=UTC) if start_ms else None
    return Run(
        metadata=RunMetadata(
            tool=Tool.LOADRUNNER_DEVWEB,
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
            response_code=[None] * len(start_ms),
        ),
    )
