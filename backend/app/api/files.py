from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from .. import attachments as attachments_svc
from .. import store
from ..auth import get_current_user
from ..schemas import AttachmentOut

router = APIRouter()
logger = logging.getLogger(__name__)


def _out(row: dict) -> AttachmentOut:
    return AttachmentOut(
        id=str(row["id"]),
        filename=row["filename"] or "",
        mime=row["mime"] or "",
        sizeBytes=int(row.get("size_bytes") or 0),
        transcriptStatus=row.get("transcript_status") or "pending",
        transcript=row.get("transcript") or "",
        createdAt=row.get("created_at"),
    )


@router.post("/api/files")
async def upload_file(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """上传学习资料附件（图片/PDF/docx/txt/md，≤50MB），上传后自动开始转写。

    返回 ``AttachmentOut``，前端凭 ``id`` 轮询 ``GET /api/files/{id}`` 拿
    转写状态与结果。类型校验以扩展名为准；超限/类型不支持直接拒绝。
    """
    uid = str(user["id"])
    mime = attachments_svc.sniff_mime(file.filename or "", file.content_type or "")
    if not mime:
        raise HTTPException(415, "不支持的文件类型：仅支持图片 / PDF / docx / txt / md")
    data = await file.read()
    if not data:
        raise HTTPException(400, "文件内容为空")
    if len(data) > attachments_svc.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "文件超过 50MB 上限")
    row = store.create_attachment(uid, (file.filename or "未命名")[:200], mime, data)
    logger.info("upload_file: user=%s file=%r mime=%s size=%d id=%s",
                user["username"], row["filename"], mime, len(data), row["id"])
    attachments_svc.start_transcription(uid, str(row["id"]))
    return _out(row)


@router.get("/api/files")
def list_files(user: dict = Depends(get_current_user)):
    """当前用户上传的全部附件（元数据，最新在前），供「学习资料」管理页。"""
    rows = store.list_attachments(str(user["id"]))
    return [_out(r) for r in rows]


@router.get("/api/files/{attachment_id}")
def get_file(attachment_id: str, user: dict = Depends(get_current_user)):
    """查询单个附件的转写状态与结果（轮询端点，仅本人可见）。"""
    row = store.get_attachment(str(user["id"]), attachment_id)
    if row is None:
        raise HTTPException(404, "附件不存在")
    return _out(row)


@router.post("/api/files/{attachment_id}/transcribe")
def retry_transcribe(attachment_id: str, user: dict = Depends(get_current_user)):
    """对转写失败的附件重新发起转写（幂等，done 状态也可重跑）。"""
    uid = str(user["id"])
    row = store.get_attachment(uid, attachment_id)
    if row is None:
        raise HTTPException(404, "附件不存在")
    attachments_svc.start_transcription(uid, attachment_id)
    return {"ok": True}


@router.get("/api/files/{attachment_id}/raw")
def get_file_raw(attachment_id: str, user: dict = Depends(get_current_user)):
    """原始文件内容（图片预览/下载用，仅本人可见）。"""
    row = store.get_attachment(str(user["id"]), attachment_id, with_data=True)
    if row is None or row.get("data") is None:
        raise HTTPException(404, "附件不存在")
    filename = quote(row["filename"] or "file")
    return Response(
        content=row["data"],
        media_type=row["mime"] or "application/octet-stream",
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{filename}"},
    )


@router.delete("/api/files/{attachment_id}")
def delete_file(attachment_id: str, user: dict = Depends(get_current_user)):
    """删除附件（转写文本一并删除）。"""
    ok = store.delete_attachment(str(user["id"]), attachment_id)
    if not ok:
        raise HTTPException(404, "附件不存在")
    return {"ok": True}
