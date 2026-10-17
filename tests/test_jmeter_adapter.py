from collections import Counter
from datetime import UTC, datetime

import pytest

from loadlens.adapters.jmeter import JtlFormatError, read_jtl
from loadlens.schema import Machine, Tool

# Real header written by JMeter 5.6.3 with load/jmeter/loadlens.properties (2026-10-17 fixtures).
HEADER = (
    "timeStamp,elapsed,label,responseCode,responseMessage,threadName,success,failureMessage,"
    "bytes,sentBytes,grpThreads,allThreads,Latency,Connect"
)
ROW = "1792224111565,6,get_payment,200,OK,get_payment arrivals 2-1,true,,295,159,1,2,6,0"


def write(tmp_path, *lines):
    path = tmp_path / "run.jtl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# --- real JMeter output -------------------------------------------------------------------


def test_nominal_run_keeps_every_row_and_label(jmeter_fixture):
    run = read_jtl(jmeter_fixture("2026-10-17-nominal-short.jtl"))
    assert run.metadata.tool is Tool.JMETER
    assert run.metadata.source_file == "2026-10-17-nominal-short.jtl"
    assert len(run.samples) == 420
    assert Counter(run.samples.transaction) == {
        "get_payment": 210,
        "get_statement": 126,
        "create_payment": 84,
    }
    assert all(run.samples.success)
    assert set(run.samples.response_code) == {"200", "201"}


def test_started_at_is_the_earliest_sample_start_in_utc(jmeter_fixture):
    run = read_jtl(jmeter_fixture("2026-10-17-nominal-short-head10.jtl"))
    # First data row of the file: timeStamp 1792224111088.
    assert run.metadata.started_at == datetime(2026, 10, 17, 8, 1, 51, 88_000, tzinfo=UTC)


def test_transport_errors_keep_their_non_numeric_response_code(jmeter_fixture):
    run = read_jtl(jmeter_fixture("2026-10-17-all-errors.jtl"))
    assert len(run.samples) == 70
    assert not any(run.samples.success)
    assert set(run.samples.response_code) == {
        "Non HTTP response code: org.apache.http.conn.HttpHostConnectException"
    }


def test_single_transaction_run(jmeter_fixture):
    run = read_jtl(jmeter_fixture("2026-10-17-single-transaction.jtl"))
    assert set(run.samples.transaction) == {"get_payment"}
    assert len(run.samples) == 55


def test_empty_run_is_a_header_only_file(jmeter_fixture):
    # Observed 2026-10-17: with every arrival rate at 0, JMeter writes the header line only.
    run = read_jtl(jmeter_fixture("2026-10-17-empty.jtl"))
    assert len(run.samples) == 0
    assert run.metadata.started_at is None


def test_caller_supplied_metadata_is_kept(jmeter_fixture):
    machine = Machine(os="Linux", cpu_count=4)
    run = read_jtl(
        jmeter_fixture("2026-10-17-empty.jtl"),
        tool_version="5.6.3",
        profile={"hold_s": "20"},
        machine=machine,
    )
    assert run.metadata.tool_version == "5.6.3"
    assert run.metadata.profile == {"hold_s": "20"}
    assert run.metadata.machine == machine


def test_tool_version_is_unknown_unless_supplied(jmeter_fixture):
    assert read_jtl(jmeter_fixture("2026-10-17-empty.jtl")).metadata.tool_version is None


# --- malformed files (synthetic, built from the real header) --------------------------------


def test_quoted_label_containing_a_comma(tmp_path):
    row = ROW.replace("get_payment,200", '"get, payment",200', 1)
    run = read_jtl(write(tmp_path, HEADER, row))
    assert run.samples.transaction == ["get, payment"]


def test_completely_empty_file_is_rejected(tmp_path):
    path = tmp_path / "run.jtl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(JtlFormatError, match="empty file"):
        read_jtl(path)


def test_file_without_header_is_rejected(tmp_path):
    with pytest.raises(JtlFormatError, match=r"line 1: missing columns .*print_field_names"):
        read_jtl(write(tmp_path, ROW))


def test_missing_required_column_is_named(tmp_path):
    header = HEADER.replace("success", "succeeded")
    with pytest.raises(JtlFormatError, match=r"missing columns \['success'\]"):
        read_jtl(write(tmp_path, header, ROW))


def test_formatted_timestamp_is_rejected(tmp_path):
    row = ROW.replace("1792224111565", "2026/10/17 08:01:51.565")
    with pytest.raises(JtlFormatError, match=r"line 2: timeStamp .*timestamp_format=ms"):
        read_jtl(write(tmp_path, HEADER, row))


def test_unknown_success_value_is_rejected(tmp_path):
    row = ROW.replace(",true,", ",TRUE,")
    with pytest.raises(JtlFormatError, match="line 2: success 'TRUE'"):
        read_jtl(write(tmp_path, HEADER, row))


def test_row_with_wrong_field_count_is_rejected(tmp_path):
    with pytest.raises(JtlFormatError, match="line 3: 13 fields, header has 14"):
        read_jtl(write(tmp_path, HEADER, ROW, ROW.rsplit(",", 1)[0]))


def test_negative_elapsed_is_rejected(tmp_path):
    row = ROW.replace(",6,get_payment", ",-6,get_payment")
    with pytest.raises(JtlFormatError, match="line 2: negative elapsed -6"):
        read_jtl(write(tmp_path, HEADER, row))
