"""
設定管理モジュール
環境変数とアプリケーション設定を管理します。
"""

from typing import List
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """アプリケーション設定"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # 余分な環境変数を無視
        env_nested_delimiter="",  # 自動的なリスト変換を無効化
    )

    # アプリケーション設定
    app_name: str = "chabot"
    app_env: str = "development"
    debug: bool = True
    api_version: str = "v1"

    # サーバー設定
    host: str = "0.0.0.0"
    port: int = 8000

    # データベース設定
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/chabot"

    # JWT認証設定（カンマ区切りの文字列で指定）
    jwt_secret_keys: str = "your-secret-key-here"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7
    jwt_key_rotation_days: int = 90

    # LINE Messaging API設定
    line_channel_secret: str = ""
    line_channel_access_token: str = ""
    line_api_base_url: str = "https://api.line.me"

    # LINE Login（OIDC）設定
    line_login_channel_id: str = ""
    line_login_channel_secret: str = ""
    line_login_callback_url: str = ""

    # Stripe設定
    stripe_secret_key: str = "sk_test_your-stripe-secret-key"
    stripe_webhook_secret: str = "whsec_your-webhook-secret"
    stripe_publishable_key: str = "pk_test_your-stripe-publishable-key"

    # Google Cloud Vertex AI設定
    google_project_id: str = "your-project-id"
    google_location: str = "asia-northeast1"
    google_corpus_id: str = "your-corpus-id"

    # CORS設定（カンマ区切りの文字列またはリスト）
    cors_allowed_origins: List[str] = ["http://localhost:3000", "http://localhost:8000"]

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        """CORS許可オリジンをパースします"""
        if isinstance(v, str):
            # JSON形式またはカンマ区切りの文字列に対応
            if v.startswith("["):
                import json
                try:
                    return json.loads(v)
                except json.JSONDecodeError:
                    pass
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @property
    def cors_allowed_origins_list(self) -> List[str]:
        """CORS許可オリジンのリストを返します"""
        if isinstance(self.cors_allowed_origins, str):
            return [origin.strip() for origin in self.cors_allowed_origins.split(";") if origin.strip()]
        return self.cors_allowed_origins

    @property
    def jwt_secret_keys_list(self) -> List[str]:
        """JWTシークレットキーのリストを返します"""
        if isinstance(self.jwt_secret_keys, str):
            return [key.strip() for key in self.jwt_secret_keys.split(",") if key.strip()]
        return self.jwt_secret_keys


settings = Settings()
