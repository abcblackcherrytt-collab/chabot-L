"""Container buildに一時認証情報を混入させないための回帰テスト。"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_google_auth_credentials_are_excluded_from_git_and_docker() -> None:
    """GitHub Actionsが生成する認証JSONを追跡・COPY対象から除外すること。"""
    for filename in (".gitignore", ".dockerignore"):
        contents = (PROJECT_ROOT / filename).read_text(encoding="utf-8")
        assert "gha-creds-*.json" in contents
