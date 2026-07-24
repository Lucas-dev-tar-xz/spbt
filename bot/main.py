import asyncio
import logging
import os
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from subs import SubscriptionIndex, init_db
from buy_tokens import init_buy_tokens_db

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
    init_buy_tokens_db()
    dp = create_dispatcher(index)
    logger.info("Telegram-бот запущен (admin: %s)", os.getenv("ADMIN_USER_ID", "5359181591"))
    await dp.start_polling(bot, handle_signals=False)


async def run_bot_standalone() -> None:
    """Запуск только бота без снайпера — для отладки."""
    init_db()
    index = SubscriptionIndex.load_from_db()
    task_bot = asyncio.create_task(run_bot(index))
    try:
        await task_bot
    except asyncio.CancelledError:
        logger.info("Получен сигнал остановки (Ctrl+C)...")
        raise
    finally:
        if not task_bot.done():
            task_bot.cancel()
            with suppress(asyncio.CancelledError):
                await task_bot


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(run_bot_standalone())
