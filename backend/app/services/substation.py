"""升压站业务规则：状态流转、字段校验与筛选口径都收在这里。

口径约定（看板、列表、详情、统计共用同一份）：
- 台账状态以 status 为准，台账列「升压站状态」始终镜像 status；
- abnormal（异常量）一律由 status == 负荷越限 即时派生，不残留历史标记；
- pending 表示是否待处理：待检修/负荷越限为待处理，运行正常/已停运为否。

并发约定：登记与动作都在模块锁内执行；同一站区编号重复登记只会保留一条。
"""
from __future__ import annotations

import re
from typing import Any

from app.store import store

MODULE = "substation"
CODE_FIELD = "站区编号"
REQUIRED_FIELDS = ["站区编号", "主变容量", "电压等级"]
STATUS_ORDER = ["待检修", "运行正常", "负荷越限", "已停运"]
ABNORMAL_STATUS = "负荷越限"
TERMINAL_STATUS = "已停运"

# 动作 -> (目标状态, 是否待处理)。检修与越限的结论一次落库，不拆两个标记。
ACTION_RULES: dict[str, tuple[str, bool]] = {
    "确认检修": ("运行正常", False),
    "登记负荷越限": ("负荷越限", True),
    "停运升压站": ("已停运", False),
}

store.register_abnormal_statuses(MODULE, {ABNORMAL_STATUS})


def _sync(entry: dict[str, Any]) -> dict[str, Any]:
    """把状态结论同步到行内所有口径字段，保证刷新后看板/列表/详情仍然一致。"""
    status = str(entry.get("status") or STATUS_ORDER[0])
    entry["status"] = status
    entry["升压站状态"] = status
    entry["abnormal"] = status == ABNORMAL_STATUS
    return entry


def _parse_rate(value: Any) -> float | None:
    """把「负荷率」解析成百分数数值；85% 与 0.85 都按 85 处理，无法解析时忽略。"""
    if value is None:
        return None
    text = str(value).strip().rstrip("%")
    if not text or not re.fullmatch(r"\d+(\.\d+)?", text):
        return None
    rate = float(text)
    return rate * 100 if 0 < rate <= 1 else rate


class SubstationService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get(CODE_FIELD, ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        # 统计与列表同一份数据、同一口径，不再各算各的
        summary = self._summarize(rows)
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = [_sync(dict(row)) for row in rows[start:start + size]]
        return page_rows, total, summary

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        with store.lock(MODULE):
            return _sync(entry)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        code = str(values.get(CODE_FIELD) or "").strip()
        missing = [
            field
            for field in REQUIRED_FIELDS
            if not str(values.get(field) or "").strip()
        ]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"

        with store.lock(MODULE):
            # 锁内按台账编号查重：并发提交同一站区编号只保留最早一条
            if store.find_by_field(MODULE, CODE_FIELD, code) is not None:
                return None, f"站区编号 {code} 已登记，不能重复建档"
            rows = store.rows(MODULE)
            entry: dict[str, Any] = {
                "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1
            }
            for field in ["站区编号", "主变容量", "电压等级", "所属场站", "上次检修日",
                          "值班班组", "负荷率"]:
                raw = values.get(field)
                if raw is not None and str(raw).strip():
                    entry[field] = str(raw).strip()
            entry["status"] = STATUS_ORDER[0]
            entry["pending"] = True
            rows.append(entry)
            return _sync(entry), ""

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str, bool]:
        """返回 (记录, 消息, 是否发生状态变化)。重复动作幂等，不重复累加计数。"""
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于升压站可执行范围", False

        with store.lock(MODULE):
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"升压站 {entry_id} 不存在或已归档", False

            current = str(entry.get("status") or "")
            if current == TERMINAL_STATUS and action != "停运升压站":
                return None, f"升压站已停运，不能再执行「{action}」；如需恢复请重新登记", False

            target, pending = ACTION_RULES[action]
            if current == target:
                # 幂等：结论早已生效，不重复计数、不报错
                return _sync(entry), f"升压站当前已是「{target}」，无需重复{action}", False

            entry["status"] = target
            entry["pending"] = pending
            _sync(entry)
            return entry, f"升压站已{action}", True

    def _summarize(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """主变容量口径：已登记主变容量的站区才纳入在运/越限统计。"""
        rated = [row for row in rows if str(row.get("主变容量") or "").strip()]
        overloaded = [row for row in rated if row.get("status") == ABNORMAL_STATUS]
        rates = [rate for rate in (_parse_rate(row.get("负荷率")) for row in rated)
                 if rate is not None]
        avg_rate = round(sum(rates) / len(rates), 1) if rates else 0
        return {
            "inService": sum(1 for row in rated if row.get("status") != TERMINAL_STATUS),
            "overloaded": len(overloaded),
            "avgLoadRate": avg_rate,
        }
