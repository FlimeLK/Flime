"""
Item Effects Processor - обробка ефектів предметів з чорного ринку
"""

from typing import Dict, List, Optional, Set, Tuple
from database.database import cursor, conn
from commands.buff_shop import (
    get_active_items_for_player, ITEMS, ItemCategory, ItemType, 
    ActivationTime, CooldownType
)
import random


def _db_fetchone(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchone()


class ItemEffectProcessor:
    """Обробляє ефекти предметів згідно з пріоритетами"""
    
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.processed_items: Set[str] = set()  # Для відстеження використаних предметів
        self.effect_results: Dict[str, any] = {}  # Результати обробки ефектів
    
    def get_player_items(self, user_id: int, activation_time: ActivationTime) -> List[Dict]:
        """Отримує активні предмети гравця для певного часу активації"""
        all_items = get_active_items_for_player(user_id, self.chat_id)
        return [
            item for item in all_items
            if item["activation_time"] == activation_time
            and item["is_active"]
        ]
    
    def process_ultra_passive_effects(self, user_id: int, state) -> Dict:
        """
        Пріоритет 1: Ультра-пасивні ефекти
        Обробляє предмети з найвищим пріоритетом
        """
        items = self.get_player_items(user_id, ActivationTime.NIGHT)
        ultra_items = [item for item in items if item["priority"] == 1]
        
        effects = {
            "invisible": False,  # Димова шашка
            "ignore_block": False,  # Адреналін
            "randomize_checks": False,  # Маска хаосу
            "redirect_all": False,  # Чорна діра
        }
        
        for item in ultra_items:
            effect_data = item.get("effect_data", {})
            effect_type = effect_data.get("effect")
            
            if effect_type == "invisible_to_night_actions":
                effects["invisible"] = True
            elif effect_type == "ignore_block":
                effects["ignore_block"] = True
            elif effect_type == "randomize_all_checks_and_buffs":
                effects["randomize_checks"] = True
            elif effect_type == "redirect_all_actions_to_random":
                effects["redirect_all"] = True
        
        return effects
    
    def process_blocking_effects(self, user_id: int, state) -> Dict:
        """
        Пріоритет 2: Блокування дій
        """
        items = self.get_player_items(user_id, ActivationTime.NIGHT)
        blocking_items = [item for item in items if item["priority"] == 2]
        
        effects = {
            "cancel_night_action": False,  # Вогнегасник
            "block_eavesdropping": False,  # Глушилка сигналу
            "block_role_check": False,  # Посвідчення особи
            "block_first_visitor": False,  # Капкан
            "reflect_effects": False,  # Дзеркало хаосу
        }
        
        for item in blocking_items:
            effect_data = item.get("effect_data", {})
            effect_type = effect_data.get("effect")
            
            if effect_type == "cancel_night_action":
                effects["cancel_night_action"] = True
            elif effect_type == "block_eavesdropping":
                effects["block_eavesdropping"] = True
            elif effect_type == "block_role_check":
                effects["block_role_check"] = True
            elif effect_type == "block_first_visitor_action":
                effects["block_first_visitor"] = True
            elif effect_type == "reflect_all_effects":
                effects["reflect_effects"] = True
        
        return effects
    
    def process_redirect_effects(self, user_id: int, state) -> Dict:
        """
        Пріоритет 3: Перенаправлення дій
        """
        items = self.get_player_items(user_id, ActivationTime.NIGHT)
        redirect_items = [item for item in items if item["priority"] == 3]
        
        effects = {
            "redirect_action": False,  # Магніт
            "redirect_all": False,  # Чорна діра
        }
        
        for item in redirect_items:
            effect_data = item.get("effect_data", {})
            effect_type = effect_data.get("effect")
            
            if effect_type == "redirect_action":
                effects["redirect_action"] = True
            elif effect_type == "redirect_all_actions_to_random":
                effects["redirect_all"] = True
        
        return effects
    
    def process_protection_effects(self, user_id: int, state) -> Dict:
        """
        Пріоритет 4: Захист
        """
        items = self.get_player_items(user_id, ActivationTime.NIGHT)
        protection_items = [item for item in items if item["priority"] == 4]
        
        effects = {
            "extra_role_action": False,  # Енергетик
        }
        
        for item in protection_items:
            effect_data = item.get("effect_data", {})
            effect_type = effect_data.get("effect")
            
            if effect_type == "extra_role_action":
                effects["extra_role_action"] = True
        
        return effects
    
    def process_post_effects(self, user_id: int, state, phase: str) -> Dict:
        """
        Пріоритет 6: Пост-ефекти (після ночі, після смерті)
        """
        activation_time = ActivationTime.AFTER_NIGHT if phase == "after_night" else ActivationTime.AFTER_DEATH
        items = self.get_player_items(user_id, activation_time)
        post_items = [item for item in items if item["priority"] == 6]
        
        effects = {
            "reveal_visitors": False,   # Пейджер
            "kill_killer": False,       # Закладка / Tommy Gun
            "skip_next_night": False,   # Чорний феєрверк
            "hide_role": False,         # Папка X
            "skip_next_night_all": False,  # Ядерний феєрверк
            "kill_all_attackers": False,   # Міна Апокаліпсис
            "reveal_killer": False,     # Ліхтарик (новий) - показати вбивцю
        }
        
        for item in post_items:
            effect_data = item.get("effect_data", {})
            effect_type = effect_data.get("effect")
            
            if effect_type == "reveal_visitors":
                effects["reveal_visitors"] = True
            elif effect_type == "kill_killer_on_death":
                effects["kill_killer"] = True
            elif effect_type == "skip_next_night_actions":
                effects["skip_next_night"] = True
            elif effect_type == "hide_role_and_actions":
                effects["hide_role"] = True
            elif effect_type == "skip_next_night_all_actions":
                effects["skip_next_night_all"] = True
            elif effect_type == "kill_all_attackers":
                effects["kill_all_attackers"] = True
            elif effect_type == "reveal_killer":
                effects["reveal_killer"] = True
        
        return effects
    
    def should_block_action(self, target_id: int, action_type: str, state) -> bool:
        """Перевіряє, чи має бути заблокована дія на гравця"""
        blocking = self.process_blocking_effects(target_id, state)
        
        if action_type == "kill" and blocking.get("cancel_night_action"):
            return True
        if action_type == "check" and blocking.get("block_role_check"):
            return True
        if action_type == "eavesdrop" and blocking.get("block_eavesdropping"):
            return True
        
        return False
    
    def should_redirect_action(self, target_id: int, state) -> Optional[int]:
        """Перевіряє, чи має бути перенаправлена дія на іншого гравця"""
        redirect = self.process_redirect_effects(target_id, state)
        
        if redirect.get("redirect_action") or redirect.get("redirect_all"):
            # Перенаправляємо на випадкового гравця
            alive_players = [pid for pid in state.membersList if pid != target_id]
            if alive_players:
                return random.choice(alive_players)
        
        return None
    
    def get_vote_reduction(self, target_id: int) -> int:
        """Повертає кількість голосів, які мають бути зменшені проти гравця"""
        items = self.get_player_items(target_id, ActivationTime.DAY)
        for item in items:
            effect_data = item.get("effect_data", {})
            if effect_data.get("effect") == "reduce_vote":
                return effect_data.get("amount", 0)
        return 0
        
    def should_randomize_single_check(self, target_id: int) -> bool:
        """Маска: Комісар побачить випадкову роль (1 раз за ніч)"""
        items = self.get_player_items(target_id, ActivationTime.NIGHT)
        for item in items:
            effect_data = item.get("effect_data", {})
            if effect_data.get("effect") == "randomize_single_check":
                return True
        return False
    
    def can_escape_voting(self, user_id: int) -> bool:
        """Перевіряє, чи може гравець втекти з голосування"""
        items = self.get_player_items(user_id, ActivationTime.DAY)
        for item in items:
            effect_data = item.get("effect_data", {})
            if effect_data.get("effect") == "escape_voting":
                return True
        return False
    
    def should_ignore_first_vote(self, player_id: int) -> bool:
        """Перевіряє, чи має гравець предмет (Цукерка), що ігнорує перший голос проти нього"""
        items = self.get_player_items(player_id, ActivationTime.DAY)
        for item in items:
            effect_data = item.get("effect_data", {})
            if effect_data.get("effect") == "ignore_first_vote" or item.get("item_id") == "candy":
                return True
        return False
    
    def should_hide_role_on_death(self, user_id: int) -> bool:
        """Перевіряє, чи має бути прихована роль після смерті"""
        effects = self.process_post_effects(user_id, None, "after_death")
        return effects.get("hide_role", False)
    
    def should_kill_killer_on_death(self, user_id: int, killer_id: Optional[int]) -> bool:
        """Перевіряє, чи має вбивця померти разом з жертвою"""
        effects = self.process_post_effects(user_id, None, "after_death")
        return effects.get("kill_killer", False) and killer_id is not None

    def should_reveal_checker(self, target_id: int) -> bool:
        """Чи має гравець предмет Дзеркальце (дізнатися, хто його перевіряв - комісар/сержант)."""
        row = _db_fetchone(
            "SELECT 1 FROM user_buffs WHERE user_id = %s AND buff_id = %s AND COALESCE(quantity, 1) > 0",
            (target_id, "mirror"),
        )
        return row is not None
