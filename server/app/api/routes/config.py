"""配置与模型选项 API，供前端切换模型使用。"""
from fastapi import APIRouter

from app.config import SERVER_BOOT_ID, settings
from app.services.llm import (
    max_llm_upstream_http_timeout_seconds,
    recommended_llm_client_timeout_ms,
)

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config")
async def get_config():
    """返回当前模型配置及可选模型列表（id + label）。"""
    return {
        "serverBootId": SERVER_BOOT_ID,
        "openRouterModel": settings.OPENROUTER_MODEL,
        "openRouterModels": [{"id": mid, "label": label} for mid, label in settings.openrouter_model_list],
        "ollamaModel": settings.OLLAMA_MODEL,
        "ollamaModels": [{"id": mid, "label": label} for mid, label in settings.ollama_model_list],
        "llmUpstreamMaxTimeoutSeconds": max_llm_upstream_http_timeout_seconds(),
        "llmClientTimeoutRecommendedMs": recommended_llm_client_timeout_ms(),
        "sessionMemoryEnabled": settings.SESSION_MEMORY_DB_ENABLED,
        "sessionMemoryTtlDays": settings.SESSION_MEMORY_TTL_DAYS,
    }
