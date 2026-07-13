"""Table data upload API."""
from __future__ import annotations

import json
from typing import Any, Dict, List

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.services.data_store import get_data_store

router = APIRouter(prefix="/api/data", tags=["data"])


class DataUploadRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    schema_: List[Dict[str, Any]] = Field(alias="schema")
    rows: List[Dict[str, Any]]


class DataUploadResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    table_id: str = Field(serialization_alias="tableId")
    row_count: int = Field(serialization_alias="rowCount")


def _request_byte_size(req: DataUploadRequest, request: Request) -> int:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            return int(content_length)
        except ValueError:
            pass
    wire = req.model_dump(by_alias=True)
    return len(json.dumps(wire, ensure_ascii=False).encode("utf-8"))


@router.post("/upload", response_model=DataUploadResponse)
def upload_table(
    req: DataUploadRequest,
    request: Request,
    x_client_request_id: str | None = Header(default=None),
) -> DataUploadResponse:
    if len(req.rows) > settings.MAX_UPLOAD_ROWS:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Upload exceeds MAX_UPLOAD_ROWS ({settings.MAX_UPLOAD_ROWS}); "
                f"got {len(req.rows)} rows"
            ),
        )

    byte_size = _request_byte_size(req, request)
    if byte_size > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Upload exceeds MAX_UPLOAD_BYTES ({settings.MAX_UPLOAD_BYTES}); "
                f"got {byte_size} bytes"
            ),
        )

    store = get_data_store()
    table_id = store.create_table(
        name=req.name,
        schema=req.schema_,
        rows=req.rows,
        client_request_id=x_client_request_id,
    )
    return DataUploadResponse(table_id=table_id, row_count=len(req.rows))
