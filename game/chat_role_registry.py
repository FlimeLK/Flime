"""
Chat Role Registry - Manages roles per chat with proper scoping and isolation.

This module ensures that:
- Each chat has its own isolated role scope
- Default roles are auto-initialized per chat
- Custom roles are isolated per chat_id
- Default roles cannot be deleted or modified
- All role operations are scoped by chat_id
"""

from typing import List, Optional, Dict
from database.database import cursor, conn
import os
from .role_system import Role, Ability, AbilityType, AbilityPhase, TargetType, UsageLimit, create_default_roles
from .role_manager import RoleManager
from datetime import datetime
import json

# #region agent log
_log_path = r"c:\Users\flime\OneDrive\Desktop\MafiaAllCaponeBot\.cursor\debug.log"
def _log_debug(session_id, run_id, hypothesis_id, location, message, data):
    try:
        os.makedirs(os.path.dirname(_log_path), exist_ok=True)
        with open(_log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                "sessionId": session_id,
                "runId": run_id,
                "hypothesisId": hypothesis_id,
                "location": location,
                "message": message,
                "data": data,
                "timestamp": int(datetime.now().timestamp() * 1000)
            }) + "\n")
            f.flush()
    except:
        pass
# #endregion


def _db_fetchone(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchone()


def _db_fetchall(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchall()


class ChatRoleRegistry:
    """
    Registry for managing roles per chat.
    Ensures complete isolation between chats - roles from one chat never appear in another.
    """
    
    # Cache for tracking which chats have initialized default roles
    _initialized_chats: set = set()
    
    @staticmethod
    def ensure_default_roles_for_chat(creator_id: int, chat_id: int) -> None:
        """
        Ensure default roles exist for a specific chat.
        Called automatically when accessing roles for a chat.
        This ensures each chat has its own copy of default roles.
        """
        # Normalize chat_id
        chat_id_int = int(chat_id) if not isinstance(chat_id, tuple) else int(chat_id[0])
        
        # Check if already initialized (using cache)
        cache_key = (creator_id, chat_id_int)
        
        # Get all default role templates (should be 10 roles now)
        default_role_templates = create_default_roles()
        expected_role_count = len(default_role_templates)
        
        # Check database which default roles exist
        rows = _db_fetchall("""
            SELECT role_name FROM custom_roles
            WHERE creator_id = %s AND group_id = %s AND is_default = TRUE
        """, (creator_id, chat_id_int))
        existing_role_names = {row[0] for row in rows}
        
        # Check if all default roles are present
        all_roles_exist = True
        for role_template in default_role_templates.values():
            if role_template.name not in existing_role_names:
                all_roles_exist = False
                break
        
        # Завжди читаємо актуальні дані з БД, не покладаємося на кеш
        # Кеш використовується тільки для оптимізації, але не для зберігання даних
        
        # Initialize missing default roles for this chat
        roles_added = 0
        roles_updated = 0
        for role_key, role_template in default_role_templates.items():
            # Check if this default role already exists for this chat
            if role_template.name in existing_role_names:
                # Завжди читаємо актуальну роль з БД, щоб отримати останні зміни
                try:
                    existing_role = RoleManager.get_role(creator_id, chat_id_int, role_template.name)
                    if existing_role:
                        # НЕ оновлюємо enabled та min_players автоматично з шаблону
                        # Це дозволяє користувачам змінювати ці значення через налаштування ролей
                        # і вони будуть зберігатися
                        pass  # Роль вже існує, залишаємо її як є
                except Exception as e:
                    print(f"Error reading default role {role_template.name} for chat {chat_id_int}: {e}")
                    import traceback
                    traceback.print_exc()
                continue  # Role already exists, skip
            
            # Create a copy of the default role for this chat (with alignment, enabled status, and min_players)
            chat_role = Role(
                name=role_template.name,
                description=role_template.description,
                abilities=role_template.abilities.copy() if role_template.abilities else [],
                creator_id=creator_id,
                group_id=chat_id_int,
                is_default=True,
                alignment=role_template.alignment if hasattr(role_template, 'alignment') else None,
                enabled=getattr(role_template, 'enabled', True),  # Копіюємо enabled з шаблону
                min_players=getattr(role_template, 'min_players', 1)  # Копіюємо min_players з шаблону
            )
            
            # Save to database
            try:
                RoleManager.save_role(chat_role)
                roles_added += 1
            except Exception as e:
                print(f"Error saving default role {role_template.name} for chat {chat_id_int}: {e}")
        
        # Mark as initialized if roles were added/updated or all already exist
        if roles_added > 0 or roles_updated > 0:
            # Commit вже виконано після кожного оновлення, але переконаємося
            if roles_added > 0:
                conn.commit()  # Для нових ролей
            if roles_added > 0:
                print(f"Initialized {roles_added} new default roles for chat {chat_id_int}")
            if roles_updated > 0:
                print(f"Updated {roles_updated} existing default roles for chat {chat_id_int}")
                # Після оновлення ролей, очищаємо кеш, щоб наступний виклик завантажив оновлені значення
                # (але не видаляємо з _initialized_chats, щоб не повторювати оновлення зайвий раз)
        
        ChatRoleRegistry._initialized_chats.add(cache_key)
    
    @staticmethod
    def get_all_roles_for_chat(creator_id: int, chat_id: int) -> List[Role]:
        """
        Get all roles (default + custom) for a specific chat.
        Ensures default roles are initialized before returning.
        
        Завжди читає актуальні дані з БД, не використовує кеш для зберігання ролей.
        Кеш використовується тільки для оптимізації ініціалізації.
        
        Args:
            creator_id: The creator/owner of the chat
            chat_id: The chat/group ID (must be unique per chat)
            
        Returns:
            List of Role objects scoped to this chat only
        """
        chat_id_int = int(chat_id) if not isinstance(chat_id, tuple) else int(chat_id[0])
        
        # Ensure default roles exist
        ChatRoleRegistry.ensure_default_roles_for_chat(creator_id, chat_id_int)
        
        # Завжди читаємо актуальні ролі з БД (не використовуємо кеш)
        # Це гарантує, що зміни, внесені через налаштування ролей, застосовуються негайно
        roles = RoleManager.get_all_roles(creator_id, chat_id_int)
        # #region agent log
        _log_debug('debug-session', 'run1', 'R1', 'chat_role_registry.py:get_all_roles_for_chat', 'Fetched roles', {
            'creator_id': creator_id,
            'chat_id': chat_id_int,
            'roles_len': len(roles)
        })
        # #endregion
        
        return roles
    
    @staticmethod
    def get_default_roles_for_chat(creator_id: int, chat_id: int) -> List[Role]:
        """
        Get only default roles for a specific chat.
        
        Args:
            creator_id: The creator/owner of the chat
            chat_id: The chat/group ID
            
        Returns:
            List of default Role objects for this chat
        """
        chat_id_int = int(chat_id) if not isinstance(chat_id, tuple) else int(chat_id[0])
        
        # Ensure default roles exist
        ChatRoleRegistry.ensure_default_roles_for_chat(creator_id, chat_id_int)
        
        # Get default roles only
        rows = _db_fetchall("""
            SELECT role_id, role_name, role_description, role_data, is_default
            FROM custom_roles
            WHERE creator_id = %s AND group_id = %s AND is_default = TRUE
            ORDER BY role_name
        """, (creator_id, chat_id_int))
        
        roles = []
        for row in rows:
            role_id, name, description, role_data_raw, is_default = row
            # Handle JSONB data
            if isinstance(role_data_raw, dict):
                role_data = role_data_raw
            elif isinstance(role_data_raw, str):
                role_data = json.loads(role_data_raw)
            else:
                continue
            
            role = Role.from_dict(role_data)
            role.role_id = role_id
            role.is_default = is_default
            roles.append(role)
        
        return roles
    
    @staticmethod
    def get_custom_roles_for_chat(creator_id: int, chat_id: int) -> List[Role]:
        """
        Get only custom (user-created) roles for a specific chat.
        
        Args:
            creator_id: The creator/owner of the chat
            chat_id: The chat/group ID
            
        Returns:
            List of custom Role objects for this chat
        """
        chat_id_int = int(chat_id) if not isinstance(chat_id, tuple) else int(chat_id[0])
        
        # Get custom roles only (is_default = FALSE)
        rows = _db_fetchall("""
            SELECT role_id, role_name, role_description, role_data, is_default
            FROM custom_roles
            WHERE creator_id = %s AND group_id = %s AND is_default = FALSE
            ORDER BY role_name
        """, (creator_id, chat_id_int))
        
        roles = []
        for row in rows:
            role_id, name, description, role_data_raw, is_default = row
            # Handle JSONB data
            if isinstance(role_data_raw, dict):
                role_data = role_data_raw
            elif isinstance(role_data_raw, str):
                role_data = json.loads(role_data_raw)
            else:
                continue
            
            role = Role.from_dict(role_data)
            role.role_id = role_id
            role.is_default = is_default
            roles.append(role)
        
        return roles
    
    @staticmethod
    def get_role_for_chat(creator_id: int, chat_id: int, role_name: str) -> Optional[Role]:
        """
        Get a specific role by name for a specific chat.
        
        Завжди читає актуальні дані з БД, не використовує кеш.
        Це гарантує, що зміни, внесені через налаштування ролей, застосовуються негайно.
        
        Args:
            creator_id: The creator/owner of the chat
            chat_id: The chat/group ID
            role_name: Name of the role to retrieve
            
        Returns:
            Role object if found, None otherwise
        """
        chat_id_int = int(chat_id) if not isinstance(chat_id, tuple) else int(chat_id[0])
        
        # Ensure default roles exist (in case we're looking for a default role)
        ChatRoleRegistry.ensure_default_roles_for_chat(creator_id, chat_id_int)
        
        # Завжди читаємо актуальну роль з БД (не використовуємо кеш)
        # Це гарантує, що зміни, внесені через налаштування ролей, застосовуються негайно
        return RoleManager.get_role(creator_id, chat_id_int, role_name)
    
    @staticmethod
    def create_custom_role_for_chat(
        creator_id: int,
        chat_id: int,
        role_name: str,
        description: str,
        abilities: List[Ability] = None
    ) -> Role:
        """
        Create a new custom role for a specific chat.
        Custom roles are isolated to the chat they were created in.
        
        Args:
            creator_id: The creator/owner of the chat
            chat_id: The chat/group ID
            role_name: Name of the new role
            description: Description of the role
            abilities: List of abilities for the role
            
        Returns:
            Created Role object
            
        Raises:
            ValueError: If role with this name already exists in this chat
        """
        chat_id_int = int(chat_id) if not isinstance(chat_id, tuple) else int(chat_id[0])
        
        # Check if role already exists in THIS chat
        existing = RoleManager.get_role(creator_id, chat_id_int, role_name)
        if existing:
            raise ValueError(f"Role '{role_name}' already exists in this chat")
        
        # Create new custom role
        new_role = Role(
            name=role_name,
            description=description,
            abilities=abilities or [],
            creator_id=creator_id,
            group_id=chat_id_int,
            is_default=False  # Custom roles are never default
        )
        
        # Save to database
        role_id = RoleManager.save_role(new_role)
        new_role.role_id = role_id
        
        return new_role
    
    @staticmethod
    def update_role_for_chat(creator_id: int, chat_id: int, role: Role) -> Role:
        """
        Update an existing role in a specific chat.
        Cannot update default roles - they are immutable.
        
        Args:
            creator_id: The creator/owner of the chat
            chat_id: The chat/group ID
            role: Role object with updated data
            
        Returns:
            Updated Role object
            
        Raises:
            ValueError: If trying to update a default role or role doesn't exist
        """
        chat_id_int = int(chat_id) if not isinstance(chat_id, tuple) else int(chat_id[0])
        
        # Verify role exists and belongs to this chat
        existing = RoleManager.get_role(creator_id, chat_id_int, role.name)
        if not existing:
            raise ValueError(f"Role '{role.name}' not found in this chat")
        
        # Prevent modification of default roles
        if existing.is_default:
            raise ValueError(f"Cannot modify default role '{role.name}'")
        
        # Ensure role belongs to correct chat
        if role.group_id != chat_id_int:
            raise ValueError("Role group_id does not match chat_id")
        
        # Update role
        role.creator_id = creator_id
        role.group_id = chat_id_int
        role.is_default = False  # Ensure it stays as custom
        
        role_id = RoleManager.save_role(role)
        role.role_id = role_id
        
        # Очищаємо кеш для цього чату, щоб зміни застосувалися негайно
        # Це гарантує, що наступні виклики get_role_for_chat та get_all_roles_for_chat
        # завантажать оновлені дані з БД
        ChatRoleRegistry.clear_chat_cache(chat_id_int)
        
        return role
    
    @staticmethod
    def delete_role_from_chat(creator_id: int, chat_id: int, role_name: str) -> bool:
        """
        Delete a custom role from a specific chat.
        Default roles cannot be deleted.
        
        Args:
            creator_id: The creator/owner of the chat
            chat_id: The chat/group ID
            role_name: Name of the role to delete
            
        Returns:
            True if deleted, False if not found
            
        Raises:
            ValueError: If trying to delete a default role
        """
        chat_id_int = int(chat_id) if not isinstance(chat_id, tuple) else int(chat_id[0])
        
        # Check if role exists and verify it's not a default role
        role = RoleManager.get_role(creator_id, chat_id_int, role_name)
        if not role:
            return False
        
        # Prevent deletion of default roles
        if role.is_default:
            raise ValueError(f"Cannot delete default role '{role_name}'")
        
        # Delete role (query already scoped by chat_id)
        return RoleManager.delete_role(creator_id, chat_id_int, role_name)
    
    @staticmethod
    def verify_chat_scope(creator_id: int, chat_id: int, role: Role) -> bool:
        """
        Verify that a role belongs to a specific chat.
        Used for security validation.
        
        Args:
            creator_id: The creator/owner of the chat
            chat_id: The chat/group ID
            role: Role object to verify
            
        Returns:
            True if role belongs to this chat, False otherwise
        """
        chat_id_int = int(chat_id) if not isinstance(chat_id, tuple) else int(chat_id[0])
        return role.creator_id == creator_id and role.group_id == chat_id_int
    
    @staticmethod
    def clear_chat_cache(chat_id: int = None):
        """
        Clear the initialization cache.
        Useful for testing or when forcing re-initialization.
        
        Args:
            chat_id: If provided, clear only this chat's cache entry. Otherwise clear all.
        """
        if chat_id is None:
            ChatRoleRegistry._initialized_chats.clear()
        else:
            chat_id_int = int(chat_id) if not isinstance(chat_id, tuple) else int(chat_id[0])
            # Remove all entries for this chat_id
            ChatRoleRegistry._initialized_chats = {
                (cid, gid) for (cid, gid) in ChatRoleRegistry._initialized_chats
                if gid != chat_id_int
            }
