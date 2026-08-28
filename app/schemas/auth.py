"""
認証関連のスキーマ（DTO）
認証APIのリクエスト・レスポンススキーマを定義します。
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """
    ログインリクエストスキーマ
    """

    email: EmailStr = Field(..., description="ユーザーメールアドレス")
    password: str = Field(..., min_length=8, description="パスワード")


class LoginResponse(BaseModel):
    """
    ログインレスポンススキーマ
    """

    user_id: str = Field(..., description="ユーザーID")
    email: str = Field(..., description="ユーザーメールアドレス")
    role: str = Field(..., description="ユーザーロール")
    access_token: str = Field(..., description="アクセストークン")
    refresh_token: str = Field(..., description="リフレッシュトークン")
    token_type: str = Field(default="Bearer", description="トークンタイプ")
    expires_in: int = Field(..., description="アクセストークンの有効期限（秒）")


class RefreshTokenRequest(BaseModel):
    """
    トークンリフレッシュリクエストスキーマ
    """

    refresh_token: Optional[str] = Field(
        default=None,
        description="リフレッシュトークン（Cookie利用時は省略可能）",
    )


class RefreshTokenResponse(BaseModel):
    """
    トークンリフレッシュレスポンススキーマ
    """

    access_token: str = Field(..., description="新しいアクセストークン")
    refresh_token: Optional[str] = Field(
        default=None,
        description="新しいリフレッシュトークン（Cookie利用時はレスポンスから除外）",
    )
    token_type: str = Field(default="Bearer", description="トークンタイプ")
    expires_in: int = Field(..., description="アクセストークンの有効期限（秒）")


class LogoutRequest(BaseModel):
    """
    ログアウトリクエストスキーマ
    """

    refresh_token: Optional[str] = Field(
        default=None,
        description="リフレッシュトークン（Cookie利用時は省略可能）",
    )


class LogoutResponse(BaseModel):
    """
    ログアウトレスポンススキーマ
    """

    message: str = Field(default="Logged out successfully", description="メッセージ")


class RevokeAllTokensRequest(BaseModel):
    """
    全トークン失効リクエストスキーマ
    """

    user_id: str = Field(..., description="ユーザーID")
    reason: Optional[str] = Field(None, description="失効理由")


class RevokeAllTokensResponse(BaseModel):
    """
    全トークン失効レスポンススキーマ
    """

    revoked_count: int = Field(..., description="失効したトークン数")
    message: str = Field(..., description="メッセージ")


class TokenInfo(BaseModel):
    """
    トークン情報スキーマ
    """

    jti: str = Field(..., description="JWT ID")
    user_id: str = Field(..., description="ユーザーID")
    email: str = Field(..., description="ユーザーメールアドレス")
    token_type: str = Field(..., description="トークンタイプ")
    expires_at: datetime = Field(..., description="有効期限")
    is_revoked: bool = Field(..., description="失効しているか")


class UserResponse(BaseModel):
    """
    ユーザーレスポンススキーマ
    """

    id: str = Field(..., description="ユーザーID")
    email: str = Field(..., description="ユーザーメールアドレス")
    role: str = Field(..., description="ユーザーロール")
    is_active: bool = Field(..., description="アカウントが有効か")
    created_at: datetime = Field(..., description="作成日時")


class ErrorResponse(BaseModel):
    """
    エラーレスポンススキーマ
    """

    error: str = Field(..., description="エラータイプ")
    message: str = Field(..., description="エラーメッセージ")
    detail: Optional[str] = Field(None, description="詳細情報")
