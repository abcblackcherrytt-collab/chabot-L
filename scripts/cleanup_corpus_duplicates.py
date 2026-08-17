#!/usr/bin/env python3
"""
重複登録されたコーパスファイル（.md なし display_name）を削除する。

前回 upload_shoulder_corpus.py が display_name の拡張子不一致で
重複検知できず、.md なしで再登録した分をクリーンアップする。
.md 付き（既存・正）は保持する。

実行（確認のみ・削除しない）:
  GRPC_DNS_RESOLVER=native ./venv/bin/python scripts/cleanup_corpus_duplicates.py

実行（実際に削除）:
  GRPC_DNS_RESOLVER=native ./venv/bin/python scripts/cleanup_corpus_duplicates.py --apply
"""

import sys

import vertexai
from vertexai import rag

PROJECT_ID = "takahashi-451312"
LOCATION = "us-central1"
CORPUS_ID = "1495705249682292736"
CORPUS_NAME = f"projects/{PROJECT_ID}/locations/{LOCATION}/ragCorpora/{CORPUS_ID}"

APPLY = "--apply" in sys.argv


def main() -> int:
    vertexai.init(project=PROJECT_ID, location=LOCATION)

    deleted = 0
    kept = 0
    for f in rag.list_files(corpus_name=CORPUS_NAME):
        dn = getattr(f, "display_name", "")
        is_dup = not dn.endswith(".md")  # .md なし＝重複登録分
        if is_dup:
            if APPLY:
                rag.delete_file(name=f.name)
                deleted += 1
                print(f"[DELETED] {dn}  ({f.name})")
            else:
                print(f"[DELETE?] {dn}  ({f.name})")
        else:
            kept += 1
            print(f"[KEEP]    {dn}")

    mode = "APPLIED（削除実行）" if APPLY else "DRY-RUN（削除なし・--apply で実行）"
    print(f"\n{mode}: deleted={deleted}, kept={kept}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
