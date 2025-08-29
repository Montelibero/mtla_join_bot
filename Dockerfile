# Используем официальный Python образ
FROM python:3.11-slim

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Добавляем MongoDB GPG ключ и репозиторий (современный способ)
RUN wget -qO - https://www.mongodb.org/static/pgp/server-7.0.asc | gpg --dearmor -o /usr/share/keyrings/mongodb-archive-keyring.gpg \
    && echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-archive-keyring.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | tee /etc/apt/sources.list.d/mongodb-org-7.0.list

# Устанавливаем MongoDB
RUN apt-get update && apt-get install -y \
    mongodb-org \
    && rm -rf /var/lib/apt/lists/*

# Создаем директории для MongoDB
RUN mkdir -p /data/db

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем requirements.txt и устанавливаем Python зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY . .

# Создаем скрипт запуска
RUN echo '#!/bin/bash\n\
# Запускаем MongoDB в фоне\n\
mongod --fork --logpath /var/log/mongodb.log --dbpath /data/db\n\
\n\
# Ждем запуска MongoDB\n\
sleep 5\n\
\n\
# Запускаем бота\n\
python main.py\n\
' > /app/start.sh && chmod +x /app/start.sh

# Запускаем скрипт
CMD ["/app/start.sh"]
