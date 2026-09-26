"""
Role Manager - handles low-level CRUD operations for roles in database.
All operations MUST filter by group_id (chat_id) to ensure proper chat scoping.

For higher-level operations (auto-initialization, role registry), use ChatRoleRegistry.
"""

from typing import List, Optional, Dict, Any
from database.database import cursor, conn
from .role_system import Role, Ability, create_default_roles
import json


def _db_fetchone(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchone()


def _db_fetchall(query: str, params: tuple = ()):
    cursor.execute(query, params)
    return cursor.fetchall()


def _db_execute(query: str, params: tuple = ()) -> None:
    cursor.execute(query, params)


class RoleManager:
    """
    Low-level database manager for roles.
    
    IMPORTANT: All queries MUST include group_id (chat_id) filter to ensure
    proper chat isolation. This class does NOT enforce scoping - use ChatRoleRegistry
    for high-level operations that guarantee chat isolation.
    """
    
    @staticmethod
    def save_role(role: Role) -> int:
        """
        Save or update a role in the database.
        
        CRITICAL: This method assumes role.group_id is already set correctly.
        Always use ChatRoleRegistry for high-level operations to ensure proper scoping.
        
        Returns:
            role_id: The database ID of the saved role
        """
        # Ensure group_id is int, not tuple
        group_id_int = int(role.group_id) if not isinstance(role.group_id, tuple) else int(role.group_id[0])
        role.group_id = group_id_int
        
        role_data = role.to_dict()
        role_json = json.dumps(role_data, ensure_ascii=False)
        
        # Check if role already exists (scoped by creator_id AND group_id)
        existing = _db_fetchone("""
            SELECT role_id FROM custom_roles 
            WHERE creator_id = %s AND group_id = %s AND role_name = %s
        """, (role.creator_id, role.group_id, role.name))
        
        if existing:
            # Update existing role - ВАЖЛИВО: оновлюємо тільки якщо creator_id та group_id співпадають
            role_id = existing[0]
            # Додаткова перевірка: переконаємося, що оновлюємо правильну роль
            _db_execute("""
                UPDATE custom_roles 
                SET role_description = %s, role_data = %s
                WHERE role_id = %s AND creator_id = %s AND group_id = %s AND role_name = %s
            """, (role.description, role_json, role_id, role.creator_id, role.group_id, role.name))
            rows_updated = cursor.rowcount
            conn.commit()
            if rows_updated == 0:
                # Якщо нічого не оновилося, можливо роль належить іншій групі - не оновлюємо
                print(f"⚠️ RoleManager.save_role: Не вдалося оновити роль {role.name} (role_id={role_id}, creator_id={role.creator_id}, group_id={role.group_id})")
            return role_id
        else:
            # Insert new role
            role_row = _db_fetchone("""
                INSERT INTO custom_roles (creator_id, group_id, role_name, role_description, role_data, is_default)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING role_id
            """, (role.creator_id, role.group_id, role.name, role.description, role_json, role.is_default))
            role_id = role_row[0]
            conn.commit()
            return role_id
    
    @staticmethod
    def get_role(creator_id: int, group_id: int, role_name: str) -> Optional[Role]:
        """
        Get a role by name for a specific creator and group (chat).
        
        CRITICAL: group_id MUST be the chat_id to ensure proper isolation.
        This method filters by both creator_id AND group_id to prevent cross-chat access.
        
        Args:
            creator_id: The creator/owner ID
            group_id: The chat/group ID (MUST be unique per chat)
            role_name: Name of the role
            
        Returns:
            Role object if found, None otherwise
        """
        # Normalize group_id
        group_id_int = int(group_id) if not isinstance(group_id, tuple) else int(group_id[0])
        
        result = _db_fetchone("""
            SELECT role_id, role_name, role_description, role_data, is_default
            FROM custom_roles
            WHERE creator_id = %s AND group_id = %s AND role_name = %s
        """, (creator_id, group_id_int, role_name))
        if result:
            role_id, name, description, role_data_raw, is_default = result
            # PostgreSQL JSONB can return as dict or string, handle both
            if isinstance(role_data_raw, dict):
                role_data = role_data_raw
            elif isinstance(role_data_raw, str):
                role_data = json.loads(role_data_raw)
            else:
                return None  # Invalid data
            
            role = Role.from_dict(role_data)
            role.role_id = role_id
            role.is_default = is_default
            return role
        return None
    
    @staticmethod
    def get_all_roles(creator_id: int, group_id: int) -> List[Role]:
        """
        Get all roles for a specific creator and group (chat).
        
        CRITICAL: group_id MUST be the chat_id to ensure proper isolation.
        Returns ONLY roles from this specific chat.
        
        Args:
            creator_id: The creator/owner ID
            group_id: The chat/group ID (MUST be unique per chat)
            
        Returns:
            List of Role objects scoped to this chat only
        """
        # Normalize group_id
        group_id_int = int(group_id) if not isinstance(group_id, tuple) else int(group_id[0])
        
        rows = _db_fetchall("""
            SELECT role_id, role_name, role_description, role_data, is_default
            FROM custom_roles
            WHERE creator_id = %s AND group_id = %s
            ORDER BY is_default DESC, role_name ASC
        """, (creator_id, group_id_int))
        
        roles = []
        for row in rows:
            role_id, name, description, role_data_raw, is_default = row
            # PostgreSQL JSONB can return as dict or string, handle both
            if isinstance(role_data_raw, dict):
                role_data = role_data_raw
            elif isinstance(role_data_raw, str):
                role_data = json.loads(role_data_raw)
            else:
                continue  # Skip invalid data
            
            role = Role.from_dict(role_data)
            role.role_id = role_id
            role.is_default = is_default
            roles.append(role)
        
        return roles
    
    @staticmethod
    def delete_role(creator_id: int, group_id: int, role_name: str) -> bool:
        """
        Delete a role from database.
        
        CRITICAL: This method does NOT protect default roles - use ChatRoleRegistry
        for high-level operations that enforce business rules.
        
        Args:
            creator_id: The creator/owner ID
            group_id: The chat/group ID
            role_name: Name of the role to delete
            
        Returns:
            True if deleted, False if not found
        """
        # Normalize group_id
        group_id_int = int(group_id) if not isinstance(group_id, tuple) else int(group_id[0])
        
        deleted = _db_fetchone("""
            DELETE FROM custom_roles
            WHERE creator_id = %s AND group_id = %s AND role_name = %s
            RETURNING role_id
        """, (creator_id, group_id_int, role_name))
        if deleted:
            conn.commit()
            return True
        return False

    @staticmethod
    def delete_all_roles_for_chat(creator_id: int, group_id: int) -> None:
        """
        Видаляє всі ролі для чату (для відновлення з бекапу).
        CRITICAL: використовувати тільки в контексті повного відновлення з бекапу.
        """
        group_id_int = int(group_id) if not isinstance(group_id, tuple) else int(group_id[0])
        _db_execute(
            "DELETE FROM custom_roles WHERE creator_id = %s AND group_id = %s",
            (creator_id, group_id_int),
        )
        conn.commit()
    
    @staticmethod
    def get_role_by_display_name(creator_id: int, group_id: int, display_name: str) -> Optional[Role]:
        """
        Get role by display name (checks both custom_roles and admin_panel for backward compatibility)
        First checks custom_roles, then falls back to admin_panel
        """
        # Check custom_roles first
        role = RoleManager.get_role(creator_id, group_id, display_name)
        if role:
            return role
        
        # Fall back to admin_panel for backward compatibility
        result = _db_fetchone("""
            SELECT doctor, doctor_text, all_capone, all_capone_text, civilian, civilian_text
            FROM admin_panel
            WHERE creator_id = %s AND group_id = %s
        """, (creator_id, group_id))
        if result:
            doctor_name, doctor_text, mafia_name, mafia_text, civilian_name, civilian_text = result
            
            # Match display name to default role names
            default_roles = create_default_roles()
            
            if display_name == mafia_name or display_name == "Аль Капоне":
                default_role = default_roles["Аль Капоне"]
                default_role.name = mafia_name
                default_role.description = mafia_text or default_role.description
                default_role.creator_id = creator_id
                default_role.group_id = group_id
                return default_role
            
            elif display_name == doctor_name or display_name == "Лікар":
                default_role = default_roles["Лікар"]
                default_role.name = doctor_name
                default_role.description = doctor_text or default_role.description
                default_role.creator_id = creator_id
                default_role.group_id = group_id
                return default_role
            
            elif display_name == civilian_name or display_name == "Мирний житель":
                default_role = default_roles["Мирний житель"]
                default_role.name = civilian_name
                default_role.description = civilian_text or default_role.description
                default_role.creator_id = creator_id
                default_role.group_id = group_id
                return default_role
        
        return None
    
    @staticmethod
    def ensure_default_roles_exist(creator_id: int, group_id: int):
        """Ensure default roles exist for a group (migrates from admin_panel if needed)"""
        # Check if roles already exist
        count_row = _db_fetchone("""
            SELECT COUNT(*) FROM custom_roles
            WHERE creator_id = %s AND group_id = %s
        """, (creator_id, group_id))
        count = count_row[0]
        if count > 0:
            return  # Roles already exist
        
        # Get from admin_panel and migrate
        result = _db_fetchone("""
            SELECT doctor, doctor_text, all_capone, all_capone_text, civilian, civilian_text
            FROM admin_panel
            WHERE creator_id = %s AND group_id = %s
        """, (creator_id, group_id))
        default_roles = create_default_roles()
        
        if result:
            doctor_name, doctor_text, mafia_name, mafia_text, civilian_name, civilian_text = result
            
            # Migrate mafia role
            mafia_role = default_roles["Аль Капоне"]
            mafia_role.name = mafia_name
            mafia_role.description = mafia_text or mafia_role.description
            mafia_role.creator_id = creator_id
            mafia_role.group_id = group_id
            mafia_role.is_default = True
            RoleManager.save_role(mafia_role)
            
            # Migrate doctor role
            doctor_role = default_roles["Лікар"]
            doctor_role.name = doctor_name
            doctor_role.description = doctor_text or doctor_role.description
            doctor_role.creator_id = creator_id
            doctor_role.group_id = group_id
            doctor_role.is_default = True
            RoleManager.save_role(doctor_role)
            
            # Migrate civilian role
            civilian_role = default_roles["Мирний житель"]
            civilian_role.name = civilian_name
            civilian_role.description = civilian_text or civilian_role.description
            civilian_role.creator_id = creator_id
            civilian_role.group_id = group_id
            civilian_role.is_default = True
            RoleManager.save_role(civilian_role)
