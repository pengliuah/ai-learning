"""路由共享助手：LLM 实例、配置校验、文档定位、SSE 帧。

全部从 main.py 迁出；路由模块通过 ``h.`` 前缀访问，测试打桩也打在这里。
"""
from __future__ import annotations

import json
import logging

from fastapi import HTTPException

from ..agent import LearningCoach
from .. import store

logger = logging.getLogger(__name__)

# SSE 长任务 (计划/测验/批改/教练) 的心跳间隔: 期间无数据回传会被 nginx/移动网络
# 当作空闲连接掐断 (浏览器报 Failed to fetch), 每 30s 发一个 ": ping" 注释帧保活。
LLM_HEARTBEAT_SECONDS = 30

# 全局唯一的教练实例 (绑定各用户模型配置的缓存也在实例里)
coach = LearningCoach()


def _user_public(user: dict) -> dict:
    """用户公开信息（绝不包含 password_hash）。"""
    return {
        "id": str(user["id"]),
        "username": user["username"],
        "email": user.get("email"),
        "role": user["role"],
        "createdAt": user.get("created_at"),
    }


def is_configured_for_user(user_id: str) -> bool:
    """Whether the user's saved model config has an API key."""
    return store.is_llm_configured_for_user(user_id)


def _require_configured(user_id: str) -> None:
    """该用户未配置模型 API Key 时抛 503，统一拦截需要调用 LLM 的端点。"""
    if not is_configured_for_user(user_id):
        raise HTTPException(status_code=503, detail="model API key not configured")


def _get_doc(plan_id: str, user_id: str):
    """按 id 取当前用户的计划文档；不存在（或属于他人）则抛 404。"""
    doc = store.get_document(plan_id, user_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="plan not found")
    return doc


def _get_module(doc, module_id: str):
    """在文档中按 id 取模块；不存在则抛 404。"""
    module = next((m for m in doc.plan.modules if m.id == module_id), None)
    if module is None:
        raise HTTPException(status_code=404, detail="module not found")
    return module




def _sse(event: str, data) -> str:
    """格式化一条 SSE 事件帧。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


