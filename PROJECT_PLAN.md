# Chabot（LINE版）プロジェクト計画・進捗

> **更新日**: 2026-09-21（Jevによる前段質問分類を実装、実アカウント接続は未設定）
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
- **テスト**: ローカル品質ゲート111件、全unitは既知のPostgreSQL Refresh Token 9件を除く126件が成功。PostgreSQL認証のunit / integration / E2Eは現在の品質ゲート対象外
- **本番状態**: Cloud Run `chabot-service-00028-cvl`（`GIT_SHA=a89ac52`）へプラン別生成プロンプト、free用Secretフォールバック、LINE Login callback修正をデプロイし、Ready・100%トラフィックを確認
- **本番最適化**: Firestore共有AsyncClient、ユーザー重複読取削減、RAG権限60秒キャッシュ、分類クライアント再利用、区間別レイテンシログを反映
- **本番認証**: 既存Firestoreユーザー再利用、Refresh Token保存・ローテーション、HttpOnly Cookie自動更新、S256 PKCE、LINE公式APIでのID Token検証、再フォロー時の再有効化、unfollow時の全セッション失効を反映
- **検証**: ローカル品質ゲート111件・対象unit 126件、GitHub Actions run `33367481704` に成功。公開 `/health` はHTTP 200、Basic登録URLは認証導線へHTTP 303、最新リビジョンのERRORログ0件。LINE Login callbackとfree質問の実端末再確認が必要
- **Stripe登録導線（テストPrice本番反映済み）**: 現行Stripeテスト鍵（アカウント `acct_1TC6dqPHtxCsCwzY`）で、Basic商品・月額499円PriceとPro商品・月額999円Priceが有効・テストモード・継続課金であることを確認。Price IDをSecret Manager経由でCloud Runへ反映し、準備中HTTP 503から認証導線HTTP 303へ切り替わったことを確認。実LINE Checkout E2Eは未確認
- **Stripe導線診断（2026-09-21）**: 「登録URLをクリックしてもStripeへ飛ばない」報告を受け調査。本番ではURL→LINE Login開始（303）→LINE authorize URLへの遷移と環境変数・Secret参照を確認。直近30日の本番ログに実端末からの該当リクエストは記録されておらず（8/31 smoke testと調査用リクエストのみ）、クリックが本番へ到達していない可能性が残る。認証後のStripe Checkout作成失敗時に生のHTTP 500となっていた問題と、callback復帰先Cookie喪失時にAccessToken入りJSONを画面表示していた問題を修正（品質ゲート126件成功）。実端末での再クリックとログ確認が残課題
- **2026-09-21本番反映**: 上記Checkout導線修正に加え、9/4ローカル実装のJWT関連対策（JWTからemail/LINE user ID除去、予約クレーム・PII追加クレーム拒否、Access Token有効期限の設定上限15分、refresh時のline_user_idクレーム廃止とユーザー文書参照化）をCloud Run `chabot-service-00029-fbh`（`GIT_SHA=ca780e8`）へデプロイ。GitHub Actions run `35591533319` 成功、/health 200・Basic/Pro 303・success/cancel 200を確認
- **CI失敗対応（2026-09-21）**: 初回push `dd1f9e5`で9/4実装のテスト（test_auth_session.py）のみをコミットし実装（app/core/security.py・app/core/config.py・app/services/firestore_auth_service.py）が漏れ、品質ゲート3件が失敗。ローカルでPython 3.11・最新依存関係のコミットツリー再現により特定し、実装と追従テストを`47d05fa`〜`ca780e8`で順に追加して解消
- **実端末報告（2026-09-21）**: ユーザーは「LINEメッセージ内の登録URLをクリックしたらエラー画面・文字列が出た」と回答。直近30日の本番ログに該当リクエストは確認できず、8/31以前のcallback HTTP 500（bcrypt 72バイト制約、当時修正済み）または本日修正済み経路の可能性。新リビジョンでの再試行と、再発時の画面の正確な内容確認が残課題
- **既存友だち対応（本番反映済み・実端末E2E待ち）**: Phase 2導入前から友だちでFirestoreユーザーがない場合、最初のテキストメッセージでLINEプロフィールと署名検証済みuserIdからfreeアカウントを自動作成し、そのメッセージをfree枠として継続処理する。プロフィール取得失敗時もuserIdから登録し、同一LINE IDには安定したドキュメントIDを使って重複作成を抑止する
- **プラン別生成指示（本番反映済み・実端末E2E待ち）**: 共通のです・ます調、辛口1か所、回答＋要約、原則500字以内を維持し、freeはfreeコーパスを根拠としてユーザーの質問へ直接答える「結論→基礎的根拠→確認点」、basic/proはpaidコーパスの複数資料を統合する「結論→根拠・機序→評価・介入への適用→限界」に分岐する。freeで取得情報が不足する場合は一般知識・推測で補完せず、不足範囲を明示する
- **freeコーパス既定値（本番反映済み）**: 通常はFirestoreのfree権限設定からコーパスIDを渡す。ID省略時も有料用へ誤接続しないよう、Vertex AIクライアントの既定値をSecret `GOOGLE_CORPUS_ID`（free用）へ修正した
- **LINE Login callback障害（本番修正済み・実端末再確認待ち）**: 実端末callbackで、長いRefresh Tokenをpasslib/bcryptへ渡した際の72バイト制限によりHTTP 500を確認。高エントロピーのRefresh Token保存をSHA-256ダイジェスト＋定時間比較へ変更し、旧bcryptハッシュの検証互換を維持した
- **対策本番反映済み**: Stripe WebhookのFirestore Transactionによる永続冪等性、失敗時HTTP 500、created/updated/deleted/paid/payment_failedの状態保存、公開Checkout/status APIの実ユーザー認証、Refresh Cookieの30日ローリング更新、1MiB Webhook上限を反映
- **Vertex AI**: 生成経路を廃止済み `vertexai.generative_models` からGoogle Gen AI SDKへ移行し、本番同等の `us-central1` と実RAGコーパスで分類・検索・回答生成に成功。ローカル個人用 `.env` の `GOOGLE_LOCATION=asia-northeast1` は古く、修正が必要
- **回答生成モデル移行（2026-09-21本番反映）**: `gemini-2.5-flash`（2026-10-16退役予定）から `gemini-3.5-flash-lite` へ移行。Gemini 3系は `us-central1` ではモデル一覧に表示されても生成APIが404となるため、生成クライアントのみ `global`（新設定 `GOOGLE_GENERATION_LOCATION`・既定値global）へ分離し、RAGコーパス参照とFirestore設定は `us-central1` を維持。実APIで grounded contexts 2件・confidence 0.85・約5〜6秒を確認し、Firestore free/basic/pro の model_name を更新・読み戻し確認済み。精度・費用の定量比較と実LINE端末E2Eは残課題
- **Jev前段分類（本番反映済み・実端末E2E待ち）**: GeminiにJSONを生成させる分類経路を、TypeSafe Jev（jev-1.13.0）の1回の型付き判定へ置換。質問主目的はChoice（知識・評価・所見解釈・介入・術後・根拠・other）、回答観点は可動域・筋力など7項目の独立Noul確率として評価し、閾値（主目的confidence 0.45、観点確率0.60）を超える上位3項目だけを回答生成へ渡す。Secret Manager `JEV_API_KEY`（version 1有効）を作成し、deploy.ymlへSecret参照を追加。実API検証では代表臨床質問7問の主目的が全問正答（confidence 0.77〜1.0）、「疼痛と筋力低下の評価」問で疼痛0.61が旧閾値0.65直下だったため観点閾値を0.60へ調整した。コミット `1c1dd20`（run `35593479479` 成功）として導入し、Gemini 3.5 Flash-Lite移行 `3e475e6` を含む現行リビジョン `chabot-service-00031-v5z`（run `35593692368` 成功、100%トラフィック、`JEV_API_KEY` Secret参照・`/health` 200・ERRORログ0件確認済み）で稼働中。キー未設定/障害時は分類なしでRAG回答を継続する設計。LINE実端末での質問→分類→回答導線のE2E確認が残課題
- **残存リスク**: Cloud Runは `min-instances=0` / `max-instances=3` で、scale-to-zero後の5件同時疎通では3件のコールドスタート中に2件が「利用可能インスタンスなし」HTTP 500となった。常時起動は継続費用が発生するため、明示承認まで有効化しない
- **次ステップ**:
  1. LINE実端末でfollow/message/unfollowとLINE Login復帰をE2E確認
  2. 実Stripe Webhook署名・再送をE2E確認
  3. free 3件 / basic 100件 / pro 500件、コーパス切替、回答構成の差を確認
  4. Cloud Runのコールドスタート対策（min instanceまたは起動処理軽量化）を費用と比較して決定
  5. 管理UIは別ASGIサービスとしてローカル開発を進める。IAP・IAM・本番公開は別作業として保留する

### 0.1 フェーズ一覧

| Phase | ゴール | データストア | Stripe | 状況 |
|---|---|---|---|---|
| Phase 1 | 友だち追加後にLINEでRAG回答 | なし | なし | **本番稼働中** |
| Phase 2 | ユーザー管理、日次回数制限、プラン別コーパス | **Firestore** | テストAPIのみ | **本番デプロイ済み・LINE E2E未確認** |
| Phase 2.5 | パフォーマンス最適化 | Firestore | - | **本番反映済み・実測比較待ち** |
| Phase 2.7 | 管理UI、動的プロンプト・上限設定、1回限り登録URL、ユーザー参照 | Firestore | - | **安全基盤をローカル実装中・本番未反映** |
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
- [ ] 管理UI導入時は、公開済みFirestore設定を回数上限の運用上の正とし、`app/core/pricing.py` の `3/100/500` は設定欠損・不正時の安全な既定値へ役割を変更する。
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
- [x] 既存友だちの初回トークfree自動登録を `chabot-service-00024-fb2`（`GIT_SHA=afa7960`）へ反映し、GitHub Actions run `33364734465` の品質ゲート107件成功、100%トラフィック、`/health` 200、ERRORログ0件を確認。
- [x] プラン別生成プロンプトとfreeコーパス根拠の回答方針を `chabot-service-00026-r62`（`GIT_SHA=548619f`）へ反映し、GitHub Actions run `33366459914` の成功、100%トラフィック、`/health` 200、Basic 303、ERRORログ0件を確認。
- [x] free用Secret `GOOGLE_CORPUS_ID` への既定フォールバックと長いRefresh Tokenのcallback修正を `chabot-service-00028-cvl`（`GIT_SHA=a89ac52`）へ反映し、GitHub Actions run `33367481704` の品質ゲート111件成功、100%トラフィック、`/health` 200、Basic 303、デプロイ後ERRORログ0件を確認。
- [x] Checkout導線の耐障害性修正（Stripeエラー時503案内、callback復帰先喪失時の再案内HTML）とJWT PII対策を `chabot-service-00029-fbh`（`GIT_SHA=ca780e8`）へ反映し、GitHub Actions run `35591533319` の成功、100%トラフィック、`/health` 200、Basic/Pro 303、success/cancel 200を確認（2026-09-21）。
- [x] Jev前段分類と回答生成モデルgemini-3.5-flash-lite移行を `chabot-service-00030-fxh` / `chabot-service-00031-v5z`（`GIT_SHA=3e475e6`）へ反映し、GitHub Actions run `35593479479` / `35593692368` の成功、100%トラフィック、`/health` 200を確認（2026-09-21）。
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
- Cloud Runはプラン別生成プロンプト、free用Secretフォールバック、長いRefresh Tokenのcallback修正、既存友だちの初回トークfree自動登録、StripeテストPrice ID、認証・Webhook・Vertex AI SDK対策を含むリビジョン `chabot-service-00028-cvl`（`GIT_SHA=a89ac52`）が100%稼働中。
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
- [x] Phase 2導入前からの既存友だちを最初のトークでfreeアカウントとして遅延作成（本番反映済み・実端末E2E未確認）
- [x] `free/basic/pro` のプラン取得
- [x] プラン別コーパス切替
- [x] 共通の文体・文字数を維持したプラン別生成プロンプト（freeはfreeコーパスを根拠に質問へ直接回答、basic/proはpaidコーパスを統合）を本番反映（実端末E2E未確認）
- [x] コーパスID省略時の既定値をfree用Secret `GOOGLE_CORPUS_ID` に修正し、有料用コーパスへの誤フォールバックを防止（本番反映済み）
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
- [x] リッチメニュー用のbasic/proプラン選択画面 /api/v1/subscription/select を追加。各カードから従来のCheckout導線（/checkout/basic・/checkout/pro）へ遷移する（2026-09-22実装、テスト追加、本番確認はデプロイ後）
- [x] Checkout成功・キャンセル後の案内ページ（本番反映・HTTP 200確認済み）
- [x] `customer.subscription.updated` のFirestore状態更新
- [x] `invoice.paid` のFirestore状態・請求期間更新
- [x] Webhook冪等性をインメモリからFirestore Transactionへ移行
- [x] Stripeテスト商品・Price IDを現行API鍵で取得確認（Basic商品 `prod_VAjwEIYvRCJ5GI` / Price `price_1UAOSwPHtxCsCwzYT0x5dBz7`、月額499円。Pro商品 `prod_VAjxOn83it8eaA` / Price `price_1UAOT8PHtxCsCwzY1tU862Dy`、月額999円。いずれもJPY・有効・テストモード）
- [x] 整合性確認済みのPrice IDをSecret Managerへ登録し、deploy.ymlからCloud Runへ反映（本番リビジョンのSecret参照とBasic/Pro HTTP 303を確認済み）
- [x] Checkout開始endpointでStripe APIエラー発生時に生のHTTP 500ではなく準備中案内画面（HTTP 503）を返すよう修正（2026-09-21、品質ゲート126件成功・本番反映はデプロイ後に確認）
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

### 2.6 Phase 2.7: Cloud Run管理UI（安全基盤をローカル実装中・本番未反映）

**2026-09-21: 機能設計を docs/admin-console-design.md に確定した（設計のみ・実装未着手）。** 対象は、クーポン発行（plan_grant / bonus_messages、Crockford Base32コード・SHA-256保存・Bot側「クーポン CODE」引き換れ）、無料アカウント作成（1回限り登録URL + LINE user ID直指定）、free/basic/pro日次回数設定（下書き→反映→ロールバック、60秒キャッシュ反映）、登録ユーザー一覧・プラン変更（plan_override、Stripe競合警告）。追加設計として監査ログ閲覧・日次ダッシュボード・設定ロールバック・引き換れレート制限を含む。管理サービスは chabot-admin として別Cloud Run URL（IAP + HTTPS LB、--no-allow-unauthenticated）とし、デプロイは専用workflowへ分離する。プラン解決優先度は Stripe契約 > plan_override > free と定義。未決定事項は設計書10節（Stripeプロモーションコード連携可否、bonus_messagesの初回含否、管理者候補、最小IAM）。

**2026-09-22: 管理コンソール設計を更新した（ユーザー指示）。** ダッシュボードは作らず、個別の集計・管理項目の中にアクティブユーザー数とメッセージ数を提示する方式へ変更。全ユーザーの質問・回答ペアを conversations コレクションへ保管する設計を追加（回答成功後に非同期保存・保存失敗で回答を止めない、患者情報検知フラグ、初期版は本文非表示・件数メタデータのみ、保持期間は未決定）。LINE側の要望受付（クイックリプライ「要望を送る」→次の1通を要望として記録、TTL10分・1日5通制限）と、管理画面での要望一覧・対応ステータス管理を追加。これに伴いFirestore新規コレクションへ conversations / feedback / feedback_pending を追加し、集計は admin_daily_stats を流用する。

#### 個人情報公開リスクレビュー（2026-09-04）

結論: 現状の計画のまま管理UIを本番公開してはならない。以下のP0対策と否定系E2Eが完了するまで `chabot-admin` は未デプロイまたはトラフィック0とする。

- **[Critical] 公開デプロイの誤流用**: 現行 `chabot-service` はLINE Webhook等のため `allUsers` Invoker・ingress `all` で稼働し、deploy workflowにも `--allow-unauthenticated` がある。管理サービスは完全に別workflowとし、`--no-allow-unauthenticated` + IAPを明示する。デプロイ後に未認証HTTP拒否、IAP有効、IAMに `allUsers` / `allAuthenticatedUsers` がないことを機械確認し、満たさなければ失敗させる。
- **[Critical] 公開Botへの管理ルート混入**: `app.server` へ管理routerを登録しない。公開claim用endpointと管理endpointを別router・別ASGI entrypointにし、BotのOpenAPI/ルート一覧に `/admin` とユーザー一覧APIが存在しないことをCIで固定する。
- **[Critical] Firestore権限境界の誤認**: Python server clientはFirestore Security Rulesを迂回してIAMで動作する。`roles/datastore.user` はデータベース内データへの広いread/write権限で、コレクション単位の制限とはみなさない。管理専用サービスアカウントと必要操作だけのcustom roleを検討し、データベース単位以上の分離が必要なら別Firestore database/projectを使用する。汎用ドキュメントパスを受け取るAPIは作らない。
- **[High] 招待トークンのURL・ログ漏えい**: 生トークンをpath/queryへ置くとブラウザ履歴、共有、Cloud Run request log、Referer等へ残り得る。URL fragmentでブラウザへ渡し、専用landing pageが同一originのPOST bodyへ移した直後に履歴から消去する。claimレスポンスは `Referrer-Policy: no-referrer` / `Cache-Control: no-store` とし、アクセスログ・監査ログ・例外へトークンを出さない。短い有効期限、十分なエントロピー、rate limit、単回消費、管理者失効を必須にする。
- **[High] 認可漏れ・IDOR**: 画面の非表示ではなく、ユーザー一覧・詳細・検索・設定変更・URL発行の全APIでIAP identityと管理者allowlistをサーバー側検証する。URLやrequest bodyで渡されたuser IDだけを信用せず、許可された操作・フィールドを固定する。書込みはCSRF tokenとOrigin検証を要求する。
- **[High] 保存型XSS**: LINE表示名、ステータスメッセージ、プロンプト、監査表示値は外部入力として扱う。Jinja2 autoescapeを無効化せず、`safe` / `innerHTML` を使用しない。inline scriptを避けたCSP、`X-Frame-Options: DENY`、MIME sniffing防止を管理サービスにも適用する。
- **[High] 現行ログへの相談内容・識別子露出**: 現行 `RAGService` は質問先頭50文字、回答先頭100文字、内部user IDをINFOログへ出す。Cloud Logging閲覧権限者から医療相談内容を閲覧できるため、質問・回答本文を直ちにログ対象外とし、user IDは不可逆ハッシュまたは短い相関IDへ置換する。例外文字列、Stripe/LINE応答、監査ログもallowlist形式にし、既存ログの保持期間・閲覧IAM・sinkを確認する。
- **[High] 国外保存・外部事業者での処理**: Cloud Runは東京だが、現行Firestore `chabotline` は米国multi-region `nam5`、Vertex AI/RAGも `us-central1` である。LINEプロフィール・アカウント情報は米国Firestoreへ保存され、質問文は米国Vertex AIで処理される。これは一般公開ではないが外部クラウド事業者・国外処理の論点になるため、追加収集前にデータフロー、契約、通知、保持、Vertex AIのabuse monitoring/retention設定を確認する。日本リージョン保存が必須なら新databaseへの移行を別途計画する。
- **[High] 患者情報の混入**: 医療専門職が質問へ患者氏名、施設名、日付等を入力すると、ログ・Vertex AI処理・障害調査経路へ第三者の情報が流れる。入力前に患者を特定できる情報を送らない旨を案内し、可能ならDLP/パターン検知で送信前警告またはマスキングを行う。管理UIへ会話本文を表示する機能は初期版に含めない。
- **[High] 過剰収集・長期保持**: 初期画面に必要なのは表示名、プラン、状態、登録日、利用回数に限定する。LINE user ID・email・画像は詳細画面で必要時だけ表示し、status message・languageは明確な運用目的が決まるまで保存しない。検索語、閲覧履歴、招待失敗情報も保存期間を定め、退会・同意撤回時の削除または匿名化手順を用意する。
- **[Medium] ブラウザ・中間キャッシュと画面共有**: 全管理HTML/APIへ `Cache-Control: no-store`、機密レスポンスへ適切な `Vary` を設定し、公開CDNへ載せない。Swagger/ReDoc/OpenAPIは無効化またはIAP内に限定し、一覧の初期HTMLへ全件データを埋め込まない。LINE画像を表示する場合は `referrerpolicy=no-referrer` とする。
- **[Medium] 権限の内部不正利用**: IAPは個人別アカウントをallowlist登録し、共有アカウントを使わない。閲覧・設定変更・招待発行の分離要否を決め、アクセス権を定期棚卸しする。監査記録自体には表示名、email、LINE user ID、トークン、プロンプト本文を保存せず、内部対象ID・操作種別・revision・結果だけを残す。
- **[Medium] バックアップ・エクスポート経由の漏えい**: ユーザーCSV一括出力は初期版へ含めない。Firestore backup、ログsink、ローカル検証データ、スクリーンショットを個人情報の複製として扱い、保存先IAM・暗号化・保持期間・削除方法を確認する。本番データを開発環境へコピーしない。

P0公開ゲート:

- [保留] 管理サービスのIAP・IAM・ingressをコード化し、未認証、許可外アカウント、失効済み管理者がすべて拒否されるE2Eを行う。IAP作業はユーザー指示により別作業とし、完了するまで本番公開しない。
- [x] 公開Botに管理routeがなく、管理サービスにLINE/Stripe Webhookなど不要な公開routeがないことを自動テストする。別ASGI entrypointとOpenAPI/route回帰テストを追加し、CI品質ゲートへ組み込んだ（ローカル成功、GitHub Actions未確認）。
- [ ] 招待トークンがURL、Cloud Run request log、application log、Referer、ブラウザ履歴へ残らないことをブラウザE2Eとログ確認で証明する。
- [ ] ユーザーA/BのID差替え、ページ番号・検索条件改ざん、CSRF、保存型XSS、クリックジャッキング、キャッシュ再表示を否定系テストする。
- [ ] Cloud Logging、Firestore、Secret Manager、backup、CI/CDのIAMメンバーを棚卸しし、個人情報を閲覧できる主体を台帳化する。
- [ ] 質問・回答本文、生の識別子、外部例外本文を出すapplication logはローカル修正・回帰テスト済み。修正後の本番ログに本文・email・LINE user ID・招待トークンがないことの確認、および既存Cloud Loggingエントリの削除・保持設定確認は本番反映後に行う。
- [ ] 収集項目ごとの利用目的、取得元、表示範囲、保持期間、削除条件をデータ台帳として確定し、プライバシー通知とLINE User Data Policy適合を確認する。
- [ ] LINE、Google Cloud（Firestore/Logging/Vertex AI/RAG）、Stripe間のデータフローと保存リージョンを台帳化し、`nam5` / `us-central1` の利用継続可否とVertex AIの保持条件を本番公開前に承認する。

#### 推奨アーキテクチャ

- [ ] 既存の公開Botサービス `chabot-service` と分離するため、管理専用ASGI entrypointを実装済み。本番の `chabot-admin` 起動・デプロイは未実施。
- [ ] 管理サービスは `app/admin_server.py` を入口として実装済み。Jinja2 + 小量のVanilla JavaScriptによる実画面は未実装。
- [ ] Botと管理UIはFirestore `chabotline` を共有する。管理サービスは専用サービスアカウントを使い、IAMで許される最小のAPI操作へ絞るが、Firestore IAMをコレクション単位の境界とはみなさない。より強い分離が必要なら別database/projectを採用する。
- [保留] 管理者認証とIAPの作業は別途行う。それまでは `ADMIN_UI_ENABLED=False` を既定とし、本番の管理サービスを公開しない。
- [ ] 管理APIはブラウザから直接Firestoreへ接続させず、すべてFastAPI経由にする。書込みには認可、CSRF対策、入力検証、監査記録を必須とする。
- [ ] 招待URLの利用者はIAP管理画面へ入れないため、URL発行は `chabot-admin`、claim landing/session/LINE callbackは公開Bot側の限定routerへ分離する。公開側から設定・ユーザー一覧・監査データを参照できる汎用APIは作らない。

#### 設定データと反映方式

- [ ] `prompt_configs` に `common` / `free` / `paid` の下書き・公開本文、revision、更新者、更新日時を保存する。画面ではfreeとpaidの実効プロンプトを読み込み・編集・プレビューできるようにする。
- [ ] basic/proは現在と同じpaidプロンプトを共有する。共通プロンプトの編集は誤変更を避けるため詳細設定として分離する。
- [ ] `plan_settings` にfree/basic/proそれぞれの公開済み `daily_message_limit` とrevisionを保存する。有料上限をbasic/pro別に維持するか共通化するかは実装前に決定する。
- [ ] 「下書き保存」と「反映」を分け、反映時はFirestore Transactionで公開revisionを原子的に切り替える。公開履歴から直前revisionへロールバックできるようにする。
- [ ] Botは公開済み設定だけを読み、短時間キャッシュする。管理サービスとはプロセスが別なので、反映保証は即時ではなく最大60秒を初期仕様とし、画面へ表示する。
- [ ] Firestore設定が欠損・不正・読取不能の場合は、コード内の現行プロンプトと `3/100/500` を安全な既定値として使い、Botの停止や無制限化を防ぐ。
- [ ] プロンプトの空文字、最大長、許可プラン、上限値の範囲をサーバー側で検証し、更新競合はrevision不一致として再読込を求める。

#### 1回限りの無料登録URL

- [ ] 管理画面から有効期限付きの暗号学的ランダムURLを1件ずつ発行する。Firestoreにはトークン平文ではなくSHA-256ハッシュ、状態、有効期限、作成者、使用者、使用日時だけを保存し、発行画面でも平文は初回だけ表示する。
- [ ] 生トークンはURL fragmentで受け渡し、専用landing pageから同一origin POSTでHttpOnly Cookieの短期claim sessionへ移した直後に履歴から削除してLINE Loginを開始する。リンクプレビューや誤タップで失効しないよう、「1回のHTTPアクセス」ではなく「1回のLINE Login成功・登録完了」を消費条件とする。
- [ ] LINE Login callbackでID Token、state、nonceを検証後、Firestore Transactionで `unused -> consumed` とfreeユーザー作成または既存ユーザー紐付けを一体で確定し、同時利用でも1人だけ成功させる。
- [ ] 作成・再利用したユーザーには `registration_source=admin_invite` と使用した招待IDを記録し、通常のfollow/message自動登録と区別できるようにする。既存ユーザーを重複作成しない。
- [ ] 使用済み、期限切れ、改ざん、認証中断を個別に扱い、失敗したLINE LoginではURLを消費しない。管理画面から未使用URLを失効できるようにする。
- [ ] LINE LoginチャネルとMessaging APIチャネルが同一LINE Provider配下か確認する。異なる場合は同一人物でもuser IDが一致しないため、Botユーザーとの自動統合を行わない。
- [ ] 同一ProviderでLINE公式アカウントをLINE Loginへリンクし、登録導線に友だち追加オプションを表示する。登録完了と友だち状態は別項目として保存・表示する。

#### 登録ユーザー参照

- [ ] `users` をページネーション付きで一覧・検索し、表示名、プラン、契約状態、有効状態、登録日、更新日、当日利用回数を表示する。
- [ ] 詳細画面でLINE user ID（一覧ではマスク）、プロフィール画像、取得日時を必要な範囲だけ表示する。status message・languageは明確な利用目的が承認されるまで収集・保存しない。既存データには画像等がないため、登録時保存と明示的なプロフィール再取得を追加する。
- [ ] Messaging APIで取得できるのは原則として友だちまたはメッセージ送信者の表示名・画像・ステータスメッセージ・言語で、ブロック後などは再取得できない前提で最終取得スナップショットを扱う。
- [ ] メールはLINE Loginのemail権限が承認され、本人が同意した場合だけ実値として保存・表示する。現在の `line_<userId>@chabot.local` は識別用プレースホルダーと明示し、実メールとして扱わない。
- [ ] 個人情報の利用目的、閲覧権限、保持期間、削除手順を本番公開前に決め、プロンプト本文・招待トークン・個人情報をアプリログへ出さない。

#### 画面構成

1. [ ] 設定: free/paidプロンプト、free/basic/pro上限、下書き保存、差分確認、反映、履歴、ロールバック
2. [ ] 無料登録URL: 発行、有効期限、コピー、未使用/使用済み/期限切れ、失効
3. [ ] ユーザー: 検索・絞込み・詳細、当日利用回数、LINEプロフィール最終取得状態
4. [ ] 監査: 設定反映、ロールバック、URL発行/失効/使用、プロフィール再取得の操作履歴

#### 実装順序と完了条件

1. [ ] 仕様確定: 有料上限のbasic/pro別・共通、有効期限既定値、既存ユーザーがURLを使った場合の扱いを決定。管理者認証/IAPは別作業として保留
2. [ ] 基盤: 管理サービスの別ASGI entrypoint、既定無効、docs無効、no-store/no-referrer/CSP等のヘッダー、公開Botとのroute分離テストまでローカル実装済み。Firestoreスキーマ、監査ログ、認証境界は未実装
3. [ ] 設定管理: 読込、下書き、差分、反映、Bot側動的読込、安全なfallback、ロールバックを実装
4. [ ] 無料登録URL: 発行、LINE Login連携、単回消費、期限切れ・失効、競合テストを実装
5. [ ] ユーザー参照: 一覧、検索、詳細、利用回数、取得可能なLINEプロフィール項目を実装
6. [ ] 検証: unit、Firestore Emulatorまたはモック、ローカルブラウザE2E、認証済みステージング、LINE実端末E2Eを順に行う
7. [ ] 本番反映: 管理者認証を有効化した後だけ `chabot-admin` をデプロイし、Bot側の設定反映、監査記録、ロールバックを確認する

#### ローカル実装状況（2026-09-04）

- [x] `app/admin_server.py` を公開Botと分離し、管理機能を既定無効、OpenAPI/Swagger/ReDocを無効にした。
- [x] 共通セキュリティヘッダーミドルウェアを切り出し、管理レスポンスへ `Cache-Control: no-store`、`Pragma: no-cache`、`Referrer-Policy: no-referrer`、CSP、frame拒否、MIME sniffing防止を適用した。
- [x] 公開Botと管理サービスのroute混入回帰テストを追加し、既存のデプロイ品質ゲートへ組み込んだ。現行workflowは公開Botだけをデプロイし、管理サービスのデプロイ処理は追加していない。
- [x] RAGの質問・回答本文、LINEメッセージ、LINE/Stripe/内部user ID等を主要なapplication logから除去し、機密値がログへ出ないことを回帰テストした。
- [x] 公開チャットAPIへLINE経路と同じ日次上限を適用し、RAG context metadataの外部返却を拒否した。
- [x] JWTからemail/LINE user IDを除去し、Stripe Customer/Checkout metadataからLINE user IDを除去した。（JWT分は2026-09-21本番反映済み、metadata分は未コミット）
- [x] GitHub Actions一時認証ファイル `gha-creds-*.json` をGitとDocker build contextから除外し、回帰テストを追加した。
- [x] ログアウト時はRefresh Tokenを即時失効・Cookieを削除し、発行済みAccess Tokenは最大15分で失効後、LINE Loginを再要求する設定とテストを固定した。環境変数でも15分超へ延長できない。（2026-09-21本番反映済み）
- [x] JWTの追加クレーム経由でemail、LINE user ID、予約クレームを再注入できないよう共通生成関数で拒否した。（2026-09-21本番反映済み）
- [x] デプロイ品質ゲート相当124件、既知のPostgreSQL Refresh Tokenテストを除くunit 139件、Python compileallにローカル成功した。
- [x] 外部クライアント、同期処理、休眠中のPostgreSQLリポジトリを含む例外ログを例外型中心のallowlist形式へ変更した。
- [ ] Cloud Loggingの既存ログ削除・保持期間・閲覧IAM・sink確認は未実施（IAM/IAPはユーザー指示により別作業）。
- [保留] IAP、管理サービス用IAM/ingress、管理者allowlist、認証E2E、`chabot-admin` のデプロイは別作業とする。

完了条件:

- [ ] 未認証者が画面・管理API・個人情報へアクセスできず、管理UI障害がLINE Webhook処理へ波及しない。
- [ ] 下書き保存ではBot挙動が変わらず、反映後60秒以内に新しいプロンプトと上限が適用され、直前revisionへ戻せる。
- [ ] 同じ登録URLへの同時アクセスでも登録完了は1件だけで、期限切れ・失効済みURLは利用できない。
- [ ] LINEから取得できない項目を「未取得」と区別し、プレースホルダーメールを実メールとして表示しない。
- [ ] 全管理操作に操作者、対象、時刻、結果、revisionが残り、機密本文・トークン平文・不要な個人情報はログへ残らない。

---

## 3. 次回デプロイ前の必須対策（P0）

### P0-1. 依存関係の再インストール

ローカル環境はPython 3.14で、`google-cloud-firestore` を含む必要パッケージをvenvへ導入済み。

- [x] Python 3.14でのSQLAlchemy/FastAPI互換性を確認
- [x] `google-cloud-firestore` をvenvへインストール
- [x] 現行品質ゲート対象の自動テスト111件に成功。全unitは既知のPostgreSQL Refresh Token 9件を除く126件が成功
- [保留] PostgreSQL認証のunit / integration / E2Eテスト（現在のFirestore運用とCI品質ゲートの対象外）
- [x] Firestore非同期I/O・Transaction・障害時案内の自動テストを追加
- [x] 2026-08-24のテスト結果を本ファイルへ記録

### P0-2. CIを正式な品質ゲートにする

- [ ] CIのPythonバージョン方針を確定（deploy.ymlは3.11、ローカルは3.14）
- [x] Firestore-only app startupテストをCIに追加
- [x] テスト環境変数にDATABASE_BACKEND=firestoreを追加
- [x] CI必須ゲートをFirestore / LINE / Vertex AIに限定し、PostgreSQL認証テストと `continue-on-error` ステップを除外
- [x] Vertex AIテストを現行Google Gen AI SDK、プラン別生成プロンプト、Markdown除去仕様へ追従
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

- [x] 移行候補モデルの利用可否を実APIで確認し `gemini-3.5-flash-lite` を選定（2026-09-21）。3系はus-central1生成で404、globalエンドポイントでは3.5/3.1とも生成可。RAG精度・応答時間・費用の定量比較は未実施で、実利用での観察が残課題
- [x] 選定モデルへコード既定値（`settings.google_model_name`）とFirestore free/basic/pro設定を同時更新し、回帰テストと実グラウンディング生成（contexts 2件・confidence 0.85）で確認（2026-09-21）
- [x] 2026-10-16より十分前にCloud Run `chabot-service-00031-v5z` へ反映し、旧モデル既定値依存がないことを確認（Firestore読み戻しで3プランとも新モデル）
- [ ] 代表的な実質問で旧モデル（2.5-flash）との回答品質・レイテンシ・費用を比較し、問題あれば調整する
- [x] 回答生成を `vertexai.generative_models` / `vertexai.rag` からGoogle Gen AI SDKの `VertexRagStore` へ移行し、実コーパスで応答確認
- [x] 分類モデルの旧 `gemini-1.5-flash` 既定値を現行 `gemini-2.5-flash` へ統一
- [ ] RAGコーパス管理スクリプトの `vertexai.rag` をAgent Platformクライアントへ移行する

補足: ローカル個人用 `.env` の `GOOGLE_LOCATION` は2026-09-21に `us-central1` へ修正した。本番Secretも `us-central1` で、RAGコーパス参照・分類はこの地域を維持する。
Gemini 3系（3.5/3.1 flash-lite）は `us-central1` のモデル一覧に表示されるが生成APIは404となり、`global` エンドポイント（enterprise/v1）でのみ生成可能。このため生成クライアントだけ `GOOGLE_GENERATION_LOCATION=global`（既定値）へ分離した。分類はJev前段分類へ置換済み。

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
- [ ] ログアウト時のCookie削除・対象Refresh Token即時失効、Access Token最大15分、失効後LINE Login再要求はコード・unit test済み。LINE unfollow時の全Refresh Token失効を含む実端末E2Eは未確認
- [ ] LINE ID → Firestore user ID → Stripe customer IDの一意性を検証
- [x] 公開POST `/subscription/checkout/create` とGET `/subscription/status` の固定 `test_user_id` を実認証へ置換
- [x] 既存友だちにfollowイベントが再発しない場合、最初のトークでfreeユーザーを自動作成してLINE Login・Stripe登録へ引き継げるよう修正（本番反映済み・実端末E2E未確認）
- [x] LINE Login callbackで復帰先Cookieが失われた場合、AccessToken等を含むJSONを画面へ返さず登録リンク再案内HTMLへ変更（Refresh Cookieは設定維持）。2026-09-21修正

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
- [x] 公開チャットAPIへ日次上限を適用し、RAG context metadataの返却を禁止
- [x] JWTとStripe metadataの不要なLINE/email識別子を削除
- [x] JWT追加クレームのPII・予約クレーム上書きを拒否し、Access Token有効期限を設定上も最大15分に制限
- [x] GitHub Actions一時認証JSONをGit/Docker build contextから除外
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
10. [x] Phase 2導入前からの既存友だちを最初のトークでfree自動登録（本番反映済み・実端末E2E未確認）
11. [x] free / basic・proで生成構成と参照方針を分岐し、freeコーパス根拠・質問への直接回答・共通文体・文字数を維持するテストに成功（`chabot-service-00028-cvl`へ本番反映・実端末E2E未確認）

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
  tests/unit/test_admin_app_security.py \
  tests/unit/test_build_security.py \
  tests/unit/test_chat_api_security.py \
  tests/unit/test_auth_session.py \
  tests/unit/test_subscription_checkout.py \
  tests/unit/test_stripe_webhook.py \
  tests/unit/test_core/test_line_id_token.py \
  tests/unit/test_clients/test_line.py \
  tests/unit/test_clients/test_vertex_ai.py \
  tests/unit/test_repositories/test_firestore_repositories.py \
  tests/unit/test_services/test_line_webhook_pipeline.py \
  tests/unit/test_services/test_line_service.py \
  tests/unit/test_services/test_rag_service.py \
  tests/unit/test_services/test_firestore_auth_service.py \
  tests/unit/test_services/test_stripe_service.py \
  tests/unit/test_subscription_privacy.py \
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
- 管理UI実装前は `app/core/pricing.py` の `DAILY_MESSAGE_LIMITS` を正とする。管理UI実装後は公開済みFirestore設定を運用上の正とし、同定数は安全なfallbackとして維持する。
- 仕様変更時はコード、初期データ、テスト、本ファイルを同時に更新する。
