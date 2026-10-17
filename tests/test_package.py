import re

import loadlens


def test_version_is_read_from_installed_metadata():
    assert re.fullmatch(r"\d+\.\d+\.\d+", loadlens.__version__)
