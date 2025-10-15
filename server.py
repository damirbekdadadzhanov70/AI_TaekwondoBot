# server.py — FastAPI backend for KukkiDo Mini‑App (coach mode inside WebApp)
from __future__ import annotations
import json, re, random, datetime as dt
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import OPENAI_API_KEY, MODEL_NAME, TEMPERATURE
from database import (
    load_profiles, load_logs,
    get_or_create_profile, update_profile,
    add_log_entry, list_templates, save_template, get_logs,
)

def _recent_blocks(user_id: int, days: int = 14, max_plans: int = 10) -> List[str]:
    def _extract(plan_text: str) -> List[str]:
        names = re.findall(r"Станция\\s+[A-ZА-Я]\\s+—\\s+([^:]+):", plan_text)
        return [n.strip().lower() for n in names]
    ans: List[str] = []
    for rec in reversed(get_logs(user_id, limit=100)):
        if rec.get("type") != "plan":
            continue
        iso = rec.get("dt")
        try:
            when = dt.datetime.fromisoformat(iso.replace("Z","+00:00"))
        except Exception:
            when = None
        if when and (dt.datetime.now(dt.timezone.utc) - when).days > days:
            continue
        ans.extend(_extract(rec.get("plan","")))
        max_plans -= 1
        if max_plans <= 0: break
    seen=set(); uniq=[]
    for x in ans:
        if x not in seen:
            seen.add(x); uniq.append(x)
    return uniq

def rule_based_coach_plan(user_id: int, params: Dict[str, Any]) -> str:
    goal = params.get("goal", "Общая")
    duration = int(params.get("duration", 45))
    loc = params.get("location", "Зал")
    inv_list = params.get("inventory_list") or []
    inv = bool(inv_list) or bool(params.get("inventory", False))
    ageb = params.get("age_band", "U13")
    group_size = int(params.get("group_size", 10))

    warm = 8 if duration >= 40 else 6
    block = max(2, (duration - warm - 6) // 8)
    cool = 5

    if ageb in ("U9","U11"):
        age_note = "Фокус: координация, скорость реакции, малый объём, игровая форма. Избегай жёсткой силовой."
    elif ageb in ("U13",):
        age_note = "Фокус: скоростно‑силовая, ловкость, техника бега/прыжка. Объём умеренный."
    elif ageb in ("U17",):
        age_note = "Фокус: сила/мощность + скорость, дозированная интервальная выносливость."
    else:
        age_note = "Фокус: индивидуализация нагрузки, RPE 7–8 на основных блоках."

    have = {k: True for k in inv_list}
    speed_pool = [
        ("Старты/реакция 10–15 м", "6× (1–2 попытки/мин), большой отдых; сигнал хлопок/свисток" + (" + конусы" if have.get("cones") else "")),
        ("Плиометрика (прыжки/подскоки)", "3×6, техника/мягкая посадка"),
        ("Лестница/координация" + (" (лестница)" if have.get("ladder") else ""), "6–8 проходов, затем COD 5–10–5, 4×"),
        ("Реакция на цвет/звук", "команды тренера, 8×20–30с"),
        ("Спринты 3×(10+10)", "разворот, качество ускорения; отдых 60–90с"),
    ]
    strength_pool = [
        ("Присед/выпады (масса тела)", "4×10, RPE 7; масштаб по уровню"),
        ("Отжимания + планка", "3×8–12 + 3×30–45с"),
        ("Тяга резинки/анти‑вращение" if have.get("bands") else "Ягодичный мост", "3×12 / 3×12–15"),
        ("Румынская тяга с мячом/партнёром" if have.get("ball") else "Гиперэкстензии", "3×10–12"),
        ("Кор: dead bug / hollow hold", "3×20–30с"),
    ]
    endur_pool = [
        ("Интервалы 30/30", f"{'скакалка' if have.get('rope') else 'бег'} 8×, RPE 7"),
        ("Круг ОФП", "джампинг‑джек 20, горка 10, скалолаз 20, присед 15 — 3 круга"),
        ("Челночные 5–10–5 / эстафеты", "6–8 повторов, игровая форма"),
        ("Фартлек 10 мин", "чередование 30с быстро / 30с легко"),
    ]
    flex_pool = [
        ("Динамическая мобилность", "тазобедр., голеностоп, плечи — 6–8 мин"),
        ("Статика по парам", "10–30с × 2–4 подхода/группа мышц"),
        ("Дыхание/релиз", "мягкие упражнения + дыхание 4–6 мин"),
        ("PNF‑растяжка лёгкая", "2–3 раунда, 10с напряжение / 20с расслабление"),
    ]
    agil_pool = [
        ("Лестница/шаги" + (" (с лестницей)" if have.get("ladder") else ""), "6–8 серий по 20–30с"),
        ("Повороты 90°/180°", "с маркерами/конусами" + (" (есть конусы)" if have.get("cones") else "")),
        ("Игра на равновесие", "стойка на 1 ноге + лёгкий толчок партнёра 3×30с/нога"),
        ("Reactivity tag", "салочки на реакцию 3×2 мин"),
    ]
    general_pool = [
        ("Круг: присед‑отжим‑планка", "3× (15/10/40с), отдых 60–90с"),
        ("Спринты 20 м / скакалка 40с", ("скакалка" if have.get("rope") else "бег") + " 4–6 повторов"),
        ("Мобилити узких мест", "5–6 мин"),
        ("Броски мяча о стену" if have.get("ball") else "Берпи лёгкий", "3×10"),
    ]
    pools = {
        "Скорость": speed_pool, "Сила": strength_pool, "Выносливость": endur_pool,
        "Гибкость": flex_pool, "Ловкость": agil_pool, "Общая": general_pool,
    }
    pool = pools.get(goal, general_pool)
    recent = set(_recent_blocks(user_id))
    filtered = [x for x in pool if x[0].strip().lower() not in recent] or pool
    seed = abs(hash(f"{user_id}-{dt.date.today().isoformat()}-{goal}-{ageb}-{group_size}-{duration}")) % (2**32)
    rng = random.Random(seed)
    rng.shuffle(filtered)
    chosen = filtered[:max(2, min(block, len(filtered)))]
    if len(chosen) < block:
        more = [x for x in pool if x not in chosen]
        rng.shuffle(more)
        chosen += more[:block-len(chosen)]

    head = f"⚙️ Rule‑based | План для группы | {duration} мин | {ageb} | {loc} | цель: {goal} | группа: {group_size} | инвентарь: {'да' if inv else 'нет'}"
    wup  = "Разминка (RAMP) " + str(warm) + " мин: лёгкий бег/скакалка → активация (ягодицы/кор) → мобилизация (тазобедр., голеностоп, плечи) → 2–3 ускорения."
    st_txt = [f"Станция {chr(65+i)} — {title}: {spec} (~8 мин)" for i,(title,spec) in enumerate(chosen)]
    game = "Игра/спарринг лайт 6–8 мин (техника > интенсивность, RPE 6–7)."
    cool = f"Заминка {cool} мин: ходьба + статическая растяжка (10–30с × 2–4 подхода)."
    coach = "Заметки тренеру: " + age_note + "\\n• Контроль RPE: основные блоки ~7–8, техника ~4–6.\\n• Делим на 2–3 подгруппы для уменьшения очередей."
    return f"{head}\\n\\n{wup}\\n\\n" + "\\n".join(f"- {x}" for x in st_txt) + f"\\n\\n- {game}\\n\\n{cool}\\n\\n{coach}"


def _openai_client():
    if not OPENAI_API_KEY:
        return None
    try:
        # Импортируем новый класс
        from openai import OpenAI
    except Exception:
        # Fallback, если OpenAI не установлен, хотя в requirements.txt он есть
        return None

    # Возвращаем инициализированный клиент
    return OpenAI(api_key=OPENAI_API_KEY)


def gpt_coach_plan(profile: Dict[str, Any], user_id: int, params: Dict[str, Any], notes: str) -> Optional[str]:
    # Используем новый клиент
    client = _openai_client()
    if not client:
        return None
    recent = _recent_blocks(user_id)

    sys = (
        "Ты — тренер‑методист по ТФК. Сгенерируй план по параметрам (возраст, цель, длительность, место, инвентарь, размер группы). "
        "Формат: Заголовок → RAMP‑разминка → 2–4 станции (время, подходы/повт., RPE) → игра/спарринг (опц.) → заминка → заметки тренеру. "
        "Учитывай инвентарь, возрастные акценты и избегай повтора станций, использованных за последние 14 дней."
    )
    try:
        messages = [
            {"role": "system", "content": sys},
            {"role": "user", "content": json.dumps({
                "profile": profile, "params": params, "notes": notes,
                "recent_blocks_14d": recent
            }, ensure_ascii=False)},
        ]

        # 🌟 ИСПОЛЬЗУЕМ НОВЫЙ СИНТАКСИС API 🌟
        resp = client.chat.completions.create(
            model=MODEL_NAME, messages=messages, temperature=TEMPERATURE, max_tokens=800
        )
        # Получаем контент из нового объекта ответа
        return "🧠 GPT\\n" + resp.choices[0].message.content.strip()
    except Exception as e:
        # Важно: печатаем ошибку для диагностики
        print(f"GPT Error: {e}")
        return None


# ... (Остальной код server.py) ...

# !!! ВАЖНО: Ниже нужно обновить логику engine, чтобы она учитывала новый префикс.
# В функции api_coach_plan замените:
# plan = gpt_coach_plan(prof, user_id, params, req.notes or "") or rule_based_coach_plan(user_id, params)
# add_log_entry(user_id, {"type": "plan", "params": params, "plan": plan})
# return {"plan": plan, "engine": "gpt" if plan.startswith("🧠 GPT") else "rule"}

# На эту логику (чтобы GPT работал, если он доступен):

@app.post("/api/coach_plan")
def api_coach_plan(req: CoachPlanRequest):
    user_id = req.user_id
    if not user_id:
        raise HTTPException(400, "user_id обязателен (Telegram.WebApp.initDataUnsafe.user.id)")
    prof = update_profile(user_id, {"role": "coach"})
    params = req.params.dict()

    # Пытаемся получить GPT-план
    gpt_plan_result = gpt_coach_plan(prof, user_id, params, req.notes or "")

    if gpt_plan_result and gpt_plan_result.startswith("🧠 GPT"):
        # GPT сработал. Удаляем префикс и устанавливаем движок.
        plan = gpt_plan_result.replace("🧠 GPT\n", "").strip()
        engine = "gpt"
    else:
        # Fallback на Rule-based
        plan = rule_based_coach_plan(user_id, params)
        engine = "rule"

    add_log_entry(user_id, {"type": "plan", "params": params, "plan": plan})
    return {"plan": plan, "engine": engine}

class CoachParams(BaseModel):
    age_band: str
    group_size: int
    goal: str
    duration: int
    location: str
    inventory: bool = False
    inventory_list: List[str] = []
class CoachPlanRequest(BaseModel):
    user_id: int
    params: CoachParams
    notes: Optional[str] = ""

class SaveTemplateRequest(BaseModel):
    user_id: int
    name: str
    plan: str
    params: Dict[str, Any]

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="KukkiDo API", version="0.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def _startup():
    load_profiles(); load_logs()

@app.post("/api/coach_plan")
def api_coach_plan(req: CoachPlanRequest):
    user_id = req.user_id
    if not user_id:
        raise HTTPException(400, "user_id обязателен (Telegram.WebApp.initDataUnsafe.user.id)")
    prof = update_profile(user_id, {"role": "coach"})
    params = req.params.dict()
    plan = gpt_coach_plan(prof, user_id, params, req.notes or "") or rule_based_coach_plan(user_id, params)
    add_log_entry(user_id, {"type": "plan", "params": params, "plan": plan})
    return {"plan": plan, "engine": "gpt" if plan.startswith("🧠 GPT") else "rule"}

@app.get("/api/templates")
def api_list_templates(user_id: int):
    return {"templates": list_templates(user_id)}

@app.post("/api/templates/save")
def api_save_template(req: SaveTemplateRequest):
    save_template(req.user_id, req.name, req.plan, req.params)
    return {"ok": True}

@app.get("/api/history")
def api_history(user_id: int, limit: int = 10):
    return {"logs": get_logs(user_id, limit=limit)}

@app.get("/api/ping")
def api_ping():
    import datetime as dt
    return {"ok": True, "time": dt.datetime.now(dt.timezone.utc).isoformat()}