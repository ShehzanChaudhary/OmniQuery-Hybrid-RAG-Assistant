from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
from jose import jwt, JWTError
from fastapi import Header, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from config.config import Config

security_scheme = HTTPBearer()
pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')

def hash_password(password: str) -> str:
    """Hashes a plain-text password using bcrypt."""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Checks a plain-text password against a bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(user_id: int, email: str) -> str:
    """Creates a signed JWT containing the user's id and email, with an expiry."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=Config.JWT_EXPIRY_MINUTES)
    payload = {
        'sub': str(user_id),
        'email': email,
        'exp': expire
    }
    return jwt.encode(payload, Config.JWT_SECRET_KEY, algorithm=Config.JWT_ALGORITHM)

def decode_access_token(token: str) -> dict | None:
    """Decodes and validates a JWT. Returns the payload dict, or None if invalid/expired."""
    try:
        payload = jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=Config.JWT_ALGORITHM)
        return payload
    except JWTError:
        return None

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security_scheme)) -> dict:
    """
    FastAPI dependency — extracts and verifies the JWT from the Authorization
    header. Raises 401 if missing or invalid. Returns {"user_id": ..., "email": ...}.
    """
    token = credentials.credentials
    payload = decode_access_token(token)

    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    return {"user_id": int(payload["sub"]), "email": payload["email"]}
