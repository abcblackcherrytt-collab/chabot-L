# Chabot（LINE版）プロジェクト計画・進捗

> **更新日**: 2026-08-31（StripeテストPrice IDの本番反映）
> **対象GCP**: `takahashi-451312`
> **Cloud Runリージョン**: `asia-northeast1`
> **進捗表記**: `[x]` 完了 / `[ ]` 未完了 / `[保留]` 現在は実施しない
> **注意**: シークレットの実値は本ファイルへ記載しない。

---

## 0. 現在の結論

現在は、次の2つを分けて管理する。

1. **本番版**: LINE Bot + Vertex AI RAG + FirestoreのPhase 2版がCloud Runで稼働中
2. **次の検証**: 実LINEユーザーで回数制限・プラン別コーパス・follow/message/unfollowをE2E確認する

2026-08-31 現状確認:
- **実DB確認**: Firestore Nativeデータベース `chabotline`（`nam5`）の存在を確認
- **根本原因修正**: コードが誤って `(default)` を参照していたため、`FIRESTORE_DATABASE_ID=chabotline` を全実行経路へ追加
- **非同期修正**: 3つのFirestoreリポジトリを `AsyncClient` に統一し、Transaction呼び出しを修正
- **初期データ**: `chabotline/rag_permissions` にfree/basic/proの3件を投入し、`3/100/500` を読み戻し確認済み
- **テスト**: GitHub Actions品質ゲート103件、全unitは既知のPostgreSQL Refresh Token 9件を除く118件が成功。PostgreSQL認証のunit / integration / E2Eは現在の品質ゲート対象外
- **本番状態**: Cloud Run `chabot-service-00023-tqm`（`GIT_SHA=fd9ecd7`）へStripeテストPrice IDを含む構成をデプロイし、Ready・100%トラフィックを確認
- **本番最適化**: Firestore共有AsyncClient、ユーザー重複読取削減、RAG権限60秒キャッシュ、分類クライアント再利用、区間別レイテンシログを反映
- **本番認証**: 既存Firestoreユーザー再利用、Refresh Token保存・ローテーション、HttpOnly Cookie自動更新、S256 PKCE、LINE公式APIでのID Token検証、再フォロー時の再有効化、unfollow時の全セッション失効を反映
- **検証**: ローカル対象テスト118件、GitHub Actions run `33363660659` の品質ゲート103件に成功。公開 `/health` はHTTP 200、Basic / Pro登録URLは認証導線へHTTP 303、成功・キャンセル画面はHTTP 200、未認証APIはHTTP 401を確認。実LINEアカウントでのcallback・Checkout E2Eは未確認
- **Stripe登録導線（テストPrice本番反映済み）**: 現行Stripeテスト鍵（アカウント `acct_1TC6dqPHtxCsCwzY`）で、Basic商品・月額499円PriceとPro商品・月額999円Priceが有効・テストモード・継続課金であることを確認。Price IDをSecret Manager経由でCloud Runへ反映し、準備中HTTP 503から認証導線HTTP 303へ切り替わったことを確認。実LINE Checkout E2Eは未確認
- **対策本番反映済み**: Stripe WebhookのFirestore Transactionによる永続冪等性、失敗時HTTP 500、created/updated/deleted/paid/payment_failedの状態保存、公開Checkout/status APIの実ユーザー認証、Refresh Cookieの30日ローリング更新、1MiB Webhook上限を反映
- **Vertex AI**: 生成経路を廃止済み `vertexai.generative_models` からGoogle Gen AI SDKへ移行し、本番同等の `us-central1` と実RAGコーパスで分類・検索・回答生成に成功。ローカル個人用 `.env` の `GOOGLE_LOCATION=asia-northeast1` は古く、修正が必要
- **残存リスク**: Cloud Runは `min-instances=0` / `max-instances=3` で、scale-to-zero後の5件同時疎通では3件のコールドスタート中に2件が「利用可能インスタンスなし」HTTP 500となった。常時起動は継続費用が発生するため、明示承認まで有効化しない
- **次ステップ**:
  1. LINE実端末でfollow/message/unfollowとLINE Login復帰をE2E確認
  2. テストPrice IDを設定し、実Stripe Webhook署名・再送をE2E確認
  3. free 3件 / basic 100件 / pro 500件とプラン別コーパス切替を確認
  4. Cloud Runのコールドスタート対策（min instanceまたは起動処理軽量化）を費用と比較して決定

### 0.1 フェーズ一覧

| Phase | ゴール | データストア | Stripe | 状況 |
|---|---|---|---|---|
| Phase 1 | 友だち追加後にLINEでRAG回答 | なし | なし | **本番稼働中** |
| Phase 2 | ユーザー管理、日次回数制限、プラン別コーパス | **Firestore** | テストAPIのみ | **本番デプロイ済み・LINE E2E未確認** |
| Phase 2.5 | パフォーマンス最適化 | Firestore | - | **本番反映済み・実測比較待ち** |
| Phase 3 | Stripeテストモードで登録・更新・解約を検証 | Firestore | テストモード | **Price検証・本番反映済み・Checkout/Webhook E2E未実施** |
| Phase 4 | Stripe本番決済と運用監視 | Firestore | 本番モード | **未着手** |
| 将来 | PostgreSQL / Cloud SQLへの移行 | PostgreSQL | 継続 | **保留** |

### 0.2 確定した方針

- [x] 初期運用のデータストアはFirestoreとする。
- [x] FastAPI起動時のPostgreSQL接続確認を一時停止する。
- [保留] Cloud SQL、VPC Connector、Alembic本番適用は当面実施しない。
- [x] 既存のサブスクリプションPOST/status APIから固定 `test_user_id` を除去し、保存済みLINE Loginセッションによる実ユーザー認証を必須化する。
- [x] 1日あたりの回数上限は次の値に統一する。
  - free: 3件
  - basic: 100件
  - pro: 500件
- [保留] FirestoreとRAGの直接並列化は、回数上限超過時の不要なVertex AI課金とプラン別コーパス誤選択を招くため採用しない。
- [x] LINE Loginは、通常利用中はセッションを自動更新し、利用者へログイン画面を繰り返し表示しない。明示的ログアウト、LINE unfollow、またはセッションを更新できない場合のみ再ログインを求める。
- [x] Stripe Basic / Proの商品・Price IDとCloud RunのStripe API鍵を同じアカウント・テストモードへ統一し、商品・継続課金・金額・通貨をAPIで確認する。
- [ ] Stripe本番キーへの切替は、テストモードE2E完了後に判断する。

---

## 1. 本番稼働状況

### 1.1 2026-08-31確認結果と進捗

**本番環境**:
- [x] Cloud Runサービス `chabot-service` はReady。
- [x] PR #2 が正常にマージ完了（コミット: `a5359b3`）。
- [x] GitHub Actions run `32701466958` が品質ゲート・ビルド・Cloud Runデプロイまで成功。
- [x] 安全なRAG処理順を含むPhase 2をCloud Runリビジョン `chabot-service-00018-jrs`（`GIT_SHA=f031631`）へデプロイし、100%トラフィックを確認。
- [x] Cloud Runサービスアカウント `chabot-sa@takahashi-451312.iam.gserviceaccount.com` へFirestore権限付与完了。
- [x] 最新リビジョンのReady状態と公開`/health` HTTP 200を確認。
- [x] 認証永続化・性能改善をCloud Run `chabot-service-00019-dx5`（`GIT_SHA=2d14eff`）へデプロイし、100%トラフィックを確認。
- [x] 公開LINE Login開始endpointで303、Secure / HttpOnly短期Cookie、S256 PKCEを確認。
- [x] `chabot-service-00019-dx5` のデプロイ後ERRORログ0件を確認。
- [x] Stripe登録導線をCloud Run `chabot-service-00020-w2r`（`GIT_SHA=23aceae`）へデプロイし、GitHub Actions run `33150433985` の成功と100%トラフィックを確認。
- [x] Price ID未設定を維持したまま、公開Basic / Pro登録URLのHTTP 503準備中画面と、成功・キャンセル画面のHTTP 200を確認。
- [x] 認証・Stripe Webhook・Vertex AI SDK対策を `chabot-service-00022-2vv`（`GIT_SHA=e8315e1`）へデプロイし、GitHub Actions run `33347377056` の成功と100%トラフィックを確認。
- [x] 新リビジョンでRefresh Token 30日、free/paidコーパスSecret参照、Price ID未設定を確認。freeコーパス3ファイル・paidコーパス16ファイルの存在も読み取り確認。
- [x] 新リビジョンで `/health` 200、Basic/Pro 503、成功/キャンセル200、未認証status/POST Checkout 401を確認。意図した503リクエストログを除くアプリ内部ERRORログ0件。
- [x] StripeテストPrice IDを `chabot-service-00023-tqm`（`GIT_SHA=fd9ecd7`）へ反映し、GitHub Actions run `33363660659` の成功、100%トラフィック、Price Secret参照、`/health` 200、Basic/Pro 303、未認証status 401、ERRORログ0件を確認。
- [ ] `min-instances=0` のコールドスタート時に発生した一時的な「利用可能インスタンスなし」HTTP 500への対策を決定する（ウォーム後の全endpointは正常）。
- [x] Firestore `chabotline` へ初期データ3件を投入し、読み戻し確認（2026-08-24）。
- [ ] LINEの実端末で「友だち追加 → 質問 → RAG回答」を今回の更新後に再確認する。

**開発環境進捗（2026-08-17作業完了）**:
- [x] Python 3.14でgoogle-cloud-firestoreインストール完了
- [x] PostgreSQL依存分離完了（deps.py、webhooks/line.py、chat.py修正）
- [x] Firestore単独起動確認（/healthエンドポイント正常動作）
- [x] Firestore回数制御Transaction化実装（increment_with_limit_check）
- [x] Stripe解約フロー矛盾解消（Stripe解約→free継続、LINE unfollow→無効化）
- [x] Cloud Run環境変数Firestore版更新（.env.example、deploy.yml修正）
- [x] Cloud Runへ `JWT_REFRESH_TOKEN_EXPIRE_DAYS=30` とfree/paidコーパスSecret参照を反映
- [x] CI品質ゲート更新（Firestore / LINE / Vertex AI / Webhook処理順の62件がローカル・GitHub Actionsともに成功）
- [x] Secret Managerシークレット登録済み確認（google-corpus-id関連）

### 1.2 本番とローカルの差

- Phase 2実装（Firestore、日次回数制限、Stripe Checkout、Firestore連携Webhook）がmainブランチにマージ完了。
- Cloud RunはStripeテストPrice ID、認証・Webhook・Vertex AI SDK対策を含むリビジョン `chabot-service-00023-tqm`（`GIT_SHA=fd9ecd7`）が100%稼働中。
- Phase 2コード、Firestore修正、Phase 2.5性能改善、LINE Loginセッション永続化・認証強化、Stripe登録URL導線、Webhook信頼性対策はmainへコミット・本番反映済み。
- `phase2/local-mock-plan` ブランチはマージ後削除済み。
- 現在はmainブランチで作業進行中。

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
- [x] Firestore `chabotline` へ初期データが正しく投入されていることを確認
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
- [x] LINE登録URL → セッション確認 → LINE Login復帰 → Stripe Checkoutリダイレクト導線（本番反映済み、Price ID未設定の準備中画面まで公開確認済み）
- [x] Checkout成功・キャンセル後の案内ページ（本番反映・HTTP 200確認済み）
- [x] `customer.subscription.updated` のFirestore状態更新
- [x] `invoice.paid` のFirestore状態・請求期間更新
- [x] Webhook冪等性をインメモリからFirestore Transactionへ移行
- [x] Stripeテスト商品・Price IDを現行API鍵で取得確認（Basic商品 `prod_VAjwEIYvRCJ5GI` / Price `price_1UAOSwPHtxCsCwzYT0x5dBz7`、月額499円。Pro商品 `prod_VAjxOn83it8eaA` / Price `price_1UAOT8PHtxCsCwzY1tU862Dy`、月額999円。いずれもJPY・有効・テストモード）
- [x] 整合性確認済みのPrice IDをSecret Managerへ登録し、deploy.ymlからCloud Runへ反映（本番リビジョンのSecret参照とBasic/Pro HTTP 303を確認済み）
- [ ] Stripeテストモードで登録・更新・支払い失敗・解約をE2E確認

### 2.4 サブスクリプションAPIの扱い

旧テストAPIも本番公開を前提に認証必須へ統一した。

- [x] Checkout作成とstatus取得から固定の `test_user_id` を除去
- [x] 保存済みRefresh Cookieを検証・ローテーションし、実ユーザーIDだけをサービスへ渡す
- [x] Stripe公式 `checkout.stripe.com` 以外のCheckout URLを拒否
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

ローカル環境はPython 3.14で、`google-cloud-firestore` を含む必要パッケージをvenvへ導入済み。

- [x] Python 3.14でのSQLAlchemy/FastAPI互換性を確認
- [x] `google-cloud-firestore` をvenvへインストール
- [x] 現行品質ゲート対象の自動テスト103件に成功。全unitは既知のPostgreSQL Refresh Token 9件を除く118件が成功
- [保留] PostgreSQL認証のunit / integration / E2Eテスト（現在のFirestore運用とCI品質ゲートの対象外）
- [x] Firestore非同期I/O・Transaction・障害時案内の自動テストを追加
- [x] 2026-08-24のテスト結果を本ファイルへ記録

### P0-2. CIを正式な品質ゲートにする

- [ ] CIのPythonバージョン方針を確定（deploy.ymlは3.11、ローカルは3.14）
- [x] Firestore-only app startupテストをCIに追加
- [x] テスト環境変数にDATABASE_BACKEND=firestoreを追加
- [x] CI必須ゲートをFirestore / LINE / Vertex AIに限定し、PostgreSQL認証テストと `continue-on-error` ステップを除外
- [x] Vertex AIテストを現行Google Gen AI SDK、生成プロンプト、Markdown除去仕様へ追従し、12件成功
- [x] デプロイ後smoke testへBasic / Pro準備中画面または認証リダイレクトと成功・キャンセル画面を追加
- [x] checkout / setup-python / Google認証 / Buildx / github-scriptをNode.js 24対応版へ更新
- [ ] FirestoreエミュレーターまたはモックをCIへ導入（将来対応）

### P0-3. Cloud Run環境変数をFirestore版へ更新

Firestore版に必要な設定をデプロイ設定へ追加し、本番リビジョンへの反映を確認した。

- [x] `DATABASE_BACKEND=firestore` (.env.exampleとdeploy.ymlに追加済み)
- [x] `FIRESTORE_PROJECT_ID=takahashi-451312` (.env.example更新済み)
- [x] `FIRESTORE_DATABASE_ID=chabotline` を設定・deploy.yml・全Firestoreクライアントへ追加
- [x] free用コーパスIDを `.env.example` とFirestore `rag_permissions` に設定し、実ドキュメントに値があることを読み取り確認
- [x] deploy.ymlへ直接 `GOOGLE_CORPUS_ID` のSecret参照を追加し、新リビジョンで反映確認して設定ドリフトを解消
- [x] 有料用 `GOOGLE_CORPUS_ID_PLAN1=1495705249682292736` (.env.example更新済み)
- [x] GitHub Actionsのdeploy.ymlにFirestore用環境変数を追加
- [x] Secret Managerにシークレット登録済み（実在名を2026-08-31に再確認）:
  - `GOOGLE_CORPUS_ID` ✅
  - `GOOGLE_CORPUS_ID_PLAN1` ✅
- [x] Cloud RunサービスアカウントへFirestoreアクセス権を付与・確認
  - サービスアカウント: `chabot-sa@takahashi-451312.iam.gserviceaccount.com`
  - 権限: `roles/datastore.user` 付与済み ✅

### P0-4. Firestore回数制御を安全にする

旧実装は「現在値を読み取り、その後setする」方式だったため、2026-08-24に非同期Transactionへ統一した。

- [x] Firestore Transactionで「上限確認 + 加算」を原子的に実行
- [x] Transactionの採用を決定（`increment_with_limit_check`実装）
- [x] 同期Clientと非同期Transactionの混在を解消し、`AsyncClient` に統一
- [x] Firestore障害と上限到達を区別し、障害時は一時エラーを案内
- [x] 日付境界をUTCではなくAsia/Tokyo基準に変更
- [x] Transaction内の上限到達・加算・例外テストを追加（実Firestore同時実行E2Eは未確認）

### P0-5. Stripe解約フローの矛盾を解消

現在の `subscription.deleted` は、ユーザーをfreeプランへ戻した直後に `is_active=False` にしている。このままではfreeプランとして利用できない。

- [x] 「有料解約後もfreeで継続」か「アカウント全体を停止」かを決定
- [x] 推奨: Stripe解約はfreeへ戻すだけにし、LINE unfollowや明示的退会時のみ無効化
- [x] Stripe解約: freeプラン戻しのみ実装（ユーザーは無効化しない）
- [x] LINE unfollow: アカウント全体を停止を実装
- [x] Firestore更新、LINE通知、テストを統合

### P0-6. Firestore経路からPostgreSQL依存を分離

起動時の `init_db()` / `close_db()` は停止済みだが、LINE Webhookや認証DependsにはSQLAlchemyセッション生成が残っている。

- [x] Firestore使用時は `async_session_maker` を生成・使用しない構造に変更
- [x] Firestore用とPostgreSQL用の依存性注入を明確に分離
- [x] Firestoreだけでアプリを起動できるテストを実施
- [ ] PostgreSQL専用auth/chatエンドポイントを維持するか、一時停止するか決定

### P0-7. パフォーマンス最適化（安全性再設計）

FirestoreアクセスとRAG処理の直接並列化案は採用しない。ユーザー情報・プラン・回数上限が確定する前にRAGを開始すると、次の回帰が発生するためである。

- 上限超過ユーザーでもVertex AIを実行し、不要なコストが発生する
- basic/proユーザーへfree用コーパスで回答する可能性がある
- 既存の入力サニタイズとエラー応答経路を迂回する

- [x] 安全な処理順へ修正（ユーザー・プラン・上限確認 → RAG → LINE返信）
- [x] 上限到達時にRAGを呼ばない回帰テストを追加
- [x] 確定済み `corpus_id` / `model_name` / `user_id` をRAGへ渡す回帰テストを追加
- [x] `RAGService.query()` のプラン別引数不整合を修正し、実サービス契約テストを追加（本番反映済み）
- [x] Firestore `AsyncClient` をプロセス内で共有し、起動・終了時にライフサイクル管理（本番反映済み）
- [x] LINEメッセージ処理で取得済みユーザーデータを再利用し、同一ユーザーの直列再読込2回を削減
- [x] RAG権限をプラン別に60秒キャッシュし、更新・削除時に無効化
- [x] Vertex AI分類クライアントを遅延生成後に再利用し、ADC・クライアント生成の繰り返しを削減
- [x] Vertex AI生成クライアントも遅延生成・再利用し、Cloud Run起動時のグローバルSDK初期化を除去
- [x] ユーザー検索・権限・使用回数・分類・RAG生成の区間別レイテンシログを追加
- [ ] Cloud Runへ反映後、実測レイテンシとエラー率を比較して次の最適化を判断

### P0-8. Cloud Runのコールドスタート耐性

2026-08-31のscale-to-zero状態への5件同時疎通では、`max-instances=3` の3インスタンスが起動する間に2件が「利用可能インスタンスなし」でHTTP 500となった。起動後は全endpointが期待どおり応答した。

- [ ] `min-instances=1` の費用と、RAG / LINE初期化の遅延・遅延初期化による起動軽量化を比較する
- [ ] `max-instances=3` の妥当性とGCP上限を確認する
- [ ] デプロイ後に直列疎通だけでなく、scale-to-zeroからの小規模burst testを追加する
- [ ] LINE Webhookの再送を前提に、コールドスタート時のユーザー影響を実端末で確認する

常時起動は継続費用が発生するため、今回のデプロイでは `min-instances=0` を維持した。SDK・Firestoreクライアントを遅延/共有化する無償範囲の軽量化は反映済み。

### P0-9. Vertex AIモデル・SDKの移行

本番とFirestore `rag_permissions` は `gemini-2.5-flash` を使用している。Google Cloud公式ライフサイクルでは2026-10-16が退役日で、`Gemini 3.5 Flash-Lite` または `Gemini 3.1 Flash-Lite` が移行候補とされている。また現行テストでは `vertexai.rag` の非推奨警告が出ている。

- [ ] 移行候補モデルをRAG精度・応答時間・費用で比較する
- [ ] 選定モデルへコード既定値とFirestoreのfree/basic/pro設定を同時更新し、回帰テストと実質問評価を行う
- [ ] 2026-10-16より十分前にCloud Runへ反映し、旧モデル依存が残っていないことを確認する
- [x] 回答生成を `vertexai.generative_models` / `vertexai.rag` からGoogle Gen AI SDKの `VertexRagStore` へ移行し、実コーパスで応答確認
- [x] 分類モデルの旧 `gemini-1.5-flash` 既定値を現行 `gemini-2.5-flash` へ統一
- [ ] RAGコーパス管理スクリプトの `vertexai.rag` をAgent Platformクライアントへ移行する

補足: ローカル個人用 `.env` の `GOOGLE_LOCATION` は古い `asia-northeast1` のため、ローカル実API検証では `us-central1` を明示した。本番Secretは `us-central1` であることを確認済み。
`gemini-3.1-flash-lite` は現行RAGリージョンの実API確認で404となったため切り替えず、互換モデル確定までは `gemini-2.5-flash` を維持する。

---

## 4. 本番決済前の対策（P1）

### P1-1. 認証・アカウント連携

- [x] LINE Login callbackでFirestoreユーザーを検索・作成（コード実装・ローカルテスト済み、本番E2E未確認）
- [x] 仮UUIDの都度発行を廃止し、既存ユーザーIDを再利用（コード実装・ローカルテスト済み、本番E2E未確認）
- [x] LINE Login Refresh TokenをFirestoreへ保存し、更新時にローテーション（コード実装・ローカルテスト済み、本番E2E未確認）
- [x] Refresh TokenをHttpOnly / Secure Cookieで保持し、CookieによるAccess Token自動更新APIを実装（本番反映済み・実LINE E2E未確認）
- [x] LINE LoginのS256 PKCEを正しく実装し、Refresh TokenをJSONへ露出しない（本番開始endpoint確認済み）
- [x] 再フォロー時に既存Firestoreユーザーを再有効化し、unfollow時に全Refresh Tokenを失効（本番反映済み・実LINE E2E未確認）
- [x] Stripe登録リンクでは保存済みRefresh Tokenを自動更新し、未認証時だけLINE Login後に元のプラン登録URLへ戻す（Price IDを本番反映し、未認証HTTP 303を確認済み・実LINE復帰E2Eは未確認）
- [x] Refresh Token / Cookieを7日から30日のローリング期間へ延長し、登録URL・Checkout/status APIアクセス時に更新する
- [ ] ログアウト・LINE unfollow時にCookie削除と全Refresh Token失効を行い、通常利用時に再ログインが表示されないことをE2E確認
- [ ] LINE ID → Firestore user ID → Stripe customer IDの一意性を検証
- [x] 公開POST `/subscription/checkout/create` とGET `/subscription/status` の固定 `test_user_id` を実認証へ置換

### P1-2. Stripe Webhookの信頼性

- [ ] Webhook署名検証をテストモードで実確認
- [x] ビジネス処理失敗時にHTTP 500を返し、Stripeが再送できるレスポンスへ修正
- [x] `subscription.created/updated/deleted` をすべてFirestoreへ反映
- [x] `invoice.paid/payment_failed` をFirestoreへ反映
- [x] イベントIDをFirestore Transactionで確保し、Cloud Runの複数インスタンス・再起動をまたぐ重複処理を防止
- [x] ハンドラ例外時はfailed状態へ戻し、5分超過したprocessingイベントも再確保可能にする
- [ ] LINE通知失敗をイベント全体の再試行対象にするか、通知outboxへ分離するか決定する
- [ ] Stripe再送時のE2Eテスト
- [ ] ログへStripe payloadや個人情報を過剰出力しないことを確認

### P1-3. セキュリティ

- [x] LINE Login ID TokenをLINE公式検証APIで署名・audience・nonce検証（本番反映済み・実LINE callback E2E未確認）
- [x] state / nonceをインメモリからHttpOnly / Secure短期Cookieへ移行し、Cloud Runインスタンス間の不整合を解消（本番開始endpoint確認済み）
- [ ] LINE Webhookと認証APIへレート制限を追加
- [x] Stripe Webhookへ1MiBのリクエストボディサイズ上限を追加
- [ ] TrustedHostMiddlewareを設定
- [ ] CORSを本番ドメインだけに制限
- [x] Secret ManagerのStripeキーがテストキーであることを値を表示せず確認（2026-08-31）
- [ ] Stripeの商品・Price・Secret Key・Publishable Key・Webhook Secretが同じアカウントおよびSandboxに属することを確認
- [ ] 本番切替時にテストキーと本番キーを混在させない

### P1-4. Firestore運用

- [ ] `users` / `rag_permissions` / `usage_daily` のバックアップ方針
- [ ] 古い `usage_daily` の削除ジョブ
- [ ] Firestore読み書き回数と費用の監視
- [ ] 5xx、Webhook失敗、RAG失敗、LINE送信失敗のアラート
- [ ] 構造化ログを導入し、ユーザーIDはマスクする

---

## 5. 推奨する作業順序（2026-08-24時点）

### ✅ Step 1: ローカル変更を安定化（完了）
- [x] Python 3.14環境でgoogle-cloud-firestoreをインストール
- [x] Firestoreのみでアプリを起動できるようPostgreSQL依存を分離
- [x] 回数制御をTransaction化する
- [x] Stripe解約時のユーザー状態を修正する
- [x] Firestore/LINE関連の自動テストを通す（28件成功）

### 🔄 Step 2: Firestore版を本番E2E検証（進行中）
1. [x] Cloud RunサービスアカウントへFirestoreアクセス権を付与・確認（2026-08-17 14:37完了）
2. [x] 安全なRAG処理順を含むPhase 2をCloud Runへデプロイ（`chabot-service-00018-jrs`、`GIT_SHA=f031631`、`/health` HTTP 200、デプロイ後ERRORログ0件）
3. [x] インポートエラー修正（rag_permission.py作成）
4. [x] 現行CI品質ゲートのローカルテスト成功（62件）。PostgreSQL Refresh Tokenを除くunitも91件成功
5. [x] Firestore `chabotline` へ初期データを投入し、3プランを読み戻し確認
6. [ ] free 3件 / basic 100件 / pro 500件を確認
7. [ ] プラン別コーパス切替を確認
8. [ ] LINE実端末でfollow/message/unfollowを確認
9. [x] free/paid両RAGコーパスの存在・ファイル件数を読み取り確認

### Step 2.5: パフォーマンス最適化（本番反映済み・実測比較待ち）

- [x] 直接並列化案の正確性・課金上の問題を確認
- [x] 安全な逐次処理と回帰テストへ戻す
- [x] 共有Firestoreクライアント、重複読取削減、RAG権限キャッシュ、分類クライアント再利用をローカル実装
- [x] 区間別レイテンシログと回帰テストを追加し、CI品質ゲート64件・unit 97件に成功
- [x] 認証永続化とともにCloud Run `chabot-service-00019-dx5` へ反映し、Ready・HTTP 200・ERRORログ0件を確認
- [ ] 本番デプロイ後に実測レイテンシを取得し、Cloud Run設定を含む次の最適化を判断
- [ ] scale-to-zeroからの同時アクセスで確認した一時HTTP 500について、min instance・起動軽量化・最大インスタンス数を比較して対策する

### Step 3: Stripeテストモード

1. [x] Webhookの失敗時非2xx、Firestore冪等性、updated / paidの状態更新を実装・本番反映
2. [x] 固定 `test_user_id` の公開APIを実認証へ置換・本番401確認
3. [x] Basic / Proの商品・Price IDと現行Stripe API鍵のアカウント・テストモードを統一
4. [x] 同じAPI鍵で商品・継続課金Priceを取得確認し、Secret Manager経由でCloud Runへ反映
5. 実LINE認証ユーザーでCheckoutとログイン復帰を検証
6. Webhookのcreated/updated/deleted/paid/payment_failedと再送を検証
7. FirestoreとStripeの整合性を確認
8. 解約後のユーザー状態を確認

### Step 4: 本番化判断

1. [x] 固定テストユーザーを実認証へ置換
2. [x] CIの必須品質ゲートでテスト失敗を許容しない
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

- [x] FirestoreのみでCloud Runが起動し、Ready・`/health` HTTP 200を確認
- [ ] followでユーザーが一意に作成される
- [ ] free/basic/proの回数上限が正しく機能する
- [ ] 同時リクエストでも上限を超えない
- [ ] プラン別コーパスが正しく選択される
- [ ] LINE実端末E2Eが成功する
- [x] CIの自動テストが成功する

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

# CI品質ゲート（Python 3.11）
pytest \
  tests/unit/test_auth_session.py \
  tests/unit/test_subscription_checkout.py \
  tests/unit/test_core/test_line_id_token.py \
  tests/unit/test_clients/test_line.py \
  tests/unit/test_clients/test_vertex_ai.py \
  tests/unit/test_repositories/test_firestore_repositories.py \
  tests/unit/test_services/test_line_webhook_pipeline.py \
  tests/unit/test_services/test_line_service.py \
  tests/unit/test_services/test_rag_service.py \
  tests/unit/test_services/test_firestore_auth_service.py \
  -v --tb=short

# 現行unit全体（保留中のPostgreSQL Refresh Tokenを除外）
pytest tests/unit/ \
  --ignore=tests/unit/test_repositories/test_refresh_token.py \
  -v --tb=short

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
