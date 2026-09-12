"""敏感字段静态加密：用户存库的 API Key 用 Fernet 加密（AES128-CBC+HMAC）。

密钥来源：``FIELD_SECRET`` 环境变量；未设置时回退 ``JWT_SECRET``。
注意：两者都未设置时 JWT_SECRET 每次启动随机生成，重启后已加密的
Key 将无法解密 —— 生产环境务必设置 JWT_SECRET（或 FIELD_SECRET）。

存储格式：密文带版本前缀 ``enc:v1:<fernet-token>``，便于将来换算法/密钥。
兼容：库里的历史明文原样读出（无前缀直接透传），下次保存时自然完成加密迁移；
解密失败（如加密密钥与写入时不一致）返回空串并打 error 日志，
而不是把垃圾字符串发给上游 LLM 服务商。
"""

from __future__ import annotations

import base64
import hashlib
import logging
import threading

from cryptography.fernet import Fernet, InvalidToken

from .config import settings

logger = logging.getLogger(__name__)

_PREFIX = "enc:v1:"
_lock = threading.Lock()
_fernet: Fernet | None = None


def _cipher() -> Fernet:
    global _fernet
    with _lock:
        if _fernet is None:
            secret = settings.field_secret or settings.jwt_secret
            key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
            _fernet = Fernet(key)
        return _fernet


def encrypt_field(plain: str) -> str:
    """加密一个敏感字段值；空值原样返回，已带前缀的密文不重复加密。"""
    if not plain or plain.startswith(_PREFIX):
        return plain
    return _PREFIX + _cipher().encrypt(plain.encode()).decode()


def decrypt_field(stored: str) -> str:
    """解密一个敏感字段值；历史明文原样返回，解密失败返回空串。"""
    if not stored or not stored.startswith(_PREFIX):
        return stored
    try:
        return _cipher().decrypt(stored[len(_PREFIX) :].encode()).decode()
    except InvalidToken:
        logger.error(
            "敏感字段解密失败：加密密钥与写入时不一致（FIELD_SECRET/JWT_SECRET 变过？），返回空串"
        )
        return ""
