import os
import sys
import warnings

warnings.filterwarnings("ignore")

# guarantee the repo root is importable regardless of where pytest is invoked from
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

TEST_TARGET_ID = "CHEMBL1163125_BRD4"   # has a complete bucket incl. run_metadata.json


@pytest.fixture(scope="session")
def target():
    """Loads one real target bucket ONCE for the whole test session — each
       load takes ~10s (AutoGluon + Chemprop checkpoint), so re-loading per
       test would make the suite unreasonably slow."""
    from serving import model_adapter as MA
    return MA.load_target(TEST_TARGET_ID)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    import app as A
    return TestClient(A.app)
