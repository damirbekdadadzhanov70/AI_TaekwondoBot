# database.py — профили (с персистентностью в JSON) и библиотека техник

from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any

# ------------ файл для хранения профилей ------------
DB_FILE = Path("profiles.json")

# Внутренняя БД (ключи — строки user_id, чтобы не путаться при JSON)
USER_PROFILES: Dict[str, Dict[str, Any]] = {}

# Профиль по умолчанию
DEFAULT_PROFILE = {
    "role": None,     # 'athlete' или 'coach'
    "age": None,
    "height": None,
    "weight": None,
    "notes": {}            # зарезервировано под дневник
}


# ------------ персистентность ------------
def _key(uid: int | str) -> str:
    return str(uid)

def load_profiles() -> None:
    """Загружаем профили из файла при старте бота."""
    global USER_PROFILES
    if DB_FILE.exists():
        try:
            data = json.loads(DB_FILE.read_text(encoding="utf-8"))
            # гарантируем словарь словарей
            if isinstance(data, dict):
                USER_PROFILES = {str(k): (v if isinstance(v, dict) else {}) for k, v in data.items()}
            else:
                USER_PROFILES = {}
        except Exception:
            USER_PROFILES = {}
    else:
        USER_PROFILES = {}

def save_profiles() -> None:
    """Сохраняем профили на диск после изменений."""
    try:
        data_to_save = json.dumps(USER_PROFILES, ensure_ascii=False, indent=2)
        DB_FILE.write_text(
            data_to_save,
            encoding="utf-8"
        )
    except Exception as e: # <-- Теперь мы увидим ошибку
        # Используем встроенное логирование Python, чтобы увидеть ошибку в консоли
        import logging
        logging.getLogger("AI_TaekwondoBot").error(f"Ошибка сохранения профилей: {e}")


# ------------ API профилей ------------
def get_or_create_profile(user_id: int | str) -> Dict[str, Any]:
    uid = _key(user_id)
    if uid not in USER_PROFILES:
        USER_PROFILES[uid] = DEFAULT_PROFILE.copy()
        save_profiles()
    return USER_PROFILES[uid]

def update_profile(user_id: int | str, **kwargs) -> Dict[str, Any]:
    uid = _key(user_id)
    prof = get_or_create_profile(uid)
    prof.update(kwargs)
    USER_PROFILES[uid] = prof
    save_profiles()
    return prof


# ------------ библиотека техник (примерные ссылки) ------------
TECHNIQUE_LIBRARY = {
    "Ap Chagi": {
        "ru": "Прямой удар ногой",
        "link": "https://files.catbox.moe/2j3p1m.mp4"   # замените на свои mp4/gif
    },
    "Dollyo Chagi": {
        "ru": "Круговой удар ногой",
        "link": "https://files.catbox.moe/q8qk9s.mp4"
    },
    "Momtong Makgi": {
        "ru": "Средний блок",
        "link": "https://files.catbox.moe/5r1y9m.mp4"
    }
    # Добавляйте свои техники
}

def attach_visuals(text: str) -> str:
    """Находит корейские термины в тексте и дописывает рядом ссылку на видео."""
    if not text:
        return text
    processed = text
    for term, data in TECHNIQUE_LIBRARY.items():
        if term in processed:
            link_md = f" ([Смотреть {data['ru']}]({data['link']}))"
            processed = processed.replace(term, term + link_md)
    return processed