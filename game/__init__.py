"""
Game module for Mafia bot - handles role management, abilities, and game logic.

Key components:
- role_system: Role and Ability classes with enums
- role_manager: Low-level database operations for roles
- chat_role_registry: High-level role registry with chat scoping and auto-initialization
- ability_resolver: Ability execution and validation logic
"""

from .role_system import (
    Role, Ability, AbilityType, AbilityPhase, TargetType, UsageLimit, RoleAlignment, create_default_roles
)
from .role_manager import RoleManager
from .chat_role_registry import ChatRoleRegistry

__all__ = [
    "Role",
    "Ability",
    "AbilityType",
    "AbilityPhase",
    "TargetType",
    "UsageLimit",
    "RoleAlignment",
    "create_default_roles",
    "RoleManager",
    "ChatRoleRegistry",
]
