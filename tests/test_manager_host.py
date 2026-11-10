"""The manager smoke suite owns its Qt application in a child process."""
from pathlib import Path
import pytest
from host_runtime import run_check


@pytest.mark.host
def test_manager_offline():
    run_check(Path(__file__).with_name('smoke_manager.py'))
