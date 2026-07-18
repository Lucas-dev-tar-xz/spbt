from dotenv import load_dotenv
import os
import config
import logging
from pathlib import Path

import asyncio
import json
import urllib.parse

import httpx
from pyrogram import Client
from pyrogram.raw import functions, types


load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("pyrogram").setLevel(logging.WARNING)




async def mrkt_(session, api_id = 2040, api_hash = "b18441a1ff607e10a989891a5462e627"):
    mrkt = config.Bots.mrkt

    async def get_init_data(bot_username: str, app_short_name: str):
        async with Client(session, api_id, api_hash) as app:
            peer = await app.resolve_peer(bot_username)

            bot_input_user = types.InputUser(
                user_id=peer.user_id,
                access_hash=peer.access_hash,
            )

            web_view = await app.invoke(
                functions.messages.RequestAppWebView(
                    peer=peer,
                    app=types.InputBotAppShortName(
                        bot_id=bot_input_user,
                        short_name=app_short_name,
                    ),
                    platform="android",
                    write_allowed=True
                )
            )

            web_app_url = web_view.url
            fragment = web_app_url.split("#", 1)[1]
            params = urllib.parse.parse_qs(fragment)
            return params["tgWebAppData"][0]

    def extract_photo(init_data: str) -> str:
        parsed = urllib.parse.parse_qs(init_data)
        user_raw = parsed.get("user", ["{}"])[0]
        try:
            user_json = json.loads(user_raw)
        except (json.JSONDecodeError, TypeError):
            user_json = {}
        return user_json.get("photo_url", "")

    async def login(init_data: str, auth_url: str):
        payload = {
            "data": init_data,
            "photo": extract_photo(init_data),
            "appId": None,
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": config.user_agent,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(auth_url, json=payload, headers=headers)
            resp.raise_for_status()
            try:
                body = resp.json()
            except (json.JSONDecodeError, ValueError):
                body = {}
            return resp.cookies, body


    async def create_access_token():
        try:
            init_data = await get_init_data(bot_username=mrkt.bot_username, app_short_name=mrkt.app_short_name)
            cookies, body = await login(init_data, auth_url=mrkt.auth_url)

            token = (
                cookies.get("access_token")
                or body.get("access_token")
                or body.get("accessToken")
                or body.get("token")
            )

            if not token:
                logging.error(f"[Create mrkt token] Не удалось получить access_token: ни в cookies, ни в теле ответа авторизации он не найден. Тело ответа: {body!r}")
                return ""

            return token
        except Exception as e:
            logging.error(f"[Create mrkt token] {e}")


    token = await create_access_token()
    return token


class GetAccessToken:
    def __init__(self, session_path: Path):
        self.session_path = session_path

    @property
    async def mrkt(self):
        mrkt = await mrkt_(self.session_path)
        return mrkt






async def send_start(n: int = None):
    """
    Send /start to all markets (mrkt, portals, tonnel)
    :param n: n-session
    """
    current_dir = Path(__file__).resolve().parent

    if current_dir.name == "sessions":
        directory = current_dir
    else:
        directory = current_dir / "sessions"

    if n:
        session_files = [directory / f"{n}.session"]
    else:
        session_files = list(directory.glob("*.session"))

    for session_path in session_files:
        name_num = session_path.stem
        session = directory / name_num
        account_json = directory / f"{name_num}.json"

        if not account_json.exists():
            continue

        with open(account_json, 'r') as file:
            data = json.load(file)

        api_id = data.get('api_id', 0)
        api_hash = data.get('api_hash', 'abcdef123456')

        try:
            async with Client(name=str(session), api_id=api_id, api_hash=api_hash) as app:
                me = await app.get_me()

                for bot in config.telegram_bots:
                    error = ''
                    name = bot.get('name')
                    username = bot.get('bot_username')

                    try:
                        await app.send_message(username, '/start')
                        status = 1
                    except Exception as e:
                        status = 0
                        error = e

                    logging.info(
                        f"[Send Start] Account: {name_num} ({me.id}) | Bot: {name} | Status: {'✅' if status else '❌'}{f' | Error: {error}' if not status else ''}"
                    )
        except Exception as e:
            logging.error(f"Error on session {name_num}: {e}")








async def main():
    await send_start()


if __name__ == '__main__':
    asyncio.run(main())