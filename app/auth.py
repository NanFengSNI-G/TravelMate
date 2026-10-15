import hashlib
import hmac
import secrets
import time
import jwt
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
    return jwt.encode(
        {"sub": user_id, "exp": int(time.time()) + 3600},
        settings().auth_secret,
        algorithm="HS256",
    )


def decode(value: str):
    try:
        payload = jwt.decode(
            value,
            settings().auth_secret,
            algorithms=["HS256"],
            options={"require": ["sub", "exp"]},
        )
        return payload["sub"]
    except jwt.InvalidTokenError as exc:
        raise ValueError("登录凭证无效或已过期") from exc
