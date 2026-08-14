import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def sample_profile() -> dict:
    """A real customer profile from the dataset (same format as the
    load script: all values as strings)."""
    with open(ROOT / "data" / "churn.csv") as f:
        row = next(iter(csv.DictReader(f)))
    row.pop("Churn")
    row.pop("customerID")
    return row
