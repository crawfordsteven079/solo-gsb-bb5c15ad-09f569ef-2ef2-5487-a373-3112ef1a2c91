import os
import tempfile

# 必须在导入 app 之前指定独立的临时数据库
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.seed import seed_rules  # noqa: E402


@pytest.fixture(scope="session")
def client():
    init_db()
    db = SessionLocal()
    try:
        seed_rules(db)
    finally:
        db.close()
    app = create_app()
    with TestClient(app) as c:
        yield c
