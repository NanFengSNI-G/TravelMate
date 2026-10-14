import base64
import hashlib
import hmac
import json
import secrets
import time
from app.config import settings


def password_hash(password: str, salt: str | None = None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 200000
    ).hex()
    return f"{salt}:{digest}"


def password_ok(password: str, stored: str):
    salt = stored.split(":")[0]
    return hmac.compare_digest(password_hash(password, salt), stored)


def token(user_id: str):
    data = base64.urlsafe_b64encode(
        json.dumps({"id": user_id, "exp": int(time.time()) + 3600}).encode()
    ).decode()
    sig = hmac.new(
        settings().auth_secret.encode(), data.encode(), hashlib.sha256
    ).hexdigest()
    return f"{data}.{sig}"


def decode(value: str):
    data, sig = value.rsplit(".", 1)
    expected = hmac.new(
        settings().auth_secret.encode(), data.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise ValueError("登录凭证无效")
    payload = json.loads(base64.urlsafe_b64decode(data))
    if payload["exp"] < time.time():
        raise ValueError("登录已过期")
    return payload["id"]