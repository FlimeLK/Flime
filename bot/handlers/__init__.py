from aiogram import Router

from bot.handlers import lobby, owner, payments, play, profile, roles_builder, settings, shop, start


def build_router() -> Router:
    root = Router(name="root")
    # Порядок важливий: deep-link-и (гра, свої ролі) — раніше загального /start;
    # «рада нечисті» (будь-який текст в особистих) — останньою.
    root.include_routers(
        lobby.router,
        roles_builder.router,
        start.router,
        profile.router,
        shop.router,
        payments.router,
        settings.router,
        owner.router,
        play.router,
    )
    return root
