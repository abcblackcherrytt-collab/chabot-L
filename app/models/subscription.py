"""
サブスクリプションモデル
ユーザーのサブスクリプション状態を管理するデータベースモデルを定義します。
"""

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class Subscription(Base, TimestampMixin):
    """
    サブスクリプションモデル

    ユーザーのプラン・支払い状態・Stripe連携を管理します。
    """

    __tablename__ = "subscriptions"

    # 主キー（UUID）
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="サブスクリプションID（UUID）",
    )

    # 外部キー
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="ユーザーID",
    )

    # Stripe連携
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
        index=True,
        comment="StripeサブスクリプションID",
    )

    # プラン
    plan: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="free",
        comment="プラン（free, basic, pro, enterprise）",
    )

    # ステータス
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="free",
        comment="ステータス（active, trialing, past_due, unpaid, canceled, incomplete, free）",
    )

    # 請求期間
    current_period_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="現在の請求期間開始日時",
    )
    current_period_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="現在の請求期間終了日時",
    )

    # 解約フラグ
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="期間終了時に解約するか",
    )

    # リレーション
    user: Mapped["User"] = relationship(
        "User",
        back_populates="subscriptions",
    )

    def is_active_paid(self) -> bool:
        """有料プランが有効かどうかを判定します"""
        return self.status in ("active", "trialing")

    def is_restricted(self) -> bool:
        """制限状態（past_due/unpaid/canceled）かどうかを判定します"""
        return self.status in ("past_due", "unpaid", "canceled", "incomplete")
