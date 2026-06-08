"""
Discord スラッシュコマンド登録スクリプト

Discord Applicationにスラッシュコマンドを登録します。
本番デプロイ後やコマンド定義を変更した際に実行してください。

使い方:
    python scripts/register_discord_commands.py

必要な環境変数:
    DISCORD_BOT_TOKEN: Bot Token
    DISCORD_APPLICATION_ID: アプリケーションID
    DISCORD_GUILD_ID: ギルドID（ギルド固有コマンドの場合）
"""

import json
import os
import sys

import httpx


def get_env_vars() -> tuple[str, str, str]:
    """
    必要な環境変数を取得します

    Returns:
        (bot_token, application_id, guild_id) のタプル
    """
    # .envファイルから読み込みを試行
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    bot_token = os.getenv("DISCORD_BOT_TOKEN")
    application_id = os.getenv("DISCORD_APPLICATION_ID") or os.getenv("APPLICATION_ID")
    guild_id = os.getenv("DISCORD_GUILD_ID")

    if not bot_token:
        print("エラー: DISCORD_BOT_TOKENが設定されていません")
        sys.exit(1)

    if not application_id:
        print("エラー: DISCORD_APPLICATION_IDが設定されていません")
        sys.exit(1)

    if not guild_id:
        print("エラー: DISCORD_GUILD_IDが設定されていません")
        sys.exit(1)

    return bot_token, application_id, guild_id


# 登録するスラッシュコマンドの定義
COMMANDS = [
    {
        "name": "chat",
        "description": "AIチャットボットに質問します",
        "options": [
            {
                "name": "message",
                "description": "質問やメッセージを入力してください",
                "type": 3,  # STRING
                "required": True,
            },
        ],
    },
]


async def register_commands(
    bot_token: str,
    application_id: str,
    guild_id: str,
) -> None:
    """
    スラッシュコマンドをDiscordに登録します

    ギルド固有のコマンドとして登録します（即座に反映されます）。

    Args:
        bot_token: Bot Token
        application_id: アプリケーションID
        guild_id: ギルドID
    """
    base_url = "https://discord.com/api/v10"
    url = f"{base_url}/applications/{application_id}/guilds/{guild_id}/commands"

    headers = {
        "Authorization": f"Bot {bot_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        # 既存コマンドを一括上書き
        print(f"コマンドを登録中: {url}")
        print(f"コマンド数: {len(COMMANDS)}")
        for cmd in COMMANDS:
            print(f"  - /{cmd['name']}: {cmd['description']}")

        response = await client.put(url, headers=headers, json=COMMANDS)

        if response.status_code in (200, 201):
            print("✅ コマンドの登録に成功しました")
            result = response.json()
            for cmd in result:
                print(f"  - /{cmd['name']} (ID: {cmd['id']})")
        else:
            print(f"❌ コマンドの登録に失敗しました (status: {response.status_code})")
            print(f"   レスポンス: {response.text}")
            sys.exit(1)


def main() -> None:
    """メイン処理"""
    print("=== Discord スラッシュコマンド登録 ===")
    bot_token, application_id, guild_id = get_env_vars()

    import asyncio
    asyncio.run(register_commands(bot_token, application_id, guild_id))


if __name__ == "__main__":
    main()
