from sessions import GetAccessToken, send_start
from pathlib import Path





async def init_starting_sniper():
    mrkt_token = GetAccessToken(Path("SniperBot/")).mrkt
