# FirestoreからCloud SQLへの移行プラン仕様書

> **バージョン**: 1.0  
> **作成日**: 2026-08-03  
> **対象プロジェクト**: Chabot (LINE版)  
> **移行対象**: Firestore → Cloud SQL for PostgreSQL

---

## 1. 移行の目的と範囲

### 1.1 移行の目的

- **コスト最適化**: ユーザー増加に伴うコスト増大を抑える
- **スケーラビリティ**: SQLの柔軟性と高度なクエリ機能の獲得
- **既存コード活用**: SQLAlchemyベースの既存実装をそのまま利用

### 1.2 移行の範囲

| コンポーネント | 移行対象 | 備考 |
|---|---|---|
| **ユーザーデータ** | ✅ 移行 | Userテーブル |
| **サブスクリプション** | ✅ 移行 | Subscriptionテーブル |
| **会話履歴** | ✅ 移行 | Conversationテーブル |
| **使用量データ** | ✅ 移行 | UsageDailyテーブル |
| **リフレッシュトークン** | ✅ 移行 | RefreshTokenテーブル |
| **RAG権限** | ✅ 移行 | RagPermissionテーブル |
| **Stripeイベント** | ✅ 移行 | StripeEventテーブル |

### 1.3 移行しないもの

- Google Cloud Storageのファイルデータ
- Vertex AI RAGコーパス
- LINE Messaging APIの設定
- Stripeの決済データ（Stripe側で管理）

---

## 2. 現状アーキテクチャ（Firestore）

### 2.1 システム構成

```
┌─────────────────────────────────────────────────────────────┐
│                        Cloud Run                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  FastAPI Application                                  │  │
│  │  ┌──────────────────────────────────────────────┐   │  │
│  │  │  Line Service                                 │   │  │
│  │  │  ├─ follow イベント処理                       │   │  │
│  │  │  ├─ message イベント処理                      │   │  │
│  │  │  └─ unfollow イベント処理                     │   │  │
│  │  └──────────────────────────────────────────────┘   │  │
│  │                                                        │  │
│  │  ┌──────────────────────────────────────────────┐   │  │
│  │  │  Repository Layer                            │   │  │
│  │  │  └─ FirestoreUserRepository                  │   │  │
│  │  └──────────────────────────────────────────────┘   │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
              ┌────────────────────────┐
              │   Firestore           │
              │  - Users              │
              │  - Subscriptions      │
              │  - Conversations      │
              │  - UsageDaily         │
              └────────────────────────┘
```

### 2.2 データモデル（Firestore）

```python
# users コレクション
{
  'id': str,                    # UUID
  'line_user_id': str,          # LINEユーザーID
  'subscription_plan': str,     # 'free', 'basic', 'pro'
  'is_active': bool,            # アカウント状態
  'created_at': str,            # ISO 8601
  'updated_at': str             # ISO 8601
}

# conversations コレクション
{
  'id': str,
  'user_id': str,
  'message': str,
  'response': str,
  'created_at': str
}

# usage_daily コレクション
{
  'id': str,
  'user_id': str,
  'date': str,                 # YYYY-MM-DD
  'message_count': int
}
```

### 2.3 費用構造（Firestore）

| ユーザー数 | 1日リクエスト | 1月リクエスト | 無料枠 | 月額 |
|---|---|---|---|---|
| 20人 | 100 | 3,000 | 50,000読取/日<br>20,000書込/日 | **$0** |
| 50人 | 250 | 7,500 | 範囲内 | **$0** |
| 100人 | 500 | 15,000 | 範囲内 | **$0** |
| 200人 | 1,000 | 30,000 | 超過 | **$2.40** |
| 500人 | 2,500 | 75,000 | 超過 | **$6.00** |

※ 超過時の料金: $0.06/100,000読み取り、$0.18/100,000書き込み

---

## 3. 移行後アーキテクチャ（Cloud SQL）

### 3.1 システム構成

```
┌─────────────────────────────────────────────────────────────┐
│                        Cloud Run                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  FastAPI Application                                  │  │
│  │  ┌──────────────────────────────────────────────┐   │  │
│  │  │  Line Service                                 │   │  │
│  │  │  ├─ follow イベント処理                       │   │  │
│  │  │  ├─ message イベント処理                      │   │  │
│  │  │  └─ unfollow イベント処理                     │   │  │
│  │  └──────────────────────────────────────────────┘   │  │
│  │                                                        │  │
│  │  ┌──────────────────────────────────────────────┐   │  │
│  │  │  Repository Layer                            │   │  │
│  │  │  └─ UserRepository (SQLAlchemy)              │   │  │
│  │  └──────────────────────────────────────────────┘   │  │
│  │                                                        │  │
│  │  ┌──────────────────────────────────────────────┐   │  │
│  │  │  Database Connection                         │   │  │
│  │  │  - AsyncSession                               │   │  │
│  │  │  - Connection Pooling                         │   │  │
│  │  └──────────────────────────────────────────────┘   │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
              ┌────────────────────────┐
              │   Cloud SQL            │
              │  (PostgreSQL 16)       │
              │  - users              │
              │  - subscriptions      │
              │  - conversations      │
              │  - usage_daily        │
              │  - refresh_tokens     │
              │  - rag_permissions    │
              │  - stripe_events      │
              └────────────────────────┘
```

### 3.2 データベーススキーマ

#### users テーブル

```sql
CREATE TABLE users (
  id VARCHAR(36) PRIMARY KEY,
  line_user_id VARCHAR(255) UNIQUE NOT NULL,
  stripe_customer_id VARCHAR(255),
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

#### subscriptions テーブル

```sql
CREATE TABLE subscriptions (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  stripe_subscription_id VARCHAR(255) UNIQUE,
  plan VARCHAR(50) DEFAULT 'free',
  status VARCHAR(50) DEFAULT 'free',
  current_period_start TIMESTAMP WITH TIME ZONE,
  current_period_end TIMESTAMP WITH TIME ZONE,
  cancel_at_period_end BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

#### conversations テーブル

```sql
CREATE TABLE conversations (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  line_message_id VARCHAR(255),
  message TEXT NOT NULL,
  response TEXT,
  rag_corpus_id VARCHAR(255),
  plan_at_request VARCHAR(50),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### 3.3 費用構造（Cloud SQL）

| ユーザー数 | マシンタイプ | ストレージ | 月額 |
|---|---|---|---|
| 20人 | db-f1-micro | SSD 10GB | **$11.26** |
| 50人 | db-f1-micro | SSD 10GB | **$11.26** |
| 100人 | db-f1-micro | SSD 10GB | **$11.26** |
| 200人 | db-f1-micro | SSD 50GB | **$27.26** |
| 500人 | db-custom-1-3840 | SSD 100GB | **$60.00** |

---

## 4. 移行タイミングと判断基準

### 4.1 移行タイミング

| ユーザー数 | 推奨アクション | 理由 |
|---|---|---|
| **0〜100人** | Firestore継続 | 無料枠内 |
| **100〜150人** | 移行準備開始 | 無料枠超過の兆し |
| **150〜200人** | 移行実施 | コスト境界線 |
| **200人以上** | Cloud SQL運用 | コストメリット明確 |

### 4.2 判断基準（数値目標）

```python
# 移行判断基準
def should_migrate(current_users: int, monthly_cost: float) -> bool:
    """
    移行すべきかどうかを判定
    
    Args:
        current_users: 現在のユーザー数
        monthly_cost: 現在の月額コスト
    
    Returns:
        移行すべきならTrue
    """
    # 基準1: ユーザー数が150人を超えたら移行
    if current_users > 150:
        return True
    
    # 基準2: 月額が$12を超えたら移行
    if monthly_cost > 12:
        return True
    
    # 基準3: 予測コストがCloud SQLを超えるなら移行
    projected_cost = estimate_firestore_cost(current_users * 2)
    cloudsql_cost = 11.26  # db-f1-micro
    if projected_cost > cloudsql_cost:
        return True
    
    return False
```

### 4.3 予測コスト計算

```python
def estimate_firestore_cost(users: int) -> float:
    """
    Firestoreの月額コストを推定
    
    Args:
        users: ユーザー数
    
    Returns:
        月額コスト（USD）
    """
    # 1ユーザーあたりの月間リクエスト数
    requests_per_user_per_month = 150  # 5リクエスト/日 × 30日
    
    # 総リクエスト数
    total_requests = users * requests_per_user_per_month
    
    # 読み取り:書き込み = 7:3（概算）
    read_requests = int(total_requests * 0.7)
    write_requests = int(total_requests * 0.3)
    
    # 無料枠を超えた場合の課金
    free_reads = 50_000  # 1日あたり
    free_writes = 20_000  # 1日あたり
    
    # 月額無料枠
    monthly_free_reads = free_reads * 30
    monthly_free_writes = free_writes * 30
    
    # 課金対象リクエスト
    billable_reads = max(0, read_requests - monthly_free_reads)
    billable_writes = max(0, write_requests - monthly_free_writes)
    
    # 課金額（$0.06/100,000読み取り、$0.18/100,000書き込み）
    read_cost = (billable_reads / 100_000) * 0.06
    write_cost = (billable_writes / 100_000) * 0.18
    
    return read_cost + write_cost
```

### 4.4 移行チェックリスト

#### 移行前確認事項

- [ ] ユーザー数が150人を超えた
- [ ] Firestore月額が$12を超えた
- [ ] Cloud SQLインスタンスを作成済み
- [ ] マイグレーションを実行済み
- [ ] 移行スクリプトを準備済み
- [ ] テスト環境で移行を検証済み

---

## 5. データ移行手順

### 5.1 移行準備

#### ステップ1: Cloud SQLインスタンス作成

```bash
# Cloud SQLインスタンス作成（db-f1-micro）
gcloud sql instances create chabot-postgres \
  --database-version=POSTGRES_16 \
  --tier=db-f1-micro \
  --region=asia-northeast1 \
  --storage-size=10 \
  --storage-auto-increase \
  --backup-start-time=15:00 \
  --enable-point-in-time-recovery \
  --activation-policy=ALWAYS \
  --pricing-plan=PER_USE

# データベース作成
gcloud sql databases create chabot \
  --instance=chabot-postgres

# ユーザー作成
gcloud sql users create chabot_user \
  --instance=chabot-postgres \
  --password="<強力なパスワード>"
```

#### ステップ2: マイグレーション実行

```bash
# マイグレーション実行
alembic upgrade head
```

### 5.2 データ移行スクリプト

```python
# scripts/migrate_firestore_to_sql.py
"""FirestoreからCloud SQLへのデータ移行スクリプト"""
import asyncio
import sys
from datetime import datetime
from google.cloud import firestore
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.models.user import User
from app.models.subscription import Subscription
from app.models.conversation import Conversation
from app.models.usage_daily import UsageDaily
from app.models.refresh_token import RefreshToken
from app.models.rag_permission import RagPermission


class MigrationService:
    """データ移行サービス"""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = None
        self.async_session = None
        self.firestore_db = firestore.Client()
    
    async def initialize_db(self):
        """データベース接続初期化"""
        self.engine = create_async_engine(
            self.database_url,
            echo=False
        )
        self.async_session = sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
    
    async def migrate_users(self):
        """ユーザーデータの移行"""
        print("=== ユーザーデータ移行開始 ===")
        
        users_ref = self.firestore_db.collection('users')
        docs = users_ref.stream()
        
        async with self.async_session() as session:
            count = 0
            for doc in docs:
                try:
                    user_data = doc.to_dict()
                    
                    # ユーザー作成
                    user = User(
                        id=user_data['id'],
                        line_user_id=user_data['line_user_id'],
                        stripe_customer_id=user_data.get('stripe_customer_id'),
                        is_active=user_data.get('is_active', True),
                        created_at=datetime.fromisoformat(user_data['created_at']),
                        updated_at=datetime.fromisoformat(user_data['updated_at'])
                    )
                    
                    # サブスクリプション作成
                    subscription = Subscription(
                        id=str(uuid.uuid4()),
                        user_id=user.id,
                        stripe_subscription_id=user_data.get('stripe_subscription_id'),
                        plan=user_data.get('subscription_plan', 'free'),
                        status=user_data.get('subscription_status', 'free'),
                        created_at=user.created_at,
                        updated_at=user.updated_at
                    )
                    
                    session.add(user)
                    session.add(subscription)
                    count += 1
                    
                    if count % 10 == 0:
                        print(f"移行進捗: {count}件")
                
                except Exception as e:
                    print(f"エラー: {doc.id} - {e}")
                    continue
            
            await session.commit()
            print(f"=== ユーザーデータ移行完了: {count}件 ===")
    
    async def migrate_conversations(self):
        """会話履歴の移行"""
        print("=== 会話履歴移行開始 ===")
        
        conv_ref = self.firestore_db.collection('conversations')
        docs = conv_ref.stream()
        
        async with self.async_session() as session:
            count = 0
            for doc in docs:
                try:
                    conv_data = doc.to_dict()
                    
                    conversation = Conversation(
                        id=conv_data['id'],
                        user_id=conv_data['user_id'],
                        line_message_id=conv_data.get('line_message_id'),
                        message=conv_data['message'],
                        response=conv_data.get('response'),
                        rag_corpus_id=conv_data.get('rag_corpus_id'),
                        plan_at_request=conv_data.get('plan_at_request'),
                        created_at=datetime.fromisoformat(conv_data['created_at'])
                    )
                    
                    session.add(conversation)
                    count += 1
                    
                    if count % 50 == 0:
                        print(f"移行進捗: {count}件")
                
                except Exception as e:
                    print(f"エラー: {doc.id} - {e}")
                    continue
            
            await session.commit()
            print(f"=== 会話履歴移行完了: {count}件 ===")
    
    async def migrate_usage_daily(self):
        """使用量データの移行"""
        print("=== 使用量データ移行開始 ===")
        
        usage_ref = self.firestore_db.collection('usage_daily')
        docs = usage_ref.stream()
        
        async with self.async_session() as session:
            count = 0
            for doc in docs:
                try:
                    usage_data = doc.to_dict()
                    
                    usage = UsageDaily(
                        id=usage_data['id'],
                        user_id=usage_data['user_id'],
                        date=datetime.fromisoformat(usage_data['date']),
                        message_count=usage_data.get('message_count', 0),
                        created_at=datetime.fromisoformat(usage_data['created_at'])
                    )
                    
                    session.add(usage)
                    count += 1
                
                except Exception as e:
                    print(f"エラー: {doc.id} - {e}")
                    continue
            
            await session.commit()
            print(f"=== 使用量データ移行完了: {count}件 ===")
    
    async def seed_rag_permissions(self):
        """RAG権限データのシード"""
        print("=== RAG権限データシード開始 ===")
        
        # シードデータ
        permissions = [
            {
                'plan': 'free',
                'rag_corpus_id': os.environ.get('GOOGLE_CORPUS_ID_FREE'),
                'model_name': 'gemini-1.5-flash',
                'max_input_tokens': 4000,
                'max_output_tokens': 4000,
                'daily_message_limit': 3,
                'enabled': True
            },
            {
                'plan': 'basic',
                'rag_corpus_id': os.environ.get('GOOGLE_CORPUS_ID_BASIC'),
                'model_name': 'gemini-1.5-flash',
                'max_input_tokens': 16000,
                'max_output_tokens': 8000,
                'daily_message_limit': 100,
                'enabled': True
            },
            {
                'plan': 'pro',
                'rag_corpus_id': os.environ.get('GOOGLE_CORPUS_ID_PRO'),
                'model_name': 'gemini-1.5-pro',
                'max_input_tokens': 32000,
                'max_output_tokens': 16000,
                'daily_message_limit': 500,
                'enabled': True
            }
        ]
        
        async with self.async_session() as session:
            for perm_data in permissions:
                permission = RagPermission(**perm_data)
                session.add(permission)
            
            await session.commit()
            print(f"=== RAG権限データシード完了: {len(permissions)}件 ===")
    
    async def verify_migration(self):
        """移行データの検証"""
        print("=== 移行データ検証開始 ===")
        
        async with self.async_session() as session:
            # ユーザー数検証
            from sqlalchemy import select, func
            user_count = await session.execute(
                select(func.count()).select_from(User)
            )
            print(f"ユーザー数: {user_count.scalar()}")
            
            # サブスクリプション数検証
            sub_count = await session.execute(
                select(func.count()).select_from(Subscription)
            )
            print(f"サブスクリプション数: {sub_count.scalar()}")
            
            # 会話履歴数検証
            conv_count = await session.execute(
                select(func.count()).select_from(Conversation)
            )
            print(f"会話履歴数: {conv_count.scalar()}")
            
            print("=== 移行データ検証完了 ===")
    
    async def close(self):
        """接続クローズ"""
        if self.engine:
            await self.engine.dispose()


async def main():
    """メイン処理"""
    # 環境変数からデータベースURL取得
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("エラー: DATABASE_URL環境変数が未設定")
        sys.exit(1)
    
    # 移行サービス初期化
    migration = MigrationService(database_url)
    await migration.initialize_db()
    
    try:
        # 移行実行
        await migration.migrate_users()
        await migration.migrate_conversations()
        await migration.migrate_usage_daily()
        await migration.seed_rag_permissions()
        
        # 検証
        await migration.verify_migration()
        
        print("\n=== データ移行完了 ===")
    
    finally:
        await migration.close()


if __name__ == "__main__":
    import uuid
    asyncio.run(main())
```

### 5.3 移行実行コマンド

```bash
# 環境変数設定
export DATABASE_URL="postgresql+asyncpg://chabot_user:<password>@//chabot?host=/cloudsql/takahashi-451312:asia-northeast1:chabot-postgres"
export GOOGLE_CORPUS_ID_FREE="free-corpus-id"
export GOOGLE_CORPUS_ID_BASIC="basic-corpus-id"
export GOOGLE_CORPUS_ID_PRO="pro-corpus-id"

# 移行スクリプト実行
python scripts/migrate_firestore_to_sql.py

# 移行結果確認
gcloud sql databases execute chabot \
  --instance=chabot-postgres \
  --sql="SELECT COUNT(*) FROM users;"
```

---

## 6. コード変更内容

### 6.1 抽象化レイヤー導入

#### ベースリポジトリ

```python
# app/repositories/base_user_repository.py
from abc import ABC, abstractmethod
from typing import Optional

class BaseUserRepository(ABC):
    """ユーザーリポジトリの抽象クラス"""
    
    @abstractmethod
    async def find_by_line_user_id(self, line_user_id: str) -> Optional[dict]:
        """LINEユーザーIDでユーザーを検索"""
        pass
    
    @abstractmethod
    async def create_line_user(self, line_user_id: str) -> dict:
        """LINEユーザーを作成"""
        pass
    
    @abstractmethod
    async def update_subscription_plan(self, user_id: str, plan: str) -> dict:
        """サブスクリプションプランを更新"""
        pass
    
    @abstractmethod
    async def find_by_id(self, user_id: str) -> Optional[dict]:
        """IDでユーザーを検索"""
        pass
```

#### Firestore実装

```python
# app/repositories/firestore_user_repository.py
from app.repositories.base_user_repository import BaseUserRepository
from google.cloud import firestore
import uuid
from datetime import datetime
from typing import Optional

class FirestoreUserRepository(BaseUserRepository):
    """Firestoreユーザーリポジトリ実装"""
    
    def __init__(self):
        self.db = firestore.Client()
    
    async def find_by_line_user_id(self, line_user_id: str) -> Optional[dict]:
        """LINEユーザーIDでユーザーを検索"""
        docs = self.db.collection('users')\
            .where('line_user_id', '==', line_user_id)\
            .limit(1)\
            .get()
        
        for doc in docs:
            return {'id': doc.id, **doc.to_dict()}
        return None
    
    async def create_line_user(self, line_user_id: str) -> dict:
        """LINEユーザーを作成"""
        user_data = {
            'id': str(uuid.uuid4()),
            'line_user_id': line_user_id,
            'subscription_plan': 'free',
            'subscription_status': 'active',
            'is_active': True,
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }
        
        self.db.collection('users').document(user_data['id']).set(user_data)
        return user_data
    
    async def update_subscription_plan(self, user_id: str, plan: str) -> dict:
        """サブスクリプションプランを更新"""
        doc_ref = self.db.collection('users').document(user_id)
        doc_ref.update({
            'subscription_plan': plan,
            'updated_at': datetime.utcnow().isoformat()
        })
        doc = doc_ref.get()
        return {'id': doc.id, **doc.to_dict()}
    
    async def find_by_id(self, user_id: str) -> Optional[dict]:
        """IDでユーザーを検索"""
        doc = self.db.collection('users').document(user_id).get()
        return {'id': doc.id, **doc.to_dict()} if doc.exists else None
```

#### Cloud SQL実装

```python
# app/repositories/user_repository.py
from app.repositories.base_user_repository import BaseUserRepository
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user import User
from app.models.subscription import Subscription
from typing import Optional
import uuid
from datetime import datetime

class UserRepository(BaseUserRepository):
    """Cloud SQLユーザーリポジトリ実装"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def find_by_line_user_id(self, line_user_id: str) -> Optional[dict]:
        """LINEユーザーIDでユーザーを検索"""
        result = await self.db.execute(
            select(User).where(User.line_user_id == line_user_id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            return {
                'id': user.id,
                'line_user_id': user.line_user_id,
                'subscription_plan': user.subscription.plan,
                'is_active': user.is_active,
                'created_at': user.created_at.isoformat(),
                'updated_at': user.updated_at.isoformat()
            }
        return None
    
    async def create_line_user(self, line_user_id: str) -> dict:
        """LINEユーザーを作成"""
        user_id = str(uuid.uuid4())
        now = datetime.utcnow()
        
        # ユーザー作成
        user = User(
            id=user_id,
            line_user_id=line_user_id,
            is_active=True,
            created_at=now,
            updated_at=now
        )
        
        # サブスクリプション作成
        subscription = Subscription(
            id=str(uuid.uuid4()),
            user_id=user_id,
            plan='free',
            status='active',
            created_at=now,
            updated_at=now
        )
        
        self.db.add(user)
        self.db.add(subscription)
        await self.db.commit()
        await self.db.refresh(user)
        
        return {
            'id': user.id,
            'line_user_id': user.line_user_id,
            'subscription_plan': 'free',
            'is_active': user.is_active,
            'created_at': user.created_at.isoformat(),
            'updated_at': user.updated_at.isoformat()
        }
    
    async def update_subscription_plan(self, user_id: str, plan: str) -> dict:
        """サブスクリプションプランを更新"""
        result = await self.db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        subscription = result.scalar_one_or_none()
        
        if subscription:
            subscription.plan = plan
            subscription.updated_at = datetime.utcnow()
            await self.db.commit()
            
            return {
                'id': subscription.id,
                'plan': subscription.plan,
                'status': subscription.status
            }
        
        return None
    
    async def find_by_id(self, user_id: str) -> Optional[dict]:
        """IDでユーザーを検索"""
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            return {
                'id': user.id,
                'line_user_id': user.line_user_id,
                'subscription_plan': user.subscription.plan,
                'is_active': user.is_active,
                'created_at': user.created_at.isoformat(),
                'updated_at': user.updated_at.isoformat()
            }
        return None
```

### 6.2 DIでの切り替え

```python
# app/core/deps.py
from fastapi import Depends
from app.repositories.base_user_repository import BaseUserRepository
from app.repositories.firestore_user_repository import FirestoreUserRepository
from app.repositories.user_repository import UserRepository
from app.core.config import settings

def get_user_repository() -> BaseUserRepository:
    """データベースバックエンドに応じたリポジトリを返す"""
    if settings.database_backend == "firestore":
        return FirestoreUserRepository()
    elif settings.database_backend == "postgresql":
        # Cloud SQLの場合はDBセッションも必要
        return get_database_session()
    else:
        raise ValueError(f"Unsupported database backend: {settings.database_backend}")
```

### 6.3 設定ファイル変更

```python
# app/core/config.py
class Settings(BaseSettings):
    # ... 既存設定 ...
    
    # データベース設定（移行用）
    database_backend: str = "firestore"  # "firestore" or "postgresql"
    firestore_project_id: str = "takahashi-451312"
    
    # Cloud SQL設定
    database_url: str = ""  # Cloud SQL接続URL
```

---

## 7. テスト計画

### 7.1 単体テスト

#### Firestoreリポジトリテスト

```python
# tests/unit/repositories/test_firestore_user_repository.py
import pytest
from app.repositories.firestore_user_repository import FirestoreUserRepository

@pytest.mark.asyncio
class TestFirestoreUserRepository:
    
    async def test_create_line_user(self):
        """ユーザー作成テスト"""
        repo = FirestoreUserRepository()
        
        # テスト用LINEユーザーID
        line_user_id = "test_line_user_123"
        
        # ユーザー作成
        user = await repo.create_line_user(line_user_id)
        
        # 検証
        assert user is not None
        assert user['line_user_id'] == line_user_id
        assert user['subscription_plan'] == 'free'
        assert user['is_active'] is True
    
    async def test_find_by_line_user_id(self):
        """LINEユーザーIDでの検索テスト"""
        repo = FirestoreUserRepository()
        
        # テストデータ作成
        line_user_id = "test_line_user_456"
        created_user = await repo.create_line_user(line_user_id)
        
        # 検索
        found_user = await repo.find_by_line_user_id(line_user_id)
        
        # 検証
        assert found_user is not None
        assert found_user['id'] == created_user['id']
```

### 7.2 統合テスト

#### 移行後の動作確認

```python
# tests/integration/test_migration.py
import pytest
from scripts.migrate_firestore_to_sql import MigrationService

@pytest.mark.asyncio
class TestMigration:
    
    async def test_user_migration(self):
        """ユーザーデータ移行テスト"""
        # テスト用Firestoreデータ準備
        # ...
        
        # 移行実行
        migration = MigrationService(test_database_url)
        await migration.initialize_db()
        await migration.migrate_users()
        
        # 検証
        # Firestoreのユーザー数 == Cloud SQLのユーザー数
        assert firestore_user_count == sql_user_count
    
    async def test_conversation_migration(self):
        """会話履歴移行テスト"""
        # 同様の手順で会話履歴を検証
        pass
```

### 7.3 エンドツーエンドテスト

```bash
# テストスクリプト
# tests/e2e/test_user_flow.py

# 1. LINE友だち追加イベント送信
# 2. ユーザーが正しく作成されることを確認
# 3. メッセージ送信
# 4. 会話履歴が正しく保存されることを確認
# 5. 使用量カウントが正しく動作することを確認
```

---

## 8. ロールバック計画

### 8.1 ロールバック条件

以下のいずれかが発生した場合、ロールバックを実施：

- データ移行中に重大なエラーが発生
- 移行後の動作確認で重大なバグを発見
- パフォーマンスが著しく低下
- データ不整合が検出される

### 8.2 ロールバック手順

```bash
# ステップ1: 環境変数をFirestoreに戻す
gcloud run services update chabot-service \
  --update-env-vars=DATABASE_BACKEND=firestore

# ステップ2: 新しいリビジョンをデプロイ
gcloud run services update chabot-service \
  --image=<以前の正常動作イメージ>

# ステップ3: 動作確認
curl -X POST https://<service-url>/api/v1/webhooks/line \
  -H "Content-Type: application/json" \
  -d '{"test": "validation"}'

# ステップ4: ロールバック完了確認
gcloud run revisions list \
  --service=chabot-service \
  --region=asia-northeast1
```

### 8.3 ロールバック後の対応

- 問題の原因調査
- 修正パッチの適用
- 再移行のスケジュール調整

---

## 9. スケジュールとコスト

### 9.1 タイムライン

| フェーズ | 期間 | タスク |
|---|---|---|
| **準備** | 1週間 | Cloud SQL作成、マイグレーション、テスト |
| **移行** | 1日（深夜実施） | データ移行、環境切り替え |
| **検証** | 3日 | 動作確認、パフォーマンス確認 |
| **安定化** | 1週間 | モニタリング、不具合修正 |

### 9.2 コスト比較

| ユーザー数 | Firestore | Cloud SQL | 差額 |
|---|---|---|---|
| 100人 | $0 | $11.26 | Firestore有利 |
| 150人 | $0 | $11.26 | Firestore有利 |
| 200人 | $2.40 | $11.26 | Firestore有利 |
| 300人 | $4.80 | $11.26 | Firestore有利 |
| 500人 | $12.00 | $11.26 | **Cloud SQL有利** |
| 1000人 | $24.00 | $11.26 | **Cloud SQL有利** |

### 9.3 担当者

| 役割 | 担当 | 責務 |
|---|---|---|
| **プロジェクトリード** | - | 全体調整、意思決定 |
| **バックエンドエンジニア** | - | コード実装、移行スクリプト作成 |
| **インフラエンジニア** | - | Cloud SQL作成、ネットワーク設定 |
| **QAエンジニア** | - | テスト計画、検証実施 |

---

## 10. 付録

### 10.1 環境変数一覧

| 変数名 | Firestore時 | Cloud SQL時 | 説明 |
|---|---|---|---|
| `DATABASE_BACKEND` | `firestore` | `postgresql` | データベースバックエンド |
| `FIRESTORE_PROJECT_ID` | `takahashi-451312` | - | FirestoreプロジェクトID |
| `DATABASE_URL` | - | Cloud SQL接続URL | データベース接続URL |

### 10.2 関連ドキュメント

- [Cloud SQL pricing](https://cloud.google.com/sql/pricing)
- [Firestore pricing](https://cloud.google.com/firestore/pricing)
- [Alembic documentation](https://alembic.sqlalchemy.org/)
- [SQLAlchemy async documentation](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)

### 10.3 用語集

| 用語 | 説明 |
|---|---|
| **Firestore** | Google CloudのNoSQLデータベースサービス |
| **Cloud SQL** | Google Cloudのマネージドリレーショナルデータベース |
| **db-f1-micro** | Cloud SQLの最小インスタンスタイプ |
| **VPC Access Connector** | Cloud RunからCloud SQLへの接続用コネクタ |
| **マイグレーション** | データベーススキーマのバージョン管理 |
| **ロールバック** | 移行失敗時の復旧処理 |

---

**文書バージョン履歴:**

| バージョン | 日付 | 変更内容 |
|---|---|---|
| 1.0 | 2026-08-03 | 初版作成 |
