import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def sample_profile() -> dict:
    """Un profil client réel issu du dataset (format identique au
    script de charge : toutes les valeurs en string)."""
    with open(ROOT / "data" / "churn.csv") as f:
        row = next(iter(csv.DictReader(f)))
    row.pop("Churn")
    row.pop("customerID")
    return row
