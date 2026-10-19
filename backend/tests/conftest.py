import os
import tempfile

# Se configura ANTES de importar la app: SQLite temporal, IA simulada, evidencias de ejemplo.
_dir = tempfile.mkdtemp()
os.environ.update(
    DATABASE_URL=f"sqlite:///{_dir}/test.db", AUTO_CREATE_TABLES="true", AUTH_MODE="dev",
    LLM_PROVIDER="mock", EVIDENCIAS_MODE="stub", ANTHROPIC_API_KEY="",
)

import pytest
from fastapi.testclient import TestClient

from app.main import app

TUTOR = {"X-User-Id": "1", "X-User-Role": "TUTOR"}
OTRO_TUTOR = {"X-User-Id": "99", "X-User-Role": "TUTOR"}
ESTUDIANTE = {"X-User-Id": "2", "X-User-Role": "ESTUDIANTE"}
OTRO_ESTUDIANTE = {"X-User-Id": "3", "X-User-Role": "ESTUDIANTE"}


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c
