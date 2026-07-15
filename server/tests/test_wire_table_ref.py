"""tableRef wire contract: TableInfo → TableContext mapping."""
from __future__ import annotations

from app.models.agent_models import TableContext
from app.models.plan import TableInfo


def test_table_info_parses_table_ref_without_sample_rows() -> None:
    info = TableInfo.model_validate(
        {
            "name": "Sheet1",
            "schema": [{"key": "a", "type": "string"}],
            "tableRef": "t1",
        }
    )
    assert info.tableRef == "t1"
    assert info.sampleRows == []


def test_table_info_sample_rows_optional_defaults_empty() -> None:
    info = TableInfo.model_validate(
        {"name": "T", "schema": [], "tableRef": "ref-1"}
    )
    assert info.sampleRows == []


def test_from_table_info_maps_table_ref_to_table_id() -> None:
    info = TableInfo.model_validate(
        {
            "name": "Sheet1",
            "schema": [{"key": "a", "type": "string"}],
            "tableRef": "t1",
        }
    )
    ctx = TableContext.from_table_info(info)
    assert ctx.table_id == "t1"
    assert ctx.name == "Sheet1"
    assert ctx.schema == info.schema_
    assert not hasattr(ctx, "sample_rows")
