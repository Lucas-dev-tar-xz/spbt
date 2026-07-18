from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

from subs import Subscription


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Подписки"), KeyboardButton(text="➕ Добавить")],
            [KeyboardButton(text="ℹ️ Помощь"), KeyboardButton(text="📊 Статистика")],
        ],
        resize_keyboard=True,
    )


def skip_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏭ Пропустить")],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
    )


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
    )


def subscriptions_list_kb(subs: list[Subscription], page: int = 0, per_page: int = 5) -> InlineKeyboardMarkup:
    start = page * per_page
    chunk = subs[start:start + per_page]
    rows: list[list[InlineKeyboardButton]] = []

    for sub in chunk:
        label = _sub_short_label(sub)
        rows.append([InlineKeyboardButton(text=label, callback_data=f"sub:{sub.id}")])

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"subs_page:{page - 1}"))
    if start + per_page < len(subs):
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"subs_page:{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="subs_refresh:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subscription_detail_kb(sub_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"sub_del:{sub_id}")],
            [InlineKeyboardButton(text="◀️ К списку", callback_data="subs_refresh:0")],
        ]
    )


def confirm_delete_kb(sub_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"sub_del_yes:{sub_id}"),
                InlineKeyboardButton(text="❌ Нет", callback_data=f"sub:{sub_id}"),
            ]
        ]
    )


def _sub_short_label(sub: Subscription) -> str:
    parts = [f"#{sub.id}"]
    if sub.collection:
        parts.append(sub.collection[:12])
    else:
        parts.append("любая")
    parts.append(f"<{sub.max_price:g} TON")
    return " · ".join(parts)
