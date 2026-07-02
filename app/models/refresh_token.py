"""
リフレッシュトークンモデル
リフレッシュトークンの失効管理を行うデータベースモデルを定義します。
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class RefreshToken(Base, TimestampMixin):
    """
    リフレッシュトークンモデル

    リフレッシュトークンの管理と失効状態を追跡します。
    ログアウト時やトークンリフレッシュ時にトークンを失効し、
    定期的なクリーンアップで失効トークンを削除します。
    """

    __tablename__ = "refresh_tokens"

    # 主キー
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        index=True,
        comment="トークンID（JTI）",
    )

    # 外部キー
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="ユーザーID",
    )

    # トークン情報
    token_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="トークンのハッシュ値",
    )

    # 有効期限管理
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        comment="トークンの有効期限",
    )

    # 失効管理
    is_revoked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
        comment="トークンが失効しているか",
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="トークンが失効した日時",
    )

    # リレーション
    user: Mapped["User"] = relationship(
        "User",
        back_populates="refresh_tokens",
    )

    # インデックスと制約
    __table_args__ = (
        # ユーザーごとの有効なリフレッシュトークンの数を制限
        Index(
            "ix_refresh_tokens_user_id_not_revoked",
            user_id,
            is_revoked,
        ),
        # ユニーク制約
        UniqueConstraint("user_id", "id", name="uq_refresh_tokens_user_token"),
    )

    def revoke(self) -> None:
        """トークンを失効させます"""
        self.is_revoked = True
        self.revoked_at = datetime.now(timezone.utc)

    def is_valid(self) -> bool:
        """
        トークンが有効かどうかをチェックします

        Returns:
            有効であればTrue、それ以外はFalse
        """
        if self.is_revoked:
            return False

        if datetime.now(timezone.utc) > self.expires_at:
            return False

        return True
