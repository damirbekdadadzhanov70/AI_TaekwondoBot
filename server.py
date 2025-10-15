# server.py — FastAPI backend for KukkiDo Mini-App (coach mode inside WebApp)
from __future__ import annotations
import json, re, random, datetime as dt, hmac, hashlib
from typing import Dict, Any, List, Optional
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import OPENAI_API_KEY, MODEL_NAME, TEMPERATURE, SECRET_TOKEN_PART, WEBAPP_PROFILE_URL
from database import (
    get_or_create_profile, update_profile,
    add_log_entry, list_templates, save_template, get_logs,
)
import openai
from openai import OpenAI

# Инициализация OpenAI
openai_client = None
if OPENAI_API_KEY:
    try:
        openai_client = OpenAI(api_key=OPENAI_API_KEY)
    except Exception as e:
        print(f"[ERROR] Не удалось инициализировать OpenAI: {e}")
        openai_client = None

# --- Инициализация FastAPI ---
app = FastAPI(title="KukkiDo AI Coach API")

# Разрешаем CORS для WebApp и локальной разработки
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*", WEBAPP_PROFILE_URL],  # Замените * на домен вашего WebApp в продакшене
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Вспомогательные функции аутентификации ---
def verify_init_data(init_data: str) -> Optional[Dict[str, Any]]:
    if not SECRET_TOKEN_PART:
        print("[ERROR] SECRET_TOKEN_PART не найден. Аутентификация невозможна.")
        return None

    # Разбираем строку initData
    params = parse_qs(init_data)

    # 1. Извлекаем и удаляем 'hash'
    hash_list = params.pop('hash', [None])
    hash_str = hash_list[0]
    if not hash_str:
        return None

    # 2. Создаем строку данных для проверки (сортируем ключи)
    data_check_list = []
    for key in sorted(params.keys()):
        # Значения приходят как список, берем первый элемент
        value = params[key][0]
        data_check_list.append(f"{key}={value}")

    data_check_string = "\n".join(data_check_list)

    # 3. Вычисляем секретный ключ (HMAC-SHA256)
    secret_key = hmac.new(
        key=b'WebAppData',
        msg=SECRET_TOKEN_PART.encode('utf-8'),
        digestmod=hashlib.sha256
    ).digest()

    # 4. Вычисляем хеш данных
    calculated_hash = hmac.new(
        key=secret_key,
        msg=data_check_string.encode('utf-8'),
        digestmod=hashlib.sha256
    ).hexdigest()

    # 5. Сравниваем
    if calculated_hash == hash_str:
        # Аутентификация успешна, возвращаем разобранные параметры (включая user)
        # Для удобства, вернем user как словарь
        if 'user' in params:
            try:
                user_data = json.loads(params['user'][0])
                params['user'] = user_data
            except:
                pass  # Пропускаем, если user невалидный JSON

        return params

    return None


def _get_user_id_from_auth(init_data: str) -> int:
    """Проверяет init_data и возвращает user_id."""
    auth_data = verify_init_data(init_data)
    if not auth_data:
        raise HTTPException(401, "Невалидные или отсутствующие данные аутентификации.")

    # Извлекаем ID из поля 'user'
    user_data = auth_data.get('user')
    if not isinstance(user_data, dict) or 'id' not in user_data:
        raise HTTPException(401, "Данные пользователя (ID) отсутствуют или невалидны.")

    try:
        user_id = int(user_data['id'])
        return user_id
    except ValueError:
        raise HTTPException(401, "Неверный формат ID пользователя.")


# --- Модели данных Pydantic ---

class PlanRequest(BaseModel):
    init_data: str
    age_band: str
    group_size: int
    goal: str  # Основное развиваемое качество (ТФК)
    duration: int
    location: str
    inventory: bool
    inventory_list: List[str]
    # 🌟 НОВОЕ: Добавляем поле для дополнительных комментариев
    additional_comments: str = ""


class SaveTemplateRequest(BaseModel):
    init_data: str
    name: str
    plan: str
    params: Dict[str, Any]


class UpdateProfileRequest(BaseModel):
    init_data: str
    role: str
    age: int
    height: int
    weight: float
    notes: Dict[str, Any]


# --- Вспомогательные функции генерации ---

def _get_gpt_plan_prompt(params: Dict[str, Any]) -> str:
    """Формирует промпт для GPT на основе параметров."""

    inventory_list = params.get('inventory_list', [])
    inventory_status = "ДА. Доступный инвентарь: " + ", ".join(inventory_list) if inventory_list else "НЕТ."

    prompt = f"""
    Ты - AI-тренер по тхэквондо (Taekwondo WT). Твоя задача — составить подробный и структурированный план тренировки, строго следуя принципам ТФК (Теория и методика физического воспитания).

    Требования к плану:
    1. Структура: **Разминка** (общая и специальная), **Основная часть** (фокус на ТФК), **Заключительная часть** (заминка, растяжка, восстановление).
    2. Фокус: Основная часть ДОЛЖНА быть направлена на развитие **Основного развиваемого качества (ТФК)**.
    3. Форматирование: Используй **Markdown** (жирный текст, нумерованные и маркированные списки) для удобства чтения в Telegram. Выделяй заголовки этапов тренировки (например, **РАЗМИНКА**).
    4. Длительность: План должен занимать ровно {params.get('duration')} минут. Укажи примерное время для каждого этапа.
    5. Контекст: Учитывай все нижеперечисленные параметры.

    Параметры тренировки:
    - **Возрастная группа (для определения нагрузки):** {params.get('age_band')}
    - **Количество участников:** {params.get('group_size')} человек
    - **Основное развиваемое качество (ТФК):** {params.get('goal')}
    - **Длительность:** {params.get('duration')} минут
    - **Место проведения:** {params.get('location')}
    - **Наличие инвентаря:** {inventory_status}
    """

    # 🌟 НОВОЕ: Добавляем дополнительные комментарии тренера в промпт
    additional = params.get('additional_comments')
    if additional:
        prompt += f"\n\nДополнительные комментарии/нюансы от тренера: {additional}. УЧТИ ИХ."

    prompt += "\n\nСоставь план тренировки:"

    return prompt


def _call_gpt_api(prompt: str) -> Optional[str]:
    """Обращается к OpenAI API для генерации плана."""
    if not openai_client:
        return None

    try:
        response = openai_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": _get_gpt_plan_prompt_system()},
                {"role": "user", "content": prompt}
            ],
            temperature=TEMPERATURE
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"[ERROR] Ошибка при вызове OpenAI API: {e}")
        return None


def _get_gpt_plan_prompt_system() -> str:
    """Системный промпт для GPT."""
    return (
        "Ты - эксперт-методист по тхэквондо (Taekwondo WT) и ТФК. "
        "Генерируй план тренировки, используя только кириллицу. "
        "Соблюдай строгую структуру: Разминка, Основная часть, Заключительная часть. "
        "Обязательно используй Markdown (жирный текст, списки) для максимальной читабельности. "
        "НИКОГДА не используй заголовок 'Системный промпт' или что-либо подобное в ответе."
    )


def rule_based_coach_plan(user_id: int, params: Dict[str, Any]) -> str:
    """Заглушка для Rule-based генерации в случае недоступности AI."""

    goal = params.get('goal', 'Общая подготовка')
    duration = params.get('duration', 60)

    plan = f"🧠 Rule-Based Fallback\n"
    plan += f"**План тренировки (Заглушка) - {duration} минут**\n"
    plan += f"Фокус ТФК: **{goal}**\n\n"
    plan += "**РАЗМИНКА (10 мин)**\n"
    plan += "1. Общая разминка суставов: голова, плечи, локти, кисти, таз, колени, стопы (по 30 сек на элемент).\n"
    plan += "2. Легкий бег с элементами (захлесты, высокий подъем бедра) - 3 мин.\n\n"
    plan += f"**ОСНОВНАЯ ЧАСТЬ ({duration - 15} мин) - Развитие {goal}**\n"
    plan += "1. Упражнения по развитию {goal} (выбираются вручную или простым алгоритмом).\n"
    plan += "2. Техническая работа по тхэквондо (базовые удары).\n\n"
    plan += "**ЗАКЛЮЧИТЕЛЬНАЯ ЧАСТЬ (5 мин)**\n"
    plan += "1. Восстановительное дыхание.\n"
    plan += "2. Растяжка основных мышечных групп (легкая)."

    return plan


# --- API Endpoints ---

@app.get("/api/profile")
def api_get_profile(request: Request):
    # Аутентификация через init_data в заголовке
    init_data = request.headers.get("X-TMA-Init-Data")
    if not init_data:
        raise HTTPException(401, "Отсутствует заголовок X-TMA-Init-Data.")
    user_id = _get_user_id_from_auth(init_data)

    profile = get_or_create_profile(user_id)
    return profile


@app.post("/api/profile/update")
def api_update_profile(req: UpdateProfileRequest):
    user_id = _get_user_id_from_auth(req.init_data)

    data = {
        "role": req.role,
        "age": req.age,
        "height": req.height,
        "weight": req.weight,
        "notes": req.notes
    }
    update_profile(user_id, data)
    return {"ok": True}


@app.post("/api/plan")
def api_generate_plan(req: PlanRequest):
    # Аутентификация
    user_id = _get_user_id_from_auth(req.init_data)

    # Загрузка профиля (теперь гарантированно содержит 'role' благодаря исправлению в database.py)
    profile = get_or_create_profile(user_id)

    # 🌟 ИСПРАВЛЕНИЕ ОШИБКИ: Безопасное чтение роли.
    role = profile.get('role', 'coach')

    # Дополнительная проверка, что только тренер может генерировать планы
    if role != 'coach':
        raise HTTPException(403, "Только роль 'Тренер' может генерировать планы.")

    params = req.model_dump(exclude={'init_data'})

    # Попытка генерации с GPT
    if openai_client:
        prompt = _get_gpt_plan_prompt(params)
        gpt_plan_result = _call_gpt_api(prompt)

        if gpt_plan_result:
            # Убираем возможный префикс GPT, если он был добавлен при отладке
            plan = gpt_plan_result.replace("🧠 GPT\n", "").strip()
            engine = "gpt"
        else:
            # Fallback на Rule-based
            plan = rule_based_coach_plan(user_id, params)
            engine = "rule"
    else:
        # Fallback на Rule-based, если API ключ не задан
        plan = rule_based_coach_plan(user_id, params)
        engine = "rule"

    add_log_entry(user_id, {"type": "plan", "params": params, "plan": plan, "engine": engine})
    return {"plan": plan, "engine": engine}


@app.get("/api/templates")
def api_list_templates(request: Request):
    # Аутентификация через init_data в заголовке
    init_data = request.headers.get("X-TMA-Init-Data")
    if not init_data:
        raise HTTPException(401, "Отсутствует заголовок X-TMA-Init-Data.")
    user_id = _get_user_id_from_auth(init_data)

    return {"templates": list_templates(user_id)}


@app.post("/api/templates/save")
def api_save_template(req: SaveTemplateRequest):
    # Использование безопасной аутентификации
    user_id = _get_user_id_from_auth(req.init_data)

    save_template(user_id, req.name, req.plan, req.params)
    return {"ok": True}


@app.get("/api/history")
def api_history(request: Request, limit: int = 10):
    # Аутентификация через init_data в заголовке
    init_data = request.headers.get("X-TMA-Init-Data")
    if not init_data:
        raise HTTPException(401, "Отсутствует заголовок X-TMA-Init-Data.")
    user_id = _get_user_id_from_auth(init_data)

    return {"logs": get_logs(user_id, limit)}


# Добавляем корневой маршрут для проверки статуса
@app.get("/")
def read_root():
    return {"status": "ok", "app": "KukkiDo AI Coach API"}
