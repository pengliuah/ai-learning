"""FastAPI 应用装配：中间件、lifespan、路由注册、静态托管。

对外接口按域拆在 ``app/api/`` 下的各 router 模块里（每个端点的 docstring
即 OpenAPI 描述，可在 /docs 查看），共享助手在 ``app/api/helpers.py``。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from . import long_memory, store
from .api import helpers as h
from .api import admin, annotations, auth, coach, ima, memories, plans
from .api import settings as settings_router
from .auth import get_current_user
from .config import BACKEND_DIR, settings
from .middleware import AccessLogMiddleware


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """拉起长期记忆的夜间整理循环（MEMORY_HOUSEKEEPING=false 关闭）。"""
    housekeeping_task = None
    if settings.memory_housekeeping:
        housekeeping_task = asyncio.create_task(long_memory.housekeeping_loop())
    yield
    if housekeeping_task is not None:
        housekeeping_task.cancel()
        try:
            await housekeeping_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="zhixue-backend", version="0.1.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(AccessLogMiddleware)

logger = logging.getLogger(__name__)

# --- 按域注册路由 ---
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(plans.router)
app.include_router(annotations.router)
app.include_router(coach.router)
app.include_router(settings_router.router)
app.include_router(memories.router)
app.include_router(ima.router)

@app.get("/api/health")
def health(user: dict = Depends(get_current_user)):
    """健康检查（需登录，按当前用户判定）。

    探测后端是否就绪、当前用户是否已配置模型 API Key。不调用任何 LLM。
    模型配置只存数据库，健康状态因人而异，因此本端点要求登录。

    返回:
        200 ``{"configured": bool, "model": str}``

        - ``configured``: 当前用户是否已在「模型设置」保存 API Key；
          为 false 时，所有需要 LLM 的生成端点会返回 503。
        - ``model``: 该用户配置的模型名（未配置为空串）。

    错误:
        401: 未登录。
    """
    try:
        _, model, _, _ = store.get_llm_config(str(user["id"]))
        return {"configured": h.is_configured_for_user(str(user["id"])), "model": model}
    except Exception:
        return {"configured": False, "model": ""}



# --- 生产静态托管: 前端构建产物 ---
_frontend_dist = BACKEND_DIR.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=_frontend_dist / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        """非 API 路径优先返回 dist 里的同名静态文件（如 favicon.svg），
        否则返回 index.html，交给前端路由处理 (SPA)。"""
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        candidate = (_frontend_dist / full_path).resolve()
        if (
            full_path
            and candidate.is_file()
            and candidate.is_relative_to(_frontend_dist.resolve())
        ):
            return FileResponse(candidate)
        return FileResponse(_frontend_dist / "index.html")
