from aiogram import Router

from bot.handlers import lobby, owner, payments, play, profile, settings, shop, start


def build_router() -> Router:
    root = Router(name="root")
    # Порядок важливий: deep-link приєднання до гри — раніше загального /start;
    # «рада нечисті» (будь-який текст в особистих) — останньою.
    root.include_routers(
        lobby.router,
        start.router,
        profile.router,
        shop.router,
        payments.router,
        settings.router,
        owner.router,
        play.router,
    )
    return root
