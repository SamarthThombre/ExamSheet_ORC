import sys
import pytest
from pathlib import Path
import starlette.testclient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.jobs import job_store
from app.auth import init_auth_db

# Ensure TestClient provides valid default API key unless explicitly overridden (e.g. headers={})
_orig_init = starlette.testclient.TestClient.__init__

def _patched_init(self, app, *args, **kwargs):
    if "headers" not in kwargs or kwargs["headers"] is None:
        kwargs["headers"] = {"X-API-Key": "ep_admin_master_secret_key_deploy2"}
    _orig_init(self, app, *args, **kwargs)

starlette.testclient.TestClient.__init__ = _patched_init


@pytest.fixture(autouse=True)
def reset_server_state():
    """Ensures each test starts with a fresh DB and clean non-shutdown state."""
    init_auth_db()
    job_store.reset_shutdown()
    yield
    job_store.reset_shutdown()
