"""敏感字段静态加密 (app/crypto.py) 的评测与胶水测试。

覆盖: 加解密往返 / 历史明文兼容 / 密文防重复加密 / 密钥不匹配安全兜底 /
落库真实密文 + 出库明文 (model 与 ima 两组设置)。
"""
from __future__ import annotations

import base64
import hashlib

import pytest
from cryptography.fernet import Fernet

from app import store
from app.crypto import decrypt_field, encrypt_field


def test_roundtrip():
    token = encrypt_field("sk-secret-123")
    assert token.startswith("enc:v1:")
    assert "sk-secret-123" not in token  # 不是明文
    assert decrypt_field(token) == "sk-secret-123"


def test_empty_and_legacy_plaintext_passthrough():
    assert encrypt_field("") == ""
    assert decrypt_field("") == ""
    # 历史明文 (无前缀) 原样读出 —— 老数据无缝兼容
    assert decrypt_field("sk-legacy-plain") == "sk-legacy-plain"


def test_no_double_encryption():
    once = encrypt_field("sk-secret")
    assert encrypt_field(once) == once


def test_wrong_key_fails_safe_to_empty():
    other = Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"wrong-key").digest()))
    forged = "enc:v1:" + other.encrypt(b"sk-stolen").decode()
    assert decrypt_field(forged) == ""


# --- 落库验证: 库里是密文, 出库是明文 ---------------------------------------

def test_model_api_key_encrypted_at_rest(tmp_store, admin_user):
    uid = str(admin_user["id"])
    store.update_model_settings(
        uid,
        api_key="sk-live-key-123",
        model="test-model",
        embedding_api_key="sk-emb-key-456",
        embedding_model="test-embedding",
    )
    with store.db_conn() as conn:
        row = conn.execute(
            "SELECT api_key, embedding_api_key FROM user_model_settings WHERE user_id = %s",
            (uid,),
        ).fetchone()
    assert row["api_key"].startswith("enc:v1:")
    assert row["embedding_api_key"].startswith("enc:v1:")
    assert "sk-live-key-123" not in row["api_key"]
    # 出库即解密
    assert store.get_llm_config(uid)[0] == "sk-live-key-123"
    assert store.get_embedding_config(uid)[0] == "sk-emb-key-456"


def test_model_api_key_legacy_plaintext_still_works(tmp_store, admin_user):
    """历史明文行 (加密上线前写入的) 原样读出, 不被当成密文破坏。"""
    uid = str(admin_user["id"])
    store.update_model_settings(uid, model="test-model", api_key="placeholder")
    with store.db_conn() as conn:
        conn.execute(
            "UPDATE user_model_settings SET api_key = 'sk-legacy-plain' WHERE user_id = %s",
            (uid,),
        )
    assert store.get_llm_config(uid)[0] == "sk-legacy-plain"


def test_ima_api_key_encrypted_at_rest(tmp_store, admin_user):
    uid = str(admin_user["id"])
    store.update_ima_settings(uid, api_key="ima-key-789")
    with store.db_conn() as conn:
        row = conn.execute(
            "SELECT ima_api_key FROM user_ima_settings WHERE user_id = %s", (uid,)
        ).fetchone()
    assert row["ima_api_key"].startswith("enc:v1:")
    assert store.get_ima_settings_row(uid)["ima_api_key"] == "ima-key-789"
