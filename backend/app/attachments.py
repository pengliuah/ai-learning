"""学习资料附件转写：把上传的文件变成 markdown 文本（两段式架构的第一段）。

全模态模型只负责"文件→文本"的理解层；计划生成与教练聊天仍走现有文本
链路，注入 ``store.get_attachments_transcripts`` 取回的转写文本。

支持类型（MVP，音视频暂不做）：
  - 图片  png/jpg/webp/gif/bmp  → base64 直接送多模态模型
  - PDF                        → PyMuPDF 逐页渲染成图送模型（≤50 页）
  - docx                       → python-docx 抽文本（含表格）
  - txt / md                   → 直接解码

转写在后台线程执行（API 层 create_task 调进来），状态写
``attachments.transcript_status``: pending → running → done / failed。
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging

from langchain_core.messages import HumanMessage

from . import store
from .llm import build_vision_model

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50MB
MAX_PDF_PAGES = 50
PAGES_PER_CALL = 10           # 每次多模态调用带多少页，控制单次 token 量
IMAGE_INLINE_BYTES = 10 * 1024 * 1024  # 超过的图片先压缩再发

# 扩展名 → mime 白名单（content_type 可伪造，以扩展名为准更稳）
MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}

_TEXT_MIMES = {"text/plain", "text/markdown"}

_TRANSCRIBE_SYSTEM = (
    "你是学习资料转写助手。把图片中的学习资料内容完整转写为 Markdown 文本：\n"
    "- 保留标题层级、列表、表格结构；数学公式用 LaTeX（行内 $...$，独立 $$...$$）；\n"
    "- 图表/示意图用文字完整描述其内容与数据；\n"
    "- 只转写，不要总结、不要省略、不要添加原文没有的内容；\n"
    "- 直接输出转写正文，不要任何解释。"
)


class TranscribeError(Exception):
    """转写失败（带可直接展示给用户的中文原因）。"""


def sniff_mime(filename: str, content_type: str = "") -> str:
    """Determine the normalized mime from the file extension.

    浏览器上报的 content_type 可信度低，扩展名是唯一权威；不在白名单的
    扩展名返回空串（调用方拒绝）。
    """
    name = (filename or "").lower()
    for ext, mime in MIME_BY_EXT.items():
        if name.endswith(ext):
            return mime
    # 无扩展名时信任浏览器上报的 content_type（移动端选文件有时缺扩展名）
    ct = (content_type or "").split(";")[0].strip().lower()
    return ct if ct in set(MIME_BY_EXT.values()) else ""


# ---------------------------------------------------------------------------
# 各类型的转写实现
# ---------------------------------------------------------------------------

def _compress_image(data: bytes) -> bytes:
    """大图（>10MB，base64 常超各模型上限）压到长边 2048 的 JPEG。"""
    if len(data) <= IMAGE_INLINE_BYTES:
        return data
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(data))
        img.thumbnail((2048, 2048))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception as exc:
        raise TranscribeError(f"图片无法解析：{exc}") from exc


def _image_part(data: bytes, mime: str) -> dict:
    b64 = base64.b64encode(data).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def _extract_usage(result) -> dict | None:
    meta = getattr(result, "usage_metadata", None)
    if not meta:
        return None
    return {
        "input_tokens": int(meta.get("input_tokens") or 0),
        "output_tokens": int(meta.get("output_tokens") or 0),
        "total_tokens": int(meta.get("total_tokens") or 0),
    }


def _invoke_vision(user_id: str, text: str, image_parts: list[dict]) -> tuple[str, dict | None]:
    """One omni-modal call. Returns (transcript, usage)."""
    model = build_vision_model(user_id)
    content: list[dict] = [{"type": "text", "text": text}, *image_parts]
    result = model.invoke([
        {"role": "system", "content": _TRANSCRIBE_SYSTEM},
        HumanMessage(content=content),
    ])
    out = result.content
    if not isinstance(out, str):
        out = str(out)
    return out.strip(), _extract_usage(result)


def _transcribe_images(user_id: str, images: list[tuple[bytes, str]], text: str) -> tuple[str, dict | None]:
    parts = [_image_part(d, m) for d, m in images]
    return _invoke_vision(user_id, text, parts)


def _transcribe_pdf(user_id: str, data: bytes, filename: str) -> tuple[str, dict | None]:
    import fitz  # pymupdf

    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise TranscribeError(f"PDF 无法解析：{exc}") from exc
    with doc:
        if doc.page_count > MAX_PDF_PAGES:
            raise TranscribeError(f"PDF 共 {doc.page_count} 页，暂只支持前 {MAX_PDF_PAGES} 页，请拆分后上传")
        total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        chunks: list[str] = []
        for start in range(0, min(doc.page_count, MAX_PDF_PAGES), PAGES_PER_CALL):
            pages = []
            for i in range(start, min(start + PAGES_PER_CALL, doc.page_count)):
                pix = doc[i].get_pixmap(dpi=150)
                pages.append((pix.tobytes("png"), "image/png"))
            text = (
                f"以下是文件《{filename}》PDF 的第 {start + 1}-{start + len(pages)} 页，请转写全部内容。"
                if doc.page_count > PAGES_PER_CALL else f"请转写文件《{filename}》的全部内容。"
            )
            out, usage = _transcribe_images(user_id, pages, text)
            chunks.append(out)
            if usage:
                for k in total_usage:
                    total_usage[k] += usage.get(k) or 0
        return "\n\n---\n\n".join(c for c in chunks if c), (total_usage if any(total_usage.values()) else None)


def _extract_docx(data: bytes) -> str:
    from docx import Document as DocxDocument

    try:
        doc = DocxDocument(io.BytesIO(data))
    except Exception as exc:
        raise TranscribeError(f"Word 文档无法解析：{exc}") from exc
    lines: list[str] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            style = (para.style.name or "").lower()
            if style.startswith("heading"):
                try:
                    level = min(int(style.rsplit(" ", 1)[-1]), 6)
                except ValueError:
                    level = 2
                lines.append(f"{'#' * level} {text}")
            else:
                lines.append(text)
    for table in doc.tables:
        rows = ["| " + " | ".join(c.text.strip().replace("\n", " ") for c in row.cells) + " |"
                for row in table.rows]
        if rows:
            lines.append("")
            lines.extend(rows)
    text = "\n".join(lines).strip()
    if not text:
        raise TranscribeError("Word 文档中没有可提取的文本")
    return text


def _decode_text(data: bytes) -> str:
    for enc in ("utf-8", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 主入口（后台线程执行）
# ---------------------------------------------------------------------------

def _do_transcribe(user_id: str, att: dict) -> None:
    aid = att["id"]
    mime = att["mime"]
    data = att["data"] or b""
    filename = att["filename"] or "未命名"
    usage = None
    if mime.startswith("image/"):
        img = _compress_image(data)
        transcript, usage = _transcribe_images(
            user_id, [(img, mime)], f"请转写文件《{filename}》的全部内容。"
        )
    elif mime == "application/pdf":
        transcript, usage = _transcribe_pdf(user_id, data, filename)
    elif mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        transcript, usage = _extract_docx(data), None
    elif mime in _TEXT_MIMES:
        transcript = _decode_text(data).strip()
        if not transcript:
            raise TranscribeError("文件内容为空")
    else:
        raise TranscribeError(f"暂不支持该文件类型：{mime}")

    if not transcript:
        raise TranscribeError("没能从文件中提取到内容")
    store.update_transcript(aid, transcript, "done")
    if usage and usage.get("total_tokens"):
        try:
            model = store.get_vision_config(user_id)[1] or store.get_llm_config(user_id)[1]
            store.record_token_usage(
                user_id, "transcribe",
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                model=model, kind="llm",
            )
        except Exception as exc:
            logger.warning("transcribe: usage record failed: %s", exc)
    logger.info("transcribe: ok attachment=%s file=%r chars=%d", aid, filename, len(transcript))


def transcribe_attachment(user_id: str, attachment_id: str) -> None:
    """Synchronous entry: transcribe one attachment and persist the result.

    任何失败都落成 transcript_status='failed'（transcript 存可直接展示的
    中文原因），绝不抛出——后台线程里没人接异常。
    """
    att = store.get_attachment(user_id, attachment_id, with_data=True)
    if att is None:
        logger.warning("transcribe: attachment %s not found", attachment_id)
        return
    if not att.get("data"):
        logger.warning("transcribe: file missing on disk attachment=%s", attachment_id)
        store.update_transcript(attachment_id, "原始文件丢失，请删除后重新上传", "failed")
        return
    store.update_transcript(attachment_id, "", "running")
    try:
        _do_transcribe(user_id, att)
    except TranscribeError as exc:
        logger.warning("transcribe: failed attachment=%s: %s", attachment_id, exc)
        store.update_transcript(attachment_id, str(exc), "failed")
    except Exception as exc:
        logger.exception("transcribe: unexpected failure attachment=%s", attachment_id)
        store.update_transcript(attachment_id, f"转写失败：{exc}", "failed")


# 后台任务集合：持有引用防止被 GC（与 long_memory._background 同款做法）
_tasks: set[asyncio.Task] = set()


def start_transcription(user_id: str, attachment_id: str) -> None:
    """Schedule background transcription from the async API layer."""
    task = asyncio.create_task(asyncio.to_thread(transcribe_attachment, user_id, attachment_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def build_materials_input(user_id: str, attachment_ids: list[str], extra_text: str = "") -> str:
    """Compose the materials-mode planner input from attachment transcripts.

    引用的附件一个都没转写完时抛 ``AttachmentsNotReady``（API 层转 409 让
    前端稍候）；部分完成时只带完成的。``extra_text`` 是用户随文件补充的
    文字说明。
    """
    rows = store.get_attachments_transcripts(user_id, attachment_ids)
    if attachment_ids and not rows:
        raise AttachmentsNotReady()
    blocks = [f"《{r['filename']}》内容：\n\n{r['transcript']}" for r in rows]
    if (extra_text or "").strip():
        blocks.append(f"补充说明：\n\n{extra_text.strip()}")
    return "\n\n---\n\n".join(blocks)


class AttachmentsNotReady(Exception):
    """引用的附件尚未完成转写。"""
