# main.py — минимальный бот: только открывает WebApp, вся логика в Mini-App + API
from __future__ import annotations

import os
import time
import logging
import urllib.parse
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

from config import TELEGRAM_BOT_TOKEN, WEBAPP_PROFILE_URL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("KukkiDo")

BACKEND_URL_FILE = os.path.expanduser("~/.kukkido_backend_url")


def build_webapp_url(base: str) -> str:
    """
    Собирает URL для WebApp:
    - добавляет параметр v=<timestamp> (ломаем кэш);
    - добавляет backend=<https-адрес_туннеля> из ~/.kukkido_backend_url (если есть).
    """
    backend = ""
    try:
        with open(BACKEND_URL_FILE, "r", encoding="utf-8") as f:
            backend = (f.read() or "").strip()
    except Exception:
        pass

    # базовый URL + cache-busting
    sep = "&" if ("?" in base) else "?"
    url = f"{base}{sep}v={int(time.time())}"

    # подставляем backend, если есть
    if backend:
        url += f"&backend={urllib.parse.quote(backend, safe='')}"

    return url


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = build_webapp_url(WEBAPP_PROFILE_URL)
    kb = [[KeyboardButton(text="Открыть KukkiDo", web_app=WebAppInfo(url=url))]]
    await update.message.reply_text(
        "Открой мини-приложение KukkiDo. Весь функционал теперь внутри WebApp.",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN не указан (см. ~/.config/kukkido/env)")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    logger.info("Bot is up (only /start, opens WebApp).")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
