import asyncio
from aiolimiter import AsyncLimiter

from curl_cffi.requests import AsyncSession
import logging
from typing import Any

from subs import SubscriptionIndex, Gift, init_db

from aiogram import Bot

from config import LOGS, CHANGES_CHAT, CHANGES_CHAT_TONNEL

from datetime import datetime

from itertools import cycle

from time import time

import os
import base64
import hashlib

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad


def evp_bytes_to_key(password: bytes, salt: bytes, key_len=32, iv_len=16):
    d = b""
    last = b""

    while len(d) < key_len + iv_len:
        last = hashlib.md5(last + password + salt).digest()
        d += last

    return d[:key_len], d[key_len:key_len + iv_len]


def encrypt_cryptojs(text: str, password: str) -> str:
    salt = os.urandom(8)

    key, iv = evp_bytes_to_key(password.encode(), salt)

    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(pad(text.encode(), AES.block_size))

    return base64.b64encode(b"Salted__" + salt + encrypted).decode()


limiter = AsyncLimiter(10, 2)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class MyError(Exception):
    def __init__(self, message: str, code: int = 0):
        self.code = code
        super().__init__(message)


class TONNEL:
    def __init__(self, bot: Bot, tokens: list, buy_token: str, poll_delay: int | float = 0.2):
        self.bot = bot
        self.parse_json_data: list[dict | None] = []
        self.buy_session: AsyncSession | None = None
        self.parse_session: AsyncSession | None = None

        self.tokens = tokens
        self.buy_token = buy_token
        self.poll_delay = poll_delay

        self.parse_url = "https://gifts2.tonnel.network/api/pageGifts"
        self.buy_url = "https://gifts.coffin.meme/api/buyGift/"


        self.parse_headers = {
            "Accept": "json",
            "Accept-Encoding": "json, gzip, deflate",
            "Accept-Language": "ru",
            "Content-Type": "application/json",
            "Origin": "https://marketplace.tonnel.network",
            "Priority": "u=3, i",
            "Referer": "https://marketplace.tonnel.network/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)",
        }

        self.buy_headers = {
            "Accept": "json",
            "Accept-Encoding": "json, gzip, deflate",
            "Accept-Language": "ru",
            "Content-Type": "application/json",
            "Origin": "https://marketplace.tonnel.network",
            "Priority": "u=3, i",
            "Referer": "https://marketplace.tonnel.network/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)",
        }




    async def close_sessions(self) -> None:
        if self.parse_session:
            await self.parse_session.close()
        self.parse_session = None

        if self.buy_session:
            await self.buy_session.close()
        self.buy_session = None


    async def init(self):
        self.parse_session = AsyncSession(headers=self.parse_headers, impersonate="chrome136")
        self.buy_session = AsyncSession(headers=self.buy_headers, impersonate="chrome136")
        await self.update_parse_jsons()


    async def update_parse_jsons(self):
        self.parse_json_data = []

        for token in self.tokens:
            json = {
                "page": 1,
                "limit": 30,
                "sort": '{"message_post_time":-1,"gift_id":-1}',
                "filter": '{"price":{"$exists":true},"buyer":{"$exists":false},"asset":"TON"}',
                "ref": 0,
                "price_range": None,
                "user_auth": token
            }
            self.parse_json_data.append(json)


    async def get_buy_data(self, gift_id: str, price: int | float):
        now = int(time())
        url = self.buy_url + gift_id
        json = {
            "authData": self.buy_token,
            "asset": "TON",
            "price": price,
            "timestamp": now,
            "wtf": encrypt_cryptojs(str(now), "yowtfisthispieceofshitiiit")
        }
        return url, json


    async def fetch_feed_page(self, payload: dict) -> list[dict] | None:
        parse_url = self.parse_url
        session = self.parse_session

        try:
            if parse_url:
                response = await session.post(url=parse_url, json=payload)
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 401:
                    raise MyError("TONNEL Access Token устарел!", 401)
                elif response.status_code == 429:
                    logging.warning("TONNEL ⚠️ 429 Too Many Requests")
                else:
                    logging.warning(f"TONNEL | Ошибка во время парсинга feed: {response.status_code}")
        except MyError as e:
            text = (f"#error #error_tonnel #parse\n"
                    f"{datetime.now().strftime('%H:%M:%S %d.%m.%Y')}\n\n"
                    f"WH: {e}")

            await self.bot.send_message(LOGS, text=text)

            if e.code == 401:
                text = "ALERT: Replace Access Token for TONNEL!!!"
                await self.bot.send_message(5359181591, text=text)

        except Exception as e:
            logging.error(f"TONNEL | 📡 Ошибка сети при пуллинге: {e}")


        return None


    async def process_feed_item(self, item: dict[str, Any], index: SubscriptionIndex) -> None:
        try:
            if not item:
                return

            raw_amount = item.get("price")
            price_ton = float(raw_amount)


            gift = Gift(
                collection=item.get("name", "Unknown"),
                model=item.get("model"),
                backdrop=item.get("backdrop"),
                pattern=item.get("symbol"),
                price=price_ton,
                gift_id=item.get("gift_id"),
                gift_name=item.get("gift_num", "1")
            )


            matches = index.find_matches(gift)
            if matches:
                logging.info(
                    f"-----------------------------------\n"
                    f"🎯 [TONNEL MATCH]\n"
                    f"Price: {gift.price}\n"
                    f"Collection: {gift.collection}\n"
                    f"Model: {gift.model}\n"
                    f"Backdrop: {gift.backdrop}\n"
                    f"Pattern: {gift.pattern}\n"
                    f"-----------------------------------"
                )


                sub = matches[0]
                asyncio.create_task(self.execute_buy(sub=sub, gift=gift))

        except Exception as e:
            logging.error(f"Ошибка при разборе айтема ленты TONNEL: {e}", exc_info=True)


    async def execute_buy(self, sub, gift: Gift) -> None:
        """
        Моментально отправляет запрос на покупку гифта.
        Использует существующую сессию для экономии времени на TLS-handshake.
        """
        gift_id = gift.gift_id
        buy_session = self.buy_session

        buy_url, payload = await self.get_buy_data(gift_id=gift_id, price=gift.price)

        logging.info(
            f"🛒 [TONNEL BUY TRIGGER] Отправляем запрос на покупку {gift_id} за {gift.price} TON для юзера {sub.user_id}...")

        try:
            if buy_url:
                response = await buy_session.post(
                    url=buy_url,
                    json=payload
                )
                response.raise_for_status()

                if response.status_code in (200, 201):
                    res_data = await response.json()
                    if not res_data:
                        logging.error(f"❌ [TONNEL BUY FAILED] Не успели")
                        return
                    if res_data.get("status") == "error":
                        logging.error(f"❌ [TONNEL BUY FAILED] {res_data.get('message')}")
                        return
                    logging.info(f"✅ [TONNEL SUCCESS] Покупка успешно совершена! Ответ сервера: {res_data}")
                    text = (
                        f"NEW BUY!!!\n\n"
                        f"Gift {gift.collection} #{gift.gift_name} bought for {gift.price}\n"
                        f"Collection: {gift.collection}\n"
                        f"Model: {gift.model}\n"
                        f"Backdrop: {gift.backdrop}\n"
                        f"Symbol: {gift.pattern}\n\n"
                        f"Market: TONNEL"
                    )
                    await self.bot.send_message(chat_id=5359181591, text=text, parse_mode='HTML')
                    await self.bot.send_message(chat_id=LOGS, text=text, parse_mode="HTML")
                elif response.status_code == 401:
                    raise MyError("TONNEL Access Token устарел!", 401)
                elif response.status_code == 429:
                    logging.error(f"❌ [TONNEL RATE LIMIT] Поймали 429 при попытке покупки листинга {gift_id}!")
                else:
                    res_text = response.text
                    logging.error(f"❌ [TONNEL BUY FAILED] Сервер вернул код {response.status}. Ответ: {res_text}")
        except Exception as e:
            logging.error(f"🚨 [TONNEL BUY ERROR] Ошибка сети при отправке запроса на покупку: {e}")


    async def pooling(self, index: SubscriptionIndex | None = None):
        logging.info("TONNEL | Начинаю pooling...")
        init_db()
        if index is None:
            index = SubscriptionIndex.load_from_db()

        processed_event_ids: set[str] = set()
        is_first_run = True

        try:
            for payload in cycle(self.parse_json_data):
                data = await self.fetch_feed_page(payload)

                if data:
                    items = data

                    for item in reversed(items):
                        event_id = item.get("gift_num")

                        if event_id not in processed_event_ids:
                            processed_event_ids.add(event_id)

                            if not is_first_run:
                                asyncio.create_task(self.process_feed_item(item=item, index=index))


                    is_first_run = False

                    if len(processed_event_ids) > 500:
                        processed_event_ids = set(list(processed_event_ids)[-200:])

                await asyncio.sleep(self.poll_delay)
        except asyncio.CancelledError:
            logging.info("TONNEL | Остановка pooling...")
            raise

