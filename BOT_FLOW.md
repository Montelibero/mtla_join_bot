# Флоу бота MTLA Join Bot

## Обзор

MTLA Join Bot - это Telegram бот для проверки формальных критериев и подготовки заявки на вступление в Ассоциацию Монтелиберо. Бот проводит пошаговую проверку всех необходимых условий и генерирует готовую заявку для подачи.

## Основные команды

### Пользовательские команды
- `/start` - начать процесс проверки
- `/restart` - начать заново (сброс прогресса)
- `/language` - сменить язык (русский/английский, в перспективе ещё)

### Административные команды
- `/stats` - статистика по пользователям
- `/incomplete` - незавершенные пользователи
- `/reminders [дни]` - кандидаты для напоминания
- `/user_info <user_id>` - детали конкретного пользователя
- `/help_admin` - справка по административным командам

## Детальный флоу проверки

### 1. Инициализация (`/start`)

**Состояние:** `CHECKING_USERNAME`

**Действия бота:**
- Определяет язык пользователя (по `language_code` из Telegram)
- Создает нового пользователя в базе данных или обновляет существующего
- Сбрасывает прогресс существующего пользователя
- Отправляет приветственное сообщение

**Сообщения:**
- **RU:** "Этот бот поможет оформить вам заявку на вступление в Ассоциацию Монтелиберо (@MTL_Association). Всего несколько шагов и несколько проверок!"
- **EN:** "This bot will help you submit an application to join the Montelibero Association (@MTL_Association). Just a few steps and a few checks!"

**Переход:** Автоматически к проверке юзернейма

---

### 2. Проверка юзернейма

**Состояние:** `CHECKING_USERNAME`

**Проверка:**
- Наличие `username` у пользователя в Telegram

**Если юзернейм есть:**
- Устанавливает `has_username = True`
- Переходит к следующему шагу

**Если юзернейма нет:**
- Отправляет сообщение о необходимости юзернейма
- Показывает ссылку на инструкцию
- Предоставляет кнопку "✅ Я установил юзернейм"

**Сообщения при отсутствии юзернейма:**
- **RU:** "У вас нет юзернейма :-(\n\nХотя правила Ассоциации не запрещают аккаунты без юзернеймов, мы не знаем, как работать с участниками без них.\n\nИнструкция по установке юзернейма:\n[ссылка]"
- **EN:** "You don't have a username. Although the Association rules don't prohibit accounts without usernames, we don't know how to work with participants who don't have them.\n\nUsername setup guide:\n[ссылка]"

**Кнопки:**
- "✅ Я установил юзернейм" (callback: `username_installed`)

**Переход:** После нажатия кнопки → проверка юзернейма повторно

---

### 3. Согласие с условиями

**Состояние:** `AGREEMENT`

**Действия бота:**
- Отправляет текст соглашения с ссылкой на документ
- Предоставляет клавиатуру с вариантами ответа

**Сообщения:**
- **RU:** "Чтобы вступить в Ассоциацию Монтелиберо, необходимо выразить согласие с актуальным текстом Соглашения.\n\nЭто наш общий контракт.\nПожалуйста, ознакомьтесь с ним:\n[ссылка на соглашение]"
- **EN:** "To join the Montelibero Association, you must express your agreement with the current text of the Agreement.\n\nThis is our common contract.\nPlease read it:\n[agreement link]"

**Клавиатура:**
- "✅ Согласен" / "✅ Agree"
- "❌ Не согласен" / "❌ Disagree"

**Обработка ответов:**
- **Согласен:** устанавливает `agreed_to_terms = True`, переходит к вводу адреса
- **Не согласен:** показывает сообщение о необходимости согласия, предлагает кнопку "✅ Согласен"

**Сообщение при отказе:**
- **RU:** "Для вступления в Ассоциацию необходимо выразить согласие с Соглашением. Без этого вступление невозможно."
- **EN:** "To join the Montelibero Association, you must agree to the Agreement. Without this, joining is impossible."

**Переход:** После согласия → ввод Стеллар адреса

---

### 4. Ввод Стеллар адреса

**Состояние:** `ENTERING_ADDRESS`

**Действия бота:**
- Отправляет инструкцию по вводу адреса
- Предоставляет клавиатуру с дополнительными опциями

**Сообщения:**
- **RU:** "Напишите ваш Stellar-адрес (строка что начинается с G...)"
- **EN:** "Enter your Stellar address (string that starts with G...)"

**Клавиатура:**
- "Что за стеллар адрес?" (информационная кнопка)

**Информационная кнопка "Что за стеллар адрес?":**
- Отправляет объяснение с ссылкой на статью
- Убирает клавиатуру

**Сообщение объяснения:**
- **RU:** "Stellar-адрес - это ваш уникальный идентификатор в блокчейне Stellar. Это как номер банковского счета, но для криптовалют.\n\nРекомендуем прочитать статью «Лёгкий вход в токеномику», по итогам которой можно получить аирдроп:\n[ссылка]"
- **EN:** "A Stellar address is your unique identifier in the Stellar blockchain. It's like a bank account number, but for cryptocurrencies.\n\nWe recommend reading the article 'Easy entry into tokenomics', the result of which is an airdrop:\n[ссылка]"

**Обработка ввода адреса:**
- **Валидация формата:** проверка по regex `^G[A-Z2-7]{55}$`

**Если адрес неверный:**
- **RU:** "Неверный формат Stellar-адреса. Строка должна начинаться с G..."
- **EN:** "Invalid Stellar address format. The string must start with G..."

Сохранить адрес в переменной `stellar_address`.

- Запрос к Stellar Network через API 

**Если адрес не активирован (не существует):**
- **RU:** "Этот адрес ещё не активирован. Возможно он только что создан. Для активации, проще всего, послать на него 2-3 XLM токена."
**Кнопка:** "🔄 Повторить проверку" / "🔄 Repeat check"

**Если запрос завершается ошибкой:**
- **RU:** "К сожалению есть какая-то проблема со связью со Stellar API ([описание ошибки]). Скорее всего это временное, попробуйте повторить ответ попозже."
**Кнопка:** "🔄 Повторить проверку" / "🔄 Repeat check"

**Если на адресе уже есть не нулевое количество MTLAP токенов:**
- **RU:** "Этот адрес уже является участником Ассоциации и там уже есть токены MTLAP. Возможно, вы вступали в Ассоциацию ранее. А может это не ваш адрес? Тогда попробуйте указать другой."
- **EN:** "This address is already a member of the Montelibero Association and has MTLAP tokens. Maybe you have already joined the Association before. Or maybe this is not your address? Then try a different address."
- Очистить адрес в переменной `stellar_address`.
- Убирает клавиатуру

**Переход:** После ввода валидного адреса → проверка адреса

---

### 5. Проверка Стеллар адреса

**Состояние:** `CHECKING_ADDRESS`

**Действия бота:**
- Отправляет сообщение о начале проверки
- Убирает клавиатуру
- Выполняет комплексную проверку из двух шагов

**Сообщение о проверке:**
- **RU:** "👀 Так, сейчас посмотрим..."
- **EN:** "👀 So, let's see..."

**Проверки:**
1. **Существование адреса** в Stellar Network
2. **Линия доверия** к токену MTLAP
3. **Рекомендации** от верифицированных участников (≥2 MTLAP токена)

**Результат проверки:**
- **Все проверки пройдены:** переход к завершению
- **Есть проблемы:** показ списка проблем с решениями

---

### 6. Показ проблем (если есть)

**Состояние:** `CHECKING_ADDRESS`

**Бот показывает каждую проблему отдельным сообщением:**

#### 6.1 Проблема с линией доверия
**Если:** `has_trustline = False`
**Сообщение:** 
- **RU:** "У вас нет линии доверия к токену MTLAP. Это наш токен участия, и без вашего разрешения его нельзя будет вам прислать.\n\nЕсли у вас возникли вопросы, обратитесь в чат Площади.\n\nОткрыть линию доверия: [ссылка]"
- **EN:** "You don't have a trustline to MTLAP token. MTLAP is a membership token, and without your permission, it cannot be sent to you.\n\nIf you have questions, contact the Square chat.\n\nOpen trustline: [ссылка]"
**Кнопка:** "🔄 Повторить проверку" / "🔄 Repeat check"

#### 6.2 Проблема с рекомендациями
**Если:** `has_recommendation = False`

**Нет рекомендаций вообще:**
- **RU:** "Для вступления в Ассоциацию нужна рекомендация от верифицированного участника (у которого есть как минимум 2 токена MTLAP)."
- **EN:** "To join the Montelibero Association, you need a recommendation from a verified member (at least 2 MTLAP tokens)."

**Есть неверифицированная рекомендация:**
- **RU:** "У вас есть рекомендация, но она не от верифицированного участника Ассоциации (у которого есть как минимум 2 токена MTLAP)."
- **EN:** "You have a recommendation, but it's not from a verified member of the Montelibero Association (at least 2 MTLAP tokens required)."

**Помощь по рекомендациям:**
- **RU:** "Рекомендацию можно получить от знакомых верифицированных участников Ассоциации или спросить в чате Площадь.\n\nЧат Площадь: [ссылка]"
- **EN:** "You can get a recommendation from verified member acquaintances or contact the Agora chat.\n\nSquare chat: [ссылка]"
**Кнопка:** "🔄 Повторить проверку" / "🔄 Repeat check"

---

### 7. Завершение (все проверки пройдены)

**Состояние:** `COMPLETED`

**Действия бота:**
- Устанавливает состояние `COMPLETED`
- Генерирует готовый текст заявки
- Отправляет инструкции по подаче

**Сообщение:**
- **RU:** "✅ Отлично! Всё готово для подачи заявки.\n\nДля этого скопируйте этот текст:\n```\n{application_text}\n```\n\nИ напишите его боту обратной связи Монтелиберо: {feedback_bot}\n\nСпасибо за участие!"
- **EN:** "Great! All checks passed successfully.\n\nTo submit the application, copy this text:\n```\n{application_text}\n```\nAnd write it to the feedback bot of Montelibero: {feedback_bot}\n\nThank you for participation!"

**Текст заявки:**
- **RU:** "Хочу вступить в Ассоциацию Монтелиберо.\nСоглашение прочитано и выражаю полное согласие с ним.\nМой адрес: {address}"
- **EN:** "I want to join the Montelibero Association.\nI have read the Agreement and express my full agreement with it.\nMy address: {address}"

---

## Обработка callback кнопок

### `lang_ru` / `lang_en`
- Обновляет язык пользователя
- Отправляет подтверждение смены языка

---

## Обработка текстовых сообщений

### Состояние `AGREEMENT`
- **"✅ Согласен"** / **"✅ Agree"** → переход к вводу адреса
- **"❌ Не согласен"** / **"❌ Disagree"** → требование согласия
- **Другое** → просьба выбрать из предложенных вариантов

### Состояние `ENTERING_ADDRESS`
- **"Что за стеллар адрес?"** → объяснение + ссылка на статью
- **Стеллар адрес** → валидация и проверка
- **Другое** → игнорируется

### Любое состояние
- **"🔄 Повторить проверку"** / **"🔄 Repeat check"** → повторная проверка

---

## Состояния пользователя

1. **`CHECKING_USERNAME`** - проверка наличия юзернейма
2. **`AGREEMENT`** - ожидание согласия с условиями
3. **`ENTERING_ADDRESS`** - ввод Стеллар адреса
4. **`CHECKING_ADDRESS`** - проверка адреса и всех условий
5. **`COMPLETED`** - все проверки пройдены

---

## Особенности реализации

### Автоматическое определение языка
- По `language_code` из Telegram
- Fallback на английский язык
- Возможность смены через `/language`

### Обработка ошибок
- Graceful fallback при ошибках API
- Логирование всех действий
- Информативные сообщения об ошибках

### Управление состоянием
- MongoDB для хранения данных
- Автоматическое восстановление состояния
- Возможность сброса прогресса

### Безопасность
- Проверка прав администратора
- Валидация всех входных данных

---

## Ссылки и ресурсы

### Русский язык
- **Соглашение:** [GitHub](https://github.com/Montelibero/MTLA-Documents/blob/main/Internal/Agreement/Agreement.ru.md)
- **Линия доверия MTLAP:** [EURMTL](https://eurmtl.me/asset/MTLAP)
- **Чат Площадь:** [Telegram](https://t.me/Montelibero_Agora)
- **Статья "Лёгкий вход в токеномику":** [Montelibero](https://montelibero.org/2022/03/10/quick-entry-to-the-montelibero-tokenomics/)
- **Бот обратной связи:** @mtl_helper_bot

### English
- **Agreement:** [GitHub](https://github.com/Montelibero/MTLA-Documents/blob/main/Internal/Agreement/Agreement.en.md)
- **MTLAP trustline:** [EURMTL](https://eurmtl.me/asset/MTLAP)
- **Square chat:** [Telegram](https://t.me/Montelibero_Agora)
- **"Easy entry to tokenomics" article:** [Montelibero](https://montelibero.org/2022/03/10/quick-entry-to-the-montelibero-tokenomics/)
- **Feedback bot:** @mtl_helper_bot
