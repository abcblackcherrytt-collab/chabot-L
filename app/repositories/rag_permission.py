"""
RAG権限リポジトリ
プラン別の RAG 設定（コーパスID・モデル・制限）の参照を提供します。

Firestore版実装をデフォルトとして使用します。
"""

from app.repositories.firestore_rag_permission_repository import FirestoreRagPermissionRepository

# Firestore実装をデフォルトとしてエクスポート
RagPermissionRepository = FirestoreRagPermissionRepository

__all__ = ['RagPermissionRepository', 'FirestoreRagPermissionRepository']
