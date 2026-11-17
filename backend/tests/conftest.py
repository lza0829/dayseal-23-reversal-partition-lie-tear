from __future__ import annotations
import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """每个用例一个全新的临时库，通过环境变量隔离数据目录。"""
    monkeypatch.setenv("DAYSEAL_DATA_DIR", str(tmp_path))
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    from app.main import app  # noqa: WPS433 导入即建表+种子
    with TestClient(app) as c:
        yield c
