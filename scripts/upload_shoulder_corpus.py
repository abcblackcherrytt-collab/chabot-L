#!/usr/bin/env python3
"""
shoulder 知識ファイル（thinking 推論メモ 13件）を実RAGコーパスへ登録する。

ローカル1回限りの実行を想定（shoulder ソースはローカルパス）。
Secret Manager で使用中のコーパス（1495705249682292736）へ追記する。
既存ファイルは display_name 重複回避で SKIP（未登録分のみ追記される）。

実行前: gcloud auth application-default login（ADC）
実行: GRPC_DNS_RESOLVER=native ./venv/bin/python scripts/upload_shoulder_corpus.py
"""

import os
import sys

import vertexai
from vertexai import rag

PROJECT_ID = "takahashi-451312"
LOCATION = "us-central1"
CORPUS_ID = "1495705249682292736"
CORPUS_NAME = f"projects/{PROJECT_ID}/locations/{LOCATION}/ragCorpora/{CORPUS_ID}"

# shoulder 知識ソース（thinking 推論メモ 12件）
SOURCE_DIR = "/Users/takahashiyoshiki/Desktop/local dev/rag_source/source_self/shoulder/md_for_rag"
FILES = [
    "thinking_2026-05-04_shoulder_frozen-stage_fibrosis-assessment-and-remodeling-strategy.md",
    "thinking_2026-05-04_shoulder_lateral-pain-passive-assessment_differential-reasoning.md",
    "thinking_2026-05-07_sab_manual_intervention.md",
    "thinking_2026-05-07_shoulder_outpatient_initial_assessment.md",
    "thinking_2026-05-12_shoulder_inflammation_assessment.md",
    "thinking_2026-05-19_shoulder_postop_dynamic_strain_fibrosis.md",
    "thinking_2026-05-23_rotator-cuff-tear-pain-source-stage-reasoning.md",
    "thinking_2026-05-28_shoulder_capsule-contracture-rehab-reasoning.md",
    "thinking_2026-05-28_shoulder_type-e-rupture-conservative-compensation.md",
    "thinking_2026-06-11_shoulder_murakami-instability-eccentric-setting.md",
    "thinking_2026-07-24_shoulder_rotator-cuff-motor-learning-dynamic-function.md",
    "thinking_2026-07-27_shoulder_first-external-rotation-trajectory-and-restriction.md",
    "thinking_2026-07-27_shoulder_second-position-rotation-muscular-soft-tissue-differential.md",
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
        display = fname  # .md 付き（既存ファイルの display_name 形式に合わせて重複チェックを正しく機能させる）
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
