"""
Stripeイベントモデル
Stripe Webhookで受信したイベントの履歴を管理するデータベースモデルを定義します。
冪等性管理とイベント処理状態の追跡に使用します。
"""

import uuid

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

from sqlalchemy import JSON


class StripeEvent(Base, TimestampMixin):
    """
    Stripeイベントモデル

    Stripe Webhookで受信したイベントを記録します。
    冪等性の担保（重複処理の防止）に使用します。
    """

    __tablename__ = "stripe_events"

    # 主キー（UUID）
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="イベントID（UUID）",
    )

    # Stripe イベントID
    stripe_event_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="StripeイベントID",
    )

    # イベントタイプ
    event_type: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="イベントタイプ（例: invoice.paid）",
    )

    # 処理状態
    processed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
        comment="処理済みかどうか",
    )

    # イベントペイロード
    payload: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        comment="Stripeイベントのペイロード（JSON）",
    )
