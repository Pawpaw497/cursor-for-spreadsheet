from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

InferredColType = Literal["numeric", "boolean", "date", "string", "mixed", "empty"]


class ColumnProfile(BaseModel):
    name: str
    inferred_type: InferredColType
    count: int
    null_count: int
    null_ratio: float
    distinct_count: int
    min_val: Optional[str] = None
    max_val: Optional[str] = None
    mean: Optional[float] = None
    std: Optional[float] = None
    top_values: list[tuple[str, int]] = Field(default_factory=list)


class TableProfile(BaseModel):
    table_name: str
    total_row_count: int
    col_count: int
    columns: list[ColumnProfile] = Field(default_factory=list)
    topic: Optional[str] = None
    description: Optional[str] = None
    granularity: Optional[str] = None


class DataContext(BaseModel):
    tables: list[TableProfile] = Field(default_factory=list)
