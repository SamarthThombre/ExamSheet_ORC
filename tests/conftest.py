import pytest
from pathlib import Path


def pytest_collection_modifyitems(config, items):
    legacy_marker = pytest.mark.legacy
    for item in items:
        # If the test is in the tests/ directory (legacy tests)
        p = Path(item.fspath)
        if "tests" in p.parts and "tests_v2" not in p.parts:
            item.add_marker(legacy_marker)
