"""
Role and Ability system for dynamic Mafia game roles
"""

from enum import Enum
from typing import List, Dict, Optional, Any
import json


class AbilityType(Enum):
    """Types of abilities a role can have"""
    KILL = "kill"                      # Kill a player at night
    HEAL = "heal"                      # Heal/protect a player at night
    CHECK_ROLE = "check_role"          # Check another player's role
    BLOCK_ACTION = "block_action"      # Block another player's action
    PROTECT = "protect"                # Protect a player from kills
    INSPECT = "inspect"                # Inspect a player (get info)
    CUSTOM_EFFECT = "custom_effect"    # Custom effect with description


class AbilityPhase(Enum):
    """When an ability can be used"""
    NIGHT = "night"
    DAY = "day"
    BOTH = "both"
    VOTING = "voting"


class TargetType(Enum):
    """Who can be targeted by an ability"""
    SELF = "self"                      # Can only target self
    ONE_PLAYER = "one_player"          # Can target one other player
    TWO_PLAYERS = "two_players"        # Can target two players
    MULTIPLE_PLAYERS = "multiple_players"  # Can target multiple players
    NO_TARGET = "no_target"            # No target required (passive ability)
    ANY_ALIVE = "any_alive"            # Can target any alive player
    ANY_DEAD = "any_dead"              # Can target any dead player


class UsageLimit(Enum):
    """How often an ability can be used"""
    UNLIMITED = "unlimited"            # Can be used every night/day
    ONCE_PER_GAME = "once_per_game"    # Can only be used once in the entire game
    ONCE_PER_NIGHT = "once_per_night"  # Can only be used once per night
    ONCE_PER_DAY = "once_per_day"     # Can only be used once per day


class Ability:
    """Represents a single ability that a role can have"""
    
    def __init__(
        self,
        ability_type: AbilityType,
        name: str,
        description: str = "",
        phase: AbilityPhase = AbilityPhase.NIGHT,
        target_type: TargetType = TargetType.ONE_PLAYER,
        usage_limit: UsageLimit = UsageLimit.UNLIMITED,
        custom_data: Optional[Dict[str, Any]] = None
    ):
        self.ability_type = ability_type
        self.name = name
        self.description = description
        self.phase = phase
        self.target_type = target_type
        self.usage_limit = usage_limit
        self.custom_data = custom_data or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert ability to dictionary for JSON storage"""
        return {
            "ability_type": self.ability_type.value,
            "name": self.name,
            "description": self.description,
            "phase": self.phase.value,
            "target_type": self.target_type.value,
            "usage_limit": self.usage_limit.value,
            "custom_data": self.custom_data
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Ability':
        """Create ability from dictionary"""
        return cls(
            ability_type=AbilityType(data["ability_type"]),
            name=data["name"],
            description=data.get("description", ""),
            phase=AbilityPhase(data.get("phase", "night")),
            target_type=TargetType(data.get("target_type", "one_player")),
            usage_limit=UsageLimit(data.get("usage_limit", "unlimited")),
            custom_data=data.get("custom_data", {})
        )
    
    def can_use_in_phase(self, phase: str) -> bool:
        """Check if ability can be used in given phase"""
        if self.phase == AbilityPhase.BOTH:
            return True
        return self.phase.value == phase
    
    def requires_target(self) -> bool:
        """Check if ability requires a target"""
        return self.target_type != TargetType.NO_TARGET
    
    def __repr__(self) -> str:
        return f"Ability(type={self.ability_type.value}, name={self.name})"


class RoleAlignment(Enum):
    """Role alignment for win condition checking"""
    EVIL = "evil"      # Злі ролі (мафія, маніяк)
    GOOD = "good"      # Добрі ролі (мирні, лікар, шериф)
    NEUTRAL = "neutral"  # Нейтральні ролі (грають за себе)


class Role:
    """Represents a game role with abilities"""
    
    def __init__(
        self,
        name: str,
        description: str,
        abilities: List[Ability],
        creator_id: int,
        group_id: int,
        role_id: Optional[int] = None,
        is_default: bool = False,
        alignment: RoleAlignment = RoleAlignment.GOOD,
        min_players: int = 1,
        enabled: bool = True,
        faction: str = "civilians",
        custom_data: Optional[Dict[str, Any]] = None
    ):
        self.role_id = role_id
        self.name = name
        self.description = description
        self.abilities = abilities
        self.creator_id = creator_id
        self.group_id = group_id
        self.is_default = is_default
        self.alignment = alignment
        self.min_players = min_players
        self.enabled = enabled
        self.faction = faction
        # Додаткові дані для ролі (наприклад, кастомні тексти повідомлень)
        self.custom_data = custom_data or {}
    
    def get_abilities_by_phase(self, phase: str) -> List[Ability]:
        """Get all abilities that can be used in given phase"""
        return [ability for ability in self.abilities if ability.can_use_in_phase(phase)]
    
    def get_ability_by_type(self, ability_type: AbilityType) -> Optional[Ability]:
        """Get first ability of given type"""
        for ability in self.abilities:
            if ability.ability_type == ability_type:
                return ability
        return None
    
    def has_ability_type(self, ability_type: AbilityType) -> bool:
        """Check if role has ability of given type"""
        return any(ability.ability_type == ability_type for ability in self.abilities)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert role to dictionary for JSON storage"""
        return {
            "role_id": self.role_id,
            "name": self.name,
            "description": self.description,
            "abilities": [ability.to_dict() for ability in self.abilities],
            "creator_id": self.creator_id,
            "group_id": self.group_id,
            "is_default": self.is_default,
            "alignment": self.alignment.value if isinstance(self.alignment, RoleAlignment) else self.alignment,
            "min_players": self.min_players,
            "enabled": self.enabled,
            "faction": self.faction,
            "custom_data": self.custom_data
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Role':
        """Create role from dictionary"""
        abilities = [Ability.from_dict(ab) for ab in data.get("abilities", [])]
        alignment_str = data.get("alignment", "good")
        alignment = RoleAlignment(alignment_str) if isinstance(alignment_str, str) else alignment_str
        return cls(
            role_id=data.get("role_id"),
            name=data["name"],
            description=data["description"],
            abilities=abilities,
            creator_id=data["creator_id"],
            group_id=data["group_id"],
            is_default=data.get("is_default", False),
            alignment=alignment,
            min_players=int(data.get("min_players", 1)) if data.get("min_players") is not None else 1,
            enabled=bool(data.get("enabled", True)) if data.get("enabled") is not None else True,
            faction=data.get("faction", "civilians"),
            custom_data=data.get("custom_data", {}) or {}
        )
    
    def to_json(self) -> str:
        """Convert role to JSON string"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'Role':
        """Create role from JSON string"""
        return cls.from_dict(json.loads(json_str))
    
    def __repr__(self) -> str:
        return f"Role(name={self.name}, abilities={len(self.abilities)})"


def create_default_roles() -> Dict[str, Role]:
    """
    Create default Mafia roles. Each chat gets a copy on first use.
    Увімкнення/вимкнення та min_players налаштовуються окремо для кожної групи через /construct_event.
    """
    roles = {}
    
    # 1. Аль Капоне (Дон) - ЗЛА роль, can kill at night
    roles["Аль Капоне"] = Role(
        name="Аль Капоне",
        description="Цієї гри - ти Аль Капоне 🎩\n\nТвоя ціль - привести свою сім'ю до перемоги, навіть ціною власного життя.",
        abilities=[
            Ability(
                ability_type=AbilityType.KILL,
                name="Вбивство",
                description="🤔 Хто перейшов тобі дорогу сьогодні?",
                phase=AbilityPhase.NIGHT,
                target_type=TargetType.ONE_PLAYER,
                usage_limit=UsageLimit.ONCE_PER_NIGHT
            )
        ],
        creator_id=0,
        group_id=0,
        is_default=True,
        alignment=RoleAlignment.EVIL,
        min_players=3,
        enabled=True,
        faction="mafia"
    )
    
    # 2. Мафія - повідомник Дона (вбиває, якщо Дон спить). З'являється при 7+ гравцях
    roles["Мафія"] = Role(
        name="Мафія",
        description="Цієї гри - ти Мафія 🤵\n\nТвоя ціль - навчитися мудрості Аль Капоне, та зайняти його місце, в разі смерті.",
        abilities=[
            Ability(
                ability_type=AbilityType.KILL,
                name="Вбивство",
                description="🤔Кому ми помстимося сьогодні?",
                phase=AbilityPhase.NIGHT,
                target_type=TargetType.ONE_PLAYER,
                usage_limit=UsageLimit.ONCE_PER_NIGHT
            )
        ],
        creator_id=0,
        group_id=0,
        is_default=True,
        alignment=RoleAlignment.EVIL,
        min_players=7,
        enabled=True,
        faction="mafia"
    )
    
    # 3. Доктор - ДОБРА роль, can heal at night (при players 4+)
    roles["Лікар"] = Role(
        name="Лікар",
        description="Цієї гри - ти Лікар 💊\n\nТвоя ціль - врятувати якомога більше безневинних, та при можливості - себе.",
        abilities=[
            Ability(
                ability_type=AbilityType.HEAL,
                name="Лікування",
                description="🤔 Кого лікуватимемо сьогодні?",
                phase=AbilityPhase.NIGHT,
                target_type=TargetType.ONE_PLAYER,
                usage_limit=UsageLimit.ONCE_PER_NIGHT
            )
        ],
        creator_id=0,
        group_id=0,
        is_default=True,
        alignment=RoleAlignment.GOOD,
        min_players=4,
        enabled=True,
        faction="civilians"
    )
    
    # 4. Комісар Каттані - ДОБРА роль, can check or kill at night (при players 4+)
    roles["Комісар Каттані"] = Role(
        name="Комісар Каттані",
        description=(
            "Цієї гри - ти Комісар Каттані 🕵️\n\n"
            "Ти - закон у місті, де закон довго не живе.\n"
            "Твоя ціль - знайти мафію та допомогти мирним вижити.\n"
            "Ти не герой. Ти - вирок."
        ),
        abilities=[
            Ability(
                ability_type=AbilityType.CHECK_ROLE,
                name="Перевірка ролі",
                description="Кого перевіримо цієї ночі?",
                phase=AbilityPhase.NIGHT,
                target_type=TargetType.ONE_PLAYER,
                usage_limit=UsageLimit.ONCE_PER_NIGHT
            ),
            Ability(
                ability_type=AbilityType.KILL,
                name="Вбивство",
                description="Обери гравця, якого хочеш усунути цієї ночі",
                phase=AbilityPhase.NIGHT,
                target_type=TargetType.ONE_PLAYER,
                usage_limit=UsageLimit.ONCE_PER_NIGHT
            )
        ],
        creator_id=0,
        group_id=0,
        is_default=True,
        alignment=RoleAlignment.GOOD,
        min_players=4,
        enabled=True,
        faction="civilians"
    )
    
    # 5. Коханка - НЕЙТРАЛЬНА роль, can block actions at night
    roles["Коханка"] = Role(
        name="Коханка",
        description="Цієї гри - ти Коханка 💃\n\nТвоя ціль - не відпустити зрадливого чоловіка додому, щоб його дружина не дізналася про вас.",
        abilities=[
            Ability(
                ability_type=AbilityType.BLOCK_ACTION,
                name="Глушіння",
                description="🤔 Хто ж сьогодні був не вірним ?",
                phase=AbilityPhase.NIGHT,
                target_type=TargetType.ONE_PLAYER,
                usage_limit=UsageLimit.ONCE_PER_NIGHT
            )
        ],
        creator_id=0,
        group_id=0,
        is_default=True,
        alignment=RoleAlignment.NEUTRAL,
        min_players=3,
        enabled=True,
        faction="civilians"
    )
    
    # 7. Маніяк - ЗЛА роль, can kill at night (independent)
    roles["Маніяк"] = Role(
        name="Маніяк",
        description=(
            "Цієї гри ти - Маніяк 🔪\n"
            "Ти не підпорядковуєшся жодній команді.\n"
            "Твоя мета - вижити і знищити стільки гравців, скільки можеш.\n\n"
        ),
        abilities=[
            Ability(
                ability_type=AbilityType.KILL,
                name="Вбивство",
                description="Обери кого вбити цієї ночі",
                phase=AbilityPhase.NIGHT,
                target_type=TargetType.ONE_PLAYER,
                usage_limit=UsageLimit.ONCE_PER_NIGHT
            )
        ],
        creator_id=0,
        group_id=0,
        is_default=True,
        alignment=RoleAlignment.EVIL,
        min_players=16,
        enabled=True,
        faction="maniac"
    )
    
    # 9. Мирний житель - ДОБРА роль, no special abilities
    roles["Мирний житель"] = Role(
        name="Мирний житель",
        description=(
            "Цієї гри - ти Мирний житель 🧍\n\n"
            "У тебе немає влади.\n"
            "У тебе є тільки інтуїція та голос."
        ),
        abilities=[],
        creator_id=0,
        group_id=0,
        is_default=True,
        alignment=RoleAlignment.GOOD,
        min_players=3,
        enabled=True,
        faction="civilians"
    )

    # 10. Самогубець
    roles["Самогубець"] = Role(
        name="Самогубець",
        description=(
            "Цієї гри - ти Самогубець 🏍️\n\n"
            "Твоя ціль - бути повішаним обманним шляхом. Ніхто не повинен дізнатися твоїх справжніх намірів 🤫"
        ),
        abilities=[],
        creator_id=0,
        group_id=0,
        is_default=True,
        alignment=RoleAlignment.NEUTRAL,
        min_players=3,
        enabled=True,
        faction="suicide"
    )
    
    # 11. Волоцюга
    roles["Волоцюга"] = Role(
        name="Волоцюга",
        description=(
            "Цієї гри — ти Волоцюга 🧥\n"
            "Твоя ціль — вижити і дізнатися, кому не спиться вночі."
        ),
        abilities=[
            Ability(
                ability_type=AbilityType.INSPECT,
                name="Спостереження",
                description="Обери гравця для спостереження",
                phase=AbilityPhase.NIGHT,
                target_type=TargetType.ONE_PLAYER,
                usage_limit=UsageLimit.ONCE_PER_NIGHT
            )
        ],
        creator_id=0,
        group_id=0,
        is_default=True,
        alignment=RoleAlignment.GOOD,
        min_players=3,
        enabled=True,
        faction="civilians"
    )
    
    # 13. Камікадзе
    roles["Камікадзе"] = Role(
        name="Камікадзе",
        description=(
            "Цієї гри — ти Камікадзе 💥\n"
            "Твоя ціль — вижити як мирний житель… але ти знаєш, що навіть смерть може бути потужною зброєю."
        ),
        abilities=[],
        creator_id=0,
        group_id=0,
        is_default=True,
        alignment=RoleAlignment.GOOD,
        min_players=3,
        enabled=True,
        faction="civilians"
    )
    
    # 15. Сержант
    roles["Сержант"] = Role(
        name="Сержант",
        description=(
            "Цієї гри - ти Сержант 🎖️\n\n"
            "Твоя ціль - служити закону і бути готовим прийняти командування.\n"
            "Поки Комісар Каттані живий - ти його тінь.\n"
            "Якщо він загине - ти займаєш його місце."
        ),
        abilities=[],
        creator_id=0,
        group_id=0,
        is_default=True,
        alignment=RoleAlignment.GOOD,
        min_players=15,
        enabled=True,
        faction="civilians"
    )
    
    # 16. Щасливчик
    roles["Щасливчик"] = Role(
        name="Щасливчик",
        description=(
            "<b>Цієї гри - ти Щасливчик</b> 🍀\n\n"
            "Фортуна завжди на твоєму боці… майже.\n"
            "Ти виживаєш там, де інші гинуть, і тобі часто щастить у випадкових ситуаціях."
        ),
        abilities=[],
        creator_id=0,
        group_id=0,
        is_default=True,
        alignment=RoleAlignment.GOOD,
        min_players=4,
        enabled=True,
        faction="civilians"
    )
    
    # 17. Мед. сестра
    roles["Мед. сестра"] = Role(
        name="Мед. сестра",
        description=(
            "Цієї гри — ти Медсестра 👩‍⚕️\n\n"
            "Твоя роль — бути поруч.\n"
            "Тримати світло в операційній увімкненим і чекати моменту, коли хтось не повернеться зі зміни.\n"
            "Поки Лікар живий, ти лише спостерігаєш, вчишся і запам'ятовуєш кожен рух."
        ),
        abilities=[
            Ability(
                ability_type=AbilityType.HEAL,
                name="Лікування",
                description="Лікування (активується після смерті Доктора)",
                phase=AbilityPhase.NIGHT,
                target_type=TargetType.ONE_PLAYER,
                usage_limit=UsageLimit.ONCE_PER_NIGHT
            )
        ],
        creator_id=0,
        group_id=0,
        is_default=True,
        alignment=RoleAlignment.GOOD,
        min_players=3,
        enabled=True,
        faction="civilians"
    )
    
    # 18. Журналіст
    roles["Журналіст"] = Role(
        name="Журналіст",
        description=(
            "<b>Цієї гри - ти Журналіст</b> 📰\n\n"
            "Ти не вбиваєш і не рятуєш, але володієш інформацією.\n"
            "Твоя ціль - виявити, хто в місті на одній хвилі, а хто ні, через нічні інтерв'ю."
        ),
        abilities=[
            Ability(
                ability_type=AbilityType.INSPECT,
                name="Перевірка клану",
                description="Обери двох гравців для порівняння",
                phase=AbilityPhase.NIGHT,
                target_type=TargetType.TWO_PLAYERS,
                usage_limit=UsageLimit.ONCE_PER_NIGHT
            )
        ],
        creator_id=0,
        group_id=0,
        is_default=True,
        alignment=RoleAlignment.GOOD,
        min_players=17,
        enabled=True,
        faction="civilians"
    )
    
    # 19. Адвокат (мафія)
    roles["Адвокат"] = Role(
        name="Адвокат",
        description=(
            "Цієї гри - ти Адвокат ⚖️\n\n"
            "Твоя ціль - впливати на результат перевірок. Ти не належиш до мафії, але можеш захистити її від викриття."
        ),
        abilities=[
            Ability(
                ability_type=AbilityType.PROTECT,
                name="Захист клієнта",
                description="Обери клієнта для захисту",
                phase=AbilityPhase.NIGHT,
                target_type=TargetType.ONE_PLAYER,
                usage_limit=UsageLimit.ONCE_PER_NIGHT
            )
        ],
        creator_id=0,
        group_id=0,
        is_default=True,
        alignment=RoleAlignment.EVIL,
        min_players=3,
        enabled=True,
        faction="mafia"
    )
    
    # 21. Клоун
    roles["Клоун"] = Role(
        name="Клоун",
        description=(
            "Цієї гри ти - Клоун 🤡\n"
            "Ти - хаос і плутанина.\n"
            "За всю гру у тебе є один шанс: зайти до двох гравців і поміняти їхні ролі місцями.\n"
            "Це може повністю змінити хід гри."
        ),
        abilities=[
            Ability(
                ability_type=AbilityType.CUSTOM_EFFECT,
                name="Обмін ролями",
                description="Обери двох гравців для обміну ролями",
                phase=AbilityPhase.NIGHT,
                target_type=TargetType.TWO_PLAYERS,
                usage_limit=UsageLimit.ONCE_PER_GAME
            )
        ],
        creator_id=0,
        group_id=0,
        is_default=True,
        alignment=RoleAlignment.NEUTRAL,
        min_players=18,
        enabled=True,
        faction="civilians"
    )
    
    # 27. Брехун
    roles["Брехун"] = Role(
        name="Брехун",
        description=(
            "Цієї гри - ти Брехун 🎭\n\n"
            "Твоя ціль - зламати довіру до Комісара.\n"
            "Ти не вбиваєш і не рятуєш.\n"
            "Ти змінюєш те, що вважають беззаперечними доказами."
        ),
        abilities=[Ability(AbilityType.CUSTOM_EFFECT, "Фальсифікація", "Обери гравця для фальсифікації досьє", AbilityPhase.NIGHT, TargetType.ONE_PLAYER, UsageLimit.ONCE_PER_NIGHT)],
        creator_id=0,
        group_id=0,
        is_default=True,
        alignment=RoleAlignment.EVIL,
        min_players=3,
        enabled=True,
        faction="mafia"
    )
    
    # 28. Диявол
    roles["Диявол"] = Role(
        name="Диявол",
        description=(
            "Цієї гри ти - 👹 Диявол.\n\n"
            "Ти - спокуса.\n"
            "Ти - шепіт у темряві.\n"
            "Ти - угода, яку не можна розірвати.\n"
            "Щоночі ти приходиш до людей.\n"
            "Не з ножем. Не з погрозами.\n"
            "А з вибором.\n"
            "Ти простягаєш контракт, написаний не чорнилом - а страхом.\n"
            "Взамін - лише дві душі."
        ),
        abilities=[
            Ability(
                ability_type=AbilityType.CUSTOM_EFFECT,
                name="Пропозиція контракту",
                description="Обери гравця, якому запропонувати контракт",
                phase=AbilityPhase.NIGHT,
                target_type=TargetType.ONE_PLAYER,
                usage_limit=UsageLimit.ONCE_PER_NIGHT
            )
        ],
        creator_id=0,
        group_id=0,
        is_default=True,
        alignment=RoleAlignment.NEUTRAL,
        min_players=3,
        enabled=True,
        faction="devil"
    )

    return roles


def create_event_roles() -> Dict[str, Role]:
    """
    Ролі сезонного івенту «Купальська ніч». Підмішуються у пул лише коли івент активний.
      • Русалка (мирна): «Водний потік» (перенаправлення) + «Оберіг глибин» (захист, далі «Виснаження»).
      • Мисливець на русалку (нейтрал): «Засідка» (блок дії) + «Гарпун» (1/гру, ігнорує щити).
    """
    roles: Dict[str, Role] = {}

    roles["Русалка"] = Role(
        name="Русалка",
        description=(
            "🧜 Цієї гри — ти Русалка\n\n"
            "Ти володієш силою води: можеш захистити обраного гравця "
            "або перенаправити небезпеку на інший шлях."
        ),
        abilities=[
            Ability(
                ability_type=AbilityType.CUSTOM_EFFECT,
                name="Водний потік",
                description="Обери Гравця А та Гравця Б: атаку злих з А буде перенаправлено на Б.",
                phase=AbilityPhase.NIGHT,
                target_type=TargetType.TWO_PLAYERS,
                usage_limit=UsageLimit.ONCE_PER_NIGHT,
            ),
            Ability(
                ability_type=AbilityType.PROTECT,
                name="Оберіг глибин",
                description="Захисти гравця на 1 ніч. Далі ти «Виснажена» (1 ніч без дій).",
                phase=AbilityPhase.NIGHT,
                target_type=TargetType.ONE_PLAYER,
                usage_limit=UsageLimit.ONCE_PER_NIGHT,
            ),
        ],
        creator_id=0,
        group_id=0,
        is_default=False,
        alignment=RoleAlignment.GOOD,
        min_players=5,
        enabled=True,
        faction="civilians",
    )

    roles["Мисливець на русалку"] = Role(
        name="Мисливець на русалку",
        description=(
            "🩸 Цієї гри — ти Мисливець на русалку\n\n"
            "Ти вистежуєш створінь глибин, руйнуєш їхні задуми та володієш зброєю, "
            "здатною пробити навіть найміцніший захист."
        ),
        abilities=[
            Ability(
                ability_type=AbilityType.BLOCK_ACTION,
                name="Засідка",
                description="Ціль не зможе використати свою нічну дію.",
                phase=AbilityPhase.NIGHT,
                target_type=TargetType.ONE_PLAYER,
                usage_limit=UsageLimit.ONCE_PER_NIGHT,
            ),
            Ability(
                ability_type=AbilityType.KILL,
                name="Гарпун",
                description="1 раз за гру: атака, що ігнорує щити (не перенаправляється).",
                phase=AbilityPhase.NIGHT,
                target_type=TargetType.ONE_PLAYER,
                usage_limit=UsageLimit.ONCE_PER_GAME,
            ),
        ],
        creator_id=0,
        group_id=0,
        is_default=False,
        alignment=RoleAlignment.NEUTRAL,
        min_players=5,
        enabled=True,
        faction="neutral",
    )

    return roles
