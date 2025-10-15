# database.py — Простая SQLite-база для KukkiDo
from __future__ import annotations
import os, datetime as dt, json
from typing import Dict, Any, List, Optional
import sqlite3 as sql
import threading

# Используем in-memory DB для тестов, иначе файл
DB_PATH = os.getenv("DB_PATH", os.path.join(os.getenv("DATA_DIR", "./data"), "kukkido.db"))
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# Глобальная блокировка для работы с SQLite
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
            role TEXT DEFAULT 'coach', -- Теперь role всегда присутствует
            age INTEGER,
            height INTEGER,
            weight REAL,
            notes TEXT
        )
    """)

    # 2. Таблица логов (history)
    c.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            timestamp TEXT,
            type TEXT, -- 'plan', 'template_save', etc.
            data TEXT -- JSON-строка параметров
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
            PRIMARY KEY (user_id, name) -- Уникальное имя для каждого пользователя
        )
    """)

    # 4. Обновление схемы, если нужно (например, чтобы добавить role старым пользователям,
    # которые были созданы до исправления, хотя это лучше делать миграцией)
    # Сейчас полагаемся на то, что новая логика в get_or_create_profile исправит это при первом обращении.

    conn.commit()


def get_or_create_profile(user_id: int) -> Dict[str, Any]:
    uid = str(user_id)
    with _LOCK:
        conn = _get_conn()

        # 1. Попытка найти существующий профиль
        cursor = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (uid,))
        row = cursor.fetchone()

        if row:
            # Профиль найден
            d = dict(row)
            # 🌟 ДОБАВЛЕНА ПРОВЕРКА: Если роль по какой-то причине отсутствует в старой записи,
            # устанавливаем 'coach' по умолчанию
            if 'role' not in d or d['role'] is None:
                d['role'] = 'coach'
                # Можно было бы и обновить БД, но для простоты просто возвращаем исправленный словарь

            d['notes'] = json.loads(d['notes'])  # Обратное преобразование JSON-строки
            return d
        else:
            # 2. Профиль не найден, создаем новый
            default_profile = {
                'user_id': uid,
                'role': 'coach',  # <--- КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ: Установка role по умолчанию
                'age': 0,
                'height': 0,
                'weight': 0.0,
                'notes': json.dumps({})  # Пустой JSON для notes
            }

            # Вставляем новый профиль
            conn.execute("""
                INSERT INTO profiles (user_id, role, age, height, weight, notes)
                VALUES (:user_id, :role, :age, :height, :weight, :notes)
            """, default_profile)
            conn.commit()

            # Возвращаем созданный профиль
            return {
                'user_id': uid,
                'role': 'coach',
                'age': 0,
                'height': 0,
                'weight': 0.0,
                'notes': {}
            }


def update_profile(user_id: int, data: Dict[str, Any]) -> None:
    uid = str(user_id)
    with _LOCK:
        conn = _get_conn()

        # Подготовка данных
        notes_json = json.dumps(data.get('notes', {}), ensure_ascii=False)

        conn.execute("""
            UPDATE profiles SET
            role = ?,
            age = ?,
            height = ?,
            weight = ?,
            notes = ?
            WHERE user_id = ?
        """, (
            data.get('role', 'coach'),
            data.get('age', 0),
            data.get('height', 0),
            data.get('weight', 0.0),
            notes_json,
            uid
        ))
        conn.commit()


# ---- Логирование (история) ----
def add_log_entry(user_id: int, data: Dict[str, Any]) -> None:
    uid = str(user_id)
    with _LOCK:
        conn = _get_conn()
        timestamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

        # Преобразование данных в JSON-строку
        data_json = json.dumps(data, ensure_ascii=False)

        conn.execute("""
            INSERT INTO history (user_id, timestamp, type, data)
            VALUES (?, ?, ?, ?)
        """, (uid, timestamp, data.get('type', 'unknown'), data_json))

        conn.commit()


def get_logs(user_id: int, limit: int) -> List[Dict[str, Any]]:
    uid = str(user_id)
    with _LOCK:
        conn = _get_conn()
        cursor = conn.execute("""
            SELECT timestamp, type, data FROM history 
            WHERE user_id = ? 
            ORDER BY timestamp DESC
            LIMIT ?
        """, (uid, limit))

        logs = []
        for row in cursor.fetchall():
            d = dict(row)
            # Обратное преобразование JSON-строки в Dict
            try:
                d['data'] = json.loads(d['data'])
            except:
                d['data'] = {}
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


# Вызываем инициализацию, чтобы создать таблицу при старте
_init_db()
