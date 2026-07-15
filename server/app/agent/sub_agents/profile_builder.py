"""纯 Python 表统计（context-analyzer Stage 3），无 I/O、无 LLM。

统计口径（R3 规则，2026-07-15 定稿）：

- null：``None`` 或 strip 后为空串。
- 判型：非空值 ≥90% 同型判该型；全 null 为 empty；否则 mixed。
- boolean：``str(v).strip().lower() in {"true", "false"}``（含 Python bool）；
  ``"1"``/``"0"`` 判 numeric 而非 boolean（电子表格惯例）。
- numeric：``int``/``float``（不含 bool），或 strip 后可被 ``float()`` 解析的字符串；
  ``"1,200"``、``"N/A"`` 非 numeric（千分位等宽松解析留给未来扩展，不做猜测）。
- date：只认 ISO（``date.fromisoformat`` / ``datetime.fromisoformat``），解析入口
  收敛在 ``_parse_date``，未来扩展格式只改这一处。
- 列来源：以 schema 为准（``key`` 或 ``name``），rows 中多余 key 忽略。
- count/null_count/distinct/top_values 按全部非空值算；mean/std/min/max 只在
  同型子集上算；``off_type_count`` = 判型后异型残值数（mixed/empty 为 0）。
  off-type 按 ``_classify`` 结果计，不是按 parse 失败计。
- std：总体标准差（ddof=0）。
- date min/max：解析后再序列化为 ISO 字符串。
- 行数 > ``PROFILE_SAMPLE_THRESHOLD_ROWS`` 时 distinct/top_values 只看前 N 行并置
  ``TableProfile.profile_sampled=True``；count/null_count/类型统计仍精确。
"""
from __future__ import annotations

import math
from collections import Counter
from datetime import date, datetime
from typing import Any

from app.models.table_models import ColumnProfile, InferredColType, TableProfile

PROFILE_SAMPLE_THRESHOLD_ROWS = 50_000
TOP_VALUES_N = 5

_BOOL_LITERALS = {"true", "false"}


def _is_null(v: Any) -> bool:
    if v is None:
        return True
    return isinstance(v, str) and not v.strip()


def _parse_numeric(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def _parse_date(v: Any) -> date | datetime | None:
    """ISO-only 日期解析；未来扩展格式只改本函数。"""
    if not isinstance(v, str):
        return None
    s = v.strip()
    try:
        return date.fromisoformat(s)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _classify(v: Any) -> InferredColType:
    if isinstance(v, bool) or (
        isinstance(v, str) and v.strip().lower() in _BOOL_LITERALS
    ):
        return "boolean"
    if _parse_numeric(v) is not None:
        return "numeric"
    if _parse_date(v) is not None:
        return "date"
    return "string"


def _schema_column_names(schema: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for c in schema:
        if not isinstance(c, dict):
            continue
        key = c.get("key") or c.get("name")
        if key:
            names.append(str(key))
    return names


def _build_column_profile(
    name: str,
    values: list[Any],
    sample_values: list[Any],
    total_rows: int,
) -> ColumnProfile:
    """``values``：全量非空值；``sample_values``：distinct/top_values 使用的（可能采样的）非空值。"""
    null_count = total_rows - len(values)
    null_ratio = (null_count / total_rows) if total_rows else 0.0

    if not values:
        return ColumnProfile(
            name=name,
            inferred_type="empty",
            count=0,
            null_count=null_count,
            null_ratio=null_ratio,
            distinct_count=0,
        )

    type_counts = Counter(_classify(v) for v in values)
    best_type, best_count = type_counts.most_common(1)[0]
    if best_count / len(values) >= 0.9:
        inferred: InferredColType = best_type
        off_type_count = len(values) - best_count
    else:
        inferred = "mixed"
        off_type_count = 0

    freq = Counter(str(v) for v in sample_values)
    distinct_count = len(freq)

    min_val: str | None = None
    max_val: str | None = None
    mean: float | None = None
    std: float | None = None
    top_values: list[tuple[str, int]] = []

    if inferred == "numeric":
        nums = [n for n in (_parse_numeric(v) for v in values) if n is not None]
        if nums:
            mean = sum(nums) / len(nums)
            std = math.sqrt(sum((x - mean) ** 2 for x in nums) / len(nums))
            lo, hi = min(nums), max(nums)
            min_val = str(int(lo)) if lo.is_integer() else str(lo)
            max_val = str(int(hi)) if hi.is_integer() else str(hi)
    elif inferred == "date":
        dates = [d for d in (_parse_date(v) for v in values) if d is not None]
        if dates:
            # date 与 datetime 混排时统一升格为 datetime 再比较
            def _as_dt(d: date | datetime) -> datetime:
                if isinstance(d, datetime):
                    return d
                return datetime(d.year, d.month, d.day)

            min_val = min(dates, key=_as_dt).isoformat()
            max_val = max(dates, key=_as_dt).isoformat()
    elif inferred == "string":
        strs = [str(v) for v in values if _classify(v) == "string"]
        if strs:
            min_val = min(strs)
            max_val = max(strs)

    if inferred != "numeric":
        # 频次降序、值升序，保证确定性
        top_values = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_VALUES_N]

    return ColumnProfile(
        name=name,
        inferred_type=inferred,
        count=len(values),
        null_count=null_count,
        null_ratio=null_ratio,
        distinct_count=distinct_count,
        off_type_count=off_type_count,
        min_val=min_val,
        max_val=max_val,
        mean=mean,
        std=std,
        top_values=top_values,
    )


def build_table_profile(
    table_name: str,
    schema: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> TableProfile:
    """从全量 rows 计算 ``TableProfile``（口径见模块 docstring）。"""
    col_names = _schema_column_names(schema)
    total_rows = len(rows)
    sampled = total_rows > PROFILE_SAMPLE_THRESHOLD_ROWS
    sample_rows = rows[:PROFILE_SAMPLE_THRESHOLD_ROWS] if sampled else rows

    columns: list[ColumnProfile] = []
    for name in col_names:
        values = [r.get(name) for r in rows if not _is_null(r.get(name))]
        if sampled:
            sample_values = [
                r.get(name) for r in sample_rows if not _is_null(r.get(name))
            ]
        else:
            sample_values = values
        columns.append(_build_column_profile(name, values, sample_values, total_rows))

    return TableProfile(
        table_name=table_name,
        total_row_count=total_rows,
        col_count=len(col_names),
        columns=columns,
        profile_sampled=sampled,
    )
