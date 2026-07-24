import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import ADMIN_USER_ID
from buy_tokens import (
    BUY_SESSION,
    MARKET_LABELS,
    apply_buy_token,
    fetch_buy_token_from_session,
    format_buy_tokens_status,
    get_buy_token,
    mask_token,
)
from subs import (
    SubscriptionIndex,
    create_subscription,
    format_subscription,
    get_subscription_db,
    load_all_subscriptions,
    remove_subscription,
)

from .keyboards import (
    buy_token_detail_kb,
    buy_tokens_menu_kb,
    cancel_kb,
    confirm_delete_kb,
    main_menu_kb,
    skip_kb,
    subscription_detail_kb,
    subscriptions_list_kb,
)
from .states import AddSubscription, EditBuyToken

router = Router(name="subscriptions")
logger = logging.getLogger(__name__)

SKIP_WORDS = {"⏭ пропустить", "пропустить", "-", "—", "skip", "any", "любой", "любая"}
CANCEL_WORDS = {"❌ отмена", "отмена", "/cancel"}


def _parse_optional(text: str) -> str | None:
    cleaned = text.strip()
    if cleaned.lower() in SKIP_WORDS:
        return None
    return cleaned


async def _send_subscriptions_list(target: Message, page: int = 0) -> None:
    subs = [s for s in load_all_subscriptions() if s.is_active]
    if not subs:
        await target.answer(
            "📋 Активных подписок пока нет.\n\nНажми «➕ Добавить», чтобы создать первую.",
            reply_markup=main_menu_kb(),
        )
        return

    await target.answer(
        f"📋 <b>Активные подписки</b> ({len(subs)})\n\nВыбери подписку для просмотра:",
        reply_markup=subscriptions_list_kb(subs, page=page),
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "👋 <b>SniperBot</b>\n\n"
        "Управление подписками на NFT-подарки MRKT.\n"
        "Бот покупает подарок, если его цена < указанного максимума "
        "и он подходит под фильтры.\n\n"
        "Используй меню ниже 👇",
        reply_markup=main_menu_kb(),
    )


@router.message(Command("cancel"))
@router.message(F.text.in_(CANCEL_WORDS))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current is None:
        await message.answer("Нечего отменять.", reply_markup=main_menu_kb())
        return
    await state.clear()
    if current and current.startswith("EditBuyToken"):
        await message.answer("❌ Изменение токена отменено.", reply_markup=main_menu_kb())
    else:
        await message.answer("❌ Добавление подписки отменено.", reply_markup=main_menu_kb())


@router.message(F.text == "ℹ️ Помощь")
@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "<b>Как работают подписки</b>\n\n"
        "Подписка — это фильтр + максимальная цена.\n"
        "Когда на MRKT появляется подарок, бот проверяет:\n"
        "• совпадает ли <b>коллекция</b>\n"
        "• совпадает ли <b>модель</b> (или любая)\n"
        "• совпадает ли <b>фон</b> (или любой)\n"
        "• совпадает ли <b>узор</b> (или любой)\n"
        "• цена <b>меньше</b> указанного максимума\n\n"
        "При создании подписки «Пропустить» = любое значение.\n\n"
        "<b>Команды:</b>\n"
        "/start — главное меню\n"
        "/subs — список подписок\n"
        "/add — добавить подписку\n"
        "/tokens — buy-токены маркетов\n"
        "/cancel — отменить текущее действие",
        reply_markup=main_menu_kb(),
    )


@router.message(F.text == "🔑 Токены")
@router.message(Command("tokens"))
async def cmd_tokens(message: Message) -> None:
    await message.answer(
        format_buy_tokens_status() + "\n\nВыбери маркет:",
        reply_markup=buy_tokens_menu_kb(),
    )


@router.callback_query(F.data == "buy_tokens_menu")
async def cb_buy_tokens_menu(query: CallbackQuery) -> None:
    await query.message.edit_text(
        format_buy_tokens_status() + "\n\nВыбери маркет:",
        reply_markup=buy_tokens_menu_kb(),
    )
    await query.answer()


@router.callback_query(F.data.startswith("buy_token:"))
async def cb_buy_token_detail(query: CallbackQuery) -> None:
    market = query.data.split(":")[1]
    label = MARKET_LABELS.get(market, market.upper())
    token = get_buy_token(market)

    await query.message.edit_text(
        f"🔑 <b>{label}</b> buy-токен\n\n"
        f"Текущий: <code>{mask_token(token)}</code>",
        reply_markup=buy_token_detail_kb(market),
    )
    await query.answer()


@router.callback_query(F.data.startswith("buy_token_edit:"))
async def cb_buy_token_edit(query: CallbackQuery, state: FSMContext) -> None:
    market = query.data.split(":")[1]
    label = MARKET_LABELS.get(market, market.upper())

    await state.set_state(EditBuyToken.waiting_token)
    await state.update_data(market=market)

    await query.message.answer(
        f"✏️ Отправь новый buy-токен для <b>{label}</b>.\n\n"
        "Можно вставить полный токен одним сообщением.",
        reply_markup=cancel_kb(),
    )
    await query.answer()


@router.callback_query(F.data.startswith("buy_token_session:"))
async def cb_buy_token_from_session(query: CallbackQuery) -> None:
    market = query.data.split(":")[1]
    label = MARKET_LABELS.get(market, market.upper())

    await query.answer("Получаю токен из сессии...")
    token = await fetch_buy_token_from_session(market)
    if not token:
        await query.message.answer(
            f"⚠️ Не удалось получить токен {label} из сессии {BUY_SESSION}.",
            reply_markup=main_menu_kb(),
        )
        return

    applied = await apply_buy_token(market, token)
    status = "применён" if applied else "сохранён (снайпер не запущен)"
    await query.message.answer(
        f"✅ {label} buy-токен обновлён из сессии и {status}.\n\n"
        f"Новый: <code>{mask_token(token)}</code>",
        reply_markup=main_menu_kb(),
    )


@router.message(EditBuyToken.waiting_token)
async def edit_buy_token(message: Message, state: FSMContext) -> None:
    if message.text and message.text.strip().lower() in CANCEL_WORDS:
        await state.clear()
        await message.answer("❌ Изменение токена отменено.", reply_markup=main_menu_kb())
        return

    token = (message.text or "").strip()
    if len(token) < 10:
        await message.answer("⚠️ Токен слишком короткий. Отправь полный buy-токен.", reply_markup=cancel_kb())
        return

    data = await state.get_data()
    market = data.get("market")
    await state.clear()

    if market not in MARKET_LABELS:
        await message.answer("⚠️ Неизвестный маркет.", reply_markup=main_menu_kb())
        return

    label = MARKET_LABELS[market]
    applied = await apply_buy_token(market, token)
    status = "применён" if applied else "сохранён (снайпер не запущен)"

    await message.answer(
        f"✅ {label} buy-токен {status}.\n\n"
        f"Новый: <code>{mask_token(token)}</code>",
        reply_markup=main_menu_kb(),
    )


@router.message(F.text == "📊 Статистика")
@router.message(Command("stats"))
async def cmd_stats(message: Message, index: SubscriptionIndex) -> None:
    all_subs = load_all_subscriptions()
    active = [s for s in all_subs if s.is_active]
    inactive = len(all_subs) - len(active)

    await message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"• Активных подписок: <b>{len(active)}</b>\n"
        f"• Деактивированных: <b>{inactive}</b>\n"
        f"• В индексе (hot path): <b>{index.active_count}</b>",
        reply_markup=main_menu_kb(),
    )


@router.message(F.text == "📋 Подписки")
@router.message(Command("subs"))
async def cmd_subs(message: Message) -> None:
    await _send_subscriptions_list(message)


@router.callback_query(F.data.startswith("subs_page:"))
@router.callback_query(F.data.startswith("subs_refresh:"))
async def cb_subs_page(query: CallbackQuery) -> None:
    page = int(query.data.split(":")[1])
    subs = [s for s in load_all_subscriptions() if s.is_active]

    if not subs:
        await query.message.edit_text("📋 Активных подписок нет.")
        await query.answer()
        return

    await query.message.edit_text(
        f"📋 <b>Активные подписки</b> ({len(subs)})\n\nВыбери подписку для просмотра:",
        reply_markup=subscriptions_list_kb(subs, page=page),
    )
    await query.answer()


@router.callback_query(F.data.startswith("sub:"))
async def cb_sub_detail(query: CallbackQuery) -> None:
    sub_id = int(query.data.split(":")[1])
    sub = get_subscription_db(sub_id)

    if sub is None or not sub.is_active:
        await query.answer("Подписка не найдена или уже удалена", show_alert=True)
        return

    await query.message.edit_text(
        format_subscription(sub),
        reply_markup=subscription_detail_kb(sub_id),
    )
    await query.answer()


@router.callback_query(F.data.startswith("sub_del:"))
async def cb_sub_delete_confirm(query: CallbackQuery) -> None:
    sub_id = int(query.data.split(":")[1])
    sub = get_subscription_db(sub_id)

    if sub is None or not sub.is_active:
        await query.answer("Подписка не найдена", show_alert=True)
        return

    await query.message.edit_text(
        f"🗑 Удалить подписку?\n\n{format_subscription(sub)}",
        reply_markup=confirm_delete_kb(sub_id),
    )
    await query.answer()


@router.callback_query(F.data.startswith("sub_del_yes:"))
async def cb_sub_delete(query: CallbackQuery, index: SubscriptionIndex) -> None:
    sub_id = int(query.data.split(":")[1])
    sub = get_subscription_db(sub_id)

    if sub is None or not sub.is_active:
        await query.answer("Подписка уже удалена", show_alert=True)
        return

    remove_subscription(index, sub_id)
    logger.info("Подписка #%s удалена пользователем %s", sub_id, query.from_user.id)

    await query.message.edit_text(f"✅ Подписка #{sub_id} удалена.")
    await query.answer("Удалено")


@router.message(F.text == "➕ Добавить")
@router.message(Command("add"))
async def cmd_add_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AddSubscription.collection)
    await message.answer(
        "➕ <b>Новая подписка</b>\n\n"
        "Шаг 1/5 — введи название <b>коллекции</b>\n"
        "(например: <code>NailBracelet</code>)\n\n"
        "Или нажми «Пропустить» — тогда подойдёт любая коллекция.",
        reply_markup=skip_kb(),
    )


@router.message(AddSubscription.collection)
async def add_collection(message: Message, state: FSMContext) -> None:
    if message.text and message.text.strip().lower() in CANCEL_WORDS:
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=main_menu_kb())
        return

    await state.update_data(collection=_parse_optional(message.text or ""))
    await state.set_state(AddSubscription.model)
    await message.answer(
        "Шаг 2/5 — введи <b>модель</b>\n"
        "(например: <code>X-Ray</code>)\n\n"
        "«Пропустить» = любая модель.",
        reply_markup=skip_kb(),
    )


@router.message(AddSubscription.model)
async def add_model(message: Message, state: FSMContext) -> None:
    if message.text and message.text.strip().lower() in CANCEL_WORDS:
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=main_menu_kb())
        return

    await state.update_data(model=_parse_optional(message.text or ""))
    await state.set_state(AddSubscription.backdrop)
    await message.answer(
        "Шаг 3/5 — введи <b>фон</b> (backdrop)\n"
        "(например: <code>Black</code>)\n\n"
        "«Пропустить» = любой фон.",
        reply_markup=skip_kb(),
    )


@router.message(AddSubscription.backdrop)
async def add_backdrop(message: Message, state: FSMContext) -> None:
    if message.text and message.text.strip().lower() in CANCEL_WORDS:
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=main_menu_kb())
        return

    await state.update_data(backdrop=_parse_optional(message.text or ""))
    await state.set_state(AddSubscription.pattern)
    await message.answer(
        "Шаг 4/5 — введи <b>узор</b> (pattern/symbol)\n"
        "(например: <code>Worker Ant</code>)\n\n"
        "«Пропустить» = любой узор.",
        reply_markup=skip_kb(),
    )


@router.message(AddSubscription.pattern)
async def add_pattern(message: Message, state: FSMContext) -> None:
    if message.text and message.text.strip().lower() in CANCEL_WORDS:
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=main_menu_kb())
        return

    await state.update_data(pattern=_parse_optional(message.text or ""))
    await state.set_state(AddSubscription.max_price)
    await message.answer(
        "Шаг 5/5 — введи <b>максимальную цену</b> в TON\n"
        "(например: <code>500</code> или <code>12.5</code>)\n\n"
        "Бот купит подарок, если цена <b>строго меньше</b> этого значения.",
        reply_markup=cancel_kb(),
    )


@router.message(AddSubscription.max_price)
async def add_max_price(message: Message, state: FSMContext, index: SubscriptionIndex) -> None:
    if message.text and message.text.strip().lower() in CANCEL_WORDS:
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=main_menu_kb())
        return

    raw = (message.text or "").strip().replace(",", ".")
    try:
        max_price = float(raw)
        if max_price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("⚠️ Введи корректную цену (число больше 0).", reply_markup=cancel_kb())
        return

    data = await state.get_data()
    await state.clear()

    sub = create_subscription(
        index=index,
        user_id=ADMIN_USER_ID,
        collection=data.get("collection"),
        model=data.get("model"),
        backdrop=data.get("backdrop"),
        pattern=data.get("pattern"),
        max_price=max_price,
    )

    logger.info("Создана подписка #%s: %s", sub.id, sub)

    await message.answer(
        f"✅ <b>Подписка создана!</b>\n\n{format_subscription(sub)}",
        reply_markup=main_menu_kb(),
    )


@router.message(StateFilter(None))
async def unknown_message(message: Message) -> None:
    await message.answer(
        "Не понял команду. Используй меню или /help.",
        reply_markup=main_menu_kb(),
    )
