from aiogram import Router

from bot.handlers import design, lobby, owner, payments, play, profile, roles, settings, shop, start


def build_router() -> Router:
    root = Router(name="root")
    # Порядок важливий: deep-link приєднання до гри - раніше загального /start;
    # «рада мафії» (будь-який текст в особистих) - останньою.
    root.include_routers(
        lobby.router,
        roles.router,
        start.router,
        profile.router,
        shop.router,
        payments.router,
        settings.router,
        owner.router,
        design.router,
        play.router,
    )
    return root
