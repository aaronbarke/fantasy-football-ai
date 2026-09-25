from pydantic import BaseModel, EmailStr, Field, field_validator

from app.utils.security import BCRYPT_MAX_BYTES


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def _fits_bcrypt(cls, password: str) -> str:
        # bcrypt ignores everything past 72 bytes, so a longer password would
        # quietly accept any string sharing its first 72 bytes.
        if len(password.encode()) > BCRYPT_MAX_BYTES:
            raise ValueError(f"Password must be at most {BCRYPT_MAX_BYTES} bytes")
        return password


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=1024)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(max_length=4096)


class GoogleAuthRequest(BaseModel):
    """The ID token (JWT) Google Identity Services returns to the browser."""

    credential: str = Field(max_length=8192)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
