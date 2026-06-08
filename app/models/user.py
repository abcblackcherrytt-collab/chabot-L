"""
ユーザーモデル
ユーザー情報を管理するデータベースモデルを定義します。
"""

from typing import List, TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.refresh_token import RefreshToken


class User(Base, TimestampMixin):
    """
    ユーザーモデル

    ユーザー情報と認証情報を管理します。
    """

    __tablename__ = "users"

    # 主キー
    id: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
        index=True,
        comment="ユーザーID",
    )

    # 認証情報
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
        comment="メールアドレス",
    )

    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="ハッシュ化されたパスワード",
    )

    # アカウント状態
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
        comment="アカウントが有効か",
    )

    # ユーザーロール
    role: Mapped[str] = mapped_column(
        String(50),
        default="user",
        nullable=False,
        comment="ユーザーロール（admin, user）",
    )

    # リレーション
    refresh_tokens: Mapped[List["RefreshToken"]] = relationship(
        "RefreshToken",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
