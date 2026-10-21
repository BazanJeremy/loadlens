import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from loadlens.adapters.loadrunner_devweb import DevWebFormatError, is_sqlite, read_devweb
from loadlens.cli import main
from loadlens.schema import Machine, Tool

SHIPPED = Path(__file__).resolve().parents[1] / "config" / "slo.yaml"

PROBE = "2026-10-17-devweb-probe.db"
NOMINAL = "2026-10-21-devweb-nominal.db"  # the three journeys, load/loadrunner/
CEST = timedelta(hours=2)  # startTime of the probe's replay_summary.json: ...T14:39:19+02:00
# Real table definition, read from the probe database (sqlite_master) on 2026-10-21.
TRANSACTIONS = (
    "CREATE TABLE Transactions (uid TEXT, timestamp TEXT, name TEXT, duration integer not null,"
    " thinkTime integer not null, status TEXT)"
)
ROW = ("1", "2026-10-17T14:39:20.619", "get_payment", 168, 0, "Passed")


def database(tmp_path, *rows, create=TRANSACTIONS):
    path = tmp_path / "devWebDB.db"
    with sqlite3.connect(path) as db:
        db.execute(create)
        if rows:
            db.executemany("INSERT INTO Transactions VALUES (?, ?, ?, ?, ?, ?)", rows)
    db.close()
    return path


# --- real DevWeb output ---------------------------------------------------------------------


def test_probe_keeps_every_transaction_and_status(loadrunner_fixture):
    run = read_devweb(loadrunner_fixture(PROBE), utc_offset=CEST)
    assert run.metadata.tool is Tool.LOADRUNNER_DEVWEB
    assert run.metadata.source_file == PROBE
    assert len(run.samples) == 120
    outcomes = Counter(zip(run.samples.transaction, run.samples.success, strict=True))
    assert outcomes == {("get_payment", True): 60, ("get_missing_payment", False): 60}
    assert set(run.samples.response_code) == {None}  # no status code per transaction


@pytest.mark.parametrize("name", [PROBE, NOMINAL])
def test_transactions_match_devweb_own_summary(loadrunner_fixture, name):
    # Conformity with the replay_summary.json DevWeb wrote for the same run: nothing is lost.
    run = read_devweb(loadrunner_fixture(name), utc_offset=CEST)
    summary = json.loads(
        loadrunner_fixture(name.replace(".db", ".replay_summary.json")).read_text("utf-8")
    )
    assert sorted(t["name"] for t in summary["transactions"]) == sorted(
        set(run.samples.transaction)
    )
    for expected in summary["transactions"]:
        rows = [
            (elapsed, ok)
            for name, elapsed, ok in zip(
                run.samples.transaction, run.samples.elapsed_ms, run.samples.success, strict=True
            )
            if name == expected["name"]
        ]
        assert sum(ok for _, ok in rows) == expected["pass"]
        assert sum(not ok for _, ok in rows) == expected["fail"]
        assert min(e for e, _ in rows) == expected["minDuration"]
        assert max(e for e, _ in rows) == expected["maxDuration"]


@pytest.mark.parametrize("name", [PROBE, NOMINAL])
def test_timestamp_marks_the_end_of_the_transaction(loadrunner_fixture, name):
    # Each script sends every request inside a transaction, so each request (table Hits, same
    # Vuser uid) must fall within the span of one of its Vuser's transactions. It does with spans
    # [timestamp - duration, timestamp]; with [timestamp, timestamp + duration] many do not.
    uri = f"{loadrunner_fixture(name).as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        rows = db.execute("SELECT uid, timestamp, duration FROM Transactions").fetchall()
        hits = db.execute("SELECT uid, timestamp FROM Hits").fetchall()

    def ms(stamp):
        return datetime.fromisoformat(stamp).timestamp() * 1000

    ends = defaultdict(list)
    for uid, stamp, duration in rows:
        ends[uid].append((ms(stamp), duration))

    def outside(as_end):
        spans = {
            uid: [(t - d, t) if as_end else (t, t + d) for t, d in values]
            for uid, values in ends.items()
        }
        return sum(not any(lo <= ms(stamp) <= hi for lo, hi in spans[uid]) for uid, stamp in hits)

    assert hits
    assert outside(as_end=True) == 0
    assert outside(as_end=False) > len(hits) // 4


def test_start_is_the_timestamp_minus_the_duration_in_utc(loadrunner_fixture):
    # Earliest start of the probe: row ('1', '2026-10-17T14:39:20.619', 'get_payment', 168),
    # ended 14:39:20.619 local = 12:39:20.619 UTC, started 168 ms earlier.
    run = read_devweb(loadrunner_fixture(PROBE), utc_offset=CEST)
    assert run.metadata.started_at == datetime(2026, 10, 17, 12, 39, 20, 451_000, tzinfo=UTC)
    assert run.samples.start_ms[0] == 1_792_240_760_451
    assert run.samples.elapsed_ms[0] == 168


def test_caller_supplied_metadata_is_kept(loadrunner_fixture):
    machine = Machine(os="Windows", cpu_count=12)
    run = read_devweb(
        loadrunner_fixture(PROBE),
        utc_offset=CEST,
        tool_version="26.3.0",
        profile={"vusers": "2"},
        machine=machine,
    )
    assert run.metadata.tool_version == "26.3.0"
    assert run.metadata.profile == {"vusers": "2"}
    assert run.metadata.machine == machine


def test_sqlite_is_told_apart_from_a_jtl(loadrunner_fixture, jmeter_fixture):
    assert is_sqlite(loadrunner_fixture(PROBE))
    assert not is_sqlite(jmeter_fixture("2026-10-17-empty.jtl"))


# --- edge cases and malformed files (synthetic, built from the real table definition) -------


def test_fraction_digits_may_be_dropped(tmp_path):
    # Observed in the probe: '...20.62' for 620 ms (and '...50.3' in another table).
    path = database(tmp_path, ("2", "2026-10-17T14:39:20.62", "get_payment", 122, 0, "Passed"))
    run = read_devweb(path, utc_offset=timedelta(0))
    assert run.samples.start_ms == [1_792_247_960_620 - 122]


def test_empty_table_is_a_run_without_samples(tmp_path):
    run = read_devweb(database(tmp_path), utc_offset=CEST)
    assert len(run.samples) == 0
    assert run.metadata.started_at is None


def test_database_without_transactions_table_is_rejected(tmp_path):
    path = database(tmp_path, create="CREATE TABLE Hits (uid TEXT, timestamp TEXT)")
    with pytest.raises(DevWebFormatError, match="table Transactions missing"):
        read_devweb(path, utc_offset=CEST)


@pytest.mark.parametrize(
    ("index", "value", "message"),
    [
        (4, 12, "row 1: thinkTime 12 ms, only 0 is supported"),
        (5, "Stopped", "row 1: status 'Stopped' is neither Passed nor Failed"),
        (1, "2026-10-17T14:39:20.619+02:00", "row 1: timestamp .* has a UTC offset"),
        (1, "17/10/2026 14:39:20", "row 1: timestamp .* is not ISO 8601"),
        (3, -1, "row 1: duration -1 is not milliseconds"),
    ],
)
def test_unobserved_values_are_rejected(tmp_path, index, value, message):
    row = list(ROW)
    row[index] = value
    with pytest.raises(DevWebFormatError, match=message):
        read_devweb(database(tmp_path, tuple(row)), utc_offset=CEST)


def test_missing_file_is_not_created(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_devweb(tmp_path / "devWebDB.db", utc_offset=CEST)
    assert not (tmp_path / "devWebDB.db").exists()


# --- verdict on DevWeb results (SLO-only) ---------------------------------------------------


def verdict_cli(*argv):
    """Exit code of `loadlens verdict` with the shipped thresholds, argparse errors included."""
    try:
        return main(["verdict", "--config", str(SHIPPED), *argv])
    except SystemExit as exit_:
        return exit_.code


def test_verdict_on_the_probe_fails_on_its_error_rate(capsys, loadrunner_fixture):
    # Half the probe's transactions request a payment that does not exist: 60 of 120 failed.
    path = str(loadrunner_fixture(PROBE))
    assert verdict_cli("--candidate", path, "--utc-offset", "+02:00") == 2
    out = capsys.readouterr().out
    assert "loadlens verdict: FAIL" in out
    assert "error rate 50.00% (60/120)" in out
    assert "no baseline: SLO-only verdict" in out


def test_verdict_on_the_nominal_run_passes_on_slos_alone(capsys, loadrunner_fixture):
    # The command of load/loadrunner/README.en.md: 10 s of ramp-up left out, 6 per second
    # declared per transaction. Every SLO is checked, throughput included; nothing else is.
    path = str(loadrunner_fixture(NOMINAL))
    targets = [
        f"--target-rps={name}=6" for name in ("create_payment", "get_payment", "get_statement")
    ]
    code = verdict_cli("--candidate", path, "--utc-offset", "+02:00", "--warmup-s", "10", *targets)
    out = capsys.readouterr().out
    assert code == 0
    assert out.splitlines()[0] == "loadlens verdict: PASS"
    assert "not checked" not in out.replace("regressions not checked", "")


def test_devweb_result_needs_its_utc_offset(capsys, loadrunner_fixture):
    assert verdict_cli("--candidate", str(loadrunner_fixture(PROBE))) == 4
    assert "--utc-offset" in capsys.readouterr().err


@pytest.mark.parametrize("arm", ["--candidate", "--baseline"])
def test_devweb_result_is_refused_with_a_baseline(capsys, loadrunner_fixture, jmeter_fixture, arm):
    probe, jtl = str(loadrunner_fixture(PROBE)), str(jmeter_fixture("2026-10-17-empty.jtl"))
    devweb, other = ("--baseline", "--candidate") if arm == "--baseline" else (arm, "--baseline")
    assert verdict_cli(devweb, probe, other, jtl, "--utc-offset", "+02:00") == 4
    assert "SLO-only verdict" in capsys.readouterr().err


def test_malformed_utc_offset_is_an_input_error(loadrunner_fixture):
    path = str(loadrunner_fixture(PROBE))
    assert verdict_cli("--candidate", path, "--utc-offset", "CEST") == 4
