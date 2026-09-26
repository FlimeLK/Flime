from aiogram.filters.callback_data import CallbackData


class NightCb(CallbackData, prefix="nt"):
    chat: int
    kind: str
    target: int  # 0 — пропустити


class VoteCb(CallbackData, prefix="vt"):
    chat: int
    target: int  # 0 — нікого


class HoneyCb(CallbackData, prefix="hn"):
    chat: int


class ConfirmCb(CallbackData, prefix="cf"):
    chat: int
    yes: int
