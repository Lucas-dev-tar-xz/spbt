import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING

from subs.index import DB_PATH

if TYPE_CHECKING:
    from parser import MRKT, PORTALS, TONNEL

logger = logging.getLogger(__name__)

SESSIONS_DIR = Path(__file__).resolve().parent / "sessions"
BUY_SESSION = 1

MARKETS = ("mrkt", "portals", "tonnel")
MARKET_LABELS = {
    "mrkt": "MRKT",
    "portals": "PORTALS",
    "tonnel": "TONNEL",
}

_mrkt: "MRKT | None" = None
_portals: "PORTALS | None" = None
_tonnel: "TONNEL | None" = None


def init_buy_tokens_db(path: str = DB_PATH) -> None:
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS buy_tokens (
                market     TEXT PRIMARY KEY,
                token      TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()


def register_parsers(mrkt: "MRKT", portals: "PORTALS", tonnel: "TONNEL") -> None:
    global _mrkt, _portals, _tonnel
    _mrkt = mrkt
    _portals = portals
    _tonnel = tonnel


def load_buy_tokens(path: str = DB_PATH) -> dict[str, str]:
    init_buy_tokens_db(path)
    with closing(sqlite3.connect(path)) as conn:
        rows = conn.execute("SELECT market, token FROM buy_tokens").fetchall()
    return {market: token for market, token in rows}


def get_buy_token(market: str, path: str = DB_PATH) -> str | None:
    tokens = load_buy_tokens(path)
    return tokens.get(market)


def save_buy_token(market: str, token: str, path: str = DB_PATH) -> None:
    if market not in MARKETS:
        raise ValueError(f"Unknown market: {market}")

    init_buy_tokens_db(path)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            """
            INSERT INTO buy_tokens (market, token, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(market) DO UPDATE SET
                token = excluded.token,
                updated_at = excluded.updated_at
            """,
            (market, token),
        )
        conn.commit()


def mask_token(token: str | None) -> str:
    if not token:
        return "не задан"
    if len(token) <= 16:
        return f"{token[:4]}...{token[-2:]}"
    return f"{token[:8]}...{token[-6:]}"


def format_buy_tokens_status() -> str:
    tokens = load_buy_tokens()
    lines = ["🔑 <b>Buy-токены</b>\n"]
    for market in MARKETS:
        label = MARKET_LABELS[market]
        token = tokens.get(market)
        lines.append(f"• <b>{label}</b>: <code>{mask_token(token)}</code>")
    return "\n".join(lines)


async def apply_buy_token(market: str, token: str) -> bool:
    save_buy_token(market, token)

    if market == "mrkt" and _mrkt:
        await _mrkt.update_buy_token(token)
        _mrkt.buy_headers["Authorization"] = token
        _mrkt.buy_headers["Cookie"] = f"access_token={token}"
        await _mrkt.update_parse_sessions()
        logger.info("MRKT buy-токен обновлён через бота")
        return True

    if market == "portals" and _portals:
        await _portals.update_buy_token(token)
        _portals.buy_headers["Authorization"] = f"tma {token}"
        await _portals.update_parse_sessions()
        logger.info("PORTALS buy-токен обновлён через бота")
        return True

    if market == "tonnel" and _tonnel:
        _tonnel.buy_token = token
        logger.info("TONNEL buy-токен обновлён через бота")
        return True

    logger.warning("Buy-токен %s сохранён, но парсер не запущен", market)
    return False


async def fetch_buy_token_from_session(market: str, session_num: int = BUY_SESSION) -> str | None:
    from sessions import GetAccessToken

    session_path = SESSIONS_DIR / f"{session_num}.session"
    if not session_path.exists():
        return None

    session = GetAccessToken(session_path)
    if market == "mrkt":
        return await session.mrkt()
    if market == "portals":
        return await session.portals()
    if market == "tonnel":
        return await session.tonnel()
    return None


async def resolve_buy_tokens(fallback: dict[str, str | None] | None = None) -> dict[str, str]:
    saved = load_buy_tokens()
    resolved: dict[str, str] = {}

    for market in MARKETS:
        if saved.get(market):
            resolved[market] = saved[market]
        elif fallback and fallback.get(market):
            resolved[market] = fallback[market]  # type: ignore[assignment]

    return resolved
