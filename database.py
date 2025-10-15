# database.py — Простая SQLite-база для KukkiDo
from __future__ import annotations
import os, datetime as dt
from typing import Dict, Any, List, Optional
import sqlite3 as sql

# Используем in-memory DB для тестов, иначе файл
DB_PATH = os.getenv("DB_PATH", os.path.join(os.getenv("DATA_DIR", "./data"), "kukkido.db"))
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# 🌟 Глобальная блокировка для работы с SQLite
_LOCK = threading.RLock()
# Хранилище подключений (чтобы не открывать/закрывать постоянно)
_CONN: Optional[sql.Connection] = None


# --- ИНИЦИАЛИЗАЦИЯ И ПОДКЛЮЧЕНИЕ ---
def _get_conn() -> sql.Connection:
    global _CONN
    if _CONN is None:
        _CONN = sql.connect(DB_PATH, check_same_thread=False)
        _CONN.row_factory = sql.Row  # чтобы возвращал словарь (dict)
    return _CONN


def load_profiles():
    # Эта функция теперь просто проверяет схему, т.к. данные загружаются по требованию
    _init_db()


def _init_db():
    conn = _get_conn()
    c = conn.cursor()

    # 1. Таблица профилей (profiles)
    c.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            user_id TEXT PRIMARY KEY,
            role TEXT DEFAULT 'athlete',
            age INTEGER,
            height REAL,
            weight REAL,
            notes TEXT
        )
    """)

    # 2. Таблица логов (logs)
    c.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            dt TEXT,
            type TEXT,
            params TEXT,
            plan TEXT,
            FOREIGN KEY(user_id) REFERENCES profiles(user_id)
        )
    """)

    # 3. Таблица шаблонов (templates)
    c.execute("""
        CREATE TABLE IF NOT EXISTS templates (
            user_id TEXT,
            name TEXT,
            plan TEXT,
            params TEXT,
            created TEXT,
            PRIMARY KEY (user_id, name),
            FOREIGN KEY(user_id) REFERENCES profiles(user_id)
        )
    """)
    conn.commit()


# --- ПРОФИЛИ ---
def get_or_create_profile(user_id: int) -> Dict[str, Any]:
    uid = str(user_id)
    with _LOCK:
        conn = _get_conn()
        row = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (uid,)).fetchone()
        if row:
            # Преобразуем Row в Dict, удаляем None
            d = dict(row)
            d.pop('notes')  # Скрываем notes
            return {k: v for k, v in d.items() if v is not None}

        # Если профиля нет, создаем
        default = {"user_id": uid, "role": "athlete", "age": 0, "height": 0, "weight": 0.0, "notes": "{}"}
        conn.execute("INSERT INTO profiles (user_id, role) VALUES (?, ?)", (uid, default['role']))
        conn.commit()
        return {k: v for k, v in default.items() if k != 'notes'}  # Возвращаем без notes


def update_profile(user_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
    uid = str(user_id)
    with _LOCK:
        conn = _get_conn()

        # Обновляем только разрешенные поля
        set_parts = []
        values = []

        for k, v in data.items():
            if k in ['role', 'age', 'height', 'weight']:
                set_parts.append(f"{k} = ?")
                values.append(v)
            # notes - это отдельное поле, которое может быть JSON-строкой
            # if k == 'notes':
            #     set_parts.append(f"{k} = ?")
            #     values.append(json.dumps(v, ensure_ascii=False))

        if not set_parts:
            return get_or_create_profile(user_id)

        values.append(uid)
        sql_update = f"UPDATE profiles SET {', '.join(set_parts)} WHERE user_id = ?"
        conn.execute(sql_update, tuple(values))
        conn.commit()

        return get_or_create_profile(user_id)


# --- ЛОГИ ---
def add_log_entry(user_id: int, entry: Dict[str, Any]) -> None:
    uid = str(user_id)
    with _LOCK:
        conn = _get_conn()
        dt_str = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

        # Преобразование plan и params в JSON-строки для хранения
        plan = entry.get("plan", "")
        params = json.dumps(entry.get("params", {}), ensure_ascii=False)
        log_type = entry.get("type", "unknown")

        conn.execute("""
            INSERT INTO logs (user_id, dt, type, params, plan)
            VALUES (?, ?, ?, ?, ?)
        """, (uid, dt_str, log_type, params, plan))

        conn.commit()

        # Очистка старых логов (оставляем только последние 500 для каждого пользователя)
        conn.execute("""
            DELETE FROM logs WHERE id NOT IN (
                SELECT id FROM logs WHERE user_id = ? ORDER BY id DESC LIMIT 500
            ) AND user_id = ?
        """, (uid, uid))
        conn.commit()


def get_logs(user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    uid = str(user_id)
    with _LOCK:
        conn = _get_conn()
        cursor = conn.execute("""
            SELECT dt, type, params, plan FROM logs 
            WHERE user_id = ? 
            ORDER BY id DESC 
            LIMIT ?
        """, (uid, limit))

        logs = []
        for row in cursor.fetchall():
            d = dict(row)
            # Обратное преобразование JSON-строки в Dict
            try:
                d['params'] = json.loads(d['params'])
            except:
                d['params'] = {}
            logs.append(d)

        return logs


# ---- шаблоны тренера ----
def save_template(user_id: int, name: str, plan_text: str, params: Dict[str, Any]) -> None:
    uid = str(user_id)
    with _LOCK:
        conn = _get_conn()
        created_dt = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

        # Преобразование params в JSON-строку
        params_json = json.dumps(params, ensure_ascii=False)

        conn.execute("""
            INSERT OR REPLACE INTO templates (user_id, name, plan, params, created)
            VALUES (?, ?, ?, ?, ?)
        """, (uid, name, plan_text, params_json, created_dt))

        conn.commit()


def list_templates(user_id: int) -> List[Dict[str, Any]]:
    uid = str(user_id)
    with _LOCK:
        conn = _get_conn()
        cursor = conn.execute("""
            SELECT name, plan, params, created FROM templates 
            WHERE user_id = ? 
            ORDER BY created DESC
        """, (uid,))

        templates = []
        for row in cursor.fetchall():
            d = dict(row)
            # Обратное преобразование JSON-строки в Dict
            try:
                d['params'] = json.loads(d['params'])
            except:
                d['params'] = {}
            templates.append(d)

        return templates


# Инициализируем базу данных при первом запуске
_init_db()