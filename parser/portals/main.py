import asyncio
from aiolimiter import AsyncLimiter

import aiohttp
import logging
from typing import Any

from subs import SubscriptionIndex, Gift, init_db

from aiogram import Bot

from config import LOGS, CHANGES_CHAT, CHANGES_CHAT_PORTALS, user_agent

from datetime import datetime

from itertools import cycle


limiter = AsyncLimiter(15, 2)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class MyError(Exception):
    def __init__(self, message: str, code: int = 0):
        self.code = code
        super().__init__(message)


class PORTALS:
    def __init__(self, bot: Bot, tokens: list, buy_token: str, poll_delay: int | float = 0.2):
        self.bot = bot
        self.sessions: list[aiohttp.ClientSession | None] = []
        self.buy_session: aiohttp.ClientSession | None = None

        self.tokens = tokens
        self.buy_token = buy_token
        self.poll_delay = poll_delay

        self.parse_url = "https://portal-market.com/api/market/actions/?offset=0&limit=20&action_types=listing,price_update"
        self.buy_url = "https://portal-market.com/api/nfts"

        self.buy_headers = {
            "Authorization": f"tma {self.buy_token}",
            "User-Agent": user_agent,
            "Accept": "application/json",
            "Content-Type": "application/json"
        }



    async def close_sessions(self) -> None:
        for session in self.sessions:
            if session and not session.closed:
                await session.close()
        self.sessions = []

        if self.buy_session and not self.buy_session.closed:
            await self.buy_session.close()
        self.buy_session = None


    async def update_parse_sessions(self):
        await self.close_sessions()

        tokens = self.tokens
        self.sessions = []

        for token in tokens:
            headers = await self.get_parse_headers(token)
            session = aiohttp.ClientSession(headers=headers)
            self.sessions.append(session)

        self.buy_session = aiohttp.ClientSession(headers=self.buy_headers)


    async def update_tokens(self, tokens: list):
        self.tokens = tokens
        return 0


    async def update_buy_token(self, buy_token: str):
        self.buy_token = buy_token
        return 0


    async def update_bot(self, bot: Bot):
        self.bot = bot
        return 0


    @staticmethod
    async def get_parse_headers(token) -> dict:
        return {
            "Authorization": f"tma {token}",
            "User-Agent": user_agent,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }


    async def fetch_feed_page(self, session: aiohttp.ClientSession) -> dict[str, Any] | None:
        parse_url = self.parse_url

        try:
            async with session.get(url=parse_url) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 401:
                    raise MyError("Access Token устарел!", 401)
                elif response.status == 429:
                    logging.warning("⚠️ 429 Too Many Requests")
                else:
                    logging.warning(f"PORTALS | Ошибка во время парсинга feed: {response.status} | {await response.text()}")
        except MyError as e:
            text = (f"#error #error_portals #parse\n"
                    f"{datetime.now().strftime('%H:%M:%S %d.%m.%Y')}\n\n"
                    f"WH: {e}")

            await self.bot.send_message(LOGS, text=text)

            if e.code == 401:
                text = "ALERT: Replace Access Token for PORTALS!!!"
                await self.bot.send_message(5359181591, text=text)

        except Exception as e:
            logging.error(f"PORTALS | 📡 Ошибка сети при пуллинге: {e}")


        return None


    async def change(self, gift: Gift, c_type: str):
        """text = (f"<a href='https://t.me/nft/{gift.gift_name}-'>GIFT</a>\n"
                f"Type: {c_type}\n"
                f"Price: {gift.price}\n\n"
                f"Collection: {gift.collection}\n"
                f"Model: {gift.model}\n"
                f"Backdrop: {gift.backdrop}\n"
                f"Pattern: {gift.pattern}")

        async with limiter:
            return 0
            #return await self.bot.send_message(chat_id=CHANGES_CHAT, text=text, message_thread_id=CHANGES_CHAT_PORTALS)"""
        return self.buy_url


    async def process_feed_item(self, item: dict[str, Any], index: SubscriptionIndex, buy_session: aiohttp.ClientSession) -> None:
        """Парсит реальный JSON-объект события из ленты PORTALS и отправляет в хот-пут матчер"""
        try:
            event_type = item.get("status")
            gift_data = item.get("nft")
            if not gift_data:
                return

            raw_amount = item.get("amount") or gift_data.get("price") or 0
            price_ton = float(raw_amount)

            attributes = {}
            for attr in gift_data.get("attributes"):
                attributes[attr.get("type")] = attr.get("value")


            gift = Gift(
                collection=gift_data.get("name", "Unknown"),
                model=attributes.get("model"),
                backdrop=attributes.get("backdrop"),
                pattern=attributes.get("symbol"),
                price=price_ton,
                gift_id=gift_data.get("id"),
                gift_name=gift_data.get("external_collection_number", "1")
            )


            matches = index.find_matches(gift)
            if matches:
                logging.info(
                    f"-----------------------------------\n"
                    f"🎯 [MATCH]\n"
                    f"Type: {event_type}\n"
                    f"Price: {gift.price}\n"
                    f"Collection: {gift.collection}\n"
                    f"Model: {gift.model}\n"
                    f"Backdrop: {gift.backdrop}\n"
                    f"Pattern: {gift.pattern}\n"
                    f"-----------------------------------"
                )


                sub = matches[0]
                asyncio.create_task(self.execute_buy(sub=sub, gift=gift, buy_session=buy_session))
            await self.change(gift=gift, c_type=event_type)
        except Exception as e:
            logging.error(f" Ошибка при разборе айтема ленты PORTALS: {e}", exc_info=True)


    async def execute_buy(self, sub, gift: Gift, buy_session: aiohttp.ClientSession) -> None:
        """
        Моментально отправляет запрос на покупку гифта.
        Использует существующую сессию для экономии времени на TLS-handshake.
        """
        gift_id = gift.gift_id

        buy_url = self.buy_url

        payload = {
            "nft_details": [
                {
                    "id": gift.gift_id,
                    "price": gift.price
                }
            ]
        }

        logging.info(
            f"🛒 [BUY TRIGGER] Отправляем запрос на покупку {gift_id} за {gift.price} TON для юзера {sub.user_id}...")

        try:
            async with buy_session.post(buy_url, json=payload) as response:
                if response.status in (200, 201):
                    response.raise_for_status()
                    res_data = await response.json()
                    if not res_data:
                        logging.error(f"❌ [BUY FAILED] Не успели")
                        return
                    logging.info(f"✅ [SUCCESS] Покупка успешно совершена! Ответ сервера: {res_data}")
                    text = (
                        f"NEW BUY!!!\n\n"
                        f"{gift.collection} {gift.gift_name} bought for {gift.price}\n"
                        f"Collection: {gift.collection}\n"
                        f"Model: {gift.model}\n"
                        f"Backdrop: {gift.backdrop}\n"
                        f"Symbol: {gift.pattern}\n\n"
                        f"Market: PORTALS"
                    )
                    await self.bot.send_message(5359181591, text=text, parse_mode='HTML')
                    await self.bot.send_message(LOGS, text=text, parse_mode='HTML')
                elif response.status == 401:
                    raise MyError("Access Token устарел!", 401)
                elif response.status == 429:
                    logging.error(f"❌ [RATE LIMIT] Поймали 429 при попытке покупки листинга {gift_id}!")
                else:
                    res_text = await response.text()
                    logging.error(f"❌ [BUY FAILED] Сервер вернул код {response.status}. Ответ: {res_text}")
        except Exception as e:
            logging.error(f"🚨 [BUY ERROR] Ошибка сети при отправке запроса на покупку: {e}")



    async def pooling(self, index: SubscriptionIndex | None = None):
        logging.info(" PORTALS | Начинаю pooling...")
        init_db()
        if index is None:
            index = SubscriptionIndex.load_from_db()

        processed_event_ids: set[str] = set()
        is_first_run = True

        try:
            for session in cycle(self.sessions):
                data = await self.fetch_feed_page(session)

                if data and "actions" in data:
                    items = data.get("actions", [])

                    for item in reversed(items):
                        event_id = str(item.get("id"))

                        if event_id not in processed_event_ids:
                            processed_event_ids.add(event_id)

                            if not is_first_run:
                                asyncio.create_task(self.process_feed_item(item=item, index=index, buy_session=self.buy_session))


                    is_first_run = False

                    if len(processed_event_ids) > 500:
                        processed_event_ids = set(list(processed_event_ids)[-200:])

                await asyncio.sleep(self.poll_delay)
        except asyncio.CancelledError:
            logging.info("PORTALS | Остановка pooling...")
            raise
