"""profile_builder：类型推断与统计口径（R3 规则，2026-07-15 定稿）。"""
from __future__ import annotations

import pytest

from app.agent.sub_agents.profile_builder import (
    PROFILE_SAMPLE_THRESHOLD_ROWS,
    build_table_profile,
)

SCHEMA_ABC = [{"key": "a"}, {"key": "b"}, {"key": "c"}]


def _col(profile, name):
    return next(c for c in profile.columns if c.name == name)


def test_empty_table_all_columns_empty_type() -> None:
    p = build_table_profile("T", SCHEMA_ABC, [])
    assert p.total_row_count == 0
    assert p.col_count == 3
    assert [c.inferred_type for c in p.columns] == ["empty", "empty", "empty"]
    assert all(c.count == 0 and c.off_type_count == 0 for c in p.columns)


def test_all_null_column_is_empty() -> None:
    rows = [{"a": None}, {"a": ""}, {"a": "  "}]
    p = build_table_profile("T", [{"key": "a"}], rows)
    col = _col(p, "a")
    assert col.inferred_type == "empty"
    assert col.count == 0
    assert col.null_count == 3
    assert col.null_ratio == 1.0


def test_numeric_column_stats() -> None:
    rows = [{"a": 1}, {"a": 2}, {"a": 3}, {"a": 4}]
    p = build_table_profile("T", [{"key": "a"}], rows)
    col = _col(p, "a")
    assert col.inferred_type == "numeric"
    assert col.count == 4
    assert col.mean == pytest.approx(2.5)
    # 总体标准差 ddof=0
    assert col.std == pytest.approx(1.118033988749895)
    assert col.min_val == "1"
    assert col.max_val == "4"
    assert col.top_values == []  # numeric 列无 top_values


def test_numeric_accepts_parseable_strings_only() -> None:
    # "1,200" 与 "N/A" 非 numeric；"5.5" 是
    rows = [{"a": "1"}, {"a": "2.5"}, {"a": "5.5"}]
    p = build_table_profile("T", [{"key": "a"}], rows)
    assert _col(p, "a").inferred_type == "numeric"

    rows2 = [{"a": "1,200"}, {"a": "N/A"}, {"a": "x"}]
    p2 = build_table_profile("T", [{"key": "a"}], rows2)
    assert _col(p2, "a").inferred_type == "string"


def test_ninety_percent_threshold_and_off_type_count() -> None:
    # 10 个非空值：9 numeric + 1 string → numeric，off_type_count=1
    rows = [{"a": i} for i in range(9)] + [{"a": "oops"}]
    p = build_table_profile("T", [{"key": "a"}], rows)
    col = _col(p, "a")
    assert col.inferred_type == "numeric"
    assert col.off_type_count == 1
    assert col.count == 10  # count 按全部非空值
    # mean 只在同型子集（0..8）上算
    assert col.mean == pytest.approx(4.0)

    # 8/10 同型 → mixed
    rows2 = [{"a": i} for i in range(8)] + [{"a": "x"}, {"a": "y"}]
    p2 = build_table_profile("T", [{"key": "a"}], rows2)
    col2 = _col(p2, "a")
    assert col2.inferred_type == "mixed"
    assert col2.off_type_count == 0  # mixed 无「同型子集」概念
    assert col2.mean is None
    assert col2.min_val is None


def test_boolean_inference_case_insensitive() -> None:
    rows = [{"a": True}, {"a": "false"}, {"a": "TRUE"}, {"a": " False "}]
    p = build_table_profile("T", [{"key": "a"}], rows)
    col = _col(p, "a")
    assert col.inferred_type == "boolean"
    assert col.mean is None
    assert col.min_val is None
    assert col.top_values  # boolean 仍有 top_values


def test_date_iso_only() -> None:
    rows = [{"a": "2026-01-05"}, {"a": "2025-12-31"}, {"a": "2026-07-15T08:00:00"}]
    p = build_table_profile("T", [{"key": "a"}], rows)
    col = _col(p, "a")
    assert col.inferred_type == "date"
    assert col.min_val == "2025-12-31"
    assert col.max_val is not None and col.max_val.startswith("2026-07-15")

    # 非 ISO 格式判 string
    rows2 = [{"a": "07/15/2026"}, {"a": "2026年7月15日"}]
    p2 = build_table_profile("T", [{"key": "a"}], rows2)
    assert _col(p2, "a").inferred_type == "string"


def test_string_column_top_values_and_lexicographic_range() -> None:
    rows = [{"a": "b"}, {"a": "b"}, {"a": "a"}, {"a": "c"}]
    p = build_table_profile("T", [{"key": "a"}], rows)
    col = _col(p, "a")
    assert col.inferred_type == "string"
    assert col.distinct_count == 3
    assert col.min_val == "a"
    assert col.max_val == "c"
    assert col.top_values[0] == ("b", 2)


def test_top_values_capped_at_five() -> None:
    rows = [{"a": f"v{i}"} for i in range(8)]
    p = build_table_profile("T", [{"key": "a"}], rows)
    assert len(_col(p, "a").top_values) == 5


def test_columns_come_from_schema_extra_row_keys_ignored() -> None:
    rows = [{"a": 1, "zz": "extra"}]
    p = build_table_profile("T", [{"key": "a"}], rows)
    assert [c.name for c in p.columns] == ["a"]


def test_schema_name_fallback_when_no_key() -> None:
    p = build_table_profile("T", [{"name": "col1"}], [{"col1": 1}])
    assert p.columns[0].name == "col1"
    assert p.columns[0].count == 1


def test_sampling_over_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.agent.sub_agents.profile_builder as pb

    monkeypatch.setattr(pb, "PROFILE_SAMPLE_THRESHOLD_ROWS", 10)
    # 20 行：前 10 行值全为 "x"，后 10 行为不同值
    rows = [{"a": "x"} for _ in range(10)] + [{"a": f"y{i}"} for i in range(10)]
    p = pb.build_table_profile("T", [{"key": "a"}], rows)
    col = _col(p, "a")
    assert p.profile_sampled is True
    assert p.total_row_count == 20
    assert col.count == 20  # count/null 仍精确
    assert col.distinct_count == 1  # distinct/top_values 只看前 10 行
    assert col.top_values == [("x", 10)]


def test_no_sampling_at_or_below_threshold() -> None:
    rows = [{"a": "x"}] * 3
    p = build_table_profile("T", [{"key": "a"}], rows)
    assert p.profile_sampled is False
    assert PROFILE_SAMPLE_THRESHOLD_ROWS == 50_000
