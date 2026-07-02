"""
ユーザーモデル
ユーザー情報を管理するデータベースモデルを定義します。
"""

import uuid
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.refresh_token import RefreshToken
    from app.models.subscription import Subscription
    from app.models.usage_daily import UsageDaily
    from app.models.conversation import Conversation


class User(Base, TimestampMixin):
    """
    ユーザーモデル

    ユーザー情報と認証情報を管理します。
    LINE userId を主な識別子とし、Stripe customer ID と紐づけます。
    """

    __tablename__ = "users"

    # 主キー（UUID）
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="ユーザーID（UUID）",
    )

    # LINE連携（PII扱い - 個人情報として適切に取り扱うこと）
    line_user_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=True,
        comment="LINE ユーザーID（PII）",
    )

    # 連絡先
    email: Mapped[Optional[str]] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=True,
        comment="メールアドレス",
    )

    display_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="表示名",
    )

    # Stripe連携
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=True,
        comment="StripeカスタマーID",
    )

    # 認証情報（Email/Password ログイン用、LINE Login のみなら不要）
    hashed_password: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
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
    subscriptions: Mapped[List["Subscription"]] = relationship(
        "Subscription",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    usage_records: Mapped[List["UsageDaily"]] = relationship(
        "UsageDaily",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    conversations: Mapped[List["Conversation"]] = relationship(
        "Conversation",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
