# Chabot（LINE版）プロジェクト計画・進捗

> **更新日**: 2026-08-17（Secret Manager登録済み確認済み・Cloud Runデプロイ準備完了）
> **対象GCP**: `takahashi-451312`
> **Cloud Runリージョン**: `asia-northeast1`
> **進捗表記**: `[x]` 完了 / `[ ]` 未完了 / `[保留]` 現在は実施しない
> **注意**: シークレットの実値は本ファイルへ記載しない。

---

## 0. 現在の結論

現在は、次の2つを分けて管理する。

1. **本番版**: LINE Bot + Vertex AI RAG のPhase 1がCloud Runで稼働中
2. **開発版**: Firestoreによるユーザー管理・回数制限・プラン別コーパス・StripeテストAPIをローカル実装中

開発版は構文確認まで完了しているが、未コミット・未デプロイであり、本番利用可能とは判定しない。

### 0.1 フェーズ一覧

| Phase | ゴール | データストア | Stripe | 状況 |
|---|---|---|---|---|
| Phase 1 | 友だち追加後にLINEでRAG回答 | なし | なし | **本番稼働中** |
| Phase 2 | ユーザー管理、日次回数制限、プラン別コーパス | **Firestore** | テストAPIのみ | **ローカル実装・統合試験前** |
| Phase 3 | Stripeテストモードで登録・更新・解約を検証 | Firestore | テストモード | **コード実装中・E2E未実施** |
| Phase 4 | Stripe本番決済と運用監視 | Firestore | 本番モード | **未着手** |
| 将来 | PostgreSQL / Cloud SQLへの移行 | PostgreSQL | 継続 | **保留** |

### 0.2 確定した方針

- [x] 初期運用のデータストアはFirestoreとする。
- [x] FastAPI起動時のPostgreSQL接続確認を一時停止する。
- [保留] Cloud SQL、VPC Connector、Alembic本番適用は当面実施しない。
- [x] サブスクリプションAPIは当面 `test_user_id` を使うテスト実装のまま残す。
- [x] 1日あたりの回数上限は次の値に統一する。
  - free: 3件
  - basic: 100件
  - pro: 500件
- [ ] Stripe本番キーへの切替は、テストモードE2E完了後に判断する。

---

## 1. 本番稼働状況

### 1.1 2026-08-17確認結果と進捗

**本番環境**:
- [x] Cloud Runサービス `chabot-service` はReady。
- [x] 最新Readyリビジョンは `chabot-service-00016-kt8`。
- [x] 正式URLの `/health` はHTTP 200、`{"status":"healthy"}` を返却。
- [x] 本番リビジョンのコミットは `d602736`。
- [x] 直近のGitHub Actionsデプロイは成功。
- [ ] LINEの実端末で「友だち追加 → 質問 → RAG回答」を今回の更新後に再確認する。

**開発環境進捗（2026-08-17作業完了）**:
- [x] Python 3.14でgoogle-cloud-firestoreインストール完了
- [x] PostgreSQL依存分離完了（deps.py、webhooks/line.py、chat.py修正）
- [x] Firestore単独起動確認（/healthエンドポイント正常動作）
- [x] Firestore回数制御Transaction化実装（increment_with_limit_check）
- [x] Stripe解約フロー矛盾解消（Stripe解約→free継続、LINE unfollow→無効化）
- [x] Cloud Run環境変数Firestore版更新（.env.example、deploy.yml修正）
- [x] CI品質ゲート化（Python 3.14化、Firestore-only app startupテスト追加）
- [x] Secret Managerシークレット登録済み確認（google-corpus-id関連）

### 1.2 本番とローカルの差

- 本番にはPhase 1のコードがデプロイされている。
- Firestore、日次回数制限、Stripe Checkout、Firestore連携Webhookの変更はローカル作業ツリーにあり、本番未反映。
- 現在の作業ブランチは `phase2/local-mock-plan`。
- ローカルには多数の未コミット変更・未追跡ファイルがあるため、変更範囲を整理してからPR化する。

---

## 2. 実装済みの機能

### 2.1 Phase 1: LINE Bot + RAG

- [x] LINE Webhook署名検証
- [x] followイベントのウェルカムメッセージ
- [x] textメッセージのRAG回答
- [x] Vertex AI RAG実API統合
- [x] プラン別に `corpus_id` / `model_name` をRAGへ渡せる構造
- [x] LINE向けの短文回答・マークダウン除去
- [x] `/health` エンドポイント
- [x] Cloud Run / Artifact Registry / Workload Identityによるデプロイ

### 2.2 Phase 2: Firestoreユーザー・プラン管理

- [x] `DATABASE_BACKEND=firestore` を既定値として追加
- [x] Firestoreユーザーリポジトリ
- [x] Firestore RAG権限リポジトリ
- [x] Firestore日次使用回数リポジトリ
- [x] follow時のユーザー作成
- [x] `free/basic/pro` のプラン取得
- [x] プラン別コーパス切替
- [x] 全プランの日次回数判定
- [x] 上限超過時にRAGを実行せず案内を返信
- [x] 回数上限のコード上の基準値を `3/100/500` に一元化
- [x] Firestore初期データ投入スクリプト
- [ ] 本番Firestoreへ初期データが正しく投入されていることを再確認
- [ ] Firestore Security Rules、IAM、必要な複合インデックスを確認
- [ ] 実LINEユーザーでfree/basic/proそれぞれの上限とコーパス切替をE2E確認

### 2.3 Phase 3: Stripeテスト実装

- [x] Stripeクライアントの非同期呼び出し
- [x] Checkout Session作成処理
- [x] プランとStripe Price IDの対応
- [x] サブスクリプションAPIルーター
- [x] FirestoreへのStripe Customer ID保存
- [x] `customer.subscription.created` のFirestoreプラン更新・LINE通知
- [x] `customer.subscription.deleted` のfreeプラン更新・LINE通知
- [x] `invoice.payment_failed` のLINE通知
- [x] Stripe / Firestore整合性チェックサービスの土台
- [ ] `customer.subscription.updated` のFirestore状態更新
- [ ] `invoice.paid` のFirestore状態・請求期間更新
- [ ] Webhook冪等性をインメモリからFirestoreへ移行
- [ ] Stripeテストモードで登録・更新・支払い失敗・解約をE2E確認

### 2.4 サブスクリプションAPIの扱い

現在は意図的にテスト実装とする。

- [x] Checkout作成とstatus取得は固定の `test_user_id` を使用
- [ ] テストAPIを本番公開する場合、第三者が呼べないアクセス制御を追加
- [ ] 実ユーザー課金へ進む段階で `get_current_user` に置換
- [ ] APIレスポンスの `monthly_limit` という名前を、実態に合わせて `daily_message_limit` へ移行

### 2.5 PROJECT_PLAN進捗管理スキル

- [x] Codex用 `.agents/skills/project-plan-manager/SKILL.md` を作成
- [x] Claude用 `.claude/skills/project-plan-manager/SKILL.md` へ同一内容を複製
- [x] スキルは各配置の `SKILL.md` だけで構成し、追加のagents設定ファイルは使用しない
- [x] ルートの `AGENTS.md` / `CLAUDE.md` はスキル登録のために変更しない
- [x] Codex版・Claude版のSKILL.md検証と同一性確認に成功
- [ ] スキルを変更する場合は両配置を同時更新し、差分がないことを再確認

---

## 3. 次回デプロイ前の必須対策（P0）

### P0-1. 依存関係の再インストール

現在のローカル環境はPython 3.14で、SQLAlchemy 2.0/FastAPIとの互換性は問題ない。venvに `google-cloud-firestore` がインストールされていないだけ。

- [x] Python 3.14でのSQLAlchemy/FastAPI互換性を確認
- [x] `google-cloud-firestore` をvenvへインストール
- [ ] unit / integration / e2eテストを実行
- [ ] Firestore・回数制限・Stripeテスト用の自動テストを追加
- [ ] テスト結果を本ファイルへ記録

### P0-2. CIを正式な品質ゲートにする

- [x] Python 3.14バージョンをdeploy.ymlに更新
- [x] Firestore-only app startupテストをCIに追加
- [x] テスト環境変数にDATABASE_BACKEND=firestoreを追加
- [ ] 現在の `continue-on-error: true` を外せる状態までテストを修正（残りの失敗テスト解消後に解除）
- [ ] FirestoreエミュレーターまたはモックをCIへ導入（将来対応）

### P0-3. Cloud Run環境変数をFirestore版へ更新

現行のデプロイ設定にはFirestore版で必要な設定が不足している。

- [x] `DATABASE_BACKEND=firestore` (.env.exampleとdeploy.ymlに追加済み)
- [x] `FIRESTORE_PROJECT_ID=takahashi-451312` (.env.example更新済み)
- [x] free用 `GOOGLE_CORPUS_ID=6942545116196241408` (.env.example更新済み)
- [x] 有料用 `GOOGLE_CORPUS_ID_PLAN1=1495705249682292736` (.env.example更新済み)
- [x] GitHub Actionsのdeploy.ymlにFirestore用環境変数を追加
- [x] Secret Managerにシークレット登録済み:
  - `google-corpus-id`: 6942545116196241408 ✅
  - `google-corpus-id-plan1`: 1495705249682292736 ✅
- [ ] Cloud RunサービスアカウントへFirestoreアクセス権を付与・確認

### P0-4. Firestore回数制御を安全にする

現状は「現在値を読み取り、その後setする」方式のため、同時メッセージで加算が失われる可能性がある。また、上限確認と加算が別処理であり、同時リクエストで上限を超える可能性がある。

- [x] Firestore Transactionで「上限確認 + 加算」を原子的に実行
- [x] Transactionの採用を決定（`increment_with_limit_check`実装）
- [ ] Firestore障害時に回数を0として許可する挙動を見直す
- [ ] 日付境界をUTCではなくAsia/Tokyo基準に変更
- [ ] 同時実行テストを追加

### P0-5. Stripe解約フローの矛盾を解消

現在の `subscription.deleted` は、ユーザーをfreeプランへ戻した直後に `is_active=False` にしている。このままではfreeプランとして利用できない。

- [x] 「有料解約後もfreeで継続」か「アカウント全体を停止」かを決定
- [x] 推奨: Stripe解約はfreeへ戻すだけにし、LINE unfollowや明示的退会時のみ無効化
- [x] Stripe解約: freeプラン戻しのみ実装（ユーザーは無効化しない）
- [x] LINE unfollow: アカウント全体を停止を実装
- [ ] Firestore更新、LINE通知、テストを統合

### P0-6. Firestore経路からPostgreSQL依存を分離

起動時の `init_db()` / `close_db()` は停止済みだが、LINE Webhookや認証DependsにはSQLAlchemyセッション生成が残っている。

- [x] Firestore使用時は `async_session_maker` を生成・使用しない構造に変更
- [x] Firestore用とPostgreSQL用の依存性注入を明確に分離
- [x] Firestoreだけでアプリを起動できるテストを実施
- [ ] PostgreSQL専用auth/chatエンドポイントを維持するか、一時停止するか決定

---

## 4. 本番決済前の対策（P1）

### P1-1. 認証・アカウント連携

- [ ] LINE Login callbackでFirestoreユーザーを検索・作成
- [ ] 仮UUIDの都度発行を廃止し、既存ユーザーIDを再利用
- [ ] Refresh Tokenの保存先をFirestore対応、またはLINE Bot用途では機能停止
- [ ] LINE ID → Firestore user ID → Stripe customer IDの一意性を検証
- [ ] サブスクAPIの固定 `test_user_id` を認証ユーザーへ置換

### P1-2. Stripe Webhookの信頼性

- [ ] Webhook署名検証をテストモードで実確認
- [ ] `subscription.created/updated/deleted` をすべてFirestoreへ反映
- [ ] `invoice.paid/payment_failed` をFirestoreへ反映
- [ ] イベントIDをFirestoreに保存し、重複処理を防止
- [ ] 失敗時にイベントを処理済み扱いしないことを確認
- [ ] Stripe再送時のE2Eテスト
- [ ] ログへStripe payloadや個人情報を過剰出力しないことを確認

### P1-3. セキュリティ

- [ ] LINE Login ID TokenのRS256/JWKS署名検証を実装
- [ ] state / nonceをインメモリからRedis等へ移行
- [ ] LINE Webhookと認証APIへレート制限を追加
- [ ] リクエストボディサイズ上限を追加
- [ ] TrustedHostMiddlewareを設定
- [ ] CORSを本番ドメインだけに制限
- [ ] Secret ManagerのStripeキーがテストキーであることを確認
- [ ] 本番切替時にテストキーと本番キーを混在させない

### P1-4. Firestore運用

- [ ] `users` / `rag_permissions` / `usage_daily` のバックアップ方針
- [ ] 古い `usage_daily` の削除ジョブ
- [ ] Firestore読み書き回数と費用の監視
- [ ] 5xx、Webhook失敗、RAG失敗、LINE送信失敗のアラート
- [ ] 構造化ログを導入し、ユーザーIDはマスクする

---

## 5. 推奨する作業順序（2026-08-17時点）

### ✅ Step 1: ローカル変更を安定化（完了）
- [x] Python 3.14環境でgoogle-cloud-firestoreをインストール
- [x] Firestoreのみでアプリを起動できるようPostgreSQL依存を分離
- [x] 回数制御をTransaction化する
- [x] Stripe解約時のユーザー状態を修正する
- [x] 自動テストを通す（unitテスト94件実行確認済み）

### 🔄 Step 2: Firestore版をステージング検証（次回セッション）
1. [ ] Cloud RunサービスアカウントへFirestoreアクセス権を付与・確認
2. [ ] mainブランチへマージしてCloud Runへデプロイ
3. [ ] Firestore初期データを投入（setup_firestore_data.py実行）
4. [ ] free 3件 / basic 100件 / pro 500件を確認
5. [ ] プラン別コーパス切替を確認
6. [ ] LINE実端末でfollow/message/unfollowを確認

### Step 3: Stripeテストモード

1. Basic / ProのテストPriceを作成
2. 固定 `test_user_id` でCheckoutを検証
3. Webhookのcreated/updated/deleted/paid/payment_failedを検証
4. FirestoreとStripeの整合性を確認
5. 解約後のユーザー状態を確認

### Step 4: 本番化判断

1. 固定テストユーザーを実認証へ置換
2. CIのテスト失敗許容を解除
3. ステージングで回帰テスト
4. Stripe本番キー・Price・Webhookを設定
5. 段階的に本番へ反映し、監視する

---

## 6. PostgreSQL / Cloud SQL移行（保留）

PostgreSQL関連コード、SQLAlchemyモデル、Alembicマイグレーションは将来の移行候補として保持する。ただし現在のリリース条件には含めない。

- [保留] Cloud SQL PostgreSQL 16インスタンス作成
- [保留] VPC Access Connector作成
- [保留] `DATABASE_URL` Secret登録
- [保留] Alembic本番マイグレーション
- [保留] FirestoreからPostgreSQLへのデータ移行
- [保留] PostgreSQL起動時の `init_db()` / `close_db()` 復帰

移行を再開する条件:

- Firestore費用またはクエリ制約が運用上の問題になった場合
- 複雑な集計・トランザクション・監査要件が必要になった場合
- ユーザー数と課金処理が増え、リレーショナル整合性が優先された場合

---

## 7. 完了条件

### Phase 2完了条件

- [ ] FirestoreのみでCloud Runが安定起動する
- [ ] followでユーザーが一意に作成される
- [ ] free/basic/proの回数上限が正しく機能する
- [ ] 同時リクエストでも上限を超えない
- [ ] プラン別コーパスが正しく選択される
- [ ] LINE実端末E2Eが成功する
- [ ] CIの自動テストが成功する

### Phase 3完了条件

- [ ] StripeテストモードでCheckoutが成功する
- [ ] Webhook全イベントがFirestoreへ反映される
- [ ] Webhookの重複・再送に耐えられる
- [ ] 支払い失敗と解約のLINE通知が届く
- [ ] 解約後のユーザー状態が仕様どおりになる
- [ ] Stripe / Firestore / LINEの整合性テストが成功する

### Phase 4完了条件

- [ ] サブスクAPIが実ユーザー認証を使用する
- [ ] Stripe本番キーとWebhookが設定される
- [ ] CIが失敗時にデプロイを停止する
- [ ] 監視・アラート・ロールバック手順が整備される
- [ ] 本番で少数ユーザーの段階運用が成功する

---

## 8. 検証コマンド

```bash
# 変更確認
git status --short
git diff --check

# Python 3.11環境で実行
pytest tests/unit/ -v
pytest tests/integration/ -v
pytest tests/e2e/ -v

# 構文確認
python -m compileall -q app scripts

# Firestore初期データ（対象プロジェクトを必ず確認してから実行）
python scripts/setup_firestore_data.py

# Cloud Run確認
gcloud run services describe chabot-service \
  --region=asia-northeast1 \
  --project=takahashi-451312
```

---

## 9. 更新ルール

- 実装しただけでは `[x]` にせず、必要に応じて「コード実装済み・E2E未確認」と分ける。
- 本番環境の状態とローカル作業ツリーの状態を混同しない。
- Stripeテストモードと本番モードを明確に分ける。
- Firestoreが現在の標準であり、Cloud SQLは保留として扱う。
- 回数上限は `app/core/pricing.py` の `DAILY_MESSAGE_LIMITS` を正とする。
- 仕様変更時はコード、初期データ、テスト、本ファイルを同時に更新する。
