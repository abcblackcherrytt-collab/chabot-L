"""既存会話データを「質問・回答・日付のみ」へ移行するスクリプト。

既定はdry-runで書き込みを行わない。実行には明示的なプロジェクトIDと
FirestoreデータベースIDが必要で、出力は件数とフィールド名のみ。
本文・識別子の値は一切表示しない。

使い方::

    python scripts/migrate_conversation_privacy.py \
        --project takahashi-451312 --database chabotline
    python scripts/migrate_conversation_privacy.py \
        --project takahashi-451312 --database chabotline --apply

対象:
- conversations: user_id/plan/分類/時刻等の付帯フィールドを削除し、
  question_text / answer_text / date（JST日付）だけへ置換する。
  本文のない上限拒否文書は削除する。
- representative_answers: 会話ランダムキーを文書IDとする3フィールド構成へ
  再配置し、旧文書を削除する。

前提: 旧形式で書き込むアプリインスタンスが停止していること（計画書の
リリース順参照）。dry-runと本適用は冪等で、再実行して差分0を確認できる。
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from typing import Any, Dict, Optional


ALLOWED_CONVERSATION_FIELDS = ("question_text", "answer_text", "date")
ALLOWED_REPRESENTATIVE_FIELDS = (
    "question_text",
    "representative_answer",
    "date",
)
BATCH_SIZE_DEFAULT = 200

_Precondition: Optional[type] = None
try:  # google-cloud-firestore 2.5+ の書き込みprecondition
    from google.cloud.firestore_v1 import Precondition as _Precondition  # type: ignore
except ImportError:  # pragma: no cover - 旧SDK環境
    try:
        from google.cloud.firestore_v1.base_precondition import (  # type: ignore
            Precondition as _Precondition,
        )
    except ImportError:
        _Precondition = None


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を解釈する。"""
    parser = argparse.ArgumentParser(
        description=(
            "conversations / representative_answers を質問・回答・日付のみの"
            "構成へ移行する（既定はdry-run）"
        )
    )
    parser.add_argument("--project", required=True, help="GCPプロジェクトID")
    parser.add_argument("--database", required=True, help="FirestoreデータベースID")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="実際に書き込む（未指定時はdry-runで変更しない）",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE_DEFAULT,
        help="1ページあたりの処理件数",
    )
    return parser.parse_args()


def to_date_str(value: Any) -> Optional[str]:
    """ISO文字列・date風の値からYYYY-MM-DD部分を取り出す。"""
    if isinstance(value, str) and len(value) >= 10 and value[4] == "-":
        return value[:10]
    return None


def set_replacing(doc_ref: Any, data: Dict[str, Any], update_time: Any) -> str:
    """全文書置換で書き込む。可能なら更新時刻preconditionを付ける。"""
    if _Precondition is not None and update_time is not None:
        try:
            doc_ref.set(data, precondition=_Precondition(update_time=update_time))
            return "precondition"
        except TypeError:
            # SDKがprecondition引数に対応していない場合は通常setへフォールバック
            pass
    doc_ref.set(data)
    return "plain"


def delete_doc(doc_ref: Any, update_time: Any) -> str:
    """可能なら更新時刻precondition付きで削除する。"""
    if update_time is not None:
        try:
            doc_ref.delete(last_update_time=update_time)
            return "precondition"
        except TypeError:
            pass
    doc_ref.delete()
    return "plain"


def iter_documents(collection, batch_size: int):
    """start_afterでページングしながら全スナップショットを返す。"""
    query = collection.order_by("__name__").limit(batch_size)
    last_snapshot = None
    while True:
        if last_snapshot is not None:
            query = (
                collection.order_by("__name__")
                .start_after(last_snapshot)
                .limit(batch_size)
            )
        docs = list(query.get())
        if not docs:
            return
        for snapshot in docs:
            yield snapshot
        last_snapshot = docs[-1]


def migrate_conversations(db, apply: bool, batch_size: int) -> Dict[str, Any]:
    """conversationsを3フィールド構成へ移行する。"""
    counts: Dict[str, Any] = {
        "scanned": 0,
        "rewritten": 0,
        "deleted_bodyless": 0,
        "skipped_invalid": 0,
        "missing_date": 0,
        "errors": 0,
    }
    removed_field_names: Counter[str] = Counter()
    collection = db.collection("conversations")

    for snapshot in iter_documents(collection, batch_size):
        counts["scanned"] += 1
        try:
            data = snapshot.to_dict() or {}
            question_text = data.get("question_text")
            answer_text = data.get("answer_text")

            if not question_text and not answer_text:
                # 本文なし（旧・上限拒否メタデータ）は削除対象
                removed_field_names.update(data.keys())
                if apply:
                    delete_doc(snapshot.reference, snapshot.update_time)
                counts["deleted_bodyless"] += 1
                continue

            if not isinstance(question_text, str) or not isinstance(answer_text, str):
                # 想定外の形式は値を触らず報告だけする
                counts["skipped_invalid"] += 1
                continue

            date_value = to_date_str(data.get("date")) or to_date_str(
                data.get("created_at")
            )
            if date_value is None:
                # 日付が復元できない文書は空文字のまま残して報告する
                counts["missing_date"] += 1
            new_data = {
                "question_text": question_text,
                "answer_text": answer_text,
                "date": date_value or "",
            }
            removed_field_names.update(
                name for name in data.keys() if name not in ALLOWED_CONVERSATION_FIELDS
            )
            if apply:
                set_replacing(snapshot.reference, new_data, snapshot.update_time)
            counts["rewritten"] += 1
        except Exception:  # noqa: BLE001 - 1件の失敗で全体を止めない
            counts["errors"] += 1

    counts["removed_field_names"] = dict(removed_field_names)
    return counts


def migrate_representative_answers(db, apply: bool, batch_size: int) -> Dict[str, Any]:
    """representative_answersを会話キー文書の3フィールド構成へ移行する。"""
    counts: Dict[str, Any] = {
        "scanned": 0,
        "rewritten_in_place": 0,
        "moved": 0,
        "skipped_missing_conversation": 0,
        "skipped_invalid": 0,
        "errors": 0,
    }
    removed_field_names: Counter[str] = Counter()
    collection = db.collection("representative_answers")

    for snapshot in iter_documents(collection, batch_size):
        counts["scanned"] += 1
        try:
            data = snapshot.to_dict() or {}
            conversation_id = data.get("conversation_id")
            question_text = data.get("question_text")
            representative_answer = data.get("representative_answer")

            if not isinstance(conversation_id, str) or not conversation_id:
                counts["skipped_missing_conversation"] += 1
                continue
            if not isinstance(representative_answer, str):
                counts["skipped_invalid"] += 1
                continue

            date_value = to_date_str(data.get("date")) or to_date_str(
                data.get("created_at") or data.get("updated_at")
            )
            new_data = {
                "question_text": (
                    question_text if isinstance(question_text, str) else None
                ),
                "representative_answer": representative_answer,
                "date": date_value,
            }
            removed_field_names.update(
                name
                for name in data.keys()
                if name not in ALLOWED_REPRESENTATIVE_FIELDS
            )

            if apply:
                target_ref = collection.document(conversation_id)
                if snapshot.id == conversation_id:
                    set_replacing(target_ref, new_data, snapshot.update_time)
                    counts["rewritten_in_place"] += 1
                else:
                    # 目標文書が既にある場合は移行で上書き（同一会話1件維持）
                    set_replacing(target_ref, new_data, None)
                    delete_doc(snapshot.reference, snapshot.update_time)
                    counts["moved"] += 1
            else:
                if snapshot.id == conversation_id:
                    counts["rewritten_in_place"] += 1
                else:
                    counts["moved"] += 1
        except Exception:  # noqa: BLE001 - 1件の失敗で全体を止めない
            counts["errors"] += 1

    counts["removed_field_names"] = dict(removed_field_names)
    return counts


def main() -> int:
    """スクリプトのエントリポイント。"""
    args = parse_args()
    if args.batch_size < 1:
        print("--batch-size must be >= 1")
        return 2

    from google.cloud import firestore as firestore_module

    db = firestore_module.Client(project=args.project, database=args.database)

    print(f"mode={'apply' if args.apply else 'dry-run'} database={args.database}")

    conversation_counts = migrate_conversations(db, args.apply, args.batch_size)
    removed = conversation_counts.pop("removed_field_names", {})
    print("conversations:")
    for key, value in conversation_counts.items():
        print(f"  {key}: {value}")
    if removed:
        print(f"  removed_field_names: {', '.join(sorted(removed))}")

    representative_counts = migrate_representative_answers(
        db, args.apply, args.batch_size
    )
    removed = representative_counts.pop("removed_field_names", {})
    print("representative_answers:")
    for key, value in representative_counts.items():
        print(f"  {key}: {value}")
    if removed:
        print(f"  removed_field_names: {', '.join(sorted(removed))}")

    if args.apply and (
        conversation_counts.get("errors") or representative_counts.get("errors")
    ):
        print("completed with errors")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
