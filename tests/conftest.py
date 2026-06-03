import pytest
from pathlib import Path


@pytest.fixture
def tmp_db(tmp_path: Path):
    from diet.db import open_db
    return open_db(tmp_path / "test.db")
