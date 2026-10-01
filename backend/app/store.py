"""数据仓库：给每个业务模块准备一份可筛选、可流转的数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
在纯内存的基础上补了两条硬约束：

- 变更走 ``transact``：同一把锁里完成"读-改-写"，并立刻把快照原子写盘，
  刷新或重启后数字不会回退；
- 落盘失败会回滚内存并抛 ``PersistError``，由业务层把原因透传给操作人，
  不允许"页面上成功了、重启后没了"。
"""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any, Callable, TypeVar

from app.config import settings
from app.seed import SEED_ROWS

T = TypeVar("T")


class PersistError(Exception):
    """台账快照写盘失败：调用方应把原因说明给操作人，本次变更不算生效。"""


class Store:
    def __init__(self, data_file: str | None = None) -> None:
        self._lock = threading.RLock()
        self._path = Path(data_file) if data_file else None
        self._tables: dict[str, list[dict[str, Any]]] = self._load()

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        """先铺种子数据，再把上次落盘的快照叠上去；快照损坏时退回种子数据。"""
        tables = {name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()}
        if self._path is not None and self._path.exists():
            try:
                saved = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                saved = None
            if isinstance(saved, dict):
                for name, rows in saved.items():
                    if isinstance(rows, list):
                        tables[name] = [dict(row) for row in rows if isinstance(row, dict)]
        return tables

    def _persist(self) -> None:
        """原子写快照：先写临时文件再替换，避免半截文件把台账写坏。"""
        if self._path is None:
            return
        payload = json.dumps(self._tables, ensure_ascii=False, indent=2)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self._path)

    def transact(self, module: str, fn: Callable[[list[dict[str, Any]]], T]) -> T:
        """在锁内执行"读-改-写"并落盘；落盘失败回滚内存，保证口径不回退。"""
        with self._lock:
            rows = self._tables.setdefault(module, [])
            backup = copy.deepcopy(rows)
            result = fn(rows)
            try:
                self._persist()
            except OSError as exc:
                self._tables[module] = backup
                raise PersistError(f"台账快照写入失败：{exc}") from exc
            return result

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        with self._lock:
            return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        with self._lock:
            for row in self._tables.get(module, []):
                if int(row.get("id", 0)) == entry_id:
                    return row
        return None

    def overview(self) -> dict[str, object]:
        with self._lock:
            modules: list[dict[str, object]] = []
            for name in self.module_names():
                rows = list(self._tables.get(name, []))
                modules.append({
                    "name": name,
                    "created": len(rows),
                    "pending": sum(1 for row in rows if row.get("pending")),
                    "abnormal": sum(1 for row in rows if row.get("abnormal")),
                })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store(settings.data_file)
