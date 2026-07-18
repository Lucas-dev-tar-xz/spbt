import asyncio
import logging

from sessions import GetAccessToken #, send_start
from pathlib import Path
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from parser import MRKT
from subs import SubscriptionIndex, init_db

from bot import bot, run_bot

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SESSIONS_DIR = Path(__file__).resolve().parent / "sessions"


mrkt_tokens = []
portals_tokens = []
tonnel_tokens = []



async def init_starting_sniper():
    global mrkt_tokens
    global portals_tokens
    global tonnel_tokens

    init_db()
    index = SubscriptionIndex.load_from_db()

    #await update_tokens()
    mrkt_tokens = ['f62ef789-d292-4074-95d6-3218add81066', 'f6b39ef7-8307-4b40-a4f4-24cc81d8ded1', '5f07b980-65fb-4b35-9caf-0d82716224ea', 'f107ebe8-dee2-4160-8ac5-edbc2f8a95b6', 'dbf9f453-0d5c-450c-86dd-45df3b34d93a', '62d0f148-1a1c-467b-89ec-a974bd4a96ac', '22add721-93a0-4954-93f0-6c0a90104540', '72acd4da-a788-4d4a-ab13-3e78c30c796a']
    await workers()

    print(mrkt_tokens)


    # ---------- Create Classes ---------- #
    mrkt = MRKT(bot=bot, tokens=mrkt_tokens, buy_token="f034640b-8830-4fbb-8654-8d913c7acadc", poll_delay=0.2)
    await mrkt.update_parse_sessions()

    # ---------- Pooling + Bot ---------- #
    task_bot = asyncio.create_task(run_bot(index))
    task_mrkt = asyncio.create_task(mrkt.pooling(index=index))

    try:
        await asyncio.gather(task_bot, task_mrkt)
    finally:
        for task in (task_bot, task_mrkt):
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        await mrkt.close_sessions()
        logging.info("MRKT | Все HTTP-сессии закрыты")




async def update_tokens():
    global mrkt_tokens
    global portals_tokens
    global tonnel_tokens

    mrkt_tokens = []
    portals_tokens = []
    tonnel_tokens = []

    for i in range(1, 9):
        session_path = SESSIONS_DIR / f"{i}.session"
        if not session_path.exists():
            continue

        session = GetAccessToken(session_path)

        mrkt_token = await session.mrkt()
        if mrkt_token:
            mrkt_tokens.append(mrkt_token)
        """# TODO portals and tonnel"""


async def workers():
    # ---------- Scheduler ---------- #
    scheduler = AsyncIOScheduler()

    # ---------- Update Tokens ---------- #
    scheduler.add_job(
        func=update_tokens,
        trigger="interval",
        hours=12
    )

    # ---------- Run Worker ---------- #
    scheduler.start()



if __name__ == '__main__':
    asyncio.run(init_starting_sniper())
