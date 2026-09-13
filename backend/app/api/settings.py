from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from .. import long_memory, store
from ..auth import get_current_user
from . import helpers as h

router = APIRouter()
logger = logging.getLogger(__name__)

from ..schemas import (
    AdminCreateUserRequest,
    AdminResetPasswordRequest,
    AnnotationCreate,
    AnnotationOut,
    AnnotationUpdate,
    AnswersState,
    Assessment,
    BookmarkOut,
    ChangePasswordRequest,
    ChatTurn,
    CoachRequest,
    Content,
    ContentUpdate,
    Difficulty,
    Document,
    GenSettings,
    GenSettingsUpdate,
    GradingResult,
    ImaArchiveRequest,
    ImaSettings,
    ImaSettingsUpdate,
    Level,
    LoginRequest,
    MemoryArchiveRequest,
    MemoryOut,
    MemoryProfileUpdate,
    MemorySettings,
    MemorySettingsUpdate,
    MemoryUpdate,
    ModelSettings,
    ModelSettingsUpdate,
    ModelTestResult,
    Module,
    ModuleStatus,
    ModuleStatusPatch,
    Plan,
    PlanCreateRequest,
    PlanListItem,
    PlanSource,
    PlansOrderUpdate,
    Question,
    QuestionResult,
    QuestionType,
    Quiz,
    RefreshRequest,
    SaveAnswersRequest,
    SaveToImaRequest,
    SaveToImaResponse,
)

@router.get("/api/settings/ima")
def get_ima_settings(user: dict = Depends(get_current_user)):
    """读取当前用户的 IMA 设置（凭证 + skill prompt）。"""
    row = store.get_ima_settings_row(str(user["id"]))
    return ImaSettings(
        imaClientId=row["ima_client_id"],
        imaApiKey=row["ima_api_key"],
        imaSkillPrompt=row["ima_skill_prompt"],
    )


@router.put("/api/settings/ima")
def put_ima_settings(req: ImaSettingsUpdate, user: dict = Depends(get_current_user)):
    """更新当前用户的 IMA 设置（仅更新提供的字段）。"""
    row = store.update_ima_settings(
        str(user["id"]),
        client_id=req.imaClientId,
        api_key=req.imaApiKey,
        skill_prompt=req.imaSkillPrompt,
    )
    logger.info("put_ima_settings: updated (client_id set=%s, prompt set=%s)",
                bool(row["ima_client_id"]), bool(row["ima_skill_prompt"]))
    return ImaSettings(
        imaClientId=row["ima_client_id"],
        imaApiKey=row["ima_api_key"],
        imaSkillPrompt=row["ima_skill_prompt"],
    )


@router.get("/api/settings/regenerate")
def get_regen_settings(user: dict = Depends(get_current_user)):
    """读取当前用户的生成策略设置（按类型：plan/content/quiz/grade）。"""
    row = store.get_gen_settings_row(str(user["id"]))
    return GenSettings(plan=row["plan"], content=row["content"], quiz=row["quiz"], grade=row["grade"])


@router.put("/api/settings/regenerate")
def put_regen_settings(req: GenSettingsUpdate, user: dict = Depends(get_current_user)):
    """更新当前用户的生成策略设置（仅更新提供的字段）。"""
    row = store.update_gen_settings(
        str(user["id"]), plan=req.plan, content=req.content, quiz=req.quiz, grade=req.grade
    )
    logger.info("put_regen_settings: plan=%s content=%s quiz=%s grade=%s",
                bool(row["plan"]), bool(row["content"]), bool(row["quiz"]), bool(row["grade"]))
    return GenSettings(plan=row["plan"], content=row["content"], quiz=row["quiz"], grade=row["grade"])


@router.get("/api/settings/model")
def get_model_settings(user: dict = Depends(get_current_user)):
    """读取当前用户在库里保存的模型设置（原样返回，不做环境变量回退）。

    只返回该用户在数据库中保存的值：空字段表示未配置，
    不会用任何默认值填充，避免误把部署级配置当成个人配置。
    """
    row = store.get_model_settings_row(str(user["id"]))
    return ModelSettings(
        apiKey=row["api_key"], model=row["model"],
        baseUrl=row["base_url"], maxTokens=row["max_tokens"],
        embeddingApiKey=row.get("embedding_api_key") or "",
        embeddingModel=row.get("embedding_model") or "",
        embeddingBaseUrl=row.get("embedding_base_url") or "",
    )


@router.put("/api/settings/model")
def put_model_settings(req: ModelSettingsUpdate, user: dict = Depends(get_current_user)):
    """保存当前用户的模型设置（仅更新提供的字段），并刷新已缓存的模型实例。"""
    row = store.update_model_settings(
        str(user["id"]),
        api_key=req.apiKey,
        model=req.model,
        base_url=req.baseUrl,
        max_tokens=req.maxTokens,
        embedding_api_key=req.embeddingApiKey,
        embedding_model=req.embeddingModel,
        embedding_base_url=req.embeddingBaseUrl,
    )
    reset = getattr(h.coach, "reset_model_runtime", None)
    if reset:
        reset()
    logger.info("put_model_settings: updated (key set=%s, model set=%s, embedding set=%s)",
                bool(row["api_key"]), bool(row["model"]), bool(row.get("embedding_model")))
    return ModelSettings(
        apiKey=row["api_key"], model=row["model"],
        baseUrl=row["base_url"], maxTokens=row["max_tokens"],
        embeddingApiKey=row.get("embedding_api_key") or "",
        embeddingModel=row.get("embedding_model") or "",
        embeddingBaseUrl=row.get("embedding_base_url") or "",
    )


@router.get("/api/usage/summary")
def usage_summary(user: dict = Depends(get_current_user)):
    """当前用户的 LLM token 用量统计（今日 / 本月 / 累计，东八区）。"""
    return store.get_usage_summary(str(user["id"]))


@router.get("/api/settings/memory")
def get_memory_settings(user: dict = Depends(get_current_user)):
    """读取长期记忆总开关（默认开启）。关掉后教练对话不写入、不召回。"""
    row = store.get_memory_settings_row(str(user["id"]))
    return MemorySettings(enabled=row["enabled"])


@router.put("/api/settings/memory")
def put_memory_settings(req: MemorySettingsUpdate, user: dict = Depends(get_current_user)):
    """更新长期记忆总开关。"""
    row = store.update_memory_settings(str(user["id"]), enabled=req.enabled)
    logger.info("put_memory_settings: enabled=%s user=%s", row["enabled"], user["username"])
    return MemorySettings(enabled=row["enabled"])


