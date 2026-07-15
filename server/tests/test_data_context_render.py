"""build_data_context_text：DataContext → prompt 文本渲染。"""
from __future__ import annotations

from app.agent.context_assembler import DATA_PROFILE_PREFIX, build_data_context_text
from app.models.table_models import ColumnProfile, DataContext, TableProfile


def _numeric_col() -> ColumnProfile:
    return ColumnProfile(
        name="price",
        inferred_type="numeric",
        count=100,
        null_count=2,
        null_ratio=0.02,
        distinct_count=87,
        min_val="1",
        max_val="99.5",
        mean=12.34567,
        std=4.5,
    )


def _string_col(off_type: int = 0) -> ColumnProfile:
    return ColumnProfile(
        name="status",
        inferred_type="string",
        count=100,
        null_count=0,
        null_ratio=0.0,
        distinct_count=3,
        off_type_count=off_type,
        min_val="active",
        max_val="done",
        top_values=[("active", 60), ("done", 30), ("hold", 10)],
    )


def test_empty_data_context_renders_empty_string() -> None:
    assert build_data_context_text(None) == ""
    assert build_data_context_text(DataContext(tables=[])) == ""


def test_render_starts_with_prefix() -> None:
    dc = DataContext(
        tables=[
            TableProfile(
                table_name="Sheet1",
                total_row_count=100,
                col_count=1,
                columns=[_numeric_col()],
            )
        ]
    )
    text = build_data_context_text(dc)
    assert text.startswith(DATA_PROFILE_PREFIX)


def test_render_numeric_and_string_columns() -> None:
    dc = DataContext(
        tables=[
            TableProfile(
                table_name="Sheet1",
                total_row_count=100,
                col_count=2,
                columns=[_numeric_col(), _string_col()],
            )
        ]
    )
    text = build_data_context_text(dc)
    assert "Sheet1" in text
    assert "100 rows" in text
    # numeric：range + mean + std
    assert "price: numeric" in text
    assert "range 1–99.5" in text
    assert "mean 12.35" in text
    # string：top values，无 mean
    assert "status: string" in text
    assert 'active (60)' in text


def test_render_off_type_count_annotation() -> None:
    dc = DataContext(
        tables=[
            TableProfile(
                table_name="T",
                total_row_count=100,
                col_count=1,
                columns=[_string_col(off_type=3)],
            )
        ]
    )
    text = build_data_context_text(dc)
    assert "(3 off-type values)" in text


def test_render_sampled_annotation() -> None:
    dc = DataContext(
        tables=[
            TableProfile(
                table_name="Big",
                total_row_count=60_000,
                col_count=1,
                columns=[_string_col()],
                profile_sampled=True,
            )
        ]
    )
    text = build_data_context_text(dc)
    assert "(distinct/top values sampled)" in text


def test_render_multiple_tables() -> None:
    tp = TableProfile(table_name="A", total_row_count=1, col_count=0)
    tp2 = TableProfile(table_name="B", total_row_count=2, col_count=0)
    text = build_data_context_text(DataContext(tables=[tp, tp2]))
    assert '"A"' in text and '"B"' in text
