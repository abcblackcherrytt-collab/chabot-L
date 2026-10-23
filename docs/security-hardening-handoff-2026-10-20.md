# セキュリティ修正・実装引き継ぎ（2026-10-20）

## 状態と依頼

計画作成済み。アプリコード変更・テスト実行・本番変更は未実施。
ユーザーは前回提案1〜4の実装を承認し、5を「質問と会話内容・日付のみを保存し、IDやユーザー情報を含めない」に変更した。通常利用で再ログインを求めない構成を継続する。今回の成果物は、次の軽量モデルが実装するための計画。

次の担当はこの文書と `AGENTS.md`、`PROJECT_PLAN.md`、project-plan-managerスキルを読み、下記S1〜S5を実装・検証する。改めて修正方針の承認を求める必要はない。前回提案6（一般Cookie操作の全面CSRF化）・7（登録存在判定）は今回の独立した改修対象にしない。ただし今回変更する失効APIの認可順序等は安全に実装する。

## 変更してはいけない利用条件

- LINEの1対1トークは署名検証済みWebhookから使え、質問のたびにWebログインを要求しない。
- プラン画面・Checkout・招待の既存認証はHttpOnly/Secure Cookieによる自動更新を維持する。Access Tokenの15分期限を「15分ごとの再ログイン」に変えない。
- 現在のRefresh Token / Cookieの30日ローリング更新を短縮しない。通常利用に新たな絶対セッション期限・定期的な認証画面・`prompt=login`強制を追加しない。
- LINEアプリのログアウトとChabotのログアウトは別。現行コードおよび確認したMessaging APIイベント仕様には、LINEアプリ自体のログアウトをChabotへ通知する経路がない。LINEのunfollow（ブロック）をアプリのログアウトと呼び替えない。
- 「LINEアプリからログアウトしなければ例外なく永久に再認証不要」とは保証しない。Cookie削除・30日以上のWeb未使用・LINE側の認可失効等では、既存LINE Loginの自動ログインを利用して復帰する。自動ログイン可否は端末・ブラウザにも依存する。Botへの質問だけではブラウザCookieを更新できない。
- 明示的Chabotログアウト、全セッション失効、アカウント停止、unfollowは承認済みの防御として有効にする。停止中のユーザーを自動ログインで再有効化しない。ログアウト直後に勝手にLINE Loginへリダイレクトして失効を打ち消さない。
- 会話保存の変更は会話アーカイブを対象とする。認証・課金・回数管理に必要な `users` / セッション / `usage_daily` のユーザーIDは削除しない。そこへ会話本文・会話への参照を新設しない。

参考（2026-10-20確認）:
- LINE自動ログインとSSO: https://developers.line.biz/ja/docs/line-login/integrate-line-login/
- Messaging APIイベント: https://developers.line.biz/en/reference/messaging-api/
- グループ返信の仕様: https://developers.line.biz/en/docs/messaging-api/group-chats

## 現状の根拠と修正ファイル

| 対象 | 現状 | 主な変更先 |
|---|---|---|
| S1 個別トーク限定 | `source.userId`だけで処理し、グループを除外していない | `app/services/line_service.py`, `app/api/v1/webhooks/line.py` |
| S2 セッション即時失効 | `get_current_user`は署名・type・ユーザー有効状態のみ。logout/revoke-allはRefresh Tokenのみ失効 | `app/core/deps.py`, `security.py`, `app/services/firestore_auth_service.py`, `app/api/v1/auth.py`, `auth_line.py` |
| S3 更新競合 | 保存済みtokenを読取→新規発行→旧token失効。Transactionなし | `app/repositories/firestore_refresh_token_repository.py`, セッション用新規repository、上記認証service |
| S4 RAG権限 | 有効権限なしでもNoneを渡し、Vertexクライアントが既定コーパスを使用 | `app/api/v1/chat.py`, `line_service.py`, `app/services/rag_service.py`, `app/clients/vertex_ai.py`, `app/core/deps.py` |
| S5 会話保存 | user_id・plan・分類等を本文に付随して保存。代表回答にも質問を複製 | `app/repositories/firestore_conversation_repository.py`, `firestore_representative_answer_repository.py`, `chat.py`, `webhooks/line.py`, `app/services/admin_service.py`, `app/admin_api.py`, `app/static/admin/admin.js` |

既存対策（署名検証、OIDC state/nonce/PKCE、公開API本人特定、管理API分離、JWTのPII排除）は維持する。本番の現状は今回再確認していない。過去のPROJECT_PLAN内の監査・デプロイ記録を今回の実測扱いしない。

## S1: LINEの処理を1対1へ限定

1. `process_webhook_event` の入口で、message/follow/unfollow/postbackについて `source.type == "user"` と非空userIdを要求する。group/room/欠損/未知typeは処理しない。署名検証を経由しない公開入口を作らない。
2. 拒否時はDB検索・新規登録・クーポン・要望状態変更・日次消費・分類・RAG・本文保存・個人宛pushを一切行わない。初期実装ではグループへ返信せずskipする（返信ループや個人状態の露出を防ぐ）。
3. postbackでもユーザー有効状態を確認する。message以外を迂回路にしない。
4. 既存テストfixtureにsource.typeがない場合、正規1対1イベントへ修正する。欠損をuser扱いする互換処理は禁止。

受入条件: group/room内に正しいuserIdがあっても外部処理0回。1対1のfollow/message/unfollow/postbackは既存機能が通る。

## S2・S3: 自動ログインを維持したセッション失効・原子的更新

両項目は同一のセッション設計として実装する。先に新repositoryとserviceのテストを作り、APIへ接続する。

### データと検証契約

- Firestore `auth_sessions/{sid}` を追加。sidはランダムでユーザー識別子を含めない。`user_id`, `auth_version`, `current_refresh_jti`, `expires_at`, `revoked_at`, `created_at`等、認証に必要な情報だけ保存する。ここには会話本文・会話IDを入れない。
- `users.auth_version` を全失効用の世代番号とする（未設定=0）。単一ログアウトはsidを失効、全失効は世代番号を原子的に加算する。大量tokenの列挙・500件batch制限に全失効の正しさを依存させない。
- 新Access/Refresh JWTに `sid`, `auth_version`, `iat`, `iss`, `aud` を追加。用途別type、sub、jti、expを必須検証し、追加claimsで予約値を上書きできないようにする。PIIをJWTへ追加しない。
- Access認証ではJWTの検証に加え、sessionの所有者=sub・未失効・有効期限・user世代一致・is_activeを確認する。Refreshローテーションだけで既存Access Tokenを無効化しない。即時失効を遅らせる有効セッションキャッシュは使わない。
- Firestore障害では503等の一時エラーとし認可を通さない。障害を「無効トークン」に変換してCookieを消したりログインへ誘導したりしない。
- 全失効API、unfollow、管理者の無効化から同じ失効serviceを呼ぶ。`auth.py`は現在repositoryを直接呼ぶ箇所があるので漏らさない。再follow/再有効化で過去sessionを復活させない。
- logoutもtype=refresh・sub/sid/jti・保存hashの一致を確認する。認証済み本人以外への全失効は対象ユーザーの検索前に拒否する。

### 更新処理

1. 新しいJWT・hash・文書IDを用意する。Firestore Transactionの再試行内で外部通信・Cookie発行をしない。
2. Transactionでuser/session/旧Refresh Tokenを読み、所有者・世代・期限・hash・未消費・current_refresh_jti一致を確認する。
3. 旧tokenを消費済みにし、新token文書作成とsession.current_refresh_jti/ローリング期限更新を同じTransactionでcommitする。commit前には新tokenを返さない。
4. 同じRefresh Tokenから成功する更新は1件のみ。プロセス内Lockだけに依存しない。logout/revoke-allと競合しても、失効済みsession/世代でtokenを発行できないことを保証する。
5. 正常な二重リクエストを即座にアカウント侵害とみなし全session失効する実装は禁止。消費済みtokenの再利用は新tokenを発行せず競合として扱う。単なる競合と管理停止・期限切れ・DB障害は別結果とする。

### 不要な再ログインを防ぐ重要な接続変更

- 現状 `subscription.select/status/checkout`, `invite.complete` は認証のたびにrefreshする。同じブラウザの並行アクセスで競合するため「Cookie認証検証」と「token更新」をservice上で分離する。単なる読取が毎回tokenを消費しない構成にする。
- 期限に余裕があるCookieは検証して再利用し、更新が必要なときにだけ30日ローリング更新する。期限直前まで更新しない構成にせず、通常アクセスで十分な余裕を維持する。
- 必要な更新の並行要求はクライアント側でも一本化する。敗者は競合として扱いCookieを消さず、勝者のSet-Cookie反映後に限定回数再試行する。無限リトライ・競合だけでLINE Loginへの遷移は禁止。必要なら既存HTML導線に小さな同一origin再試行処理を追加する。
- 認証更新後にStripe/招待処理が失敗しても新Cookieをレスポンスに反映する共通処理を設ける。現在はCheckoutエラー等で新Cookieを失う経路がある。token更新と業務処理成功を混同しない。
- 通信切断で更新レスポンスを完全に失った場合の回復はテストする。使用済みtokenを無条件に再有効化したり後継tokenを配布したりしない。回復不能時は既存LINE自動ログインへ戻し、無操作復帰の保証限界として記録する。

### 既存セッションの移行

- 既存Refresh Tokenを一斉失効しない。旧形式であっても署名・期限・provider・type・保存hash・所有者・未失効を検証できる場合に限り、新sessionへTransactionで一度だけ移行する。
- 旧形式受付には設定で固定した期限を設ける（最後の旧形式発行停止から現行Refresh寿命30日以上の移行期間）。起動のたびに期限を延ばさない。移行中の全失効は世代更新と旧token失効を整合させ、旧形式受付が失効の迂回路にならないようにする。
- 旧Access JWTにはsidがないため新認証ではそのまま許可しない。既存Refresh Cookieから自動更新できる導線を先行実装する。Bearerのみのクライアントは保持するRefresh Tokenで交換する契約をテストする。新形式への切替で手動ログインを要求しない。
- 休眠中PostgreSQL経路へFirestore依存を混入させない。共通JWT関数変更時は旧AuthServiceの呼び出しも整合させ、対応範囲外のセッション即時失効を実装済みと称さない。本番はFirestoreが対象。

受入条件: logout直後の旧Access拒否、別端末sessionの維持、全失効後の全Access/Refresh拒否、再有効化後の旧token拒否、更新競合成功1件、DB障害でfail closedかつCookie維持、既存Cookieの無操作移行、15分経過後の自動更新、複数画面同時アクセス、Checkout失敗後の認証維持。

## S4: RAG権限を確定できないときは検索禁止

1. LINEと公開チャットで同じ実効プラン解決を使う。現状chatは `current_user.subscription_plan`、LINEは `resolve_effective_plan` なので、管理者override/service→pro等を含む契約を揃える。認証済みDB情報から決め、リクエストのplan/user_id/corpus_idを信用しない。
2. 共通resolverを追加し、有効な権限レコード・正しいプラン対応・空でない実コーパスIDを要求する。None/空文字/placeholder/無効レコード/不正形式/DB障害で停止する。基本・Proのコーパス共有は既存仕様どおり許容する。
3. コーパス認可は日次消費の前に完了させる。権限欠損で利用回数を減らさない。APIは固定文言の503、LINEは個別トークへ一時利用不可の案内。コーパス名・プロジェクト名・内部例外を返さない。
4. `RAGService.query`〜`VertexAIClient`にも公開経路で明示corpus_id必須の防御を置く。`corpus_id or self.corpus_id` による暗黙fallbackを公開経路で使わない。内部管理・health用途で必要な既定値は明示指定に変更する。
5. 権限の無効化が60秒cacheに残らないよう、認可に使う有効レコードは毎回確認する。設定表示用cacheとは分離する。公開済み回数上限の安全な既定値3/100/500は維持する。
6. 管理画面コーパス表示のfallbackは「検索許可」と誤認させない表示・テストへ追従する。質問・回答のコーパスへの自動投入は追加しない。

受入条件: 正常free/basic/pro/serviceで期待コーパス、権限None/disabled/空/不正/読取失敗で検索0回・消費0回、有効→無効変更を次要求で拒否、リクエスト偽造で他プランに変わらない。

## S5: 会話は質問・回答・日付の3項目だけ保存

### 新規保存の契約

保存フィールドを次に固定する（例は架空）。日付はAsia/Tokyoの日単位とし、時刻によるユーザーログとの容易な照合も減らす。

```json
{
  "question_text": "肩の評価手順を教えてください",
  "answer_text": "まず問診と可動域を確認します。",
  "date": "2026-10-20"
}
```

- `user_id`, LINE ID, email, 表示名, plan, session/token ID, request/event/message ID, IP, user-agent, 分類, denial, pii_suspected, 正確な時刻を保存しない。ハッシュ化ユーザーID・対応表による追跡も作らない。
- Firestoreの文書キーは保存上不可避なランダムキーのみ。ユーザー由来のキーやuser配下のsubcollectionは不可。`id`フィールドとして保存せず、画面の列にも表示しない。既存質問選択・代表回答編集のため管理APIが必要とするopaqueな会話参照は、ユーザーに紐付かない内部キーに限定する。
- `save_conversation` の引数もquestion_text/answer_text/dateだけにし、呼び出し元からユーザー文書やIDを渡さない。LINE/API両方の保存タスクを変更する。
- 利用上限拒否は質問・回答のペアではないため `conversations` への保存をやめる。日次集計・課金用回数管理は維持する。集計から会話文書への逆引きは設けない。
- 保存失敗で回答を止めない既存動作を維持する。会話IDとuserIdを同一ログに出さず、本文もログに出さない。
- 本文中に利用者が自分で書いた氏名等は、この3項目化だけでは消えない。今回ユーザーは本文保存を求めているため、無断で本文を改変・マスキングする機能は追加しない。「完全匿名化済み」とは記録しない。

### 管理画面・代表回答・既存データ

1. 会話一覧・質問抽出APIは許可フィールドを組み立てて返す（旧文書のdictをそのまま返さない）。ユーザー/プラン/分類/PII列を除去し、日付と質問・回答の閲覧導線を整合させる。管理認証・CSP・textContentによる表示を維持する。
2. 代表回答の保存も質問・代表回答本文・日付へ縮小し、利用者属性・分類・更新者email等を本文文書に持たせない。1会話1件の編集には同じランダム文書キーを用い、フィールドに会話IDを重複保存しない。管理操作の監査は別の既存監査基盤で維持し、エンドユーザーとの対応を残さない。
3. `scripts/migrate_conversation_privacy.py` を用意する。既定dry-run、明示project/database、applyフラグ、ページ処理、再実行可能、更新時刻precondition等の競合保護、件数とフィールド名だけの出力を必須にする。本番本文・識別子の表示/ローカルdumpは禁止。
4. 既存conversationsを3フィールドへ置換（mergeで旧フィールドを残さない）、created_atをJST日付へ変換する。本文なしの上限拒否文書は削除対象として件数を分ける。日付不正・本文不整合は捏造せず件数のみ報告し保留する。
5. 既存representative_answersは会話ランダムキーへの再配置と古い属性の削除を行う。重複・会話欠損をdry-runで検出し無言で上書きしない。旧質問コピーのユーザー属性も除去対象にする。
6. users等、認証・利用回数・要望管理用コレクションは削除しない。会話への参照を持つ複製が別にある場合は調べ、移行対象を記録する。過去ログ/backup内の残存は本番移行の検証項目として明記する。
7. `docs/admin-console-design.md` とPROJECT_PLANの現行方針を更新する。過去の実施記録は残し、新方針への置換を明記する。

受入条件: Firestoreへの書込キー集合が厳密に3項目、API/LINE双方で同じ契約、ユーザーA/Bを変えても会話文書にID差分なし、未認証管理閲覧拒否、旧文書のAPI応答からも利用者情報なし、代表回答編集と一覧が正常、移行dry-run無変更・再実行で差分なし・本文非出力。

## 実装順・検証・リリース

1. S1とS4を独立した小さな変更として実装する。
2. S2/S3のrepository・service・競合テスト→API接続→既存セッション移行と自動更新回帰の順に実装する。
3. S5の読取/UI互換→新規書込契約→既存データ移行スクリプトの順に実装する。
4. 以下の既存テストへ否定系を追加し、新規session repository・Firestore Emulator競合テスト・移行テストを用意する。AsyncMockで順番を見るだけでは原子性の検証完了にしない。

| 領域 | 既存の主なテスト |
|---|---|
| S1 | `test_services/test_line_service.py`, `test_line_admin_flows.py`, `test_line_webhook_pipeline.py` |
| S2/S3 | `test_auth_session.py`, `test_services/test_firestore_auth_service.py`, `test_subscription_checkout.py`, `test_invite_claim.py`, `test_admin_api.py` |
| S4 | `test_chat_api_security.py`, `test_services/test_rag_service.py`, `test_clients/test_vertex_ai.py`, `test_admin_corpora.py`, `test_pricing.py` |
| S5 | `test_repositories/test_firestore_conversation_repository.py`, `test_admin_repositories.py`, `test_admin_api.py`, `test_admin_ui.py`, Webhook/chatテスト |

上記パスは `tests/unit/` 配下。テスト用ダミー認証情報・エミュレーターを使用し、実ユーザーやStripe決済を操作しない。新しいテストも `.github/workflows/deploy.yml` の品質ゲートへ追加する。

```bash
git diff --check
pytest tests/unit/ --ignore=tests/unit/test_repositories/test_refresh_token.py -v --tb=short
python -m compileall -q app scripts
node --check app/static/admin/admin.js
```

品質ゲートはPROJECT_PLANの古いコマンド一覧ではなく、その時点の `.github/workflows/deploy.yml` にも照合する。Emulator未利用なら競合保証は「未検証」として残す。UI変更時は既存デザインスキルに従い、ローカル架空データで表示確認する。

### 本番反映の手順（今回未実施）

- mainへのpushは自動デプロイを起こす。この計画作成ではpush・デプロイ・本番移行を行っていない。次担当はまず実装・ローカル検証を完了し、実際の本番反映の指示範囲を確認する。
- 旧Cookie移行と新旧文書読取の互換コードを先に用意し、Botと管理サービスの両方へ反映する。会話の旧書込を行うインスタンスが停止してからデータ移行を実施する。
- 移行dry-run結果は件数・異常件数のみでレビュー可能にする。実移行後は本文を出さず全件の許可フィールド集合・日付・残存属性・代表回答整合を確認する。
- 認証切替で既存Cookieからの自動更新を実端末確認する。1対1質問、プラン画面、Checkoutへの復帰、明示ログアウト、unfollow、グループ無処理、失効直後のAPI拒否を確認する。
- ロールバック時もユーザー情報を会話へ再保存する旧writerや、失効を無視する旧認証へ戻さない。データ削減は不可逆なので、コード互換を保った前進修正を基本とする。無断でPII入りバックアップを新規作成しない。

## 完了チェック（次担当が結果を追記）

- [x] S1 実装・否定系テスト（2026-10-20・非1対1ソースは処理前にskip。ローカルunit検証済み）
- [x] S2/S3 実装・通常更新/既存Cookie移行・即時失効テスト（2026-10-20・authenticate_refreshによる非消費検証、Transactionによる単回消費、logout/revoke-allのsession+世代更新。ローカルunit検証済み。Firestore Emulatorでの実同時競合は未実施）
- [ ] S2/S3 Firestore Emulatorによる同時更新・失効競合検証
- [x] S4 実装・権限欠損/停止時の検索・消費ゼロ検証（2026-10-20・LINE/chat/RAGServiceの3層でfail closed。並行して実装されたカテゴリ別コーパス分類機能と統合済み。ローカルunit検証済み）
- [x] S5 新規3フィールド保存・管理UI・代表回答・移行スクリプト検証（2026-10-20・conversations/representative_answersを質問・回答・日付のみへ変更、管理UI/API追従、移行スクリプトはdry-run既定。ローカルunit検証済み。実Firestoreデータでのdry-run/本適用は未実施）
- [x] 全unit・CI品質ゲート相当・構文・差分確認（2026-10-20・unit 272件成功、compileall・node --check・git diff --check成功。GitHub Actionsは未実行）
- [ ] Bot/admin本番反映（実施時のみ記入）
- [ ] 本番既存会話移行・残存属性検証（実施時のみ記入）
- [ ] 実端末E2E・再ログイン不要の通常導線確認
- [ ] PROJECT_PLANへ実装/ローカル検証/E2E/本番/移行状態を分けて記録
