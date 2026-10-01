"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。

口径约定（看板、列表、详情共用同一份）：
- 异常量优先按各模块注册的 abnormal_statuses 对 status 即时派生，
  避免历史脏数据里的 abnormal 标记与状态脱节；
- 每个写动作都在模块锁内完成，并发提交同一张台账编号只会落一条。
"""
from __future__ import annotations

import threading
from typing import Any

from app.seed import SEED_ROWS


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        # 每个模块一把可重入锁：列表内的登记/动作串行化，杜绝同编号并发落两条
        self._locks: dict[str, threading.RLock] = {
            name: threading.RLock() for name in self._tables
        }
        # 模块自报的异常状态口径；未注册的模块回退到行内 abnormal 标记
        self._abnormal_statuses: dict[str, set[str]] = {}

    def lock(self, module: str) -> threading.RLock:
        """返回模块写锁；登记与状态流转都应在该锁内执行。"""
        if module not in self._locks:
            self._locks[module] = threading.RLock()
        return self._locks[module]

    def register_abnormal_statuses(self, module: str, statuses: set[str]) -> None:
        """登记模块的异常状态口径；看板异常量与业务统计都从这里派生。"""
        self._abnormal_statuses[module] = set(statuses)

    def is_abnormal(self, module: str, row: dict[str, Any]) -> bool:
        """按统一口径判断单行是否异常：有注册状态就看 status，否则回退 abnormal 标记。"""
        statuses = self._abnormal_statuses.get(module)
        if statuses is not None:
            return row.get("status") in statuses
        return bool(row.get("abnormal"))

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def find_by_field(self, module: str, field: str, value: str) -> dict[str, Any] | None:
        """按台账字段（如站区编号）查唯一记录，供并发登记去重使用。"""
        for row in self.rows(module):
            if str(row.get(field) or "").strip() == value:
                return row
        return None

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if self.is_abnormal(name, row)),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
