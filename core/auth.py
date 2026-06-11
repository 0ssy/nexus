import hashlib
import secrets
from datetime import datetime, timedelta
from jose import jwt, JWTError
from core.types import Config

def generate_api_key():
    return secrets.token_urlsafe(32)

def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()

def create_token(agent_id: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=Config.JWT_EXPIRE_HOURS)
    return jwt.encode(
        {"sub": agent_id, "exp": expire},
        Config.SECRET_KEY,
        algorithm=Config.JWT_ALGORITHM
    )

def verify_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=[Config.JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None

def generate_id(prefix: str = "") -> str:
    return f"{prefix}{secrets.token_hex(8)}"