#!/usr/bin/env python3
"""
RAG コーパスのメタデータとインポート済みファイル一覧を表示する。

ローカル実行（要 ADC）:
  gcloud auth application-default login
  GRPC_DNS_RESOLVER=native ./venv/bin/python scripts/list_corpus_files.py
"""

import vertexai
from vertexai import rag

PROJECT_ID = "takahashi-451312"
LOCATION = "us-central1"

# 実コーパスを先頭に。参考で旧コーパスIDも併記
CORPUS_IDS = [
    "1495705249682292736",  # ★ 実際の Secret Manager 設定コーパス（shoulder・アプリが使用中）
    "1766660099138387968",  # 旧コーパス（upload_shoulder_corpus.py ハードコード・メモリ旧記録）
    "6942545116196241408",  # .env GOOGLE_CORPUS_ID（旧変数・参考）
]


def main() -> int:
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    for cid in CORPUS_IDS:
        name = f"projects/{PROJECT_ID}/locations/{LOCATION}/ragCorpora/{cid}"
        print(f"\n=== Corpus {cid} ({LOCATION}) ===")
        try:
            c = rag.get_corpus(name=name)
            print(f"display_name : {getattr(c, 'display_name', '?')}")
            print(f"description : {getattr(c, 'description', '') or '(empty)'}")
        except Exception as e:
            print(f"  [get_corpus 失敗] {e}")
        print("files:")
        try:
            count = 0
            for f in rag.list_files(corpus_name=name):
                count += 1
                print(f"  - {getattr(f, 'display_name', '?')}  "
                      f"{getattr(f, 'gcs_uri', '') or ''}")
            if count == 0:
                print("  (ファイルなし)")
        except Exception as e:
            print(f"  [list_files 失敗] {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
