from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def jmeter_fixture():
    """Path of a committed JMeter result file (see fixtures/jmeter/PROVENANCE.md)."""

    def _path(name: str) -> Path:
        path = FIXTURES / "jmeter" / name
        assert path.is_file(), f"missing fixture {path}"
        return path

    return _path
