#!/usr/bin/env python3
"""
shoulder 知識ファイル（journal×3 + self×1）を既存RAGコーパスへ登録する。

ローカル1回限りの実行を想定（shoulder ソースはローカルパス）。
.env / Secret Manager の GOOGLE_CORPUS_ID が指すコーパスへ追記する。

実行前: gcloud auth application-default login（ADC）
実行: GRPC_DNS_RESOLVER=native ./venv/bin/python scripts/upload_shoulder_corpus.py
"""

import os
import sys

import vertexai
from vertexai import rag

PROJECT_ID = "takahashi-451312"
LOCATION = "us-central1"
CORPUS_ID = "1766660099138387968"
CORPUS_NAME = f"projects/{PROJECT_ID}/locations/{LOCATION}/ragCorpora/{CORPUS_ID}"

# shoulder 知識ソース（学術エビデンス journal 3件 + 評価/介入手順 self 1件）
SOURCE_DIR = "/Users/takahashiyoshiki/Desktop/local dev/rag_source/source/shoulder"
FILES = [
    "shoulder_journal.md",
    "shoulder_journal2.md",
    "shoulder_journal3.md",
    "shoulder_self.md",
]


def main() -> int:
    if not os.path.isdir(SOURCE_DIR):
        print(f"ERROR: SOURCE_DIR not found: {SOURCE_DIR}", file=sys.stderr)
        return 1

    vertexai.init(project=PROJECT_ID, location=LOCATION)

    # 既存ファイル一覧（display_name 重複回避）
    try:
        existing = {
            getattr(f, "display_name", "")
            for f in rag.list_files(corpus_name=CORPUS_NAME)
        }
    except Exception as e:
        print(f"WARNING: list_files failed ({e}); upload without dedup", file=sys.stderr)
        existing = set()

    for fname in FILES:
        path = os.path.join(SOURCE_DIR, fname)
        if not os.path.exists(path):
            print(f"SKIP (not found): {fname}", file=sys.stderr)
            continue
        display = os.path.splitext(fname)[0]
        if display in existing:
            print(f"SKIP (already uploaded): {fname}")
            continue
        try:
            rag_file = rag.upload_file(
                corpus_name=CORPUS_NAME,
                path=path,
                display_name=display,
                description=f"shoulder knowledge: {display}",
            )
            print(f"[OK] {fname} -> {rag_file.name}")
        except Exception as e:
            print(f"[ERR] {fname}: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
