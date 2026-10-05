"""应用配置。

可通过环境变量覆盖：
- DATABASE_URL: 数据库连接串，默认 sqlite:///./data/recycle.db
- APP_NAME / APP_ENV
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'recycle.db'}")
APP_NAME = os.getenv("APP_NAME", "回收分拣来料污染判定系统")
APP_ENV = os.getenv("APP_ENV", "dev")

# 金额/比率保留小数位
MONEY_QUANT = "0.01"
RATE_QUANT = "0.0001"
