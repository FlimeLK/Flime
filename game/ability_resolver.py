"""
Ability Resolver - executes abilities during game phases
"""

from typing import List, Dict, Optional, Any, Set
import asyncio
from database.database import cursor, conn
from .role_system import Role, Ability, AbilityType, AbilityPhase, TargetType


class AbilityResolver:
    """Resolves and executes role abilities during game phases"""
    
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.ability_usage_tracker: Dict[int, Dict[str, Set[int]]] = {}  # {player_id: {ability_type: {night_number}}}
        self.action_results: Dict[str, Any] = {}  # Stores results of actions (e.g., {"kill": target_id})
    
    def reset_for_new_game(self):
        """Reset tracking for a new game"""
        self.ability_usage_tracker.clear()
        self.action_results.clear()
    
    def reset_for_new_night(self):
        """Reset night-specific tracking"""
        # Keep once_per_game tracking, but reset night tracking
        for player_id in self.ability_usage_tracker:
            # Remove night-specific entries (will be repopulated)
            self.ability_usage_tracker[player_id] = {
                k: v for k, v in self.ability_usage_tracker[player_id].items()
                if AbilityType(k) in [AbilityType.KILL, AbilityType.HEAL]  # These reset each night
            }
        self.action_results.clear()

    async def _db_fetchone(self, query: str, params: tuple = ()):
        def _run():
            cursor.execute(query, params)
            return cursor.fetchone()
        return await asyncio.to_thread(_run)

    async def _db_execute_commit(self, query: str, params: tuple = ()) -> None:
        def _run():
            cursor.execute(query, params)
            conn.commit()
        await asyncio.to_thread(_run)
    
    def can_use_ability(
        self,
        player_id: int,
        ability: Ability,
        night_number: int = 1
    ) -> tuple[bool, Optional[str]]:
        """
        Check if player can use an ability
        Returns (can_use, reason_if_not)
        """
        # Check usage limits
        if ability.usage_limit.value == "once_per_game":
            if player_id not in self.ability_usage_tracker:
                self.ability_usage_tracker[player_id] = {}
            if ability.ability_type.value in self.ability_usage_tracker[player_id]:
                return False, "Цю здатність можна використати лише один раз за гру"
        
        elif ability.usage_limit.value == "once_per_night":
            if player_id not in self.ability_usage_tracker:
                self.ability_usage_tracker[player_id] = {}
            if ability.ability_type.value in self.ability_usage_tracker[player_id]:
                if night_number in self.ability_usage_tracker[player_id][ability.ability_type.value]:
                    return False, "Ти вже використав цю здатність цієї ночі"
        
        elif ability.usage_limit.value == "once_per_day":
            # Similar logic for day (if needed)
            pass
        
        return True, None
    
    def record_ability_usage(
        self,
        player_id: int,
        ability: Ability,
        night_number: int = 1
    ):
        """Record that an ability was used"""
        if player_id not in self.ability_usage_tracker:
            self.ability_usage_tracker[player_id] = {}
        
        if ability.ability_type.value not in self.ability_usage_tracker[player_id]:
            self.ability_usage_tracker[player_id][ability.ability_type.value] = set()
        
        self.ability_usage_tracker[player_id][ability.ability_type.value].add(night_number)
    
    async def execute_ability(
        self,
        player_id: int,
        ability: Ability,
        target_ids: Optional[List[int]] = None,
        night_number: int = 1,
        bot = None
    ) -> Dict[str, Any]:
        """
        Execute an ability and return result
        Returns result dictionary with action details
        """
        target_ids = target_ids or []
        
        # Check if ability can be used
        can_use, reason = self.can_use_ability(player_id, ability, night_number)
        if not can_use:
            return {"success": False, "reason": reason}
        
        result = {
            "success": True,
            "player_id": player_id,
            "ability_type": ability.ability_type.value,
            "target_ids": target_ids,
            "night_number": night_number
        }
        
        # Execute based on ability type
        if ability.ability_type == AbilityType.KILL:
            if target_ids:
                target_id = target_ids[0]
                await self._db_execute_commit("UPDATE users SET killed = %s WHERE id = %s", (1, target_id,))
                result["target_killed"] = target_id
                self.action_results["kill"] = target_id
        
        elif ability.ability_type == AbilityType.HEAL:
            if target_ids:
                target_id = target_ids[0]
                await self._db_execute_commit("UPDATE users SET cured = %s WHERE id = %s", (1, target_id,))
                result["target_healed"] = target_id
                self.action_results["heal"] = target_id
        
        elif ability.ability_type == AbilityType.CHECK_ROLE:
            if target_ids:
                target_id = target_ids[0]
                role_result = await self._db_fetchone("SELECT role FROM users WHERE id = %s", (target_id,))
                if role_result:
                    result["checked_role"] = role_result[0]
                    if bot:
                        name_result = await self._db_fetchone("SELECT tg_name FROM users WHERE id = %s", (target_id,))
                        target_name = name_result[0] if name_result else "Невідомий"
                        await bot.send_message(
                            chat_id=player_id,
                            text=f"Ти перевірив {target_name}. Його роль: {role_result[0]}"
                        )
        
        elif ability.ability_type == AbilityType.BLOCK_ACTION:
            if target_ids:
                target_id = target_ids[0]
                result["blocked_player"] = target_id
                self.action_results[f"block_{target_id}"] = True
        
        elif ability.ability_type == AbilityType.PROTECT:
            if target_ids:
                target_id = target_ids[0]
                await self._db_execute_commit("UPDATE users SET cured = %s WHERE id = %s", (1, target_id,))
                result["protected_player"] = target_id
                self.action_results["protect"] = target_id
        
        elif ability.ability_type == AbilityType.CUSTOM_EFFECT:
            result["custom_effect"] = ability.custom_data.get("effect_description", "")
            # Custom effects can be extended by game logic
        
        # Record usage
        self.record_ability_usage(player_id, ability, night_number)
        
        return result
    
    def get_action_result(self, action_type: str) -> Optional[Any]:
        """Get result of a specific action type"""
        return self.action_results.get(action_type)
    
    def was_player_blocked(self, player_id: int) -> bool:
        """Check if player's action was blocked"""
        return self.action_results.get(f"block_{player_id}", False)
    
    def get_killed_target(self) -> Optional[int]:
        """Get ID of player who was killed (if any)"""
        return self.action_results.get("kill")
    
    def get_healed_target(self) -> Optional[int]:
        """Get ID of player who was healed (if any)"""
        return self.action_results.get("heal")


def validate_ability_configuration(abilities: List[Dict[str, Any]]) -> tuple[bool, Optional[str]]:
    """
    Validate ability configuration to prevent game-breaking logic
    Returns (is_valid, error_message)
    """
    # Prevent multiple kill abilities on same role
    kill_count = sum(1 for ab in abilities if ab.get("ability_type") == "kill")
    if kill_count > 1:
        return False, "Роль не може мати більше однієї здатності вбивати"
    
    # Prevent invalid target types for kill/heal
    for ab in abilities:
        ability_type = ab.get("ability_type")
        target_type = ab.get("target_type")
        
        if ability_type in ["kill", "heal", "check_role"]:
            if target_type not in ["one_player", "self", "any_alive"]:
                return False, f"Здатність {ability_type} може націлюватися лише на одного гравця"
        
        if ability_type == "kill" and target_type == "self":
            return False, "Здатність вбивати не може націлюватися на себе"
    
    return True, None
