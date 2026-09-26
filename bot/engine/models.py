"""Стан гри. Чисті дані без залежності від Telegram, серіалізуються в JSON."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum

from bot.engine.roles import NightKind, Role, Team, register_custom, role

MIN_PLAYERS = 4
MAX_PLAYERS = 30

# Боти для тестових ігор мають id від -1 до -99 (справжні користувачі — додатні, групи — ≤ -100).
BOT_NAMES = ["Оксана", "Тарас", "Ярина", "Остап", "Соломія", "Богдан", "Марічка", "Данило",
             "Мирослава", "Устим", "Горпина", "Панас", "Одарка", "Микола", "Параска", "Семен",
             "Христя", "Грицько", "Катря", "Омелько"]


def is_bot_player(user_id: int) -> bool:
    return -100 < user_id < 0


class Phase(StrEnum):
    LOBBY = "lobby"
    NIGHT = "night"
    DAY = "day"
    VOTE = "vote"
    CONFIRM = "confirm"
    FINISHED = "finished"


@dataclass
class Player:
    user_id: int
    name: str
    role: str = ""
    alive: bool = True
    # Предмети, взяті з собою в цю гру (ще не використані).
    pocket: list[str] = field(default_factory=list)
    # Службові позначки ролей: kum_saved, self_healed, saber_used, last_heal.
    flags: dict[str, int | bool] = field(default_factory=dict)
    vip: bool = False

    @property
    def role_obj(self) -> Role:
        return role(self.role)

    @property
    def team(self) -> Team:
        return role(self.role).team

    def has(self, item: str) -> bool:
        return item in self.pocket

    def use(self, item: str) -> bool:
        if item in self.pocket:
            self.pocket.remove(item)
            return True
        return False


@dataclass
class Action:
    actor: int
    kind: NightKind
    target: int
    target2: int | None = None


@dataclass
class Game:
    chat_id: int
    phase: Phase = Phase.LOBBY
    players: dict[int, Player] = field(default_factory=dict)
    day: int = 0
    # Нічні дії: ключ "uid:slot" (slot = role | item), щоб гравець міг і діяти роллю, і застосувати вилу.
    actions: dict[str, Action] = field(default_factory=dict)
    # Голоси нечисті за жертву: хто → за кого.
    evil_votes: dict[int, int] = field(default_factory=dict)
    # Денне голосування: хто → за кого (0 = пропустити).
    votes: dict[int, int] = field(default_factory=dict)
    honey_voters: list[int] = field(default_factory=list)
    candidate: int | None = None
    # Підтвердження страти: хто → так/ні.
    confirm: dict[int, bool] = field(default_factory=dict)
    winner: str | None = None
    fool_won: bool = False
    # Налаштування чату на момент старту гри (GroupSettings.to_dict()).
    settings: dict = field(default_factory=dict)
    # Службові ідентифікатори повідомлень у чаті.
    lobby_message_id: int | None = None
    starter_id: int | None = None

    # ---- запити ----
    def alive(self) -> list[Player]:
        return [p for p in self.players.values() if p.alive]

    def alive_ids(self) -> list[int]:
        return [p.user_id for p in self.players.values() if p.alive]

    def by_role(self, role: str, alive_only: bool = True) -> list[Player]:
        return [p for p in self.players.values() if p.role == role and (p.alive or not alive_only)]

    def team_alive(self, team: Team) -> list[Player]:
        return [p for p in self.alive() if p.team == team]

    def evil_leader(self) -> Player | None:
        """Ватажок нечисті: жива Відьма, інакше перший живий Упир, інакше Мавка, інакше будь-хто з нечисті."""
        for key in ("vidma", "upyr", "mavka"):
            found = self.by_role(key)
            if found:
                return found[0]
        evil = self.team_alive(Team.EVIL)
        return evil[0] if evil else None

    def evil_voters(self) -> list[Player]:
        return [p for p in self.alive() if NightKind.KILL in self.night_kinds(p)]

    def night_kinds(self, player: Player) -> list[NightKind]:
        """Які нічні дії доступні гравцю саме цієї ночі."""
        if not player.alive:
            return []
        kinds = list(player.role_obj.night)
        if player.role == "mavka" and not self.by_role("vidma") and not self.by_role("upyr"):
            # Остання з нечисті — сама обирає жертву замість заманювання.
            kinds = [NightKind.KILL]
        if NightKind.SABER in kinds and player.flags.get("saber_used"):
            kinds.remove(NightKind.SABER)
        if player.has("pitchfork"):
            kinds.append(NightKind.PITCHFORK)
        return kinds

    # ---- серіалізація ----
    def to_dict(self) -> dict:
        d = asdict(self)
        d["players"] = [asdict(p) for p in self.players.values()]
        d["actions"] = {k: asdict(a) for k, a in self.actions.items()}
        # JSON-ключі завжди рядки
        d["evil_votes"] = {str(k): v for k, v in self.evil_votes.items()}
        d["votes"] = {str(k): v for k, v in self.votes.items()}
        d["confirm"] = {str(k): v for k, v in self.confirm.items()}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Game:
        g = cls(chat_id=d["chat_id"])
        g.phase = Phase(d["phase"])
        g.players = {p["user_id"]: Player(**p) for p in d["players"]}
        g.day = d["day"]
        g.actions = {
            k: Action(a["actor"], NightKind(a["kind"]), a["target"], a.get("target2"))
            for k, a in d["actions"].items()
        }
        g.evil_votes = {int(k): v for k, v in d["evil_votes"].items()}
        g.votes = {int(k): v for k, v in d["votes"].items()}
        g.honey_voters = list(d["honey_voters"])
        g.candidate = d["candidate"]
        g.confirm = {int(k): v for k, v in d["confirm"].items()}
        g.winner = d["winner"]
        g.fool_won = d["fool_won"]
        g.settings = d["settings"]
        register_custom(g.settings.get("custom_roles", []))
        g.lobby_message_id = d.get("lobby_message_id")
        g.starter_id = d.get("starter_id")
        return g
