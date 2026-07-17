"""DataContext models and AgentState.data_context round-trip."""
from __future__ import annotations

from app.models.agent_models import AgentState
from app.models.table_models import ColumnProfile, DataContext, TableProfile


def test_column_profile_defaults() -> None:
    col = ColumnProfile(
        name="price",
        inferred_type="numeric",
        count=10,
        null_count=0,
        null_ratio=0.0,
        distinct_count=5,
    )
    assert col.top_values == []
    assert col.min_val is None
    assert col.mean is None
    assert col.off_type_count == 0


def test_table_profile_sampled_defaults_false() -> None:
    table = TableProfile(table_name="T", total_row_count=0, col_count=0)
    assert table.profile_sampled is False


def test_table_profile_reserved_fields_default_none() -> None:
    table = TableProfile(
        table_name="Sheet1",
        total_row_count=100,
        col_count=3,
        columns=[
            ColumnProfile(
                name="a",
                inferred_type="string",
                count=100,
                null_count=0,
                null_ratio=0.0,
                distinct_count=50,
            )
        ],
    )
    assert table.topic is None
    assert table.description is None
    assert table.granularity is None


def test_data_context_instantiation() -> None:
    ctx = DataContext(
        tables=[
            TableProfile(
                table_name="T",
                total_row_count=1,
                col_count=1,
                columns=[],
            )
        ]
    )
    assert len(ctx.tables) == 1


def test_agent_state_data_context_defaults_none() -> None:
    state = AgentState(tables=[], messages=[])
    assert state.data_context is None


def test_agent_state_data_context_roundtrip() -> None:
    state = AgentState(
        tables=[],
        messages=[],
        data_context=DataContext(
            tables=[
                TableProfile(
                    table_name="Sheet1",
                    total_row_count=2,
                    col_count=1,
                    columns=[
                        ColumnProfile(
                            name="status",
                            inferred_type="string",
                            count=2,
                            null_count=0,
                            null_ratio=0.0,
                            distinct_count=2,
                            off_type_count=1,
                            top_values=[("active", 1), ("done", 1)],
                        )
                    ],
                )
            ]
        ),
    )
    dumped = state.model_dump()
    restored = AgentState.model_validate(dumped)
    assert restored.data_context is not None
    col = restored.data_context.tables[0].columns[0]
    assert col.top_values == [("active", 1), ("done", 1)]
    assert col.off_type_count == 1
