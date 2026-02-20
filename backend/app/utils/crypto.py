"""
Password and JWT utilities (pure functions, no FastAPI dependencies).
"""
from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timezone, timedelta
import os

# JWT Config
JWT_SECRET = os.environ.get('JWT_SECRET', 'dev-secret-key')
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(pw: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(pw)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain, hashed)


def create_token(data: dict) -> str:
    """Create a JWT token with expiration."""
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS)
    return jwt.encode({**data, "exp": expire}, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode a JWT token. Raises JWTError if invalid."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
