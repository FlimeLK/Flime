from bot.engine.models import Game, Phase, Player


def make_game(roles: list[str], pockets: dict[int, list[str]] | None = None) -> Game:
    """Гра з гравцями 1..n у заданих ролях, одразу в фазі ночі."""
    g = Game(chat_id=-1)
    for i, role in enumerate(roles, start=1):
        g.players[i] = Player(user_id=i, name=f"P{i}", role=role, pocket=list((pockets or {}).get(i, [])))
    g.phase = Phase.NIGHT
    g.day = 1
    return g
