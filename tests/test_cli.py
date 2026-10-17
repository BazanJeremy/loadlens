import json
import subprocess
import sys

import pytest

from loadlens.cli import EXIT_INPUT_ERROR, main


def run_cli(capsys, *argv):
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_kpi_prints_metadata_and_kpis_as_json(capsys, jmeter_fixture):
    path = jmeter_fixture("2026-10-17-nominal-short-head10.jtl")
    code, out, _ = run_cli(
        capsys,
        "kpi",
        str(path),
        "--tool-version",
        "5.6.3",
        "--profile",
        "hold_s=120",
        "--profile",
        "ramp_s=10",
        "--cpu-count",
        "4",
    )
    assert code == 0
    report = json.loads(out)
    assert report["metadata"]["tool"] == "jmeter"
    assert report["metadata"]["tool_version"] == "5.6.3"
    assert report["metadata"]["profile"] == {"hold_s": "120", "ramp_s": "10"}
    assert report["metadata"]["machine"] == {"os": None, "cpu_model": None, "cpu_count": 4}
    assert report["kpis"]["overall"]["count"] == 10
    assert report["kpis"]["overall"]["p95_ms"] == 33.0
    assert report["warmup_s"] == 0.0


def test_machine_is_unknown_when_not_supplied(capsys, jmeter_fixture):
    code, out, _ = run_cli(capsys, "kpi", str(jmeter_fixture("2026-10-17-empty.jtl")))
    assert code == 0
    assert json.loads(out)["metadata"]["machine"] is None


def test_warmup_leaves_out_early_samples(capsys, jmeter_fixture):
    # First sample starts at ...111088; with 0.5 s of warm-up the cut-off is ...111588, which
    # drops the samples started at ...111088, ...111565 and ...111571 (7 of 10 remain).
    path = jmeter_fixture("2026-10-17-nominal-short-head10.jtl")
    code, out, _ = run_cli(capsys, "kpi", str(path), "--warmup-s", "0.5")
    assert code == 0
    report = json.loads(out)
    assert report["kpis"]["overall"]["count"] == 7
    assert report["warmup_s"] == 0.5


def test_missing_file_is_an_input_error(capsys, tmp_path):
    code, out, err = run_cli(capsys, "kpi", str(tmp_path / "absent.jtl"))
    assert (code, out) == (EXIT_INPUT_ERROR, "")
    assert err.startswith("loadlens: ")


def test_malformed_file_is_an_input_error(capsys, tmp_path):
    path = tmp_path / "bad.jtl"
    path.write_text("not,a,jtl\n", encoding="utf-8")
    code, _, err = run_cli(capsys, "kpi", str(path))
    assert code == EXIT_INPUT_ERROR
    assert "missing columns" in err


@pytest.mark.parametrize(
    "extra",
    [["--profile", "no-equals-sign"], ["--cpu-count", "zero"], ["--unknown-flag"]],
    ids=["profile", "cpu-count-type", "unknown-flag"],
)
def test_invalid_arguments_exit_with_the_input_error_code_not_2(capsys, jmeter_fixture, extra):
    path = jmeter_fixture("2026-10-17-empty.jtl")
    with pytest.raises(SystemExit) as exit_info:
        main(["kpi", str(path), *extra])
    assert exit_info.value.code == EXIT_INPUT_ERROR


@pytest.mark.parametrize(
    "extra",
    [["--cpu-count", "0"], ["--warmup-s", "-1"], ["--apdex-t-ms", "0"]],
    ids=["cpu-count-zero", "negative-warmup", "zero-apdex"],
)
def test_out_of_range_values_are_input_errors(capsys, jmeter_fixture, extra):
    path = jmeter_fixture("2026-10-17-nominal-short-head10.jtl")
    code, out, _ = run_cli(capsys, "kpi", str(path), *extra)
    assert (code, out) == (EXIT_INPUT_ERROR, "")


def test_module_entry_point(jmeter_fixture):
    path = jmeter_fixture("2026-10-17-empty.jtl")
    result = subprocess.run(
        [sys.executable, "-m", "loadlens", "kpi", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["kpis"]["overall"]["count"] == 0
