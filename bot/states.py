from aiogram.fsm.state import State, StatesGroup


class AddSubscription(StatesGroup):
    collection = State()
    model = State()
    backdrop = State()
    pattern = State()
    max_price = State()


class EditBuyToken(StatesGroup):
    waiting_token = State()
