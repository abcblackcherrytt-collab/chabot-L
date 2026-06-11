"""
会話ログモデル
ユーザーとLLMの会話履歴を管理するデータベースモデルを定義します。
"""

import uuid
from typing import Optional, TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class Conversation(Base, TimestampMixin):
    """
    会話ログモデル

    ユーザーとLLMの1往復の会話を記録します。
    リクエスト時のプラン・RAG corpus・トークン使用量も保存します。
    """

    __tablename__ = "conversations"

    # 主キー（UUID）
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="会話ID（UUID）",
    )

    # 外部キー
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="ユーザーID",
    )

    # LINE メッセージID
    line_message_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="LINEメッセージID",
    )

    # メッセージ内容
    user_message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="ユーザーのメッセージ",
    )
    assistant_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="アシスタントの回答",
    )

    # リクエスト時のコンテキスト
    plan_at_request: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="リクエスト時のプラン",
    )
    rag_corpus_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="使用したRAG corpus ID",
    )

    # トークン使用量
    input_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="入力トークン数",
    )
    output_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="出力トークン数",
    )

    # リレーション
    user: Mapped["User"] = relationship(
        "User",
        back_populates="conversations",
    )
