"""
Password and JWT utilities (pure functions, no FastAPI dependencies).
"""
from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timezone, timedelta

# JWT Config
# SEC-03 (M-1): this module no longer has its own key or fallback. The one key
# is ``app.deps.auth.JWT_SECRET`` (fail-closed: no known default, ≥ 32 bytes
# outside an explicit test run). It is read at call time so importing
# ``app.utils`` stays free of the database import that ``app.deps.auth`` does.


def _jwt_secret() -> str:
    from app.deps.auth import JWT_SECRET
    return JWT_SECRET


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
    return jwt.encode({**data, "exp": expire}, _jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode a JWT token. Raises JWTError if invalid."""
    return jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
