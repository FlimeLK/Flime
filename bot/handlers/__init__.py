from aiogram import Router

from bot.handlers import (
    design,
    lobby,
    omerta,
    owner,
    payments,
    play,
    profile,
    roles,
    settings,
    shop,
    start,
)


def build_router() -> Router:
    root = Router(name="root")
    # Порядок важливий: омерта - першою (вона пропускає все, що не треба видаляти);
    # deep-link (гра, ролі, налаштування) - раніше загального /start;
    # «рада мафії» (будь-який текст в особистих) - останньою.
    root.include_routers(
        omerta.router,
        lobby.router,
        roles.router,
        settings.router,
        start.router,
        profile.router,
        shop.router,
        payments.router,
        owner.router,
        design.router,
        play.router,
    )
    return root
