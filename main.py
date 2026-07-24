import asyncio
import logging
from contextlib import suppress

from sessions import GetAccessToken #, send_start
from pathlib import Path
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from parser import MRKT, PORTALS, TONNEL
from subs import SubscriptionIndex, init_db
from buy_tokens import (
    BUY_SESSION,
    init_buy_tokens_db,
    load_buy_tokens,
    register_parsers,
    resolve_buy_tokens,
)

from bot import bot, run_bot

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SESSIONS_DIR = Path(__file__).resolve().parent / "sessions"
TOKEN_REFRESH_HOURS = 3

mrkt_tokens = []
portals_tokens = []
tonnel_tokens = []

mrkt: MRKT | None = None
portals: PORTALS | None = None
tonnel: TONNEL | None = None
scheduler: AsyncIOScheduler | None = None


async def _cancel_tasks(tasks: list[asyncio.Task]) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task


async def _run_until_shutdown(*tasks: asyncio.Task) -> None:
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logging.info("Получен сигнал остановки (Ctrl+C)...")
        raise
    finally:
        await _cancel_tasks(list(tasks))



async def init_starting_sniper():
    global mrkt, portals, tonnel, scheduler

    init_db()
    init_buy_tokens_db()
    index = SubscriptionIndex.load_from_db()

    session_buy_tokens = await fetch_session_buy_tokens()
    buy_tokens = await resolve_buy_tokens(fallback=session_buy_tokens)

    await fetch_all_tokens()

    mrkt = MRKT(bot=bot, tokens=mrkt_tokens, buy_token=buy_tokens.get("mrkt", ""), poll_delay=0.2)
    await mrkt.update_parse_sessions()

    portals = PORTALS(bot=bot, tokens=portals_tokens, buy_token=buy_tokens.get("portals", ""), poll_delay=0.1)
    await portals.update_parse_sessions()

    tonnel = TONNEL(bot=bot, tokens=tonnel_tokens, buy_token=buy_tokens.get("tonnel", ""), poll_delay=0.5)
    await tonnel.init()

    register_parsers(mrkt, portals, tonnel)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        func=refresh_tokens,
        trigger="interval",
        hours=TOKEN_REFRESH_HOURS,
    )
    scheduler.start()
    logging.info(f"Автообновление токенов каждые {TOKEN_REFRESH_HOURS} ч.")

    # ---------- Pooling + Bot ---------- #
    task_bot = asyncio.create_task(run_bot(index))
    task_mrkt = asyncio.create_task(mrkt.pooling(index=index))
    task_portals = asyncio.create_task(portals.pooling(index=index))
    task_tonnel = asyncio.create_task(tonnel.pooling(index=index))

    try:
        await _run_until_shutdown(task_bot, task_mrkt, task_portals, task_tonnel)
    finally:
        if scheduler and scheduler.running:
            scheduler.shutdown(wait=False)
            logging.info("Scheduler остановлен")

        await mrkt.close_sessions()
        logging.info("MRKT | Все HTTP-сессии закрыты")

        await portals.close_sessions()
        logging.info("PORTALS | Все HTTP-сессии закрыты")

        await tonnel.close_sessions()
        logging.info("TONNEL | Все HTTP-сессии закрыты")




async def fetch_session_buy_tokens() -> dict[str, str | None]:
    buy_mrkt = buy_portals = buy_tonnel = None
    session_path = SESSIONS_DIR / f"{BUY_SESSION}.session"
    if not session_path.exists():
        return {"mrkt": None, "portals": None, "tonnel": None}

    session = GetAccessToken(session_path)
    buy_mrkt = await session.mrkt()
    buy_portals = await session.portals()
    buy_tonnel = await session.tonnel()
    return {"mrkt": buy_mrkt, "portals": buy_portals, "tonnel": buy_tonnel}


async def fetch_all_tokens():
    global mrkt_tokens, portals_tokens, tonnel_tokens

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

        portals_token = await session.portals()
        if portals_token:
            portals_tokens.append(portals_token)

        tonnel_token = await session.tonnel()
        if tonnel_token:
            tonnel_tokens.append(tonnel_token)

    logging.info(
        "Токены получены: MRKT=%s, PORTALS=%s, TONNEL=%s",
        len(mrkt_tokens), len(portals_tokens), len(tonnel_tokens),
    )


async def apply_tokens_to_parsers():
    buy_tokens = load_buy_tokens()

    if mrkt:
        await mrkt.update_tokens(mrkt_tokens)
        if buy_tokens.get("mrkt"):
            await mrkt.update_buy_token(buy_tokens["mrkt"])
            mrkt.buy_headers["Authorization"] = buy_tokens["mrkt"]
            mrkt.buy_headers["Cookie"] = f"access_token={buy_tokens['mrkt']}"
        await mrkt.update_parse_sessions()

    if portals:
        await portals.update_tokens(portals_tokens)
        if buy_tokens.get("portals"):
            await portals.update_buy_token(buy_tokens["portals"])
            portals.buy_headers["Authorization"] = f"tma {buy_tokens['portals']}"
        await portals.update_parse_sessions()

    if tonnel:
        tonnel.tokens = tonnel_tokens
        if buy_tokens.get("tonnel"):
            tonnel.buy_token = buy_tokens["tonnel"]
        await tonnel.update_parse_jsons()


async def refresh_tokens():
    logging.info("Запуск автообновления токенов...")
    await fetch_all_tokens()
    await apply_tokens_to_parsers()
    logging.info("Токены обновлены и применены к парсерам")



if __name__ == '__main__':
    asyncio.run(init_starting_sniper())
