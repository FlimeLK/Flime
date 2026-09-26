"""
Database module for Mafia Bot
Handles PostgreSQL connection and table initialization
"""

import os
import asyncio
import threading
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool
import logging
import json
from datetime import datetime

# #region agent log
def _log_debug(session_id, run_id, hypothesis_id, location, message, data):
    try:
        # Portable path: .cursor/debug.log next to project root (works on Windows and Linux)
        _base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_path = os.path.join(_base, ".cursor", "debug.log")
        log_dir = os.path.dirname(log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        with open(log_path, 'a', encoding='utf-8') as f:
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
    except Exception as log_err:
        # Fallback: try to print to stderr if file logging fails
        try:
            import sys
            print(f"LOG_ERROR: {log_err}", file=sys.stderr)
        except: pass
# #endregion

# Database configuration (env vars override for hosting)
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("DB_NAME", "mafia"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
}

# #region agent log
_log_debug('debug-session', 'run1', 'A', 'database.py:19', 'DB_CONFIG loaded', {
    'host': DB_CONFIG['host'],
    'port': DB_CONFIG['port'],
    'database': DB_CONFIG['database'],
    'user': DB_CONFIG['user'],
    'password': '***' if DB_CONFIG['password'] else None,
    'env_DB_HOST': os.getenv('DB_HOST'),
    'env_DB_PORT': os.getenv('DB_PORT'),
    'env_DB_NAME': os.getenv('DB_NAME'),
    'env_DB_USER': os.getenv('DB_USER'),
    'env_DB_PASSWORD': '***' if os.getenv('DB_PASSWORD') else None
})
# #endregion

# Connection pool
connection_pool = None
conn = None
cursor = None

logger = logging.getLogger(__name__)
_db_call_lock = threading.RLock()


def run_blocking_db_call(func, *args, **kwargs):
    """Run one DB call under lock to avoid shared-cursor races."""
    with _db_call_lock:
        ensure_db_connection_usable()
        return func(*args, **kwargs)


async def run_db_call_async(func, *args, **kwargs):
    """Async adapter over legacy sync DB helpers."""
    return await asyncio.to_thread(run_blocking_db_call, func, *args, **kwargs)


def ensure_db_connection_usable() -> None:
    """
    Після помилки SQL PostgreSQL лишає з'єднання в стані aborted: усі наступні команди
    дають InFailedSqlTransaction, доки не виконати ROLLBACK. Викликати перед блоком
    запитів, якщо попередня операція на цьому ж conn могла завершитись помилкою.
    """
    global conn, cursor, connection_pool
    # 0) Самовідновлення мертвого з'єднання/курсора (обрив мережі, idle-таймаут, recycling пулу).
    #    Без цього після «cursor already closed» весь бот ламався до перезапуску.
    try:
        conn_dead = (conn is None) or (getattr(conn, "closed", 1) != 0)
        cur_dead = (cursor is None) or bool(getattr(cursor, "closed", True))
    except Exception:
        conn_dead = cur_dead = True
    if conn_dead or cur_dead:
        try:
            if connection_pool is None:
                initialize_db()
            else:
                if conn is not None:
                    try:
                        connection_pool.putconn(conn, close=True)
                    except Exception:
                        pass
                conn = connection_pool.getconn()
                # autocommit: read-функції (is_user_blocked тощо) роблять SELECT без commit;
                # без autocommit це лишало з'єднання в "idle in transaction" і вичерпувало пул.
                try:
                    conn.autocommit = True
                except Exception:
                    pass
                cursor = conn.cursor()
        except Exception:
            try:
                initialize_db()
            except Exception:
                pass
        return

    if conn is None:
        return
    try:
        from psycopg2 import extensions as _pg_ext

        if conn.get_transaction_status() == _pg_ext.TRANSACTION_STATUS_INERROR:
            conn.rollback()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def initialize_db():
    """Initialize database connection and create tables if they don't exist"""
    global conn, cursor, connection_pool
    
    # #region agent log
    _log_debug('debug-session', 'run1', 'A', 'database.py:32', 'initialize_db() called', {
        'DB_CONFIG_host': DB_CONFIG['host'],
        'DB_CONFIG_port': DB_CONFIG['port'],
        'DB_CONFIG_port_type': type(DB_CONFIG['port']).__name__,
        'DB_CONFIG_database': DB_CONFIG['database'],
        'DB_CONFIG_user': DB_CONFIG['user']
    })
    # #endregion
    
    try:
        # #region agent log
        port_value = int(DB_CONFIG['port'])
        _log_debug('debug-session', 'run1', 'D', 'database.py:40', 'Before connection pool creation', {
            'host': DB_CONFIG['host'],
            'port': port_value,
            'port_type': type(port_value).__name__,
            'database': DB_CONFIG['database'],
            'user': DB_CONFIG['user']
        })
        # #endregion
        
        # Create connection pool
        connection_pool = psycopg2.pool.SimpleConnectionPool(
            1, 20,
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port'],
            database=DB_CONFIG['database'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password'],
            # Захист від «вічного» зависання бота на мертвому/повільному з'єднанні з БД:
            connect_timeout=10,                       # не висіти на конекті
            keepalives=1, keepalives_idle=30,         # TCP keepalive: виявляти обрив сокета
            keepalives_interval=10, keepalives_count=3,
            # statement_timeout: будь-який запит > 20с → помилка (а не зависання)
            # idle_in_transaction_session_timeout: вбити «idle in transaction» через 60с,
            #   щоб «забута» транзакція не тримала локи й не блокувала бота назавжди.
            options='-c statement_timeout=20000 -c idle_in_transaction_session_timeout=60000',
        )
        
        # #region agent log
        _log_debug('debug-session', 'run1', 'A', 'database.py:52', 'Connection pool created', {
            'pool_exists': connection_pool is not None
        })
        # #endregion
        
        if connection_pool:
            logger.info("Database connection pool created successfully")
            # Get connection from pool
            conn = connection_pool.getconn()
            if conn:
                # autocommit: щоб read-функції не лишали "idle in transaction" і не вичерпували пул.
                try:
                    conn.autocommit = True
                except Exception:
                    pass
                cursor = conn.cursor()
                logger.info("Database connection established")
            else:
                raise Exception("Failed to get connection from pool")
        else:
            raise Exception("Failed to create connection pool")
        
        # Create tables
        create_tables()
        
    except psycopg2.OperationalError as e:
        # #region agent log
        _log_debug('debug-session', 'post-fix', 'A', 'database.py:65', 'Connection error caught', {
            'error_type': type(e).__name__,
            'error_message': str(e),
            'error_args': str(e.args) if hasattr(e, 'args') else None,
            'connection_params': {
                'host': DB_CONFIG['host'],
                'port': DB_CONFIG['port'],
                'database': DB_CONFIG['database'],
                'user': DB_CONFIG['user']
            }
        })
        # #endregion
        error_msg = str(e)
        if "Connection refused" in error_msg or "could not connect" in error_msg.lower():
            logger.error("=" * 70)
            logger.error("CRITICAL: PostgreSQL server is not running!")
            logger.error("=" * 70)
            logger.error(f"Connection failed to: {DB_CONFIG['host']}:{DB_CONFIG['port']}")
            logger.error("")
            logger.error("To fix this issue:")
            logger.error("1. Start PostgreSQL server on your system")
            logger.error("   - Windows: Check Services or run 'net start postgresql-x64-XX'")
            logger.error("   - Linux/Mac: Run 'sudo systemctl start postgresql' or 'brew services start postgresql'")
            logger.error("")
            logger.error("2. Verify PostgreSQL is running:")
            logger.error(f"   - Check if port {DB_CONFIG['port']} is listening")
            logger.error("   - Try: 'psql -U postgres -h localhost' to test connection")
            logger.error("")
            logger.error("3. If using different host/port, set environment variables:")
            logger.error("   - DB_HOST=your_host")
            logger.error("   - DB_PORT=your_port")
            logger.error("   - DB_NAME=your_database")
            logger.error("   - DB_USER=your_user")
            logger.error("   - DB_PASSWORD=your_password")
            logger.error("=" * 70)
        else:
            logger.error(f"Database connection error: {e}")
        raise
    except Exception as e:
        # #region agent log
        _log_debug('debug-session', 'post-fix', 'A', 'database.py:95', 'Non-OperationalError caught', {
            'error_type': type(e).__name__,
            'error_message': str(e)
        })
        # #endregion
        logger.error(f"Error initializing database: {e}")
        raise


def create_tables():
    """Create all required tables if they don't exist"""
    global conn, cursor
    
    try:
        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY,
                tg_name VARCHAR(255),
                link VARCHAR(255),
                role VARCHAR(255),
                killed INTEGER DEFAULT 0,
                cured INTEGER DEFAULT 0,
                votes INTEGER DEFAULT 0,
                balance INTEGER DEFAULT 0
            )
        """)
        
        # Додаємо поле balance, якщо його немає (для існуючих таблиць)
        cursor.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'users' AND column_name = 'balance'
                ) THEN
                    ALTER TABLE users ADD COLUMN balance INTEGER DEFAULT 0;
                END IF;
            END $$;
        """)
        # Донат-валюта (золоті монети) - для преміум/бафів, окремо від карбованців
        cursor.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'users' AND column_name = 'donate_coins'
                ) THEN
                    ALTER TABLE users ADD COLUMN donate_coins INTEGER DEFAULT 0;
                END IF;
            END $$;
        """)
        # Подарунковий бонус для перших 100: чи вже отримав
        cursor.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'users' AND column_name = 'received_starter_gift'
                ) THEN
                    ALTER TABLE users ADD COLUMN received_starter_gift BOOLEAN DEFAULT FALSE;
                END IF;
            END $$;
        """)
        # Лимони (квіти-подарунки): скільки має користувач
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = 'users' AND column_name = 'marigolds'
                ) THEN
                    ALTER TABLE users ADD COLUMN marigolds INTEGER NOT NULL DEFAULT 0;
                END IF;
            END $$
        """)
        # /test_vip — безкоштовний тест VIP+ на 2 дні, один раз на акаунт
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = 'users' AND column_name = 'test_vip_used'
                ) THEN
                    ALTER TABLE users ADD COLUMN test_vip_used BOOLEAN NOT NULL DEFAULT FALSE;
                END IF;
            END $$
        """)
        # Тестовий ігровий VIP окремо від subscriptions (щоб не затирати підписку «для чату»)
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = 'users' AND column_name = 'game_vip_test_until'
                ) THEN
                    ALTER TABLE users ADD COLUMN game_vip_test_until TIMESTAMP NULL;
                END IF;
            END $$
        """)

        # Фонд підписок: золоті монети, переведені гравцями на підтримку підписки
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscription_fund (
                id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                gold_balance BIGINT NOT NULL DEFAULT 0
            )
        """)
        cursor.execute("""
            INSERT INTO subscription_fund (id, gold_balance) VALUES (1, 0)
            ON CONFLICT (id) DO NOTHING
        """)
        
        # Admin panel table (for backward compatibility and group management)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admin_panel (
                creator_id BIGINT NOT NULL,
                group_id BIGINT NOT NULL,
                doctor VARCHAR(255),
                doctor_text TEXT,
                all_capone VARCHAR(255),
                all_capone_text TEXT,
                civilian VARCHAR(255),
                civilian_text TEXT,
                registration_time INTEGER DEFAULT 90,
                is_blocked BOOLEAN DEFAULT FALSE,
                afk_auto_choice_enabled BOOLEAN DEFAULT FALSE,
                PRIMARY KEY (creator_id, group_id)
            )
        """)
        
        # Додаємо поле registration_time, якщо його немає (для існуючих таблиць)
        cursor.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'admin_panel' AND column_name = 'registration_time'
                ) THEN
                    ALTER TABLE admin_panel ADD COLUMN registration_time INTEGER DEFAULT 90;
                END IF;
            END $$;
        """)
        
        # Додаємо поле is_blocked, якщо його немає (для існуючих таблиць)
        cursor.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'admin_panel' AND column_name = 'is_blocked'
                ) THEN
                    ALTER TABLE admin_panel ADD COLUMN is_blocked BOOLEAN DEFAULT FALSE;
                END IF;
            END $$;
        """)
        
        # Додаємо поле voting_prep_time, якщо його немає (для існуючих таблиць)
        cursor.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'admin_panel' AND column_name = 'voting_prep_time'
                ) THEN
                    ALTER TABLE admin_panel ADD COLUMN voting_prep_time INTEGER DEFAULT 30;
                END IF;
            END $$;
        """)
        
        # Додаємо поле hanging_vote_time, якщо його немає (для існуючих таблиць)
        cursor.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'admin_panel' AND column_name = 'hanging_vote_time'
                ) THEN
                    ALTER TABLE admin_panel ADD COLUMN hanging_vote_time INTEGER DEFAULT 30;
                END IF;
            END $$;
        """)
        
        # Додаємо тематичні налаштування, якщо їх немає (відображення ролей / таємне голосування / нічні цілі / дружній вогонь)
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'admin_panel' AND column_name = 'hide_dead_roles'
                ) THEN
                    ALTER TABLE admin_panel ADD COLUMN hide_dead_roles BOOLEAN DEFAULT FALSE;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'admin_panel' AND column_name = 'hide_killer_roles'
                ) THEN
                    ALTER TABLE admin_panel ADD COLUMN hide_killer_roles BOOLEAN DEFAULT FALSE;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'admin_panel' AND column_name = 'secret_voting'
                ) THEN
                    ALTER TABLE admin_panel ADD COLUMN secret_voting BOOLEAN DEFAULT FALSE;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'admin_panel' AND column_name = 'show_night_targets'
                ) THEN
                    ALTER TABLE admin_panel ADD COLUMN show_night_targets BOOLEAN DEFAULT FALSE;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'admin_panel' AND column_name = 'allow_friendly_fire'
                ) THEN
                    ALTER TABLE admin_panel ADD COLUMN allow_friendly_fire BOOLEAN DEFAULT FALSE;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'admin_panel' AND column_name = 'silence_role_block_enabled'
                ) THEN
                    ALTER TABLE admin_panel ADD COLUMN silence_role_block_enabled BOOLEAN DEFAULT TRUE;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'admin_panel' AND column_name = 'silence_dead_players_enabled'
                ) THEN
                    ALTER TABLE admin_panel ADD COLUMN silence_dead_players_enabled BOOLEAN DEFAULT TRUE;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'admin_panel' AND column_name = 'silence_non_players_enabled'
                ) THEN
                    ALTER TABLE admin_panel ADD COLUMN silence_non_players_enabled BOOLEAN DEFAULT TRUE;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'admin_panel' AND column_name = 'allow_skip_night_action'
                ) THEN
                    ALTER TABLE admin_panel ADD COLUMN allow_skip_night_action BOOLEAN DEFAULT FALSE;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'admin_panel' AND column_name = 'afk_auto_choice_enabled'
                ) THEN
                    ALTER TABLE admin_panel ADD COLUMN afk_auto_choice_enabled BOOLEAN DEFAULT FALSE;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'admin_panel' AND column_name = 'duels_enabled'
                ) THEN
                    ALTER TABLE admin_panel ADD COLUMN duels_enabled BOOLEAN DEFAULT FALSE;
                END IF;
            END $$;
        """)
        
        # Налаштування бафів по групі: чи бафи ввімкнені в грі, які вимкнені, чи тільки унікальні (з порталу)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS group_buff_settings (
                group_id BIGINT PRIMARY KEY,
                buffs_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                disabled_buff_ids JSONB NOT NULL DEFAULT '[]',
                unique_buffs_only BOOLEAN NOT NULL DEFAULT FALSE
            )
        """)
        try:
            cursor.execute("""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = current_schema() AND table_name = 'group_buff_settings' AND column_name = 'unique_buffs_only'
                    ) THEN
                        ALTER TABLE group_buff_settings ADD COLUMN unique_buffs_only BOOLEAN NOT NULL DEFAULT FALSE;
                    END IF;
                END $$
            """)
        except Exception:
            pass

        # Портал: доступ (куплений прохід) та прогрес/завершення сюжету
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_portal_access (
                user_id BIGINT PRIMARY KEY,
                unlocked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_portal_progress (
                user_id BIGINT PRIMARY KEY,
                completed_at TIMESTAMP,
                reward_granted BOOLEAN NOT NULL DEFAULT FALSE
            )
        """)

        # Custom roles table (for new role system)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS custom_roles (
                role_id SERIAL PRIMARY KEY,
                creator_id BIGINT NOT NULL,
                group_id BIGINT NOT NULL,
                role_name VARCHAR(255) NOT NULL,
                role_description TEXT,
                role_data JSONB,
                is_default BOOLEAN DEFAULT FALSE,
                UNIQUE(creator_id, group_id, role_name)
            )
        """)

        # Role backups (max 5 per group) for /construct_event
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS role_backups (
                id SERIAL PRIMARY KEY,
                creator_id BIGINT NOT NULL,
                group_id BIGINT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                snapshot JSONB NOT NULL
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_role_backups_creator_group
            ON role_backups(creator_id, group_id)
        """)
        try:
            cursor.execute("""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = current_schema() AND table_name = 'role_backups' AND column_name = 'name'
                    ) THEN
                        ALTER TABLE role_backups ADD COLUMN name VARCHAR(255);
                    END IF;
                END $$
            """)
        except Exception:
            pass

        # Subscriptions table (is_purchased: True = куплена користувачем/золотом, False = подарунок адміна/промо/адвент)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id BIGINT PRIMARY KEY,
                subscription_type VARCHAR(255) NOT NULL,
                subscription_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                subscription_end TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                auto_renew BOOLEAN DEFAULT FALSE,
                is_purchased BOOLEAN DEFAULT TRUE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            cursor.execute("""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = current_schema() AND table_name = 'subscriptions' AND column_name = 'is_purchased'
                    ) THEN
                        ALTER TABLE subscriptions ADD COLUMN is_purchased BOOLEAN DEFAULT TRUE;
                    END IF;
                END $$
            """)
        except Exception:
            pass
        
        # Shop purchases table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shop_purchases (
                purchase_id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                item_name VARCHAR(255) NOT NULL,
                item_type VARCHAR(255) NOT NULL,
                amount_paid INTEGER NOT NULL,
                currency VARCHAR(32) NOT NULL,
                telegram_payment_charge_id VARCHAR(255) UNIQUE,
                purchase_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                refunded BOOLEAN DEFAULT FALSE,
                refund_date TIMESTAMP
            )
        """)
        # Міграція: currency була VARCHAR(10) — коди на кшталт TEST_VIP_PLUS не вміщались
        try:
            cursor.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = 'shop_purchases'
                          AND column_name = 'currency'
                          AND character_maximum_length IS NOT NULL
                          AND character_maximum_length < 32
                    ) THEN
                        ALTER TABLE shop_purchases
                        ALTER COLUMN currency TYPE VARCHAR(32);
                    END IF;
                END $$
            """)
        except Exception:
            pass

        # Buff shop: owned buffs (internal currency)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_buffs (
                user_id BIGINT NOT NULL,
                buff_id VARCHAR(64) NOT NULL,
                buff_name VARCHAR(255) NOT NULL,
                purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT FALSE,
                metadata JSONB,
                quantity INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (user_id, buff_id)
            )
        """)
        # Easter egg event (/egg)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS egg_event_state (
                user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                has_egg BOOLEAN NOT NULL DEFAULT FALSE,
                stage INTEGER NOT NULL DEFAULT 1,
                progress INTEGER NOT NULL DEFAULT 0,
                growth INTEGER NOT NULL DEFAULT 0,
                stability INTEGER NOT NULL DEFAULT 0,
                quality INTEGER NOT NULL DEFAULT 0,
                risk INTEGER NOT NULL DEFAULT 0,
                lamp_until TIMESTAMP,
                incubator_cooldown_until TIMESTAMP,
                lamp_uses INTEGER NOT NULL DEFAULT 0,
                incubator_uses INTEGER NOT NULL DEFAULT 0,
                feed_uses INTEGER NOT NULL DEFAULT 0,
                clean_uses INTEGER NOT NULL DEFAULT 0,
                overcare_percent INTEGER NOT NULL DEFAULT 0,
                feed_date DATE,
                feed_count INTEGER NOT NULL DEFAULT 0,
                clean_date DATE,
                clean_count INTEGER NOT NULL DEFAULT 0,
                opened BOOLEAN NOT NULL DEFAULT FALSE,
                result_type VARCHAR(32),
                opened_at TIMESTAMP,
                last_action_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Міграція: лічильники використання лампи/інкубатора (для ефектів "перегрів"/"занадто прискорюєш")
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = 'egg_event_state' AND column_name = 'lamp_uses'
                ) THEN
                    ALTER TABLE egg_event_state ADD COLUMN lamp_uses INTEGER NOT NULL DEFAULT 0;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = 'egg_event_state' AND column_name = 'incubator_uses'
                ) THEN
                    ALTER TABLE egg_event_state ADD COLUMN incubator_uses INTEGER NOT NULL DEFAULT 0;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = 'egg_event_state' AND column_name = 'feed_uses'
                ) THEN
                    ALTER TABLE egg_event_state ADD COLUMN feed_uses INTEGER NOT NULL DEFAULT 0;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = 'egg_event_state' AND column_name = 'clean_uses'
                ) THEN
                    ALTER TABLE egg_event_state ADD COLUMN clean_uses INTEGER NOT NULL DEFAULT 0;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = 'egg_event_state' AND column_name = 'overcare_percent'
                ) THEN
                    ALTER TABLE egg_event_state ADD COLUMN overcare_percent INTEGER NOT NULL DEFAULT 0;
                END IF;
            END $$
        """)
        # Міграція: додати quantity якщо таблиця вже існувала без нього
        try:
            cursor.execute("""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = current_schema() AND table_name = 'user_buffs' AND column_name = 'quantity'
                    ) THEN
                        ALTER TABLE user_buffs ADD COLUMN quantity INTEGER NOT NULL DEFAULT 1;
                    END IF;
                END $$
            """)
        except Exception:
            pass
        # Міграція: додати infinite (безкінечні бафи від засновника)
        try:
            cursor.execute("""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = current_schema() AND table_name = 'user_buffs' AND column_name = 'infinite'
                    ) THEN
                        ALTER TABLE user_buffs ADD COLUMN infinite BOOLEAN NOT NULL DEFAULT FALSE;
                    END IF;
                END $$
            """)
        except Exception:
            pass
        # Міграція: унікальні бафи (з порталу) - позначка в user_buffs
        try:
            cursor.execute("""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = current_schema() AND table_name = 'user_buffs' AND column_name = 'is_unique'
                    ) THEN
                        ALTER TABLE user_buffs ADD COLUMN is_unique BOOLEAN NOT NULL DEFAULT FALSE;
                    END IF;
                END $$
            """)
        except Exception:
            pass

        # Buff shop: purchase history (audit log)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS buff_purchases (
                purchase_id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                buff_id VARCHAR(64) NOT NULL,
                buff_name VARCHAR(255) NOT NULL,
                amount_paid INTEGER NOT NULL,
                currency VARCHAR(16) NOT NULL,
                purchase_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Support tickets (тех. підтримка через ПП)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                username VARCHAR(255),
                category VARCHAR(128) NOT NULL,
                message_text TEXT NOT NULL,
                status VARCHAR(32) DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_support_tickets_status ON support_tickets(status);
            CREATE INDEX IF NOT EXISTS idx_support_tickets_user ON support_tickets(user_id);
        """)

        # Founders table (for admin access)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS founders (
                founder_id BIGINT PRIMARY KEY,
                added_by BIGINT NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                notes TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Лінія підтримки (не засновники): тікети в ПП, панель /support_panel
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS support_staff (
                user_id BIGINT PRIMARY KEY,
                added_by BIGINT NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Промокоди (створюються власниками через /capone_admin)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS promocodes (
                id SERIAL PRIMARY KEY,
                code VARCHAR(255) NOT NULL UNIQUE,
                name VARCHAR(255),
                max_activations INTEGER NOT NULL DEFAULT 1,
                current_activations INTEGER NOT NULL DEFAULT 0,
                reward_balance INTEGER NOT NULL DEFAULT 0,
                reward_gold INTEGER NOT NULL DEFAULT 0,
                reward_buffs JSONB DEFAULT '[]',
                reward_subscription_item_id VARCHAR(64),
                reward_subscription_days INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by BIGINT,
                is_active BOOLEAN DEFAULT TRUE
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS promocode_activations (
                id SERIAL PRIMARY KEY,
                promocode_id INTEGER NOT NULL REFERENCES promocodes(id),
                user_id BIGINT NOT NULL,
                activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(promocode_id, user_id)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_promocodes_code ON promocodes(code);
            CREATE INDEX IF NOT EXISTS idx_promocode_activations_promocode ON promocode_activations(promocode_id);
            CREATE INDEX IF NOT EXISTS idx_promocode_activations_user ON promocode_activations(user_id);
        """)

        # Весняний адвент-календар: дні 1-31 (31 день)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS advent_opens (
                user_id BIGINT NOT NULL,
                event_key VARCHAR(32) NOT NULL,
                day_number SMALLINT NOT NULL CHECK (day_number >= 1 AND day_number <= 31),
                opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, event_key, day_number)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_advent_opens_user_event ON advent_opens(user_id, event_key);
        """)
        # Міграція: діапазон днів 1-31 (якщо таблиця вже існувала з іншим CHECK)
        try:
            cursor.execute("ALTER TABLE advent_opens DROP CONSTRAINT IF EXISTS advent_opens_day_number_check")
            cursor.execute("ALTER TABLE advent_opens ADD CONSTRAINT advent_opens_day_number_check CHECK (day_number >= 1 AND day_number <= 31)")
        except Exception:
            pass
        # Вибір бафа в адвенті (день з buff_choice): зберігаємо, щоб не дати вибрати двічі
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS advent_buff_choice (
                user_id BIGINT NOT NULL,
                event_key VARCHAR(32) NOT NULL,
                day_number SMALLINT NOT NULL,
                buff_id VARCHAR(64) NOT NULL,
                chosen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, event_key, day_number)
            )
        """)

        # Адмін-оверрайд для адвенту: дозволити конкретному користувачу відкрити конкретний день (навіть якщо пропущено)
        # used_at: коли оверрайд був використаний (день відкритий)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS advent_unlocks (
                user_id BIGINT NOT NULL,
                event_key VARCHAR(32) NOT NULL,
                day_number SMALLINT NOT NULL CHECK (day_number >= 1 AND day_number <= 31),
                granted_by BIGINT NOT NULL,
                granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                used_at TIMESTAMP,
                PRIMARY KEY (user_id, event_key, day_number)
            )
        """)

        # Story cards (сюжетні карточки, відкриваються через досягнення)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS story_cards (
                id SERIAL PRIMARY KEY,
                card_order INTEGER NOT NULL UNIQUE,
                title_uk VARCHAR(255) NOT NULL,
                text_uk TEXT NOT NULL
            )
        """)

        # Achievements (досягнення: умова, ціль, нагорода - карточка)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                id SERIAL PRIMARY KEY,
                achievement_key VARCHAR(64) NOT NULL UNIQUE,
                name_uk VARCHAR(255) NOT NULL,
                condition_type VARCHAR(64) NOT NULL,
                condition_role VARCHAR(255),
                target_value INTEGER NOT NULL,
                story_card_id INTEGER REFERENCES story_cards(id)
            )
        """)

        # User achievement progress (лічильник прогресу, completed_at якщо виконано)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_achievement_progress (
                user_id BIGINT NOT NULL,
                achievement_key VARCHAR(64) NOT NULL,
                current_value INTEGER DEFAULT 0,
                completed_at TIMESTAMP,
                PRIMARY KEY (user_id, achievement_key)
            )
        """)

        # User unlocked story cards
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_story_cards (
                user_id BIGINT NOT NULL,
                card_id INTEGER NOT NULL REFERENCES story_cards(id),
                unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, card_id)
            )
        """)

        # User story choice (one choice per user per card; e.g. Al Capone - 1 of 3 options)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_story_choices (
                user_id BIGINT NOT NULL,
                card_id INTEGER NOT NULL REFERENCES story_cards(id),
                choice_index INTEGER NOT NULL,
                chosen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, card_id)
            )
        """)

        # Відкладена доставка сюжетки: після досягнення - надсилаємо сюжет через 1-3 дні (рандом)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS achievement_story_delivery (
                user_id BIGINT NOT NULL,
                card_id INTEGER NOT NULL REFERENCES story_cards(id),
                achievement_key VARCHAR(64) NOT NULL,
                scheduled_send_at TIMESTAMP NOT NULL,
                sent_at TIMESTAMP,
                PRIMARY KEY (user_id, card_id)
            )
        """)
        
        # Заблоковані користувачі (не можуть користуватися ботом)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS blocked_users (
                user_id BIGINT PRIMARY KEY,
                blocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Контрабанда: кулдаун 3 год, події 72 год, перехоплення
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contraband_cooldown (
                user_id BIGINT PRIMARY KEY,
                last_used_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contraband_events (
                user_id BIGINT PRIMARY KEY,
                last_event_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                event_type VARCHAR(32)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contraband_interception (
                id SERIAL PRIMARY KEY,
                smuggler_id BIGINT NOT NULL,
                cargo_type VARCHAR(16) NOT NULL,
                route VARCHAR(16) NOT NULL,
                has_guard BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                resolved BOOLEAN NOT NULL DEFAULT FALSE,
                interceptor_id BIGINT
            )
        """)

        # Галас у казино: міні-режим між іграми - ставки на події в наступній грі
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS casino_rounds (
                id SERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                resolved_at TIMESTAMP,
                first_night_death BOOLEAN,
                commissioner_executed_by_day3 BOOLEAN,
                mafia_wins BOOLEAN
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS casino_bets (
                id SERIAL PRIMARY KEY,
                round_id INTEGER NOT NULL REFERENCES casino_rounds(id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL,
                event_id VARCHAR(64) NOT NULL,
                amount INTEGER NOT NULL CHECK (amount > 0),
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                won BOOLEAN,
                payout INTEGER
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_casino_rounds_chat ON casino_rounds(chat_id);
            CREATE INDEX IF NOT EXISTS idx_casino_bets_round ON casino_bets(round_id);
            CREATE INDEX IF NOT EXISTS idx_casino_bets_user ON casino_bets(user_id);
        """)
        # Додаткові колонки для казино (закриття ставок при старті гри + видалення повідомлення)
        for ddl in [
            "ALTER TABLE casino_rounds ADD COLUMN IF NOT EXISTS bets_closed_at TIMESTAMP",
            "ALTER TABLE casino_rounds ADD COLUMN IF NOT EXISTS message_id BIGINT",
        ]:
            try:
                cursor.execute(ddl)
            except Exception:
                pass

        # Рулетка (/roulette): профіль гравця для серій/кд/подій
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS roulette_profiles (
                user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                last_play_at TIMESTAMP,
                cooldown_until TIMESTAMP,
                win_streak INTEGER NOT NULL DEFAULT 0,
                lose_streak INTEGER NOT NULL DEFAULT 0,
                debt_multiplier BOOLEAN NOT NULL DEFAULT FALSE,
                cat_debuff_until TIMESTAMP,
                contract_multiplier_next INTEGER NOT NULL DEFAULT 1,
                contract_penalty BOOLEAN NOT NULL DEFAULT FALSE,
                pending_custom_until TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_roulette_cooldown ON roulette_profiles(cooldown_until);")

        # Пінгачок (/play): зберігаємо user_id, яких можна тегати в конкретному чаті
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ping_chat_members (
                chat_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                added_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, user_id)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ping_chat_members_chat_added
            ON ping_chat_members(chat_id, added_at DESC)
        """)

        # Відписка від пінгачка («Анрег» / /unreg) - переживає перезапуск бота
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ping_chat_opt_out (
                chat_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                opted_out_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, user_id)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ping_chat_opt_out_chat
            ON ping_chat_opt_out(chat_id)
        """)

        # Групи/супергрупи, де бот колись бачив активність (для статистики /capone_admin)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_known_groups (
                group_id BIGINT PRIMARY KEY,
                first_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_bot_known_groups_last_seen
            ON bot_known_groups(last_seen_at DESC)
        """)
        # Початкове заповнення з уже наявних таблиць (група могла писати в чат без admin_panel)
        try:
            cursor.execute("""
                INSERT INTO bot_known_groups (group_id, first_seen_at, last_seen_at)
                SELECT DISTINCT group_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM admin_panel
                ON CONFLICT (group_id) DO NOTHING
            """)
            cursor.execute("""
                INSERT INTO bot_known_groups (group_id, first_seen_at, last_seen_at)
                SELECT DISTINCT chat_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM ping_chat_members
                ON CONFLICT (group_id) DO NOTHING
            """)
            cursor.execute("""
                INSERT INTO bot_known_groups (group_id, first_seen_at, last_seen_at)
                SELECT DISTINCT group_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM group_buff_settings
                ON CONFLICT (group_id) DO NOTHING
            """)
            cursor.execute("""
                INSERT INTO bot_known_groups (group_id, first_seen_at, last_seen_at)
                SELECT DISTINCT chat_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM casino_rounds
                ON CONFLICT (group_id) DO NOTHING
            """)
            cursor.execute("""
                INSERT INTO bot_known_groups (group_id, first_seen_at, last_seen_at)
                SELECT DISTINCT group_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM custom_roles
                ON CONFLICT (group_id) DO NOTHING
            """)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        
        # Якщо БД вже була створена раніше - додамо колонку pending_custom_until
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'roulette_profiles' AND column_name = 'pending_custom_until'
                ) THEN
                    ALTER TABLE roulette_profiles ADD COLUMN pending_custom_until TIMESTAMP;
                END IF;
            END $$;
        """)

        # VIP: страховка / перекрут / щоденний бонус у рулетці
        for vip_col, vip_type in [
            ("vip_insurance_used_today", "INTEGER NOT NULL DEFAULT 0"),
            ("vip_insurance_day", "DATE"),
            ("vip_reroll_used_day", "DATE"),
            ("vip_daily_grant_day", "DATE"),
        ]:
            cursor.execute(f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = 'roulette_profiles'
                          AND column_name = '{vip_col}'
                    ) THEN
                        ALTER TABLE roulette_profiles ADD COLUMN {vip_col} {vip_type};
                    END IF;
                END $$;
            """)

        # VIP-значок (VIP+): вибір емодзі; повідомлення про закінчення VIP (один раз на період)
        for ucol, utype in [
            ("vip_badge_choice", "VARCHAR(16)"),
            ("vip_farewell_last_end", "TIMESTAMP"),
        ]:
            cursor.execute(f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = 'users'
                          AND column_name = '{ucol}'
                    ) THEN
                        ALTER TABLE users ADD COLUMN {ucol} {utype};
                    END IF;
                END $$;
            """)

        # Час першого запису користувача (для знижки новачку на VIP)
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'users'
                      AND column_name = 'registered_at'
                ) THEN
                    ALTER TABLE users ADD COLUMN registered_at TIMESTAMP;
                END IF;
            END $$;
        """)
        try:
            cursor.execute(
                "UPDATE users SET registered_at = CURRENT_TIMESTAMP WHERE registered_at IS NULL"
            )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        
        # Адміни групи (рівні 1-4). Власник групи в Telegram має максимальний рівень (4).
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS group_admins (
                group_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                level SMALLINT NOT NULL CHECK (level >= 1 AND level <= 4),
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                added_by BIGINT,
                PRIMARY KEY (group_id, user_id)
            )
        """)
        try:
            cursor.execute("""
                INSERT INTO bot_known_groups (group_id, first_seen_at, last_seen_at)
                SELECT DISTINCT group_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM group_admins
                ON CONFLICT (group_id) DO NOTHING
            """)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        
        # Глобальне вимкнення slash-команд бота (керують лише BOT_OWNER_IDS через /cmd_off, /cmd_on)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS disabled_bot_commands (
                command_name VARCHAR(64) PRIMARY KEY,
                disabled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Сезонні івенти: один рядок (id=1) тримає id активного івенту (або NULL).
        # Single-row дизайн гарантує, що активним може бути лише один івент одночасно.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS seasonal_event_state (
                id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                active_event_id VARCHAR(64),
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            INSERT INTO seasonal_event_state (id, active_event_id)
            VALUES (1, NULL)
            ON CONFLICT (id) DO NOTHING
        """)

        # Інвентар сезонного івенту «Купальська ніч»: папороть, вінки тощо.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS kupala_inventory (
                user_id BIGINT NOT NULL,
                item_id VARCHAR(64) NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, item_id)
            )
        """)
        # Кулдаун «Похід до лісу» (раз на 24 год).
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS kupala_player (
                user_id BIGINT PRIMARY KEY,
                forest_trip_at TIMESTAMP
            )
        """)
        # Застосований (але ще не зіграний) вінок-баф: чекає на найближчу гру гравця.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS kupala_pending_buffs (
                user_id BIGINT PRIMARY KEY,
                buff_id VARCHAR(64) NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes for better performance
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
            CREATE INDEX IF NOT EXISTS idx_users_killed ON users(killed);
            CREATE INDEX IF NOT EXISTS idx_custom_roles_creator_group ON custom_roles(creator_id, group_id);
            CREATE INDEX IF NOT EXISTS idx_custom_roles_group ON custom_roles(group_id);
            CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id);
            CREATE INDEX IF NOT EXISTS idx_subscriptions_active ON subscriptions(is_active);
            CREATE INDEX IF NOT EXISTS idx_admin_panel_creator ON admin_panel(creator_id);
            CREATE INDEX IF NOT EXISTS idx_admin_panel_group ON admin_panel(group_id);
            CREATE INDEX IF NOT EXISTS idx_group_admins_group ON group_admins(group_id);
            CREATE INDEX IF NOT EXISTS idx_group_admins_user ON group_admins(user_id);
            CREATE INDEX IF NOT EXISTS idx_user_buffs_user ON user_buffs(user_id);
            CREATE INDEX IF NOT EXISTS idx_buff_purchases_user ON buff_purchases(user_id);
            CREATE INDEX IF NOT EXISTS idx_user_achievement_progress_user ON user_achievement_progress(user_id);
            CREATE INDEX IF NOT EXISTS idx_user_story_cards_user ON user_story_cards(user_id);
            CREATE INDEX IF NOT EXISTS idx_user_story_choices_user ON user_story_choices(user_id);
            CREATE INDEX IF NOT EXISTS idx_achievement_story_delivery_send ON achievement_story_delivery(scheduled_send_at) WHERE sent_at IS NULL;
        """)

        # Єдина сюжетна карточка (card_order=0): Аль Капоне
        AL_CAPONE_INTRO = (
            "💥 ВІДКРИТО СЮЖЕТНИЙ ПОВОРОТ\n\n"
            "Львів, ніч 15 листопада 1931 року\n\n"
            "Туман повільно стелиться вузькими вулицями Львова.\n"
            "Ліхтарі мерехтять у калюжах, а запах гарячої кави змішується з пилом і страхом.\n\n"
            "Ви стоїте в тіні будівлі, спостерігаючи за людьми на Ринку.\n"
            "Серед них - перші підлеглі нового «короля» Борислава, ще не впевнені, чому повинні слухатися чужого чоловіка з Гданська.\n\n"
            "Той самий чоловік у фетровому капелюсі з італійським акцентом - Великий Ел - повільно обходить своїх людей, оцінює, хто справжній, а хто боїться.\n"
            "Його присутність одразу змушує людей зупинятися, обережно кивати, не дихати зайвий раз.\n\n"
            "🚨 Вибір:"
        )
        cursor.execute("SELECT COUNT(*) FROM story_cards")
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "INSERT INTO story_cards (card_order, title_uk, text_uk) VALUES (0, %s, %s)",
                ("Аль Капоне", AL_CAPONE_INTRO),
            )
        else:
            cursor.execute(
                "UPDATE story_cards SET title_uk = %s, text_uk = %s WHERE card_order = 0",
                ("Аль Капоне", AL_CAPONE_INTRO),
            )

        # Досягнення: виконання відкриває сюжетку Аль Капоне
        cursor.execute("SELECT id FROM story_cards WHERE card_order = 0 LIMIT 1")
        al_capone_row = cursor.fetchone()
        al_capone_card_id = al_capone_row[0] if al_capone_row else None
        cursor.execute("SELECT COUNT(*) FROM achievements")
        if cursor.fetchone()[0] == 0 and al_capone_card_id is not None:
            cursor.execute(
                "INSERT INTO achievements (achievement_key, name_uk, condition_type, condition_role, target_value, story_card_id) VALUES "
                "(%s, %s, %s, %s, %s, %s)",
                ("first_win", "Перша перемога", "wins_total", None, 1, al_capone_card_id),
            )
        # Досягнення «Аль-Капоне» - видається командою /getAlcap (30 сек таймер, потім в ПП)
        cursor.execute(
            "INSERT INTO achievements (achievement_key, name_uk, condition_type, condition_role, target_value, story_card_id) "
            "SELECT 'al_capone', 'Аль-Капоне', 'manual', NULL, 1, %s "
            "WHERE NOT EXISTS (SELECT 1 FROM achievements WHERE achievement_key = 'al_capone') AND %s IS NOT NULL",
            (al_capone_card_id, al_capone_card_id),
        )

        # Сюжетна карточка Мафія (card_order=1)
        MAFIA_STORY_TEXT = (
            "‼️СЮЖЕТКА\n"
            "💥ВИ ВІДКРИЛИ ЧАСТИНУ СЮЖЕТУ💥\n\n"
            "🕴🏻 Я - Мафія, Тінь Великого Ела, Наступник Чорного Золота 🕴🏻\n\n"
            "Сідай ближче в тінь, брат по Сім'ї. "
            "Налий собі з пляшки, що пахне нафтою й порохом. "
            "Я розповім тобі, хто я такий у цій грі, бо ти - мої руки, мої очі, моя помста.\n"
            "Я народився в диму Борислава, де вишки гудуть, як серце Галичини, а люди копають землю руками за крихти. "
            "Пацифікація спалила моє минуле, польські жандарми залишили лише попіл і ненависть. "
            "Я став вуличним вовком Підзамче - краду, б'ю, виживаю. "
            "А потім з'явився він - Великий Ел, Шраматик з-за океану. Він не просто годував голодних варениками, він давав сенс: \"Нафта - це новий віскі, а ти - мій наступник. Вчися мудрості: зрадники вмирають першими, а вірні піднімаються\".\n\n"
            "Я стояв поруч, коли гримів Tommy Gun у Бориславській Різанині. "
            "Я тримав казино на Ринку, вербував стрільців з Карпат, переправляв бочки в Рейх і Совітів. "
            "Я вчився його харизмі, його параної, його жорстокості. "
            "Тепер я готовий: якщо Великий Ел впаде - я візьму трон. Сім'я не розпадеться. Помста буде холодною, як сніг над вишками.\n\n"
            "Твоя роль у грі - моя спадщина\n"
            "Ціль: Навчитися мудрості Великого Ела та зайняти його місце, якщо зрадники його доб'ють.\n\n"
            "Галичина - це арена. Копи, журналісти, маніяки, повстанці - всі хочуть шматок. "
            "Але нафта тече, кров зрадників - теж. Довіряй лише Сім'ї. Грай мудро, як учив Великий Ел. Трон чекає. 🕴🏻"
        )
        cursor.execute("SELECT id FROM story_cards WHERE card_order = 1 LIMIT 1")
        mafia_row = cursor.fetchone()
        if mafia_row is None:
            cursor.execute(
                "INSERT INTO story_cards (card_order, title_uk, text_uk) VALUES (1, %s, %s)",
                ("Мафія", MAFIA_STORY_TEXT),
            )
        cursor.execute("SELECT id FROM story_cards WHERE card_order = 1 LIMIT 1")
        mafia_card_row = cursor.fetchone()
        mafia_card_id = mafia_card_row[0] if mafia_card_row else None
        cursor.execute(
            "INSERT INTO achievements (achievement_key, name_uk, condition_type, condition_role, target_value, story_card_id) "
            "SELECT 'mafia', 'Мафія!', 'manual', NULL, 1, %s "
            "WHERE NOT EXISTS (SELECT 1 FROM achievements WHERE achievement_key = 'mafia') AND %s IS NOT NULL",
            (mafia_card_id, mafia_card_id),
        )

        # Сюжетний поворот «Початок Мафія» (card_order=2) - для тих, хто має Дона і Мафію; доставка через 1 день
        MAFIA_START_INTRO = (
            "💥ВІДКРИТО СЮЖЕТНИЙ ПОВОРОТ\n\n"
            "Львів, ніч 3 серпня 1932 року\n\n"
            "Темні тіні складу на Підзамчі ховають підлеглих Ела. Звуки далекого ринку і брязкіт сигаретного паперу розрізають нічну тишу.\n"
            "Великий Ел стоїть під лампою, руки схрещені на грудях, його погляд розсікає темряву, наче він бачить кожного.\n"
            "Ти спостерігаєш, ховаючись у тіні. Повітря густе від нафти і пилу. Хтось шепоче про \"зрадника серед нас\", інші просто мовчать, бо бояться зробити крок.\n\n"
            "🚨 Вибір:"
        )
        cursor.execute("SELECT id FROM story_cards WHERE card_order = 2 LIMIT 1")
        mafia_start_row = cursor.fetchone()
        if mafia_start_row is None:
            cursor.execute(
                "INSERT INTO story_cards (card_order, title_uk, text_uk) VALUES (2, %s, %s)",
                ("Аль Капоне + Мафія", MAFIA_START_INTRO),
            )
        else:
            cursor.execute(
                "UPDATE story_cards SET title_uk = %s WHERE card_order = 2",
                ("Аль Капоне + Мафія",),
            )

        # Карточка Комісар Каттані (card_order=3)
        cursor.execute("SELECT id FROM story_cards WHERE card_order = 3 LIMIT 1")
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO story_cards (card_order, title_uk, text_uk) VALUES (3, %s, %s)",
                ("Комісар Каттані", "📇 Унікальна карточка: Комісар Каттані"),
            )
        cursor.execute("SELECT id FROM story_cards WHERE card_order = 3 LIMIT 1")
        komisar_row = cursor.fetchone()
        komisar_card_id = komisar_row[0] if komisar_row else None
        cursor.execute(
            "INSERT INTO achievements (achievement_key, name_uk, condition_type, condition_role, target_value, story_card_id) "
            "SELECT 'komisar', 'Комісар Каттані', 'manual', NULL, 1, %s "
            "WHERE NOT EXISTS (SELECT 1 FROM achievements WHERE achievement_key = 'komisar') AND %s IS NOT NULL",
            (komisar_card_id, komisar_card_id),
        )

        # Сюжетний поворот «Аль-Капоне і Комісар» (card_order=4) - для тих, хто має Аль Капоне і Комісара; доставка через 1 день
        AL_KOMISAR_INTRO = (
            "💥ВІДКРИТО СЮЖЕТНИЙ ПОВОРОТ\n\n"
            "Львів, ніч 12 квітня 1932 року\n\n"
            "Туман стелиться над вузькими вуличками Підзамче. Десь далеко чути дзвони і крики.\n"
            "Ти стоїш за дерев'яним парканом і бачиш: Великий Ел обговорює щось зі своїм охоронцем, коли раптом із темряви з'являється Комісар Каттані.\n\n"
            "Він тихо підходить, погляд гострий, ніби бачить крізь стіни.\n"
            "Його присутність додає напруженості: тут перетинаються два світи - контроль і хаос.\n"
            "Ти - свідок цього моменту.\n"
            "Легкий подих вітру зриває сигаретний дим, і ти чуєш слова, які не повинні були пролунати назовні…\n\n"
            "🚨 Вибір:"
        )
        cursor.execute("SELECT id FROM story_cards WHERE card_order = 4 LIMIT 1")
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO story_cards (card_order, title_uk, text_uk) VALUES (4, %s, %s)",
                ("Аль-Капоне і Комісар", AL_KOMISAR_INTRO),
            )

        # Сюжетний поворот «Аль-Капоне і Сержант» (card_order=5) - для тих, хто має Аль Капоне; доставка через 1 день
        AL_SERGEANT_INTRO = (
            "💥ВІДКРИТО СЮЖЕТНИЙ ПОВОРОТ\n\n"
            "Львів, ніч 19 лютого 1939 року\n\n"
            "Сніг падає великими пластівцями на бруківку вулиці Клепарівської, глушить кроки. "
            "Старий трамвайний вагон стоїть без руху, ліхтарі мерехтять крізь іній.\n"
            "Ти притулився до стіни закинутої крамниці, і бачиш: Великий Ел виходить з чорного \"Опеля\", комір піднятий, сигара тліє. "
            "Напроти, у тіні під аркою, стоїть Сержант - мундир розстебнутий, рука в кишені, де револьвер.\n"
            "Між ними - метр порожнечі, наповненої снігом і ненавистю. "
            "Ел пропонує щось, Сержант мовчить. Один жест - і ніч стане червоною...\n\n"
            "🚨 Вибір:"
        )
        cursor.execute("SELECT id FROM story_cards WHERE card_order = 5 LIMIT 1")
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO story_cards (card_order, title_uk, text_uk) VALUES (5, %s, %s)",
                ("Аль-Капоне і Сержант", AL_SERGEANT_INTRO),
            )

        # Унікальна карточка Сержант (card_order=6)
        cursor.execute("SELECT id FROM story_cards WHERE card_order = 6 LIMIT 1")
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO story_cards (card_order, title_uk, text_uk) VALUES (6, %s, %s)",
                ("Сержант", "📇 Унікальна карточка: Сержант"),
            )
        cursor.execute("SELECT id FROM story_cards WHERE card_order = 6 LIMIT 1")
        sergeant_row = cursor.fetchone()
        sergeant_card_id = sergeant_row[0] if sergeant_row else None
        cursor.execute(
            "INSERT INTO achievements (achievement_key, name_uk, condition_type, condition_role, target_value, story_card_id) "
            "SELECT 'sergeant', 'Сержант', 'manual', NULL, 1, %s "
            "WHERE NOT EXISTS (SELECT 1 FROM achievements WHERE achievement_key = 'sergeant') AND %s IS NOT NULL",
            (sergeant_card_id, sergeant_card_id),
        )

        # Сюжетний поворот «Аль Капоне і Лікар» (card_order=7) - для тих, хто має Аль Капоне і досягнення Лікар
        AL_DOCTOR_TITLE = "Аль Капоне і Лікар"
        cursor.execute("SELECT id FROM story_cards WHERE card_order = 7 LIMIT 1")
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO story_cards (card_order, title_uk, text_uk) VALUES (7, %s, %s)",
                (AL_DOCTOR_TITLE, ""),
            )
        else:
            cursor.execute("UPDATE story_cards SET title_uk = %s WHERE card_order = 7", (AL_DOCTOR_TITLE,))

        # Сюжетний поворот «Аль Капоне і МедСестра» (card_order=8) - для тих, хто має Аль Капоне і досягнення Мед-сестра
        AL_NURSE_TITLE = "Аль Капоне і Медсестра"
        cursor.execute("SELECT id FROM story_cards WHERE card_order = 8 LIMIT 1")
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO story_cards (card_order, title_uk, text_uk) VALUES (8, %s, %s)",
                (AL_NURSE_TITLE, ""),
            )
        else:
            cursor.execute("UPDATE story_cards SET title_uk = %s WHERE card_order = 8", (AL_NURSE_TITLE,))

        # Сюжетний поворот «Аль-Капоне і Коханка» (card_order=9) - для тих, хто має Аль Капоне і досягнення Коханка
        AL_PROSTITUTE_TITLE = "Аль Капоне і Коханка"
        cursor.execute("SELECT id FROM story_cards WHERE card_order = 9 LIMIT 1")
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO story_cards (card_order, title_uk, text_uk) VALUES (9, %s, %s)",
                (AL_PROSTITUTE_TITLE, ""),
            )
        # Сюжетний поворот «Аль-Капоне і Брехун» (card_order=10) - для тих, хто має Аль Капоне і досягнення Брехун
        AL_TRICKSTER_TITLE = "Аль Капоне і Брехун"
        cursor.execute("SELECT id FROM story_cards WHERE card_order = 10 LIMIT 1")
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO story_cards (card_order, title_uk, text_uk) VALUES (10, %s, %s)",
                (AL_TRICKSTER_TITLE, ""),
            )
        # Сюжетний поворот «Аль-Капоне і Адвокат» (card_order=11) - для тих, хто має Аль Капоне і досягнення Адвокат
        AL_LAWYER_TITLE = "Аль Капоне і Адвокат"
        cursor.execute("SELECT id FROM story_cards WHERE card_order = 11 LIMIT 1")
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO story_cards (card_order, title_uk, text_uk) VALUES (11, %s, %s)",
                (AL_LAWYER_TITLE, ""),
            )
        # Унікальна карточка Лікар (card_order=12) - при досягненні Лікар
        UNIQUE_DOCTOR_TITLE = "Лікар"
        cursor.execute("SELECT id FROM story_cards WHERE card_order = 12 LIMIT 1")
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO story_cards (card_order, title_uk, text_uk) VALUES (12, %s, %s)",
                (UNIQUE_DOCTOR_TITLE, "📇 Унікальна карточка: Лікар"),
            )
        # Унікальна карточка Мед. сестра (card_order=13) - при досягненні Мед-сестра
        UNIQUE_NURSE_TITLE = "Мед. сестра"
        cursor.execute("SELECT id FROM story_cards WHERE card_order = 13 LIMIT 1")
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO story_cards (card_order, title_uk, text_uk) VALUES (13, %s, %s)",
                (UNIQUE_NURSE_TITLE, "📇 Унікальна карточка: Мед. сестра"),
            )
        # Унікальна карточка Коханка (card_order=14) - при досягненні Коханка
        UNIQUE_PROSTITUTE_TITLE = "Коханка"
        cursor.execute("SELECT id FROM story_cards WHERE card_order = 14 LIMIT 1")
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO story_cards (card_order, title_uk, text_uk) VALUES (14, %s, %s)",
                (UNIQUE_PROSTITUTE_TITLE, "📇 Унікальна карточка: Коханка"),
            )
        # Унікальна карточка Брехун (card_order=15) - при досягненні Брехун
        UNIQUE_TRICKSTER_TITLE = "Брехун"
        cursor.execute("SELECT id FROM story_cards WHERE card_order = 15 LIMIT 1")
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO story_cards (card_order, title_uk, text_uk) VALUES (15, %s, %s)",
                (UNIQUE_TRICKSTER_TITLE, "📇 Унікальна карточка: Брехун"),
            )
        # Унікальна карточка Адвокат (card_order=16) - при досягненні Адвокат
        UNIQUE_LAWYER_TITLE = "Адвокат"
        cursor.execute("SELECT id FROM story_cards WHERE card_order = 16 LIMIT 1")
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO story_cards (card_order, title_uk, text_uk) VALUES (16, %s, %s)",
                (UNIQUE_LAWYER_TITLE, "📇 Унікальна карточка: Адвокат"),
            )
        # Унікальна карточка Самогубець (card_order=17) - при досягненні Самогубця
        UNIQUE_SUICIDE_TITLE = "Самогубець"
        cursor.execute("SELECT id FROM story_cards WHERE card_order = 17 LIMIT 1")
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO story_cards (card_order, title_uk, text_uk) VALUES (17, %s, %s)",
                (UNIQUE_SUICIDE_TITLE, "📇 Унікальна карточка: Самогубець"),
            )
        # Унікальна карточка Клоун (card_order=18) - може випасти в адвенті з шансом 1%
        CLOWN_CARD_TITLE = "Клоун"
        CLOWN_CARD_TEXT = (
            "💥ВИ ВІДКРИЛИ ЧАСТИНУ СЮЖЕТУ💥\n\n"
            "🤡 Я - Клоун, Той, Хто Міняє Маски на Сцені Хаосу 🤡\n\n"
            "Сідай на арену старого цирку на околиці Львова, де шапіто давно проржавіло, а клітка лева стоїть порожня, ніби чекає на чергову жертву. "
            "Я в кольоровому костюмі, з червоним носом, що блищить під єдиним прожектором, в руках - рожевий молоток і маска з посмішкою диявола. "
            "Музика грамофона грає \"Вальс чаклунів\" задом наперед. "
            "Ти - мій єдиний глядач цієї ночі. Слухай сміх, бо він ховає крик.\n\n"
            "Я не народився клоуном. Я став ним. "
            "1898-й, Варшава, родина циркових акробатів - батько жонглер, мати - канатохідка. "
            "Ми приїхали до Львова 1920-го, ставили шапіто на Ринку, смішили бідних хлібом й жартами. "
            "Люди сміялися, кидали копійки, забували про голод.\n\n"
            "Пацифікація 1930-го все зламала. "
            "Польські жандарми спалили цирк - \"повстанці ховаються під шатром\". "
            "Батько намагався пожартувати з офіцером - отримав кулю в живіт. Мати впала з каната в полум'я.\n\n"
            "Мені було 32. Я вижив, бо сміявся: \"Господарі, це ж частина шоу!\". Вони засміялися й відпустили.\n\n"
            "З того дня я - Клоун. Не для сміху. Для плутанини. "
            "Ходжу по кав'ярнях Великого Ела, жонглюю сигарами в казино, малюю посмішки на стінах Підзамче. "
            "Аль Капоне думає, що я його блазень - годує варениками, кидає монети. "
            "Комісар Каттані дивиться крізь мене, як крізь повітря. "
            "Але в мене є один трюк - один шанс за всю гру. "
            "Я заходжу до двох гравців, хапаю їхні маски й міняю місцями. "
            "Мафіозі стає Лікарем, Комісар - Маніяком, Мирний - Аль Капоне.\n\n"
            "Хаос! Плани руйнуються, Сім'я гризе лікті, закон сліпий. Це не помста. Це шоу. Найкраще шоу Галичини.\n\n"
            "Я сміюся не тому, що щасливий. Я сміюся, бо світ - цирк, а я - єдиний, хто знає, де підміна.\n\n"
            "Твоя роль у грі - мій великий трюк. "
            "Ціль: Засіяти хаос і плутанину. За всю гру у тебе один шанс: зайти до двох гравців і поміняти їхні ролі місцями. Це зламає плани будь-якої команди.\n\n"
            "Сміх - найкраща помста. Міняй маски, і шоу почнеться!\n\n"
            "Твоя черга. Кого обміняємо на цій арені? 🤡"
        )
        cursor.execute("SELECT id FROM story_cards WHERE card_order = 18 LIMIT 1")
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO story_cards (card_order, title_uk, text_uk) VALUES (18, %s, %s)",
                (CLOWN_CARD_TITLE, CLOWN_CARD_TEXT),
            )
        else:
            cursor.execute(
                "UPDATE story_cards SET title_uk = %s, text_uk = %s WHERE card_order = 18",
                (CLOWN_CARD_TITLE, CLOWN_CARD_TEXT),
            )

        # Розділи 10–18 у /story (card_order 19–27); умови відкриття — у commands/story_achievements.py
        story_late_chapters = (
            (19, 10, "Самогубець"),
            (20, 11, "Мирний житель"),
            (21, 12, "Волоцюга"),
            (22, 13, "Камікадзе"),
            (23, 14, "Щасливчик"),
            (24, 15, "Журналіст"),
            (25, 16, "Маніяк"),
            (26, 17, "Клоун"),
            (27, 18, "Диявол"),
        )
        for co, section_num, role_name in story_late_chapters:
            title_uk = f"Розділ {section_num} — {role_name}"
            placeholder_intro = (
                "💥 ВІДКРИТО СЮЖЕТНИЙ ПОВОРОТ\n\n"
                "Львів\n\n"
                f"Розділ {section_num} ({role_name}): текст сюжету готується. Ти вже виконав умови, щоб бачити цей розділ у літописі.\n\n"
                "🚨 Вибір:"
            )
            cursor.execute("SELECT id FROM story_cards WHERE card_order = %s LIMIT 1", (co,))
            if cursor.fetchone() is None:
                cursor.execute(
                    "INSERT INTO story_cards (card_order, title_uk, text_uk) VALUES (%s, %s, %s)",
                    (co, title_uk, placeholder_intro),
                )
            else:
                cursor.execute(
                    "UPDATE story_cards SET title_uk = %s, text_uk = %s WHERE card_order = %s",
                    (title_uk, placeholder_intro, co),
                )

        # Унікальні карточки (відео в Media/Унікальні) — card_order 28–34
        unique_media_cards = (
            (28, "Мирний житель", "📇 Унікальна карточка: Мирний житель"),
            (29, "Волоцюга", "📇 Унікальна карточка: Волоцюга"),
            (30, "Камікадзе", "📇 Унікальна карточка: Камікадзе"),
            (31, "Щасливчик", "📇 Унікальна карточка: Щасливчик"),
            (32, "Журналіст", "📇 Унікальна карточка: Журналіст"),
            (33, "Маніяк", "📇 Унікальна карточка: Маніяк"),
            (34, "Диявол", "📇 Унікальна карточка: Диявол"),
        )
        for co, title_u, text_u in unique_media_cards:
            cursor.execute("SELECT id FROM story_cards WHERE card_order = %s LIMIT 1", (co,))
            if cursor.fetchone() is None:
                cursor.execute(
                    "INSERT INTO story_cards (card_order, title_uk, text_uk) VALUES (%s, %s, %s)",
                    (co, title_u, text_u),
                )
            else:
                cursor.execute(
                    "UPDATE story_cards SET title_uk = %s, text_uk = %s WHERE card_order = %s",
                    (title_u, text_u, co),
                )

        # Бот «Кримінальне чтиво» (NOIR) — профіль детектива, інвентар, справи
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS noir_users (
                user_id BIGINT PRIMARY KEY,
                dossier_no INTEGER NOT NULL,
                cash INTEGER NOT NULL DEFAULT 50,
                xp INTEGER NOT NULL DEFAULT 0,
                vigilance_lvl INTEGER NOT NULL DEFAULT 1,
                persuasion_lvl INTEGER NOT NULL DEFAULT 1,
                has_flashlight INTEGER NOT NULL DEFAULT 0,
                batteries INTEGER NOT NULL DEFAULT 0,
                camel_packs INTEGER NOT NULL DEFAULT 0,
                whiskey_unused INTEGER NOT NULL DEFAULT 0,
                case1_started INTEGER NOT NULL DEFAULT 0
            )
        """)

        # Оновлення опису дефолтної ролі «Щасливчик» у чатах (у JSON лишався старий текст про 75%%)
        _lucky_desc_new = (
            "<b>Цієї гри - ти Щасливчик</b> 🍀\n\n"
            "Фортуна завжди на твоєму боці… майже.\n"
            "Ти виживаєш там, де інші гинуть, і тобі часто щастить у випадкових ситуаціях."
        )
        try:
            cursor.execute(
                """
                UPDATE custom_roles
                SET role_description = %s,
                    role_data = jsonb_set(
                        COALESCE(role_data, '{}'::jsonb),
                        '{description}',
                        to_jsonb(%s::text),
                        true
                    )
                WHERE role_name = 'Щасливчик'
                  AND is_default = TRUE
                  AND (
                        (role_data->>'description') = 'При спробі вбивства має 75%% шанс вижити.'
                     OR (role_data->>'description') LIKE '%%При спробі вбивства%%75%%'
                     OR role_description = 'При спробі вбивства має 75%% шанс вижити.'
                     OR (
                          (role_data->>'description') LIKE '%%Щасливчик%%🤞%%'
                      AND (role_data->>'description') LIKE '%%75%%'
                     )
                  )
                """,
                (_lucky_desc_new, _lucky_desc_new),
            )
        except Exception as _lucky_mig_err:
            logger.warning("noir/lucky role description migration skipped: %s", _lucky_mig_err)

        conn.commit()
        logger.info("Database tables created/verified successfully")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error creating tables: {e}")
        raise


def is_user_blocked(user_id: int) -> bool:
    """Перевіряє, чи заблокований користувач за ID."""
    global cursor
    if cursor is None:
        return False
    try:
        cursor.execute("SELECT 1 FROM blocked_users WHERE user_id = %s", (user_id,))
        return cursor.fetchone() is not None
    except Exception:
        return False


def block_user(user_id: int) -> bool:
    """Блокує користувача за ID. Повертає True якщо успішно."""
    global conn, cursor
    if conn is None or cursor is None:
        return False
    try:
        cursor.execute(
            "INSERT INTO blocked_users (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING",
            (user_id,),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False


def unblock_user(user_id: int) -> bool:
    """Розблоковує користувача за ID. Повертає True якщо успішно."""
    global conn, cursor
    if conn is None or cursor is None:
        return False
    try:
        cursor.execute("DELETE FROM blocked_users WHERE user_id = %s", (user_id,))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False


async def is_user_blocked_async(user_id: int) -> bool:
    return await run_db_call_async(is_user_blocked, user_id)


async def is_bot_command_disabled_async(command_name: str) -> bool:
    return await run_db_call_async(is_bot_command_disabled, command_name)


async def touch_known_group_async(group_id: int) -> None:
    await run_db_call_async(touch_known_group, group_id)


async def block_user_async(user_id: int) -> bool:
    return await run_db_call_async(block_user, user_id)


async def unblock_user_async(user_id: int) -> bool:
    return await run_db_call_async(unblock_user, user_id)


async def try_grant_starter_gift_async(user_id: int) -> bool:
    return await run_db_call_async(try_grant_starter_gift, user_id)


async def get_group_creator_id_async(group_id: int):
    return await run_db_call_async(get_group_creator_id, group_id)


async def deduct_user_gold_async(user_id: int, amount: int) -> bool:
    return await run_db_call_async(deduct_user_gold, user_id, amount)


async def add_gold_to_user_async(user_id: int, amount: int) -> None:
    await run_db_call_async(add_gold_to_user, user_id, amount)


async def get_active_founder_ids_async() -> list[int]:
    return await run_db_call_async(get_active_founder_ids)


async def get_balance_async(user_id: int) -> int:
    return await run_db_call_async(get_balance, user_id)


async def deduct_balance_async(user_id: int, amount: int) -> bool:
    return await run_db_call_async(deduct_balance, user_id, amount)


async def add_balance_to_user_async(user_id: int, amount: int) -> None:
    await run_db_call_async(add_balance_to_user, user_id, amount)


async def casino_create_round_async(chat_id: int) -> int:
    return await run_db_call_async(casino_create_round, chat_id)


async def casino_get_open_round_async(chat_id: int):
    return await run_db_call_async(casino_get_open_round, chat_id)


async def casino_get_pending_round_async(chat_id: int):
    return await run_db_call_async(casino_get_pending_round, chat_id)


async def casino_is_round_open_async(round_id: int) -> bool:
    return await run_db_call_async(casino_is_round_open, round_id)


async def casino_place_bet_async(round_id: int, user_id: int, event_id: str, amount: int) -> bool:
    return await run_db_call_async(casino_place_bet, round_id, user_id, event_id, amount)


async def casino_get_bets_for_round_async(round_id: int):
    return await run_db_call_async(casino_get_bets_for_round, round_id)


async def casino_resolve_round_async(round_id: int, first_night_death: bool, commissioner_executed_by_day3: bool, mafia_wins: bool, extra_outcomes: dict = None, odds_by_event: dict = None) -> None:
    await run_db_call_async(casino_resolve_round, round_id, first_night_death, commissioner_executed_by_day3, mafia_wins, extra_outcomes, odds_by_event)


async def casino_set_round_message_id_async(round_id: int, message_id: int) -> None:
    await run_db_call_async(casino_set_round_message_id, round_id, message_id)


async def roulette_get_profile_async(user_id: int) -> dict:
    return await run_db_call_async(roulette_get_profile, user_id)


async def roulette_update_profile_async(
    user_id: int,
    win_streak: int | None = None,
    lose_streak: int | None = None,
    cat_debuff_minutes: int | None = None,
    debt_multiplier: bool | None = None,
    contract_multiplier_next: int | None = None,
    contract_penalty: bool | None = None,
    pending_custom_minutes: int | None = None,
    clear_pending_custom: bool = False,
    set_last_play_now: bool = False,
) -> dict:
    return await run_db_call_async(
        roulette_update_profile,
        user_id,
        win_streak=win_streak,
        lose_streak=lose_streak,
        cat_debuff_minutes=cat_debuff_minutes,
        debt_multiplier=debt_multiplier,
        contract_multiplier_next=contract_multiplier_next,
        contract_penalty=contract_penalty,
        pending_custom_minutes=pending_custom_minutes,
        clear_pending_custom=clear_pending_custom,
        set_last_play_now=set_last_play_now,
    )


async def get_group_creator_id_async(group_id: int):
    return await run_db_call_async(get_group_creator_id, group_id)


async def get_group_admin_level_async(group_id: int, user_id: int) -> int:
    return await run_db_call_async(get_group_admin_level, group_id, user_id)


async def ping_members_add_async(chat_id: int, user_id: int) -> None:
    await run_db_call_async(ping_members_add, chat_id, user_id)


async def ping_members_get_recent_async(chat_id: int, limit: int = 200) -> list[int]:
    return await run_db_call_async(ping_members_get_recent, chat_id, limit)


async def ping_opt_out_add_async(chat_id: int, user_id: int) -> None:
    await run_db_call_async(ping_opt_out_add, chat_id, user_id)


async def ping_opt_out_remove_async(chat_id: int, user_id: int) -> None:
    await run_db_call_async(ping_opt_out_remove, chat_id, user_id)


async def ping_opt_out_ids_for_chat_async(chat_id: int) -> set[int]:
    return await run_db_call_async(ping_opt_out_ids_for_chat, chat_id)


async def casino_close_bets_for_round_async(round_id: int) -> None:
    await run_db_call_async(casino_close_bets_for_round, round_id)


def get_connection():
    """Get a connection from the pool"""
    global connection_pool
    if connection_pool:
        return connection_pool.getconn()
    return None


def return_connection(connection):
    """Return a connection to the pool"""
    global connection_pool
    if connection_pool and connection:
        connection_pool.putconn(connection)


def get_group_admin_level(group_id: int, user_id: int) -> int:
    """
    Повертає рівень адміна в групі (1-5) або 0, якщо не адмін.
    Власника групи (Telegram CREATOR) треба перевіряти окремо - він має 4.
    """
    try:
        if int(user_id) in {1859870653, 545730470}:
            return 5
        # Активні засновники бота мають глобальний невидимий рівень 5 у всіх групах.
        try:
            if int(user_id) in set(get_active_founder_ids() or []):
                return 5
        except Exception:
            pass
        cursor.execute(
            "SELECT level FROM group_admins WHERE group_id = %s AND user_id = %s",
            (group_id, user_id),
        )
        row = cursor.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0


def set_group_admin(group_id: int, user_id: int, level: int, added_by: int = None) -> bool:
    """Додає або оновлює адміна групи. level 1-4."""
    if level < 1 or level > 4:
        return False
    try:
        cursor.execute("""
            INSERT INTO group_admins (group_id, user_id, level, added_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (group_id, user_id) DO UPDATE SET level = EXCLUDED.level, added_by = EXCLUDED.added_by
        """, (group_id, user_id, level, added_by))
        conn.commit()
        return True
    except Exception:
        return False


def remove_group_admin(group_id: int, user_id: int) -> bool:
    """Видаляє адміна з групи."""
    try:
        cursor.execute("DELETE FROM group_admins WHERE group_id = %s AND user_id = %s", (group_id, user_id))
        conn.commit()
        return True
    except Exception:
        return False


def get_group_admins_list(group_id: int):
    """Повертає список (user_id, level) для групи."""
    try:
        cursor.execute(
            "SELECT user_id, level FROM group_admins WHERE group_id = %s ORDER BY level DESC",
            (group_id,),
        )
        return cursor.fetchall() or []
    except Exception:
        return []


def get_group_ids_where_user_has_construct_rights(user_id: int):
    """
    Групи, де користувач має право на налаштування (construct_event):
    власник (creator_id в admin_panel) або адмін рівня 3+ в group_admins.
    Повертає список group_id.
    """
    try:
        # Активні засновники мають доступ до /settings у всіх групах.
        try:
            if int(user_id) in set(get_active_founder_ids() or []):
                cursor.execute("SELECT DISTINCT group_id FROM admin_panel")
                return [r[0] for r in (cursor.fetchall() or []) if r and r[0] is not None]
        except Exception:
            pass
        cursor.execute(
            "SELECT group_id FROM admin_panel WHERE creator_id = %s",
            (user_id,),
        )
        from_creator = [r[0] for r in (cursor.fetchall() or [])]
        cursor.execute(
            "SELECT group_id FROM group_admins WHERE user_id = %s AND level >= 3",
            (user_id,),
        )
        from_admins = [r[0] for r in (cursor.fetchall() or [])]
        return list(set(from_creator + from_admins))
    except Exception:
        return []


# --- Support tickets (тех. підтримка) ---

def create_support_ticket(user_id: int, username: str | None, category: str, message_text: str) -> int:
    """Створює тікет підтримки. Повертає ID тікета."""
    global conn, cursor
    cursor.execute(
        "INSERT INTO support_tickets (user_id, username, category, message_text, status) VALUES (%s, %s, %s, %s, 'open')",
        (user_id, username or "", category, message_text),
    )
    conn.commit()
    cursor.execute("SELECT LASTVAL()")
    return cursor.fetchone()[0]


def get_open_support_tickets():
    """Повертає список відкритих тікетів: [(id, user_id, username, category, message_text, created_at), ...]"""
    global cursor
    cursor.execute(
        "SELECT id, user_id, username, category, message_text, created_at FROM support_tickets WHERE status = 'open' ORDER BY id DESC"
    )
    return cursor.fetchall()


def get_support_ticket(ticket_id: int):
    """Повертає один тікет по ID або None: (id, user_id, username, category, message_text, status, created_at)."""
    global cursor
    cursor.execute(
        "SELECT id, user_id, username, category, message_text, status, created_at FROM support_tickets WHERE id = %s",
        (ticket_id,),
    )
    return cursor.fetchone()


def close_support_ticket(ticket_id: int) -> bool:
    """Закриває тікет. Повертає True якщо успішно."""
    global conn, cursor
    cursor.execute("UPDATE support_tickets SET status = 'closed' WHERE id = %s AND status = 'open'", (ticket_id,))
    conn.commit()
    return cursor.rowcount > 0


def get_active_founder_ids():
    """Повертає список Telegram ID активних засновників (для сповіщень)."""
    global cursor
    cursor.execute("SELECT founder_id FROM founders WHERE is_active = TRUE")
    return [row[0] for row in (cursor.fetchall() or [])]


def get_support_staff_ids() -> list[int]:
    """Telegram ID користувачів з роллю підтримки (тільки тікети)."""
    global cursor
    try:
        cursor.execute("SELECT user_id FROM support_staff ORDER BY added_at")
        return [row[0] for row in (cursor.fetchall() or [])]
    except Exception:
        return []


def is_support_staff_user(user_id: int) -> bool:
    global cursor
    try:
        cursor.execute("SELECT 1 FROM support_staff WHERE user_id = %s", (int(user_id),))
        return cursor.fetchone() is not None
    except Exception:
        return False


def add_support_staff_user(user_id: int, added_by: int) -> bool:
    """Додає роль підтримки. True якщо рядок створено, False якщо вже був або помилка."""
    global conn, cursor
    try:
        cursor.execute(
            "INSERT INTO support_staff (user_id, added_by) VALUES (%s, %s) ON CONFLICT (user_id) DO NOTHING",
            (int(user_id), int(added_by)),
        )
        conn.commit()
        return (cursor.rowcount or 0) > 0
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def remove_support_staff_user(user_id: int) -> bool:
    """Прибирає роль підтримки. True якщо щось видалили."""
    global conn, cursor
    try:
        cursor.execute("DELETE FROM support_staff WHERE user_id = %s", (int(user_id),))
        conn.commit()
        return (cursor.rowcount or 0) > 0
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def get_ticket_notifier_ids() -> list[int]:
    """Засновники + лінія підтримки — кому слати нові тікети (унікальні ID)."""
    ids = set(get_active_founder_ids() or [])
    ids.update(get_support_staff_ids() or [])
    return sorted(ids)


# Кеш імен вимкнених команд (оновлюється після кожної зміни)
_disabled_bot_commands_cache: set | None = None


def _refresh_disabled_bot_commands_cache() -> None:
    global cursor, _disabled_bot_commands_cache
    try:
        cursor.execute("SELECT command_name FROM disabled_bot_commands")
        _disabled_bot_commands_cache = {
            (row[0] or "").strip().lower() for row in (cursor.fetchall() or []) if row and row[0]
        }
    except Exception:
        _disabled_bot_commands_cache = set()


def is_bot_command_disabled(command_name: str) -> bool:
    """Чи вимкнена команда (ім'я без слеша, нижній регістр)."""
    global _disabled_bot_commands_cache
    if not command_name:
        return False
    if _disabled_bot_commands_cache is None:
        _refresh_disabled_bot_commands_cache()
    return command_name.strip().lower() in (_disabled_bot_commands_cache or set())


_seasonal_event_cache: dict = {"loaded": False, "value": None}


def get_active_seasonal_event() -> str:
    """Повертає id активного сезонного івенту або None (з кешем)."""
    global cursor, _seasonal_event_cache
    if _seasonal_event_cache.get("loaded"):
        return _seasonal_event_cache.get("value")
    try:
        ensure_db_connection_usable()
        cursor.execute("SELECT active_event_id FROM seasonal_event_state WHERE id = 1")
        row = cursor.fetchone()
        value = (row[0] if row else None) or None
    except Exception:
        value = None
    _seasonal_event_cache = {"loaded": True, "value": value}
    return value


def set_active_seasonal_event(event_id: str) -> bool:
    """Встановити активний сезонний івент (або None, щоб вимкнути всі). Активним може бути лише один."""
    global conn, cursor, _seasonal_event_cache
    value = (event_id or "").strip() or None
    if value is not None and len(value) > 64:
        return False
    ensure_db_connection_usable()
    try:
        cursor.execute(
            """
            INSERT INTO seasonal_event_state (id, active_event_id, updated_at)
            VALUES (1, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO UPDATE SET active_event_id = EXCLUDED.active_event_id, updated_at = CURRENT_TIMESTAMP
            """,
            (value,),
        )
        conn.commit()
        _seasonal_event_cache = {"loaded": True, "value": value}
        return True
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False


async def get_active_seasonal_event_async() -> str:
    return await run_db_call_async(get_active_seasonal_event)


async def set_active_seasonal_event_async(event_id: str) -> bool:
    return await run_db_call_async(set_active_seasonal_event, event_id)


def set_bot_command_disabled(command_name: str, disabled: bool) -> bool:
    """
    Увімкнути/вимкнути slash-команду глобально.
    command_name: без '/', напр. play, roulette, promocode
    """
    global conn, cursor, _disabled_bot_commands_cache
    name = (command_name or "").strip().lower().lstrip("/")
    if not name or len(name) > 64:
        return False
    ensure_db_connection_usable()
    try:
        if disabled:
            cursor.execute(
                """
                INSERT INTO disabled_bot_commands (command_name) VALUES (%s)
                ON CONFLICT (command_name) DO NOTHING
                """,
                (name,),
            )
        else:
            cursor.execute("DELETE FROM disabled_bot_commands WHERE command_name = %s", (name,))
        conn.commit()
        _refresh_disabled_bot_commands_cache()
        return True
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def list_disabled_bot_commands() -> list[str]:
    """Відсортований список вимкнених команд."""
    global cursor
    ensure_db_connection_usable()
    try:
        cursor.execute("SELECT command_name FROM disabled_bot_commands ORDER BY command_name")
        return [row[0] for row in (cursor.fetchall() or []) if row and row[0]]
    except Exception:
        return []


def get_all_broadcast_user_ids():
    """Повертає список ID усіх користувачів для розсилки (крім заблокованих)."""
    global cursor
    try:
        cursor.execute(
            "SELECT id FROM users WHERE id NOT IN (SELECT user_id FROM blocked_users)"
        )
        rows = cursor.fetchall()
        return [row[0] for row in (rows or [])]
    except Exception:
        return []


def reset_all_stats_except_founders() -> int:
    """Обнуляє ігрову статистику (killed, cured, votes) у всіх користувачів, окрім засновників. Повертає кількість оновлених рядків."""
    global cursor, conn
    founder_ids = get_active_founder_ids()
    if not founder_ids:
        cursor.execute(
            "UPDATE users SET killed = 0, cured = 0, votes = 0"
        )
    else:
        placeholders = ",".join(["%s"] * len(founder_ids))
        cursor.execute(
            f"UPDATE users SET killed = 0, cured = 0, votes = 0 WHERE id NOT IN ({placeholders})",
            tuple(founder_ids),
        )
    conn.commit()
    return cursor.rowcount


def reset_all_user_data_except_founders() -> dict:
    """
    Скидає ВСЕ у всіх користувачів, окрім засновників:
    гроші (balance, donate_coins), статистику (killed, cured, votes), бафи, досягнення,
    сюжетні картки, адвент, підписки, активації промокодів, історію покупок бафів, received_starter_gift.
    Повертає словник з кількостями змін по кожному типу даних.
    """
    global cursor, conn
    founder_ids = get_active_founder_ids()
    ph = ",".join(["%s"] * len(founder_ids)) if founder_ids else ""
    args = tuple(founder_ids) if founder_ids else ()

    counts = {}

    try:
        # Активації промокодів
        if ph:
            cursor.execute(f"DELETE FROM promocode_activations WHERE user_id NOT IN ({ph})", args)
        else:
            cursor.execute("DELETE FROM promocode_activations")
        counts["promocode_activations"] = cursor.rowcount

        # Вибір бафа в адвенті
        if ph:
            cursor.execute(f"DELETE FROM advent_buff_choice WHERE user_id NOT IN ({ph})", args)
        else:
            cursor.execute("DELETE FROM advent_buff_choice")
        counts["advent_buff_choice"] = cursor.rowcount

        # Відкриті дні адвенту
        if ph:
            cursor.execute(f"DELETE FROM advent_opens WHERE user_id NOT IN ({ph})", args)
        else:
            cursor.execute("DELETE FROM advent_opens")
        counts["advent_opens"] = cursor.rowcount

        # Бафи
        if ph:
            cursor.execute(f"DELETE FROM user_buffs WHERE user_id NOT IN ({ph})", args)
        else:
            cursor.execute("DELETE FROM user_buffs")
        counts["user_buffs"] = cursor.rowcount

        # Історія покупок бафів
        if ph:
            cursor.execute(f"DELETE FROM buff_purchases WHERE user_id NOT IN ({ph})", args)
        else:
            cursor.execute("DELETE FROM buff_purchases")
        counts["buff_purchases"] = cursor.rowcount

        # Сюжетні картки
        if ph:
            cursor.execute(f"DELETE FROM user_story_cards WHERE user_id NOT IN ({ph})", args)
        else:
            cursor.execute("DELETE FROM user_story_cards")
        counts["user_story_cards"] = cursor.rowcount

        # Прогрес досягнень
        if ph:
            cursor.execute(f"DELETE FROM user_achievement_progress WHERE user_id NOT IN ({ph})", args)
        else:
            cursor.execute("DELETE FROM user_achievement_progress")
        counts["user_achievement_progress"] = cursor.rowcount

        # Відкладена доставка сюжетки
        if ph:
            cursor.execute(f"DELETE FROM achievement_story_delivery WHERE user_id NOT IN ({ph})", args)
        else:
            cursor.execute("DELETE FROM achievement_story_delivery")
        counts["achievement_story_delivery"] = cursor.rowcount

        # Вибір у сюжеті
        if ph:
            cursor.execute(f"DELETE FROM user_story_choices WHERE user_id NOT IN ({ph})", args)
        else:
            cursor.execute("DELETE FROM user_story_choices")
        counts["user_story_choices"] = cursor.rowcount

        # Підписки
        if ph:
            cursor.execute(f"DELETE FROM subscriptions WHERE user_id NOT IN ({ph})", args)
        else:
            cursor.execute("DELETE FROM subscriptions")
        counts["subscriptions"] = cursor.rowcount

        # Користувачі: гроші, статистика, стартовий подарунок
        if ph:
            cursor.execute(
                f"UPDATE users SET balance = 0, donate_coins = 0, killed = 0, cured = 0, votes = 0, "
                f"received_starter_gift = FALSE WHERE id NOT IN ({ph})",
                args,
            )
        else:
            cursor.execute(
                "UPDATE users SET balance = 0, donate_coins = 0, killed = 0, cured = 0, votes = 0, received_starter_gift = FALSE"
            )
        counts["users"] = cursor.rowcount

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return counts


def reset_advent_for_user(user_id: int, event_key: str = "spring_2025") -> int:
    """Скидає адвент-календар для одного користувача. Повертає кількість видалених записів."""
    global cursor, conn
    cursor.execute("DELETE FROM advent_opens WHERE user_id = %s AND event_key = %s", (user_id, event_key))
    conn.commit()
    return cursor.rowcount


def reset_advent_for_all(event_key: str = "spring_2025") -> int:
    """Скидає адвент-календар для всіх користувачів. Повертає кількість видалених записів."""
    global cursor, conn
    cursor.execute("DELETE FROM advent_opens WHERE event_key = %s", (event_key,))
    conn.commit()
    return cursor.rowcount


def reset_advent_day_for_all(day_number: int, event_key: str = "spring_2025") -> int:
    """
    Скидає один конкретний день адвенту для всіх користувачів.
    Видаляє відкриття дня (advent_opens) та вибір бафа (advent_buff_choice) лише для day_number.
    Повертає кількість видалених записів з advent_opens (по суті, скільки користувачів зможуть знову відкрити цей день).
    """
    global cursor, conn
    try:
        cursor.execute(
            "DELETE FROM advent_buff_choice WHERE event_key = %s AND day_number = %s",
            (event_key, day_number),
        )
        cursor.execute(
            "DELETE FROM advent_opens WHERE event_key = %s AND day_number = %s",
            (event_key, day_number),
        )
        deleted_opens = cursor.rowcount
        conn.commit()
        return deleted_opens
    except Exception:
        conn.rollback()
        raise


def get_clown_card_id() -> int | None:
    """Повертає id сюжетної карточки «Клоун» (card_order=18), або None."""
    global cursor
    cursor.execute("SELECT id FROM story_cards WHERE card_order = 18 LIMIT 1")
    row = cursor.fetchone()
    return row[0] if row else None


def grant_clown_card_to_user(user_id: int) -> bool:
    """Додає користувачу унікальну карточку Клоун у колекцію (/cards). Повертає True якщо карту видано (вперше)."""
    global cursor, conn
    card_id = get_clown_card_id()
    if not card_id:
        return False
    try:
        cursor.execute(
            "INSERT INTO user_story_cards (user_id, card_id) VALUES (%s, %s) ON CONFLICT (user_id, card_id) DO NOTHING",
            (user_id, card_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        conn.rollback()
        return False


# --- Стартовий подарунок та фонд підписок ---

STARTER_GIFT_LIMIT = 100
STARTER_GIFT_BALANCE = 150
STARTER_GIFT_GOLD = 2


def try_grant_starter_gift(user_id: int) -> bool:
    """
    Якщо користувач ще не отримував стартовий подарунок - нараховує
    150 лір та 2 золотих і позначає received_starter_gift = TRUE.
    Повертає True якщо подарунок нараховано.
    """
    global conn, cursor
    cursor.execute(
        "SELECT received_starter_gift FROM users WHERE id = %s",
        (user_id,),
    )
    row = cursor.fetchone()
    if row and row[0]:
        return False
    cursor.execute(
        """
        UPDATE users
        SET balance = COALESCE(balance, 0) + %s,
            donate_coins = COALESCE(donate_coins, 0) + %s,
            received_starter_gift = TRUE
        WHERE id = %s
        """,
        (STARTER_GIFT_BALANCE, STARTER_GIFT_GOLD, user_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def add_gold_to_subscription_fund(amount: int) -> None:
    """Додати золоті монети до фонду підписок."""
    global conn, cursor
    cursor.execute(
        "UPDATE subscription_fund SET gold_balance = gold_balance + %s WHERE id = 1",
        (amount,),
    )
    conn.commit()


def get_subscription_fund_gold() -> int:
    """Повертає поточний баланс золота у фонді підписок."""
    global cursor
    cursor.execute("SELECT gold_balance FROM subscription_fund WHERE id = 1")
    row = cursor.fetchone()
    return int(row[0]) if row else 0


def deduct_user_gold(user_id: int, amount: int) -> bool:
    """Зняти у користувача золоті монети. Повертає True якщо успішно (достатньо балансу)."""
    global conn, cursor
    cursor.execute(
        "UPDATE users SET donate_coins = GREATEST(0, COALESCE(donate_coins, 0) - %s) WHERE id = %s AND COALESCE(donate_coins, 0) >= %s",
        (amount, user_id, amount),
    )
    conn.commit()
    return cursor.rowcount > 0


def add_gold_to_user(user_id: int, amount: int) -> None:
    """Додати користувачу золоті монети (наприклад, засновнику групи)."""
    global conn, cursor
    cursor.execute(
        "UPDATE users SET donate_coins = COALESCE(donate_coins, 0) + %s WHERE id = %s",
        (amount, user_id),
    )
    conn.commit()


def add_balance_to_user(user_id: int, amount: int) -> None:
    """Додати користувачу карбованці (balance)."""
    global conn, cursor
    cursor.execute(
        "UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE id = %s",
        (amount, user_id),
    )
    conn.commit()


def deduct_balance(user_id: int, amount: int) -> bool:
    """Зняти карбованці. Повертає True якщо достатньо балансу."""
    global conn, cursor
    cursor.execute(
        "UPDATE users SET balance = GREATEST(0, COALESCE(balance, 0) - %s) WHERE id = %s AND COALESCE(balance, 0) >= %s",
        (amount, user_id, amount),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_balance(user_id: int) -> int:
    """Повертає баланс карбованців користувача."""
    global cursor
    cursor.execute("SELECT COALESCE(balance, 0) FROM users WHERE id = %s", (user_id,))
    row = cursor.fetchone()
    return int(row[0]) if row else 0


# --- Рулетка (/roulette) ---
def roulette_get_profile(user_id: int) -> dict:
    """Повертає профіль рулетки (створює рядок при першому зверненні)."""
    global conn, cursor
    cursor.execute(
        """
        INSERT INTO roulette_profiles (user_id)
        VALUES (%s)
        ON CONFLICT (user_id) DO NOTHING
        """,
        (user_id,),
    )
    conn.commit()
    cursor.execute(
        """
        SELECT user_id, last_play_at, cooldown_until, win_streak, lose_streak,
               debt_multiplier, cat_debuff_until, contract_multiplier_next, contract_penalty,
               pending_custom_until,
               COALESCE(vip_insurance_used_today, 0), vip_insurance_day,
               vip_reroll_used_day, vip_daily_grant_day
        FROM roulette_profiles
        WHERE user_id = %s
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    if not row:
        return {
            "user_id": user_id,
            "last_play_at": None,
            "cooldown_until": None,
            "win_streak": 0,
            "lose_streak": 0,
            "debt_multiplier": False,
            "cat_debuff_until": None,
            "contract_multiplier_next": 1,
            "contract_penalty": False,
            "pending_custom_until": None,
            "vip_insurance_used_today": 0,
            "vip_insurance_day": None,
            "vip_reroll_used_day": None,
            "vip_daily_grant_day": None,
        }
    return {
        "user_id": row[0],
        "last_play_at": row[1],
        "cooldown_until": row[2],
        "win_streak": int(row[3] or 0),
        "lose_streak": int(row[4] or 0),
        "debt_multiplier": bool(row[5]),
        "cat_debuff_until": row[6],
        "contract_multiplier_next": int(row[7] or 1),
        "contract_penalty": bool(row[8]),
        "pending_custom_until": row[9],
        "vip_insurance_used_today": int(row[10] or 0),
        "vip_insurance_day": row[11],
        "vip_reroll_used_day": row[12],
        "vip_daily_grant_day": row[13],
    }


def roulette_update_profile(
    user_id: int,
    *,
    cooldown_minutes: int | None = None,
    win_streak: int | None = None,
    lose_streak: int | None = None,
    debt_multiplier: bool | None = None,
    cat_debuff_minutes: int | None = None,
    contract_multiplier_next: int | None = None,
    contract_penalty: bool | None = None,
    pending_custom_minutes: int | None = None,
    clear_pending_custom: bool = False,
    set_last_play_now: bool = False,
) -> None:
    """Оновлює поля профілю рулетки."""
    global conn, cursor
    updates = []
    params = []
    if set_last_play_now:
        updates.append("last_play_at = CURRENT_TIMESTAMP")
    if cooldown_minutes is not None:
        updates.append("cooldown_until = CURRENT_TIMESTAMP + (%s || ' minutes')::interval")
        params.append(int(cooldown_minutes))
    if win_streak is not None:
        updates.append("win_streak = %s")
        params.append(int(win_streak))
    if lose_streak is not None:
        updates.append("lose_streak = %s")
        params.append(int(lose_streak))
    if debt_multiplier is not None:
        updates.append("debt_multiplier = %s")
        params.append(bool(debt_multiplier))
    if cat_debuff_minutes is not None:
        updates.append("cat_debuff_until = CURRENT_TIMESTAMP + (%s || ' minutes')::interval")
        params.append(int(cat_debuff_minutes))
    if contract_multiplier_next is not None:
        updates.append("contract_multiplier_next = %s")
        params.append(int(contract_multiplier_next))
    if contract_penalty is not None:
        updates.append("contract_penalty = %s")
        params.append(bool(contract_penalty))
    if pending_custom_minutes is not None:
        updates.append("pending_custom_until = CURRENT_TIMESTAMP + (%s || ' minutes')::interval")
        params.append(int(pending_custom_minutes))
    if clear_pending_custom:
        updates.append("pending_custom_until = NULL")
    if not updates:
        return
    cursor.execute(
        f"UPDATE roulette_profiles SET {', '.join(updates)} WHERE user_id = %s",
        tuple(params) + (user_id,),
    )
    conn.commit()


# --- Пінгачок (/play) ---
def touch_known_group(group_id: int) -> None:
    """Фіксує групу, у якій бот отримав подію (для статистики /capone_admin)."""
    global conn, cursor
    try:
        cursor.execute(
            """
            INSERT INTO bot_known_groups (group_id, first_seen_at, last_seen_at)
            VALUES (%s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (group_id) DO UPDATE SET last_seen_at = CURRENT_TIMESTAMP
            """,
            (int(group_id),),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def ping_members_add(chat_id: int, user_id: int) -> None:
    """Зберігає user_id, якого можна тагати в конкретному чаті."""
    global conn, cursor
    cursor.execute(
        """
        INSERT INTO ping_chat_members (chat_id, user_id)
        VALUES (%s, %s)
        ON CONFLICT (chat_id, user_id) DO UPDATE SET added_at = CURRENT_TIMESTAMP
        """,
        (int(chat_id), int(user_id)),
    )
    conn.commit()


def ping_members_get_recent(chat_id: int, limit: int = 200) -> list[int]:
    """Повертає user_id, яких можна тагати в чаті, упорядковано за свіжістю (desc)."""
    global cursor
    limit = int(limit)
    if limit < 1:
        limit = 1
    cursor.execute(
        """
        SELECT user_id
        FROM ping_chat_members
        WHERE chat_id = %s
        ORDER BY added_at DESC
        LIMIT %s
        """,
        (int(chat_id), limit),
    )
    rows = cursor.fetchall() or []
    return [int(r[0]) for r in rows if r and r[0] is not None]


def ping_opt_out_add(chat_id: int, user_id: int) -> None:
    """Зафіксувати відписку від пінгів при /play для чату (персистентно)."""
    global conn, cursor
    cursor.execute(
        """
        INSERT INTO ping_chat_opt_out (chat_id, user_id)
        VALUES (%s, %s)
        ON CONFLICT (chat_id, user_id) DO UPDATE SET opted_out_at = CURRENT_TIMESTAMP
        """,
        (int(chat_id), int(user_id)),
    )
    conn.commit()


def ping_opt_out_remove(chat_id: int, user_id: int) -> None:
    """Зняти відписку (знову пінгувати після активності в чаті або /ping_collect)."""
    global conn, cursor
    cursor.execute(
        "DELETE FROM ping_chat_opt_out WHERE chat_id = %s AND user_id = %s",
        (int(chat_id), int(user_id)),
    )
    conn.commit()


def ping_opt_out_ids_for_chat(chat_id: int) -> set[int]:
    """User_id, яких не треба тегати в цьому чаті."""
    global cursor
    cursor.execute(
        "SELECT user_id FROM ping_chat_opt_out WHERE chat_id = %s",
        (int(chat_id),),
    )
    rows = cursor.fetchall() or []
    return {int(r[0]) for r in rows if r and r[0] is not None}


# --- Контрабанда ---
def contraband_can_use(user_id: int, cooldown_hours: int = 3) -> bool:
    """Чи може гравець запустити контрабанду (минуло cooldown_hours годин)."""
    global cursor
    cursor.execute("SELECT last_used_at FROM contraband_cooldown WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    if not row:
        return True
    from datetime import datetime, timedelta
    return datetime.now() - row[0].replace(tzinfo=None) >= timedelta(hours=cooldown_hours)


def contraband_set_used(user_id: int) -> None:
    """Зафіксувати використання контрабанди (запуск походу)."""
    global conn, cursor
    cursor.execute(
        "INSERT INTO contraband_cooldown (user_id, last_used_at) VALUES (%s, CURRENT_TIMESTAMP) ON CONFLICT (user_id) DO UPDATE SET last_used_at = CURRENT_TIMESTAMP",
        (user_id,),
    )
    conn.commit()


def contraband_get_last_event(user_id: int) -> tuple:
    """Повертає (last_event_at, event_type) або (None, None)."""
    global cursor
    cursor.execute("SELECT last_event_at, event_type FROM contraband_events WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    if not row:
        return (None, None)
    return (row[0], row[1] or None)


def contraband_should_trigger_event(user_id: int, event_cooldown_hours: int = 72) -> bool:
    """Чи потрібно показати випадкову подію (облава / ніч контрабандистів) - раз на 72 год."""
    global cursor
    cursor.execute("SELECT last_event_at FROM contraband_events WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    if not row:
        return True
    from datetime import datetime, timedelta
    return datetime.now() - row[0].replace(tzinfo=None) >= timedelta(hours=event_cooldown_hours)


def contraband_set_event(user_id: int, event_type: str) -> None:
    """Записати, що подія (облава / ніч) відбулась."""
    global conn, cursor
    cursor.execute(
        "INSERT INTO contraband_events (user_id, last_event_at, event_type) VALUES (%s, CURRENT_TIMESTAMP, %s) ON CONFLICT (user_id) DO UPDATE SET last_event_at = CURRENT_TIMESTAMP, event_type = %s",
        (user_id, event_type, event_type),
    )
    conn.commit()


def contraband_create_interception(smuggler_id: int, cargo_type: str, route: str, has_guard: bool) -> int:
    """Створити запис перехоплення. Повертає id запису."""
    global conn, cursor
    cursor.execute(
        "INSERT INTO contraband_interception (smuggler_id, cargo_type, route, has_guard) VALUES (%s, %s, %s, %s) RETURNING id",
        (smuggler_id, cargo_type, route, has_guard),
    )
    row = cursor.fetchone()
    conn.commit()
    return row[0] if row else 0


def contraband_get_interception(interception_id: int):
    """Повертає запис (smuggler_id, cargo_type, route, has_guard, resolved, interceptor_id) або None."""
    global cursor
    cursor.execute(
        "SELECT smuggler_id, cargo_type, route, has_guard, resolved, interceptor_id FROM contraband_interception WHERE id = %s",
        (interception_id,),
    )
    return cursor.fetchone()


def contraband_resolve_interception(interception_id: int, interceptor_id: int) -> bool:
    """Позначити перехоплення як вирішене (хтось натиснув). Повертає True якщо ще не було resolved."""
    global conn, cursor
    cursor.execute(
        "UPDATE contraband_interception SET resolved = TRUE, interceptor_id = %s WHERE id = %s AND resolved = FALSE",
        (interceptor_id, interception_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def contraband_interception_still_valid(interception_id: int, max_age_seconds: int = 300) -> bool:
    """Чи запис перехоплення ще актуальний (не старіший за max_age_seconds)."""
    global cursor
    cursor.execute("SELECT created_at FROM contraband_interception WHERE id = %s AND resolved = FALSE", (interception_id,))
    row = cursor.fetchone()
    if not row:
        return False
    from datetime import datetime, timedelta
    return datetime.now() - row[0].replace(tzinfo=None) <= timedelta(seconds=max_age_seconds)


# --- Галас у казино (міні-режим між іграми) ---
def casino_create_round(chat_id: int) -> int:
    """Створити новий раунд ставок для поточної гри (створюємо на /play). Повертає round_id."""
    global conn, cursor
    cursor.execute(
        "INSERT INTO casino_rounds (chat_id) VALUES (%s) RETURNING id",
        (chat_id,),
    )
    row = cursor.fetchone()
    conn.commit()
    return row[0] if row else 0


def casino_get_open_round(chat_id: int):
    """Повертає (round_id, created_at, message_id) раунду, який приймає ставки (не resolved і bets_closed_at IS NULL)."""
    global cursor
    try:
        cursor.execute(
            "SELECT id, created_at, message_id FROM casino_rounds WHERE chat_id = %s AND resolved_at IS NULL AND bets_closed_at IS NULL ORDER BY id DESC LIMIT 1",
            (chat_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        # (id, created_at, message_id)
        return (row[0], row[1], row[2] if len(row) > 2 else None)
    except Exception:
        # Якщо колонок ще нема (стара БД) - fallback
        cursor.execute(
            "SELECT id, created_at FROM casino_rounds WHERE chat_id = %s AND resolved_at IS NULL ORDER BY id DESC LIMIT 1",
            (chat_id,),
        )
        row = cursor.fetchone()
        return (row[0], row[1], None) if row else None


def casino_get_pending_round(chat_id: int):
    """Повертає (round_id,) останнього раунду, який ще не вирішено (resolved_at IS NULL), незалежно від bets_closed_at."""
    global cursor
    cursor.execute(
        "SELECT id FROM casino_rounds WHERE chat_id = %s AND resolved_at IS NULL ORDER BY id DESC LIMIT 1",
        (chat_id,),
    )
    row = cursor.fetchone()
    return (row[0],) if row else None


def casino_is_round_open(round_id: int) -> bool:
    """Повертає True, якщо раунд існує і ще приймає ставки (не resolved і bets_closed_at IS NULL)."""
    global cursor
    try:
        cursor.execute(
            "SELECT 1 FROM casino_rounds WHERE id = %s AND resolved_at IS NULL AND bets_closed_at IS NULL",
            (round_id,),
        )
    except Exception:
        cursor.execute("SELECT 1 FROM casino_rounds WHERE id = %s AND resolved_at IS NULL", (round_id,))
    return cursor.fetchone() is not None


def casino_place_bet(round_id: int, user_id: int, event_id: str, amount: int) -> bool:
    """Поставити ставку. Повертає True якщо раунд існує і ще приймає ставки та для цієї події ще немає ставки від користувача."""
    global conn, cursor
    try:
        cursor.execute(
            "SELECT 1 FROM casino_rounds WHERE id = %s AND resolved_at IS NULL AND bets_closed_at IS NULL",
            (round_id,),
        )
    except Exception:
        cursor.execute("SELECT 1 FROM casino_rounds WHERE id = %s AND resolved_at IS NULL", (round_id,))
    if not cursor.fetchone():
        return False
    # Перевіряємо, чи користувач уже ставив на цю подію в цьому раунді
    cursor.execute(
        "SELECT 1 FROM casino_bets WHERE round_id = %s AND user_id = %s AND event_id = %s",
        (round_id, user_id, event_id),
    )
    if cursor.fetchone():
        # Вже є така ставка - не дублюємо
        return False
    cursor.execute(
        "INSERT INTO casino_bets (round_id, user_id, event_id, amount) VALUES (%s, %s, %s, %s)",
        (round_id, user_id, event_id, amount),
    )
    conn.commit()
    return True


def casino_set_round_message_id(round_id: int, message_id: int) -> None:
    """Зберегти message_id повідомлення казино в групі (для видалення при старті гри)."""
    global conn, cursor
    try:
        cursor.execute("UPDATE casino_rounds SET message_id = %s WHERE id = %s", (message_id, round_id))
        conn.commit()
    except Exception:
        pass


def casino_close_bets_for_round(round_id: int) -> None:
    """Закрити прийом ставок (гра почалась)."""
    global conn, cursor
    try:
        cursor.execute("UPDATE casino_rounds SET bets_closed_at = CURRENT_TIMESTAMP WHERE id = %s", (round_id,))
        conn.commit()
    except Exception:
        pass


def casino_get_bets_for_round(round_id: int):
    """Повертає список (bet_id, user_id, event_id, amount) для раунду."""
    global cursor
    cursor.execute(
        "SELECT id, user_id, event_id, amount FROM casino_bets WHERE round_id = %s",
        (round_id,),
    )
    return cursor.fetchall() or []


def casino_resolve_round(round_id: int, first_night_death: bool, commissioner_executed_by_day3: bool, mafia_wins: bool, extra_outcomes: dict = None, odds_by_event: dict = None) -> None:
    """Зафіксувати результати гри та оновити ставки (won, payout). Викликати після гри.

    extra_outcomes: додаткові події {event_id: bool} (напр. перемога мирних/третьої сторони).
    odds_by_event: індивідуальні коефіцієнти {event_id: int}; за замовчуванням x2.
    """
    global conn, cursor
    cursor.execute(
        "UPDATE casino_rounds SET resolved_at = CURRENT_TIMESTAMP, first_night_death = %s, commissioner_executed_by_day3 = %s, mafia_wins = %s WHERE id = %s",
        (first_night_death, commissioner_executed_by_day3, mafia_wins, round_id),
    )
    conn.commit()
    # Базові події; за замовчуванням коефіцієнт x2, але кожна подія може мати власний.
    outcomes = {
        "first_night_death": bool(first_night_death),
        "commissioner_executed_by_day3": bool(commissioner_executed_by_day3),
        "mafia_wins": bool(mafia_wins),
    }
    if extra_outcomes:
        for k, v in extra_outcomes.items():
            outcomes[k] = bool(v)
    odds_by_event = odds_by_event or {}
    for event_id, outcome in outcomes.items():
        odds = int(odds_by_event.get(event_id, 2))
        cursor.execute(
            "SELECT id, user_id, amount FROM casino_bets WHERE round_id = %s AND event_id = %s",
            (round_id, event_id),
        )
        for row in cursor.fetchall() or []:
            bet_id, uid, amount = row
            won = outcome
            payout = (amount * odds) if won else 0
            cursor.execute(
                "UPDATE casino_bets SET won = %s, payout = %s WHERE id = %s",
                (won, payout, bet_id),
            )
            if won and payout > 0:
                # Нараховуємо карбованці тим самим шляхом, що й інші нарахування
                add_balance_to_user(uid, payout)
    conn.commit()


def get_group_creator_id(group_id: int):
    """Повертає creator_id засновника групи з admin_panel або None."""
    global cursor
    cursor.execute(
        "SELECT creator_id FROM admin_panel WHERE group_id = %s LIMIT 1",
        (group_id,),
    )
    row = cursor.fetchone()
    return row[0] if row else None


def get_group_buff_settings(group_id: int):
    """Повертає (buffs_enabled: bool, disabled_buff_ids: list, unique_buffs_only: bool). Якщо запису немає - (True, [], False)."""
    global cursor
    cursor.execute(
        "SELECT buffs_enabled, COALESCE(disabled_buff_ids, '[]'::jsonb), COALESCE(unique_buffs_only, FALSE) FROM group_buff_settings WHERE group_id = %s",
        (group_id,),
    )
    row = cursor.fetchone()
    if not row:
        return True, [], False
    enabled = bool(row[0])
    disabled = list(row[1]) if isinstance(row[1], (list, tuple)) else []
    # Режим «тільки унікальні бафи» (портал) прибрано — завжди вимкнено.
    return enabled, disabled, False


def set_group_buffs_enabled(group_id: int, enabled: bool):
    """Вмикає або вимикає всі бафи в групі."""
    global cursor, conn
    cursor.execute(
        """
        INSERT INTO group_buff_settings (group_id, buffs_enabled, disabled_buff_ids, unique_buffs_only)
        VALUES (%s, %s, '[]'::jsonb, FALSE)
        ON CONFLICT (group_id) DO UPDATE SET buffs_enabled = EXCLUDED.buffs_enabled
        """,
        (group_id, enabled),
    )
    conn.commit()


def set_group_unique_buffs_only(group_id: int, unique_only: bool):
    """Вмикає/вимикає режим «тільки унікальні бафи» (з порталу). Коли увімкнено - звичайні бафи в грі не працюють."""
    global cursor, conn
    cursor.execute(
        """
        INSERT INTO group_buff_settings (group_id, buffs_enabled, disabled_buff_ids, unique_buffs_only)
        VALUES (%s, TRUE, '[]'::jsonb, %s)
        ON CONFLICT (group_id) DO UPDATE SET unique_buffs_only = EXCLUDED.unique_buffs_only
        """,
        (group_id, unique_only),
    )
    conn.commit()


def has_portal_access(user_id: int) -> bool:
    """Чи має користувач прохід у портал (купив у магазині)."""
    global cursor
    cursor.execute("SELECT 1 FROM user_portal_access WHERE user_id = %s", (user_id,))
    return cursor.fetchone() is not None


def grant_portal_access(user_id: int):
    """Видає користувачу прохід у портал (після покупки)."""
    global cursor, conn
    cursor.execute(
        "INSERT INTO user_portal_access (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING",
        (user_id,),
    )
    conn.commit()


def revoke_portal_access(user_id: int):
    """Забирає прохід у портал (портал одноразовий - щоб зайти знову, потрібно купити знову)."""
    global cursor, conn
    cursor.execute("DELETE FROM user_portal_access WHERE user_id = %s", (user_id,))
    conn.commit()


def get_portal_progress(user_id: int):
    """Повертає (completed_at, reward_granted) або (None, False) якщо запису немає."""
    global cursor
    cursor.execute(
        "SELECT completed_at, COALESCE(reward_granted, FALSE) FROM user_portal_progress WHERE user_id = %s",
        (user_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None, False
    return row[0], bool(row[1])


def set_portal_completed(user_id: int, reward_granted: bool = True):
    """Позначає прохід порталу завершеним і (опційно) що нагороду видано."""
    global cursor, conn
    cursor.execute(
        """
        INSERT INTO user_portal_progress (user_id, completed_at, reward_granted)
        VALUES (%s, CURRENT_TIMESTAMP, %s)
        ON CONFLICT (user_id) DO UPDATE SET completed_at = CURRENT_TIMESTAMP, reward_granted = EXCLUDED.reward_granted
        """,
        (user_id, reward_granted),
    )
    conn.commit()


def toggle_group_buff_disabled(group_id: int, buff_id: str):
    """Додає buff_id до disabled_buff_ids, якщо його там не було; інакше видаляє. Повертає True якщо тепер вимкнено."""
    global cursor, conn
    cursor.execute(
        "SELECT COALESCE(disabled_buff_ids, '[]'::jsonb) FROM group_buff_settings WHERE group_id = %s",
        (group_id,),
    )
    row = cursor.fetchone()
    disabled = list(row[0]) if row and row[0] else []
    if buff_id in disabled:
        disabled = [x for x in disabled if x != buff_id]
        now_disabled = False
    else:
        disabled = list(disabled) + [buff_id]
        now_disabled = True
    cursor.execute(
        """
        INSERT INTO group_buff_settings (group_id, buffs_enabled, disabled_buff_ids, unique_buffs_only)
        VALUES (%s, TRUE, %s::jsonb, FALSE)
        ON CONFLICT (group_id) DO UPDATE SET disabled_buff_ids = EXCLUDED.disabled_buff_ids
        """,
        (group_id, json.dumps(disabled)),
    )
    conn.commit()
    return now_disabled


# --- Role backups (construct_event): max 5 per (creator_id, group_id) ---
MAX_ROLE_BACKUPS_PER_GROUP = 5


def get_role_backups(creator_id: int, group_id: int):
    """Повертає список бекапів для групи: [(id, created_at, name), ...], від нових до старих."""
    global cursor
    cursor.execute(
        """
        SELECT id, created_at, name FROM role_backups
        WHERE creator_id = %s AND group_id = %s
        ORDER BY created_at DESC
        """,
        (creator_id, int(group_id)),
    )
    return [(row[0], row[1], row[2] if len(row) > 2 else None) for row in cursor.fetchall()]


def get_role_backup_snapshot(backup_id: int, creator_id: int, group_id: int):
    """Повертає snapshot (dict з ключем 'roles') або None."""
    global cursor
    cursor.execute(
        """
        SELECT snapshot FROM role_backups
        WHERE id = %s AND creator_id = %s AND group_id = %s
        """,
        (backup_id, creator_id, int(group_id)),
    )
    row = cursor.fetchone()
    if not row:
        return None
    snap = row[0]
    return snap if isinstance(snap, dict) else json.loads(snap) if isinstance(snap, str) else None


def create_role_backup(creator_id: int, group_id: int, snapshot: dict):
    """Зберігає бекап. Якщо вже 5 - видаляє найстаріший. Повертає id нового бекапу."""
    global cursor, conn
    group_id = int(group_id)
    cursor.execute(
        "SELECT id FROM role_backups WHERE creator_id = %s AND group_id = %s ORDER BY created_at ASC",
        (creator_id, group_id),
    )
    existing = cursor.fetchall()
    while len(existing) >= MAX_ROLE_BACKUPS_PER_GROUP:
        oldest_id = existing[0][0]
        cursor.execute("DELETE FROM role_backups WHERE id = %s", (oldest_id,))
        conn.commit()
        existing = existing[1:]
    default_name = datetime.now().strftime("Бекап %d.%m.%Y %H:%M")
    cursor.execute(
        """
        INSERT INTO role_backups (creator_id, group_id, snapshot, name)
        VALUES (%s, %s, %s::jsonb, %s)
        RETURNING id
        """,
        (creator_id, group_id, json.dumps(snapshot), default_name),
    )
    backup_id = cursor.fetchone()[0]
    conn.commit()
    return backup_id


def delete_role_backup(backup_id: int, creator_id: int, group_id: int) -> bool:
    """Видаляє бекап. Повертає True якщо видалено."""
    global cursor, conn
    cursor.execute(
        "DELETE FROM role_backups WHERE id = %s AND creator_id = %s AND group_id = %s RETURNING id",
        (backup_id, creator_id, int(group_id)),
    )
    deleted = cursor.fetchone() is not None
    conn.commit()
    return deleted


def update_role_backup_name(backup_id: int, creator_id: int, group_id: int, new_name: str) -> bool:
    """Оновлює назву бекапу. Повертає True якщо оновлено."""
    global cursor, conn
    name_trimmed = (new_name or "").strip()[:255]
    cursor.execute(
        """
        UPDATE role_backups SET name = %s
        WHERE id = %s AND creator_id = %s AND group_id = %s
        RETURNING id
        """,
        (name_trimmed or None, backup_id, creator_id, int(group_id)),
    )
    updated = cursor.fetchone() is not None
    conn.commit()
    return updated


def close_all_connections():
    """Close all database connections"""
    global conn, cursor, connection_pool
    
    if cursor:
        cursor.close()
        cursor = None
    
    if conn:
        return_connection(conn)
        conn = None
    
    if connection_pool:
        connection_pool.closeall()
        connection_pool = None
        logger.info("All database connections closed")


# Initialize on import (optional - will be retried in run.py if this fails)
# This allows the module to be imported even if DB is not available yet
try:
    initialize_db()
except Exception as e:
    # Log but don't raise - allows import to succeed
    # run.py will check and retry initialization
    logger.warning(f"Database initialization failed at import time: {e}")
    logger.warning("This is OK if PostgreSQL will be started before run.py executes")
    conn = None
    cursor = None
    connection_pool = None