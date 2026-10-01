"""升压站业务规则：状态流转、字段校验与筛选口径都收在这里。

口径约定（看板、列表、详情都按这一份算）：

- ``status`` 与台账列 ``升压站状态`` 在一次事务里同时改写，不允许一个变一个不变；
- ``abnormal`` 不由动作名决定，而由结果状态决定：落在 ``ABNORMAL_STATUSES``
  里的状态才算异常，这样看板"异常量"恒等于"负荷越限站区数量"；
- ``站区编号`` 是台账主键：同一编号只留一条，重复/并发提交直接说明原因；
- 所有变更走 ``store.transact``，落盘成功才算生效，刷新后数字不回退。
"""
from __future__ import annotations

from typing import Any

from app.store import PersistError, store

MODULE = "substation"
REQUIRED_FIELDS = ["站区编号", "主变容量", "电压等级"]
LEDGER_FIELDS = ["站区编号", "主变容量", "电压等级", "所属场站", "上次检修日", "值班班组", "负荷率", "升压站状态"]
STATUS_ORDER = ["待检修", "运行正常", "负荷越限", "已停运"]
ACTION_RULES = {"确认检修": "运行正常", "登记负荷越限": "负荷越限", "停运升压站": "已停运"}
ABNORMAL_STATUSES = {"负荷越限"}
STATUS_FIELD = "升压站状态"
UNIQUE_FIELD = "站区编号"


def _normalize_code(value: Any) -> str:
    """站区编号沿用台账字段本身，只做首尾空白归一，不改写内容。"""
    return str(value or "").strip()


class SubstationService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get(UNIQUE_FIELD, ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """登记升压站：缺字段、编号重复、落盘失败都要给出可读原因。"""
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        code = _normalize_code(values.get(UNIQUE_FIELD))

        def _apply(rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
            for row in rows:
                if _normalize_code(row.get(UNIQUE_FIELD)) == code:
                    return None, f"站区编号 {code} 已存在（记录 #{row.get('id')}），未重复登记"
            entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            for field in LEDGER_FIELDS:
                if field in values:
                    entry[field] = values[field]
            entry[UNIQUE_FIELD] = code
            entry["status"] = STATUS_ORDER[0]
            entry[STATUS_FIELD] = STATUS_ORDER[0]
            entry["pending"] = True
            entry["abnormal"] = STATUS_ORDER[0] in ABNORMAL_STATUSES
            rows.append(entry)
            return entry, ""

        try:
            return store.transact(MODULE, _apply)
        except PersistError as exc:
            return None, f"登记未生效：{exc}"

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        """状态流转：status、台账状态列、异常标在同一事务里一次改完。

        重复执行同一动作是幂等的：状态不变、计数不增，只在消息里说明。
        """
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于升压站可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"

        def _apply(rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
            entry = next((row for row in rows if int(row.get("id", 0)) == entry_id), None)
            if entry is None:
                return None, f"升压站 {entry_id} 不存在或已归档"
            changed = entry.get("status") != target
            entry["status"] = target
            entry[STATUS_FIELD] = target
            entry["pending"] = target != STATUS_ORDER[-1]
            entry["abnormal"] = target in ABNORMAL_STATUSES
            if changed:
                return entry, f"升压站已{action}，状态与台账已同步为「{target}」"
            return entry, f"升压站已处于「{target}」，本次{action}未重复计数"

        try:
            return store.transact(MODULE, _apply)
        except PersistError as exc:
            return None, f"{action}未生效：{exc}"

    def summary(self) -> dict[str, Any]:
        """页头统计卡：与列表、详情、看板读同一批行，口径不另起炉灶。"""
        rows = list(store.rows(MODULE))
        in_service = sum(1 for row in rows if row.get("status") != STATUS_ORDER[-1])
        over_limit = sum(1 for row in rows if row.get("status") in ABNORMAL_STATUSES)
        rates: list[float] = []
        for row in rows:
            raw = str(row.get("负荷率") or "").strip().rstrip("%")
            try:
                rates.append(float(raw))
            except ValueError:
                continue
        average = f"{round(sum(rates) / len(rates), 1)}%" if rates else "—"
        return {
            "module": MODULE,
            "stats": [
                {"label": "在运升压站", "value": in_service},
                {"label": "负荷越限站数", "value": over_limit},
                {"label": "平均负荷率", "value": average},
            ],
        }
