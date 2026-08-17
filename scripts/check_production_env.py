"""
本番環境の環境変数確認スクリプト

Secret Manager に格納されている本番環境の設定値を確認します。

使用方法:
    python scripts/check_production_env.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.cloud import secretmanager
import json


def access_secret_version(project_id, secret_id, version_id="latest"):
    """
    Secret Manager のシークレットにアクセス

    Args:
        project_id: GCPプロジェクトID
        secret_id: シークレットID
        version_id: バージョンID（デフォルト: "latest"）

    Returns:
        シークレットの値（文字列）
    """
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


def check_production_secrets(project_id="takahashi-451312"):
    """
    本番環境のシークレットを確認

    Args:
        project_id: GCPプロジェクトID
    """
    print(f"=== 本番環境設定確認（プロジェクト: {project_id}）===\n")

    # チェックするシークレットのリスト
    secrets_to_check = [
        {"id": "chabot-env", "description": "環境変数全体"},
        {"id": "chabot-line-channel-secret", "description": "LINEチャネルシークレット"},
        {"id": "chabot-line-channel-access-token", "description": "LINEチャネルアクセストークン"},
        {"id": "chabot-stripe-secret-key", "description": "Stripeシークレットキー"},
        {"id": "chabot-stripe-webhook-secret", "description": "Stripeウェブフックシークレット"},
        {"id": "chabot-google-corpus-id", "description": "Freeプラン用コーパスID（GOOGLE_CORPUS_ID）"},
        {"id": "chabot-google-corpus-id-plan1", "description": "有料プラン用コーパスID（GOOGLE_CORPUS_ID_PLAN1）"},
    ]

    found_secrets = {}

    for secret in secrets_to_check:
        try:
            print(f"🔍 {secret['description']} ({secret['id']}):")
            value = access_secret_version(project_id, secret['id'])

            if secret['id'] == 'chabot-env':
                # 環境変数全体の場合はJSONとしてパース
                try:
                    env_data = json.loads(value)
                    print(f"  ✅ 環境変数データ取得成功（{len(env_data)}項目）")

                    # 重要な項目を抽出
                    important_keys = [
                        'GOOGLE_CORPUS_ID',  # freeプラン用コーパスID
                        'GOOGLE_CORPUS_ID_PLAN1',  # 有料プラン用コーパスID
                        'STRIPE_SECRET_KEY',
                        'STRIPE_WEBHOOK_SECRET',
                        'FIRESTORE_PROJECT_ID',
                        'DATABASE_BACKEND'
                    ]

                    for key in important_keys:
                        if key in env_data:
                            # 値をマスキングして表示
                            value = env_data[key]
                            if 'secret' in key.lower() or 'key' in key.lower() or 'token' in key.lower():
                                masked_value = value[:8] + "..." if len(value) > 8 else "***"
                                print(f"    - {key}: {masked_value}")
                            else:
                                print(f"    - {key}: {value}")
                except json.JSONDecodeError:
                    print(f"  ⚠️ JSONパースエラー、生データ: {value[:100]}...")
            else:
                # 値をマスキングして表示
                masked_value = value[:8] + "..." if len(value) > 8 else "***"
                print(f"  ✅ 値: {masked_value}")

            found_secrets[secret['id']] = value
            print()

        except Exception as e:
            print(f"  ❌ エラー: {e}")
            print()

    return found_secrets


def check_firestore_collections(project_id="takahashi-451312"):
    """
    Firestoreのコレクション構造を確認

    Args:
        project_id: GCPプロジェクトID
    """
    print(f"=== Firestoreコレクション確認（プロジェクト: {project_id}）===\n")

    try:
        from google.cloud import firestore
        db = firestore.Client(project=project_id)

        # コレクション一覧を取得
        collections = db.collections()

        found_collections = []
        for collection in collections:
            collection_name = collection.id
            count = len(list(collection.limit(1).get()))
            found_collections.append(collection_name)
            print(f"📁 {collection_name}: （ドキュメント数: {count}以上）")

        if not found_collections:
            print("⚠️ コレクションが見つかりません。初期データを作成してください。")
            print("  実行: python scripts/setup_firestore_data.py")

        return found_collections

    except Exception as e:
        print(f"❌ Firestore確認エラー: {e}")
        return []


def main():
    """メイン処理"""
    print("🚀 本番環境の設定値を確認します...\n")

    try:
        # プロジェクトIDの設定
        project_id = "takahashi-451312"

        # Secret Managerの確認
        print("🔐 Secret Manager の確認:")
        print("-" * 50)
        secrets = check_production_secrets(project_id)

        # Firestoreの確認
        print("\n🔥 Firestore の確認:")
        print("-" * 50)
        collections = check_firestore_collections(project_id)

        # サマリー
        print("\n" + "=" * 50)
        print("📋 確認結果サマリー:")
        print("=" * 50)
        print(f"Secret Manager: {len(secrets)}個のシークレットを確認")
        print(f"Firestore: {len(collections)}個のコレクションを確認")

        # 設定値が見つからない場合のガイダンス
        if len(secrets) == 0:
            print("\n⚠️ 本番環境のシークレットが見つかりませんでした。")
            print("以下の手順で設定してください:")
            print("1. GCPコンソールでSecret Managerを開く")
            print("2. 各シークレットを作成:")
            for secret in [
                "chabot-env (環境変数JSON)",
                "chabot-google-corpus-id (freeプラン用)",
                "chabot-google-corpus-id-plan1 (有料プラン用)",
                "chabot-stripe-secret-key",
                "chabot-stripe-webhook-secret"
            ]:
                print(f"  - {secret}")
            print("3. Secret Managerの値を確認後に再度実行")

    except Exception as e:
        print(f"❌ エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
