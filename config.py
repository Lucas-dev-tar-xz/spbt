from dataclasses import dataclass



@dataclass(frozen=True)
class Bot:
    name: str
    bot_username: str
    app_short_name: str
    auth_url: str

class Bots:
    mrkt = Bot(
        name="mrkt",
        bot_username="mrkt",
        app_short_name="app",
        auth_url="https://api.tgmrkt.io/api/v1/auth"
    )

    portals = Bot(
        name="portals",
        bot_username="portals",
        app_short_name="market",
        auth_url="https://portal-market.com/?v=4"
    )

    tonnel = Bot(
        name="tonnel",
        bot_username="Tonnel_Network_bot",
        app_short_name="gift",
        auth_url=""
    )





telegram_bots = [
    {
        'name': 'mrkt',
        'bot_username': 'mrkt',
        'app_short_name': 'app',
        'auth_url': 'https://api.tgmrkt.io/api/v1/auth'
    },
    {
        'name': 'portals',
        'bot_username': 'portals',
        'app_short_name': 'market',
        'auth_url': ''
    },
    {
        'name': 'tonnel',
        'bot_username': 'Tonnel_Network_bot',
        'app_short_name': 'gift',
        'auth_url': ''
    }
]


user_agent = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
"(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")


LOGS: int = -1004341936393
CHANGES_CHAT: int = -1003993068793
CHANGES_CHAT_MRKT: int = 2
CHANGES_CHAT_PORTALS: int = 3
CHANGES_CHAT_TONNEL: int = 4