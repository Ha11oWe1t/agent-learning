from pathlib import Path
from uuid import uuid4


def pytest_configure(config):
    # Keep temporary databases inside the writable workspace on Windows.
    root = Path(__file__).resolve().parents[1] / 'data' / 'tests'
    root.mkdir(parents=True, exist_ok=True)
    config.option.basetemp = str(root / uuid4().hex)
