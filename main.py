import asyncio

from sessions import GetAccessToken #, send_start
from pathlib import Path
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from parser import MRKT

from bot import bot


mrkt_tokens = []
portals_tokens = []
tonnel_tokens = []



async def init_starting_sniper():
    await update_tokens()
    await workers()


    # ---------- Create Classes ---------- #
    mrkt = MRKT(bot=bot, tokens=mrkt_tokens, buy_token="LOOOL", poll_delay=0.2)
    await mrkt.update_parse_sessions()

    # ---------- Pooling ---------- #
    task_mrkt = asyncio.create_task(mrkt.pooling())

    # ---------- Gather Them ---------- #
    await asyncio.gather(task_mrkt)




async def update_tokens():
    global mrkt_tokens
    global portals_tokens
    global tonnel_tokens

    mrkt_tokens = []
    portals_tokens = []
    tonnel_tokens = []

    for i in range(1, 9):
        session = GetAccessToken(Path(f"SniperBot/session/{i}.session"))

        mrkt_tokens.append(session.mrkt)
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
