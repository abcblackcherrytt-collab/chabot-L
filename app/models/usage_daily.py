"""
日次利用量モデル
ユーザーの日次メッセージ利用回数とトークン使用量を管理するデータベースモデルを定義します。
"""

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class UsageDaily(Base, TimestampMixin):
    """
    日次利用量モデル

    ユーザーの1日あたりのメッセージ回数・トークン使用量を追跡します。
    ユーザーIDと日付の組み合わせでユニーク制約を設定します。
    """

    __tablename__ = "usage_daily"

    # 主キー（UUID）
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="利用量ID（UUID）",
    )

    # 外部キー
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="ユーザーID",
    )

    # 利用日
    usage_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        comment="利用日",
    )

    # 利用回数
    message_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="メッセージ送信回数",
    )

    # トークン使用量
    input_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="入力トークン使用量",
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="出力トークン使用量",
    )

    # リレーション
    user: Mapped["User"] = relationship(
        "User",
        back_populates="usage_records",
    )

    # ユニーク制約（user_id + usage_date）
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "usage_date",
            name="uq_usage_daily_user_date",
        ),
    )
