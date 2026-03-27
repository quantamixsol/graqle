"""test_cli conftest — mark all CLI tests as serial.

CLI tests use os.chdir(), subprocess.Popen(), and heavy tmp_path I/O.
These are unsafe for parallel execution under pytest-xdist.
Run with: pytest tests/test_cli/ (serial, no -n flag needed)
"""
import pytest

# All tests in this directory are marked serial — do not parallelise.
# They use os.chdir() which mutates global process state, and spawn
# subprocesses that can conflict under xdist workers.
pytestmark = pytest.mark.serial
