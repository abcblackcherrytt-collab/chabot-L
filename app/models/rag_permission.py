"""
RAG権限モデル
プラン別のRAG corpus・モデル設定を管理するデータベースモデルを定義します。
"""

import uuid

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class RagPermission(Base, TimestampMixin):
    """
    RAG権限モデル

    各プランで使用可能なRAG corpus、モデル名、トークン上限、
    1日のメッセージ上限を管理します。
    """

    __tablename__ = "rag_permissions"

    # 主キー（UUID）
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="RAG権限ID（UUID）",
    )

    # プラン
    plan: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        comment="プラン（free, basic, pro, enterprise）",
    )

    # RAG corpus
    rag_corpus_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="RAG corpus ID",
    )

    # モデル設定
    model_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="使用するモデル名",
    )

    # トークン上限
    max_input_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="最大入力トークン数",
    )
    max_output_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="最大出力トークン数",
    )

    # 1日のメッセージ上限
    daily_message_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="1日のメッセージ上限",
    )

    # 有効フラグ
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="このプラン設定が有効か",
    )
