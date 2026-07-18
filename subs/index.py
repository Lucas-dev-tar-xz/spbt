"""
Матчинг-движок подписок для снайпер-бота NFT-подарков (MRKT).

Архитектура
-----------
1. SQLite — источник правды. Переживает рестарт бота, ноль настройки.
   При росте до нескольких процессов с одновременной записью — меняется
   на Postgres, схема останется той же (меняется только слой подключения).

2. In-memory индекс (SubscriptionIndex) — то, что реально стоит на
   хот-пути (проверка каждого нового листинга). Чистые структуры Python,
   без похода в БД и без сети — микросекунды, а не десятки миллисекунд.

3. При старте индекс строится из SQLite. Создание/удаление подписки
   пишется в БД и одновременно применяется к индексу — в рантайме
   матчинга БД больше не трогаем.
"""

from __future__ import annotations

import bisect
import os
import random
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass

DB_PATH = "subscriptions.db"
ANY = None  # сентинел "любое значение" для model/backdrop/pattern


# --------------------------------------------------------------------------
# Модели данных
# --------------------------------------------------------------------------

@dataclass
class Subscription:
    id: int
    user_id: int
    collection: str
    model: str | None       # None = любая модель
    backdrop: str | None    # None = любой фон
    pattern: str | None     # None = любой узор
    max_price: float        # покупаем, если price < max_price
    is_active: bool = True


@dataclass
class Gift:
    collection: str
    model: str
    backdrop: str
    pattern: str
    price: float
    gift_name: str
    gift_id: str = ""


# --------------------------------------------------------------------------
# SQLite — источник правды
# --------------------------------------------------------------------------

def init_db(path: str = DB_PATH) -> None:
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                collection  TEXT,
                model       TEXT,
                backdrop    TEXT,
                pattern     TEXT,
                max_price   REAL NOT NULL,
                is_active   INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_subs_collection
            ON subscriptions(collection) WHERE is_active = 1
        """)
        conn.commit()


def _row_to_sub(row: tuple) -> Subscription:
    return Subscription(
        id=row[0], user_id=row[1], collection=row[2],
        model=row[3], backdrop=row[4], pattern=row[5],
        max_price=row[6], is_active=bool(row[7]),
    )


def load_active_subscriptions(path: str = DB_PATH) -> list[Subscription]:
    with closing(sqlite3.connect(path)) as conn:
        rows = conn.execute("""
            SELECT id, user_id, collection, model, backdrop, pattern, max_price, is_active
            FROM subscriptions WHERE is_active = 1
        """).fetchall()
    return [_row_to_sub(r) for r in rows]


def insert_subscription_db(sub: Subscription, path: str = DB_PATH) -> int:
    with closing(sqlite3.connect(path)) as conn:
        cur = conn.execute("""
            INSERT INTO subscriptions
                (user_id, collection, model, backdrop, pattern, max_price, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (sub.user_id, sub.collection, sub.model, sub.backdrop,
              sub.pattern, sub.max_price, int(sub.is_active)))
        conn.commit()
        return cur.lastrowid


def deactivate_subscription_db(sub_id: int, path: str = DB_PATH) -> None:
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("UPDATE subscriptions SET is_active = 0 WHERE id = ?", (sub_id,))
        conn.commit()


def load_all_subscriptions(path: str = DB_PATH) -> list[Subscription]:
    with closing(sqlite3.connect(path)) as conn:
        rows = conn.execute("""
            SELECT id, user_id, collection, model, backdrop, pattern, max_price, is_active
            FROM subscriptions
            ORDER BY id DESC
        """).fetchall()
    return [_row_to_sub(r) for r in rows]


def get_subscription_db(sub_id: int, path: str = DB_PATH) -> Subscription | None:
    with closing(sqlite3.connect(path)) as conn:
        row = conn.execute("""
            SELECT id, user_id, collection, model, backdrop, pattern, max_price, is_active
            FROM subscriptions WHERE id = ?
        """, (sub_id,)).fetchone()
    return _row_to_sub(row) if row else None


def format_subscription(sub: Subscription) -> str:
    def field(label: str, value: str | None) -> str:
        display = value if value else "любой"
        return f"  • {label}: <b>{display}</b>"

    status = "✅ активна" if sub.is_active else "⏸ деактивирована"
    return (
        f"<b>Подписка #{sub.id}</b> ({status})\n"
        f"{field('Коллекция', sub.collection)}\n"
        f"{field('Модель', sub.model)}\n"
        f"{field('Фон', sub.backdrop)}\n"
        f"{field('Узор', sub.pattern)}\n"
        f"  • Макс. цена: <b>{sub.max_price:g} TON</b>"
    )


# --------------------------------------------------------------------------
# In-memory индекс — hot path
# --------------------------------------------------------------------------

class _Bucket:
    """Все подписки под один конкретный (collection, model|ANY, backdrop|ANY, pattern|ANY).
    Отсортированы по max_price -> matches_above работает бинарным поиском."""
    __slots__ = ("prices", "sub_ids")

    def __init__(self) -> None:
        self.prices: list[float] = []
        self.sub_ids: list[int] = []

    def add(self, sub_id: int, max_price: float) -> None:
        idx = bisect.bisect_right(self.prices, max_price)
        self.prices.insert(idx, max_price)
        self.sub_ids.insert(idx, sub_id)

    def remove(self, sub_id: int) -> None:
        try:
            idx = self.sub_ids.index(sub_id)
        except ValueError:
            return
        del self.prices[idx]
        del self.sub_ids[idx]

    def matches_above(self, price: float) -> list[int]:
        """Подписки с max_price > price (условие 'цена меньше max_price')."""
        idx = bisect.bisect_right(self.prices, price)
        return self.sub_ids[idx:]


class SubscriptionIndex:
    """Единый индекс всех активных подписок в памяти процесса."""

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str | None, str | None, str | None], _Bucket] = {}
        self._by_id: dict[int, Subscription] = {}

    @classmethod
    def load_from_db(cls, path: str = DB_PATH) -> "SubscriptionIndex":
        index = cls()
        for sub in load_active_subscriptions(path):
            index.add(sub)
        return index

    @staticmethod
    def _key(sub: Subscription) -> tuple[str, str | None, str | None, str | None]:
        return (sub.collection, sub.model, sub.backdrop, sub.pattern)

    def add(self, sub: Subscription) -> None:
        self._buckets.setdefault(self._key(sub), _Bucket()).add(sub.id, sub.max_price)
        self._by_id[sub.id] = sub

    def remove(self, sub_id: int) -> None:
        sub = self._by_id.pop(sub_id, None)
        if sub is None:
            return
        bucket = self._buckets.get(self._key(sub))
        if bucket:
            bucket.remove(sub_id)

    def find_matches(self, gift: Gift) -> list[Subscription]:
        """Главная функция: какие подписки хотят купить этот подарок."""
        matches: list[Subscription] = []
        for collection in (gift.collection, ANY):
            for model in (gift.model, ANY):
                for backdrop in (gift.backdrop, ANY):
                    for pattern in (gift.pattern, ANY):
                        bucket = self._buckets.get((collection, model, backdrop, pattern))
                        if bucket is None:
                            continue
                        for sub_id in bucket.matches_above(gift.price):
                            matches.append(self._by_id[sub_id])
        return matches

    def should_buy(self, gift: Gift) -> bool:
        return bool(self.find_matches(gift))

    @property
    def active_count(self) -> int:
        return len(self._by_id)


# --------------------------------------------------------------------------
# Публичное API для управления подписками (вызывать из хендлеров бота)
# --------------------------------------------------------------------------

def create_subscription(
    index: SubscriptionIndex, user_id: int, collection: str | None, max_price: float,
    model: str | None = None, backdrop: str | None = None, pattern: str | None = None,
    db_path: str = DB_PATH,
) -> Subscription:
    sub = Subscription(id=0, user_id=user_id, collection=collection,
                        model=model, backdrop=backdrop, pattern=pattern,
                        max_price=max_price)
    sub.id = insert_subscription_db(sub, db_path)
    index.add(sub)
    return sub


def remove_subscription(index: SubscriptionIndex, sub_id: int, db_path: str = DB_PATH) -> None:
    deactivate_subscription_db(sub_id, db_path)
    index.remove(sub_id)


# --------------------------------------------------------------------------
# Опционально: синхронизация нескольких инстансов через Redis Pub/Sub.
# Нужно, только если матчинг разнесён на несколько процессов/машин.
# Для одного процесса — не подключай, это лишний сетевой хоп.
# --------------------------------------------------------------------------
#
# import json
# import redis
# r = redis.Redis(host="localhost", port=6379, decode_responses=True)
#
# def publish_change(action: str, sub: Subscription) -> None:
#     r.publish("subs:changes", json.dumps({"action": action, "sub": sub.__dict__}))
#
# def run_change_listener(index: SubscriptionIndex) -> None:
#     pubsub = r.pubsub()
#     pubsub.subscribe("subs:changes")
#     for msg in pubsub.listen():
#         if msg["type"] != "message":
#             continue
#         data = json.loads(msg["data"])
#         if data["action"] == "add":
#             index.add(Subscription(**data["sub"]))
#         else:
#             index.remove(data["sub"]["id"])


# --------------------------------------------------------------------------
# Тесты корректности + SQLite round-trip + бенчмарк скорости
# --------------------------------------------------------------------------

def _correctness_checks() -> None:
    index = SubscriptionIndex()
    index.add(Subscription(1, 100, "NailBracelet", None, "Black", None, 500))
    index.add(Subscription(2, 101, "NailBracelet", "X-Ray", "Black", "Worker Ant", 1000))
    index.add(Subscription(3, 102, "OtherCollection", None, None, None, 10_000))

    gift = Gift("NailBracelet", "X-Ray", "Black", "Worker Ant", 300)
    matched = sorted(s.id for s in index.find_matches(gift))
    assert matched == [1, 2], matched

    too_expensive = Gift("NailBracelet", "X-Ray", "Black", "Worker Ant", 1500)
    assert index.find_matches(too_expensive) == []

    other = Gift("OtherCollection", "Anything", "Anything", "Anything", 50)
    assert sorted(s.id for s in index.find_matches(other)) == [3]

    index.remove(1)
    assert sorted(s.id for s in index.find_matches(gift)) == [2]

    print("Корректность (in-memory): все проверки пройдены")


def _db_roundtrip_check() -> None:
    test_db = "test_subs.db"
    if os.path.exists(test_db):
        os.remove(test_db)
    init_db(test_db)

    index = SubscriptionIndex.load_from_db(test_db)
    gift = Gift("NailBracelet", "X-Ray", "Black", "Worker Ant", 300)
    assert index.find_matches(gift) == []

    sub = create_subscription(index, user_id=1, collection="NailBracelet",
                               max_price=500, backdrop="Black", db_path=test_db)
    assert index.should_buy(gift) is True

    remove_subscription(index, sub.id, db_path=test_db)
    assert index.should_buy(gift) is False

    # после "рестарта" (свежая загрузка из БД) неактивная подписка не всплывёт
    fresh_index = SubscriptionIndex.load_from_db(test_db)
    assert fresh_index.should_buy(gift) is False

    os.remove(test_db)
    for ext in ("-wal", "-shm"):
        if os.path.exists(test_db + ext):
            os.remove(test_db + ext)
    print("SQLite round-trip: все проверки пройдены")


def _benchmark(n_subs: int = 100_000, n_lookups: int = 20_000) -> None:
    index = SubscriptionIndex()
    collections = [f"Collection{i}" for i in range(30)]
    models = [f"Model{i}" for i in range(10)]
    backdrops = [f"Backdrop{i}" for i in range(10)]
    patterns = [f"Pattern{i}" for i in range(10)]

    for sub_id in range(1, n_subs + 1):
        index.add(Subscription(
            id=sub_id, user_id=sub_id,
            collection=random.choice(collections),
            model=random.choice(models + [None]),
            backdrop=random.choice(backdrops + [None]),
            pattern=random.choice(patterns + [None]),
            max_price=random.uniform(50, 2000),
        ))

    # "горячий" бакет: 10 000 подписчиков на "любой X-Ray/Black/любой узор" в одной коллекции
    for sub_id in range(n_subs + 1, n_subs + 10_001):
        index.add(Subscription(sub_id, sub_id, "HotCollection", None, None, None,
                                max_price=random.uniform(50, 2000)))

    normal_gift = Gift(collections[0], models[0], backdrops[0], patterns[0], 300)
    hot_gift = Gift("HotCollection", "AnyModel", "AnyBackdrop", "AnyPattern", 300)

    print(f"\nВсего подписок в индексе: {n_subs + 10_000:,}")
    for label, gift in (("обычный бакет", normal_gift),
                        ("горячий бакет (10k подписчиков на фильтр)", hot_gift)):
        start = time.perf_counter()
        for _ in range(n_lookups):
            index.find_matches(gift)
        elapsed = time.perf_counter() - start
        print(f"  {label}: {elapsed / n_lookups * 1e6:.2f} мкс/вызов "
              f"({n_lookups:,} вызовов за {elapsed*1000:.1f} мс)")


if __name__ == "__main__":
    _correctness_checks()
    _db_roundtrip_check()
    _benchmark()