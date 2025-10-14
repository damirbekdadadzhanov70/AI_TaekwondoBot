### 🚀 Фронтенд: Telegram Mini App (TMA)

Для удобной настройки профиля (возраст, рост, вес) используется Telegram Mini App, реализованный на чистом HTML/CSS/JS (`profile_app.html`).

**1. Хостинг:**
Файл `profile_app.html` размещен на GitHub Pages по адресу:
`https://damirbekdadazhanov70.github.io/AI_TaekwondoBot/profile_app.html`

**2. Настройка в Telegram:**
Для корректной работы этого функционала необходимо зарегистрировать домен вашего Mini App в BotFather:
- Откройте BotFather -> `/mybots` -> Выберите бота.
- Нажмите `Bot Settings` -> `Menu Button` (или `Web App`).
- Введите команду `/profile`.
- Введите полный URL: `https://damirbekdadazhanov70.github.io/AI_TaekwondoBot/profile_app.html`

**3. Логика:**
- Бот запускает Mini App по команде `/profile` или кнопке "Обновить профиль" на старте.
- Mini App собирает данные и отправляет их обратно боту в виде JSON, который обрабатывается функцией `handle_profile_data` в `main.py`.
