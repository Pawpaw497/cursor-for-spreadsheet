"""健康检查路由。"""
from fastapi import APIRouter

from app.config import SERVER_BOOT_ID

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {"ok": True, "serverBootId": SERVER_BOOT_ID}
