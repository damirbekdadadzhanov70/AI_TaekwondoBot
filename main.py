# main.py — ядро бота: роли, минимальный профиль, старт-меню и ПЕРСОНАЛЬНЫЙ мастер /plan
# Требует соседние файлы: config.py и database.py (из нашего проекта).

from __future__ import annotations
import logging
import traceback  # НОВОЕ: для отладки
from typing import Optional
import json  # НОВЫЙ КОД: Нужен для обработки JSON из Mini App

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters
)

from openai import OpenAI  # OpenAI SDK v1.x

from config import TELEGRAM_BOT_TOKEN, OPENAI_API_KEY, MODEL_NAME, TEMPERATURE
from database import get_or_create_profile, update_profile, attach_visuals, load_profiles

# ------------------------------------------------- ЛОГИРОВАНИЕ
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("AI_TaekwondoBot")


# ------------------------------------------------- УТИЛИТЫ КЛАВИАТУР
def _kb(rows):  # reply-клавиатура
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


def role_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Спортсмен 🥋", callback_data="set_role_athlete")],
        [InlineKeyboardButton("Тренер 🧑‍🏫", callback_data="set_role_coach")],
    ])


# ------------------------------------------------- /start
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    user = update.effective_user
    user_id = user.id
    name = user.first_name or "друг"
    profile = get_or_create_profile(user_id)

    role = profile.get("role", "athlete")
    role_human = "Спортсмен" if role == "athlete" else "Тренер"

    if role == "coach":
        text = (
            f"🥋 Привет, *{name}*!\n"
            f"Роль: **{role_human}**\n\n"
            "Параметры группы и целевое качество выберем в мастере /plan.\n"
            "Выберите действие:"
        )
    else:
        age = profile.get("age", "—")
        height = profile.get("height", "—")
        weight = profile.get("weight", "—")
        text = (
            f"🥋 Привет, *{name}*!\n"
            f"Роль: **{role_human}**\n"
            f"Возраст: {age} | Рост: {height} см | Вес: {weight} кг\n\n"
            "Выберите действие:"
        )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Обновить профиль", callback_data="open_profile")],
        [InlineKeyboardButton("🔄 Сменить роль", callback_data="open_role_picker")],
    ])

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=kb,
            parse_mode="Markdown"
        )
    elif update.message:
        await update.message.reply_text(
            text=text,
            reply_markup=kb,
            parse_mode="Markdown"
        )

    return ConversationHandler.END


# ------------------------------------------------- /role (команда) + callbacks
async def role_command(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    p = get_or_create_profile(update.effective_user.id)
    role_human = "Спортсмен" if p.get("role", "athlete") == "athlete" else "Тренер"
    await update.message.reply_text(
        f"Текущая роль: *{role_human}*.\nВыберите новую роль:",
        reply_markup=role_kb(),
        parse_mode="Markdown"
    )


async def cb_open_role(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Выберите новую роль:", reply_markup=role_kb())


async def cb_set_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if q.data == "set_role_athlete":
        update_profile(uid, role="athlete")
    elif q.data == "set_role_coach":
        update_profile(uid, role="coach")

    await start_command(update, context)


# ------------------------------------------------- ПРОФИЛЬ (Mini App)
# ВАШ АДРЕС:
YOUR_APP_URL = "https://damirbekdadadzhanov70.github.io/AI_TaekwondoBot/profile_app.html"


# main.py, строка ~150
# ...
# ------------------------------------------------- ПРОФИЛЬ (Mini App)
# ...

async def handle_profile_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Принимает JSON-данные о профиле, отправленные из Mini App."""
    if not update.message.web_app_data:
        return

    data = update.message.web_app_data.data
    uid = update.effective_user.id

    # 💡 НОВЫЙ КОД ДЛЯ ДЕБАГА
    logger.info(f"Получены данные Mini App от {uid}: {data}")

    try:
        profile_data = json.loads(data)

        # Валидация и обновление
        age = int(profile_data.get("age", 0))
        height = int(profile_data.get("height", 0))
        weight = float(profile_data.get("weight", 0))

        # 💡 НОВЫЙ КОД ДЛЯ ДЕБАГА
        logger.info(f"Parsed data: age={age}, height={height}, weight={weight}")

        if age >= 4 and height >= 80 and weight >= 15:
            # Вызываем функцию из database.py
            saved = update_profile(uid, age=age, height=height, weight=weight)

            # 💡 НОВЫЙ КОД ДЛЯ ДЕБАГА
            logger.info(f"Профиль {uid} успешно обновлен. Отправка ответа.")

            await update.message.reply_text(
                "✅ *Профиль спортсмена обновлен через Mini App*.\n"
                f"Возраст: {saved['age']} | Рост: {saved['height']} см | Вес: {saved['weight']} кг",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ Ошибка валидации данных. Проверьте введенные значения.")

    except Exception as e:
        # 💡 Улучшенное логирование с traceback
        logger.error(f"Критическая ошибка при обработке данных Mini App для {uid}: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Произошла ошибка при обработке данных Mini App: {e}")


# НОВЫЙ КОД / ИСПРАВЛЕНИЕ: Запускает Mini App вместо диалога
async def profile_command(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    role = get_or_create_profile(uid).get("role", "athlete")

    if role == "coach":
        await update.message.reply_text(
            "✅ Профиль тренера активирован.\n"
            "Возраст/уровень/инвентарь укажете прямо в мастере /plan."
        )
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Настроить профиль (Mini App)", web_app={"url": YOUR_APP_URL})]
    ])

    await update.message.reply_text(
        "Нажмите кнопку, чтобы настроить профиль спортсмена в удобном окне:",
        reply_markup=kb
    )
    return


# НОВЫЙ КОД / ИСПРАВЛЕНИЕ: Запускает Mini App из кнопки
async def profile_from_button(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    if get_or_create_profile(uid).get("role", "athlete") == "coach":
        await q.edit_message_text("✅ Профиль тренера активирован. Детали зададите в /plan.")
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Настроить профиль (Mini App)", web_app={"url": YOUR_APP_URL})]
    ])

    await q.edit_message_text(
        "Нажмите кнопку, чтобы настроить профиль спортсмена в удобном окне:",
        reply_markup=kb
    )
    return


# ------------------------------------------------- /plan — мастер персонализации
# состояния
P_COACH_AGE, P_COACH_GOAL, P_COACH_INV, P_COACH_DUR, \
    P_ATH_GOAL, P_ATH_LOC, P_ATH_INV, P_ATH_DUR = range(100, 108)

PLAN_GOALS = ["Скорость", "Сила", "Выносливость", "Гибкость", "Ловкость", "Статика", "Игровая", "Другое"]
DURATIONS = ["30", "45", "60"]
YN = [["Да"], ["Нет"]]
ATH_LOC = [["Зал"], ["Дом"], ["Улица"]]


async def plan_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    p = get_or_create_profile(update.effective_user.id)
    role = p.get("role", "athlete")
    context.user_data["plan"] = {}

    if role == "coach":
        await update.message.reply_text(
            "Для какой возрастной группы сейчас план? (например: 8–10 / 10–12 / смешанная)",
            reply_markup=ReplyKeyboardRemove()
        )
        return P_COACH_AGE
    else:
        await update.message.reply_text("Выберите целевое качество:", reply_markup=_kb([[g] for g in PLAN_GOALS]))
        return P_ATH_GOAL


# --- тренер (Остались без изменений)
async def p_coach_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["plan"]["group_age"] = update.message.text.strip()
    await update.message.reply_text("Какое качество развиваем?", reply_markup=_kb([[g] for g in PLAN_GOALS]))
    return P_COACH_GOAL


async def p_coach_goal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["plan"]["goal"] = update.message.text.strip()
    await update.message.reply_text("Есть инвентарь (лапа/эластик/коны и т.п.)?", reply_markup=_kb(YN))
    return P_COACH_INV


async def p_coach_inv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["plan"]["inventory"] = (update.message.text.strip().lower() == "да")
    await update.message.reply_text("Длительность, минут:", reply_markup=_kb([[d] for d in DURATIONS]))
    return P_COACH_DUR


async def p_coach_finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    duration = int(update.message.text.strip()) if update.message.text.strip().isdigit() else 60
    context.user_data["plan"]["duration"] = duration
    prof = get_or_create_profile(update.effective_user.id)
    params = context.user_data["plan"].copy() | {"role": "coach"}
    # Здесь должен быть вызов _generate_and_send_plan (ваш код опущен)
    # await _generate_and_send_plan(update, context, prof, params)
    context.user_data.pop("plan", None)
    return ConversationHandler.END


# --- спортсмен (Остались без изменений)
async def p_ath_goal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["plan"]["goal"] = update.message.text.strip()
    await update.message.reply_text("Где тренируемся?", reply_markup=_kb(ATH_LOC))
    return P_ATH_LOC


async def p_ath_loc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["plan"]["location"] = update.message.text.strip()
    await update.message.reply_text("Есть инвентарь?", reply_markup=_kb(YN))
    return P_ATH_INV


async def p_ath_inv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["plan"]["inventory"] = (update.message.text.strip().lower() == "да")
    await update.message.reply_text("Длительность, минут:", reply_markup=_kb([[d] for d in DURATIONS]))
    return P_ATH_DUR


async def p_ath_finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    duration = int(update.message.text.strip()) if update.message.text.strip().isdigit() else 60
    context.user_data["plan"]["duration"] = duration
    prof = get_or_create_profile(update.effective_user.id)
    params = context.user_data["plan"].copy() | {"role": "athlete"}
    # Здесь должен быть вызов _generate_and_send_plan (ваш код опущен)
    # await _generate_and_send_plan(update, context, prof, params)
    context.user_data.pop("plan", None)
    return ConversationHandler.END


async def plan_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("plan", None)
    await update.message.reply_text("Окей, отменил. Запускайте /plan, когда будете готовы.",
                                    reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ------------------------------------------------- OpenAI client (+ /diag)
_openai_client: Optional[OpenAI] = None


def get_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY не найден. Проверь .env.")
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


async def diag(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        c = get_client()
        r = c.chat.completions.create(model=MODEL_NAME, messages=[{"role": "user", "content": "ping"}], max_tokens=2)
        _ = r.choices[0].message.content
        await update.message.reply_text(f"✅ OpenAI доступен. Модель: {MODEL_NAME}")
    except Exception as e:
        await update.message.reply_text(f"❌ OpenAI недоступен: {e}")


# ------------------------------------------------- РЕГИСТРАЦИЯ И ЗАПУСК
def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Ошибка: TELEGRAM_BOT_TOKEN не загружен. Проверь .env!")
        return

    load_profiles()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("role", role_command))
    app.add_handler(CommandHandler("diag", diag))

    # НОВЫЙ КОД / ИСПРАВЛЕНИЕ: Обработчики для Mini App
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CallbackQueryHandler(profile_from_button, pattern=r"^open_profile$"))

    # 🌟 КЛЮЧЕВОЙ ХЕНДЛЕР: Ловит данные, которые Mini App отправляет после закрытия
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_profile_data))

    # Выбор/смена роли из кнопки
    app.add_handler(CallbackQueryHandler(cb_open_role, pattern=r"^open_role_picker$"))
    app.add_handler(CallbackQueryHandler(cb_set_role, pattern=r"^set_role_"))

    # Мастер персонализации плана (остается ConversationHandler)
    plan_conv = ConversationHandler(
        entry_points=[CommandHandler("plan", plan_entry)],
        states={
            # тренер
            P_COACH_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, p_coach_age)],
            P_COACH_GOAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, p_coach_goal)],
            P_COACH_INV: [MessageHandler(filters.TEXT & ~filters.COMMAND, p_coach_inv)],
            P_COACH_DUR: [MessageHandler(filters.TEXT & ~filters.COMMAND, p_coach_finish)],
            # спортсмен
            P_ATH_GOAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, p_ath_goal)],
            P_ATH_LOC: [MessageHandler(filters.TEXT & ~filters.COMMAND, p_ath_loc)],
            P_ATH_INV: [MessageHandler(filters.TEXT & ~filters.COMMAND, p_ath_inv)],
            P_ATH_DUR: [MessageHandler(filters.TEXT & ~filters.COMMAND, p_ath_finish)],
        },
        fallbacks=[
            CommandHandler("cancel", plan_cancel),
            CommandHandler("start", start_command)
        ],
    )
    app.add_handler(plan_conv)

    logger.info("Бот запущен. Ожидание команд…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()