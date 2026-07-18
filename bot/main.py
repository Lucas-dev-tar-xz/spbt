import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from subs import SubscriptionIndex, init_db

from .handlers import router
from .middleware import AdminOnlyMiddleware, IndexMiddleware

load_dotenv()

logger = logging.getLogger(__name__)

bot = Bot(
    token=os.getenv("telegram_bot_token"),
    default=DefaultBotProperties(parse_mode="HTML"),
)


def create_dispatcher(index: SubscriptionIndex) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(AdminOnlyMiddleware())
    dp.update.middleware(IndexMiddleware(index))
    dp.include_router(router)
    return dp


async def run_bot(index: SubscriptionIndex) -> None:
    init_db()
    dp = create_dispatcher(index)
    logger.info("Telegram-бот запущен (admin: %s)", os.getenv("ADMIN_USER_ID", "5359181591"))
    await dp.start_polling(bot)


async def run_bot_standalone() -> None:
    """Запуск только бота без снайпера — для отладки."""
    init_db()
    index = SubscriptionIndex.load_from_db()
    await run_bot(index)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(run_bot_standalone())
