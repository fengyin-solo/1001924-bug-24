"""运行配置：端口、跨域、运行环境。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "store.json"


@dataclass(frozen=True)
class Settings:
    app_name: str = "风电场机组运维平台"
    env: str = "local"
    port: int = 8000
    allowed_origins: list[str] = field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
    )
    page_size_default: int = 20
    page_size_max: int = 200
    # 台账快照落盘位置：写库失败时接口必须报错，不能让数字静默回退。
    data_file: str = field(
        default_factory=lambda: os.environ.get("APP_DATA_FILE", str(_DEFAULT_DATA_FILE))
    )


settings = Settings()
