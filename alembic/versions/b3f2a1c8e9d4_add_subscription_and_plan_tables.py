"""Add subscription, usage_daily, rag_permissions, conversations, stripe_events tables and update users

Revision ID: b3f2a1c8e9d4
Revises: da7afce18552
Create Date: 2026-06-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3f2a1c8e9d4'
down_revision: Union[str, None] = 'da7afce18552'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ========================================
    # 1. users テーブルにカラム追加
    # ========================================
    # line_user_id 追加
    op.add_column('users', sa.Column(
        'line_user_id', sa.String(length=255), nullable=True,
        comment='LINE ユーザーID（PII）',
    ))
    op.create_index(op.f('ix_users_line_user_id'), 'users', ['line_user_id'], unique=True)

    # email を nullable に変更（LINE Login のみのユーザー対応）
    op.alter_column('users', 'email',
                    existing_type=sa.String(length=255),
                    nullable=True)

    # display_name 追加
    op.add_column('users', sa.Column(
        'display_name', sa.String(length=255), nullable=True,
        comment='表示名',
    ))

    # stripe_customer_id 追加
    op.add_column('users', sa.Column(
        'stripe_customer_id', sa.String(length=255), nullable=True,
        comment='StripeカスタマーID',
    ))
    op.create_index(op.f('ix_users_stripe_customer_id'), 'users', ['stripe_customer_id'], unique=True)

    # hashed_password を nullable に変更（LINE Login のみのユーザー対応）
    op.alter_column('users', 'hashed_password',
                    existing_type=sa.String(length=255),
                    nullable=True)

    # ========================================
    # 2. subscriptions テーブル作成
    # ========================================
    op.create_table('subscriptions',
        sa.Column('id', sa.String(length=36), nullable=False, comment='サブスクリプションID（UUID）'),
        sa.Column('user_id', sa.String(length=36), nullable=False, comment='ユーザーID'),
        sa.Column('stripe_subscription_id', sa.String(length=255), nullable=True, comment='StripeサブスクリプションID'),
        sa.Column('plan', sa.String(length=50), nullable=False, comment='プラン（free, basic, pro, enterprise）'),
        sa.Column('status', sa.String(length=50), nullable=False, comment='ステータス（active, trialing, past_due, unpaid, canceled, incomplete, free）'),
        sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=True, comment='現在の請求期間開始日時'),
        sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True, comment='現在の請求期間終了日時'),
        sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False, comment='期間終了時に解約するか'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_subscriptions_id'), 'subscriptions', ['id'], unique=False)
    op.create_index(op.f('ix_subscriptions_user_id'), 'subscriptions', ['user_id'], unique=False)
    op.create_index(op.f('ix_subscriptions_stripe_subscription_id'), 'subscriptions', ['stripe_subscription_id'], unique=True)

    # ========================================
    # 3. usage_daily テーブル作成
    # ========================================
    op.create_table('usage_daily',
        sa.Column('id', sa.String(length=36), nullable=False, comment='利用量ID（UUID）'),
        sa.Column('user_id', sa.String(length=36), nullable=False, comment='ユーザーID'),
        sa.Column('usage_date', sa.Date(), nullable=False, comment='利用日'),
        sa.Column('message_count', sa.Integer(), nullable=False, comment='メッセージ送信回数'),
        sa.Column('input_tokens', sa.Integer(), nullable=False, comment='入力トークン使用量'),
        sa.Column('output_tokens', sa.Integer(), nullable=False, comment='出力トークン使用量'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'usage_date', name='uq_usage_daily_user_date'),
    )
    op.create_index(op.f('ix_usage_daily_id'), 'usage_daily', ['id'], unique=False)
    op.create_index(op.f('ix_usage_daily_user_id'), 'usage_daily', ['user_id'], unique=False)
    op.create_index(op.f('ix_usage_daily_usage_date'), 'usage_daily', ['usage_date'], unique=False)

    # ========================================
    # 4. rag_permissions テーブル作成
    # ========================================
    op.create_table('rag_permissions',
        sa.Column('id', sa.String(length=36), nullable=False, comment='RAG権限ID（UUID）'),
        sa.Column('plan', sa.String(length=50), nullable=False, comment='プラン（free, basic, pro, enterprise）'),
        sa.Column('rag_corpus_id', sa.String(length=255), nullable=False, comment='RAG corpus ID'),
        sa.Column('model_name', sa.String(length=255), nullable=False, comment='使用するモデル名'),
        sa.Column('max_input_tokens', sa.Integer(), nullable=False, comment='最大入力トークン数'),
        sa.Column('max_output_tokens', sa.Integer(), nullable=False, comment='最大出力トークン数'),
        sa.Column('daily_message_limit', sa.Integer(), nullable=False, comment='1日のメッセージ上限'),
        sa.Column('enabled', sa.Boolean(), nullable=False, comment='このプラン設定が有効か'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_rag_permissions_id'), 'rag_permissions', ['id'], unique=False)
    op.create_index(op.f('ix_rag_permissions_plan'), 'rag_permissions', ['plan'], unique=True)

    # ========================================
    # 5. conversations テーブル作成
    # ========================================
    op.create_table('conversations',
        sa.Column('id', sa.String(length=36), nullable=False, comment='会話ID（UUID）'),
        sa.Column('user_id', sa.String(length=36), nullable=False, comment='ユーザーID'),
        sa.Column('line_message_id', sa.String(length=255), nullable=True, comment='LINEメッセージID'),
        sa.Column('user_message', sa.Text(), nullable=False, comment='ユーザーのメッセージ'),
        sa.Column('assistant_message', sa.Text(), nullable=True, comment='アシスタントの回答'),
        sa.Column('plan_at_request', sa.String(length=50), nullable=False, comment='リクエスト時のプラン'),
        sa.Column('rag_corpus_id', sa.String(length=255), nullable=True, comment='使用したRAG corpus ID'),
        sa.Column('input_tokens', sa.Integer(), nullable=True, comment='入力トークン数'),
        sa.Column('output_tokens', sa.Integer(), nullable=True, comment='出力トークン数'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_conversations_id'), 'conversations', ['id'], unique=False)
    op.create_index(op.f('ix_conversations_user_id'), 'conversations', ['user_id'], unique=False)

    # ========================================
    # 6. stripe_events テーブル作成
    # ========================================
    op.create_table('stripe_events',
        sa.Column('id', sa.String(length=36), nullable=False, comment='イベントID（UUID）'),
        sa.Column('stripe_event_id', sa.String(length=255), nullable=False, comment='StripeイベントID'),
        sa.Column('event_type', sa.String(length=255), nullable=False, comment='イベントタイプ'),
        sa.Column('processed', sa.Boolean(), nullable=False, comment='処理済みかどうか'),
        sa.Column('payload', sa.JSON(), nullable=False, comment='Stripeイベントのペイロード'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_stripe_events_id'), 'stripe_events', ['id'], unique=False)
    op.create_index(op.f('ix_stripe_events_stripe_event_id'), 'stripe_events', ['stripe_event_id'], unique=True)
    op.create_index(op.f('ix_stripe_events_event_type'), 'stripe_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_stripe_events_processed'), 'stripe_events', ['processed'], unique=False)


def downgrade() -> None:
    # 新規テーブルを削除（逆順）
    op.drop_index(op.f('ix_stripe_events_processed'), table_name='stripe_events')
    op.drop_index(op.f('ix_stripe_events_event_type'), table_name='stripe_events')
    op.drop_index(op.f('ix_stripe_events_stripe_event_id'), table_name='stripe_events')
    op.drop_index(op.f('ix_stripe_events_id'), table_name='stripe_events')
    op.drop_table('stripe_events')

    op.drop_index(op.f('ix_conversations_user_id'), table_name='conversations')
    op.drop_index(op.f('ix_conversations_id'), table_name='conversations')
    op.drop_table('conversations')

    op.drop_index(op.f('ix_rag_permissions_plan'), table_name='rag_permissions')
    op.drop_index(op.f('ix_rag_permissions_id'), table_name='rag_permissions')
    op.drop_table('rag_permissions')

    op.drop_index(op.f('ix_usage_daily_usage_date'), table_name='usage_daily')
    op.drop_index(op.f('ix_usage_daily_user_id'), table_name='usage_daily')
    op.drop_index(op.f('ix_usage_daily_id'), table_name='usage_daily')
    op.drop_table('usage_daily')

    op.drop_index(op.f('ix_subscriptions_stripe_subscription_id'), table_name='subscriptions')
    op.drop_index(op.f('ix_subscriptions_user_id'), table_name='subscriptions')
    op.drop_index(op.f('ix_subscriptions_id'), table_name='subscriptions')
    op.drop_table('subscriptions')

    # users テーブルのカラムを元に戻す
    op.drop_index(op.f('ix_users_stripe_customer_id'), table_name='users')
    op.drop_column('users', 'stripe_customer_id')

    op.drop_column('users', 'display_name')

    op.alter_column('users', 'hashed_password',
                    existing_type=sa.String(length=255),
                    nullable=False)

    op.alter_column('users', 'email',
                    existing_type=sa.String(length=255),
                    nullable=False)

    op.drop_index(op.f('ix_users_line_user_id'), table_name='users')
    op.drop_column('users', 'line_user_id')
