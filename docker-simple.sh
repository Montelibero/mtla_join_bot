#!/bin/bash

# Управление MTLA Join Bot через Docker Compose.

set -euo pipefail

IMAGE_NAME="mtla-join-bot:local"
PREVIOUS_IMAGE_NAME="mtla-join-bot:previous"
LEGACY_CONTAINER_NAME="mtla-join-bot"
VOLUME_NAME="mtla_join_bot_data"
ENV_FILE="${MTLA_JOIN_BOT_ENV_FILE:-.env}"
TOKEN_FILE="${MTLA_JOIN_BOT_TELEGRAM_TOKEN_FILE:-}"
COMPOSE_FILES=(-f compose.yaml)

run_compose() {
    MTLA_JOIN_BOT_ENV_FILE="$ENV_FILE" \
    MTLA_JOIN_BOT_TELEGRAM_TOKEN_FILE="$TOKEN_FILE" \
        docker compose "${COMPOSE_FILES[@]}" "$@"
}

require_runtime_files() {
    if [ ! -f "$ENV_FILE" ] || [ ! -r "$ENV_FILE" ]; then
        echo "❌ Файл окружения не найден или недоступен для чтения: $ENV_FILE"
        echo "Создайте его из env_example.txt или задайте MTLA_JOIN_BOT_ENV_FILE."
        exit 1
    fi

    if [ -n "$TOKEN_FILE" ]; then
        if [ ! -f "$TOKEN_FILE" ] || [ ! -r "$TOKEN_FILE" ]; then
            echo "❌ Файл токена не найден или недоступен для чтения: $TOKEN_FILE"
            exit 1
        fi
        case "$TOKEN_FILE" in
            /*) ;;
            *)
                echo "❌ Для файла токена нужен абсолютный путь: $TOKEN_FILE"
                exit 1
                ;;
        esac
        if grep -Eq '^[[:space:]]*TELEGRAM_TOKEN([[:space:]]*=|[[:space:]]*$)' "$ENV_FILE"; then
            echo "❌ Удалите TELEGRAM_TOKEN из $ENV_FILE при использовании отдельного файла токена."
            exit 1
        fi
    else
        echo "⚠️ TELEGRAM_TOKEN будет передан через окружение контейнера."
        echo "   Для production используйте MTLA_JOIN_BOT_TELEGRAM_TOKEN_FILE."
    fi
}

legacy_container_exists() {
    docker container inspect "$LEGACY_CONTAINER_NAME" >/dev/null 2>&1
}

compose_up() {
    run_compose up -d --no-build --force-recreate --wait --wait-timeout 90
}

rollback_after_failed_deploy() {
    if ! run_compose down; then
        echo "❌ Не удалось гарантированно остановить новый Compose stack."
        echo "   Старый экземпляр не запускается во избежание двух MongoDB на одном volume."
        return 1
    fi
    if [ "$LEGACY_STOPPED" = "true" ]; then
        echo "↩️ Возвращаем прежний compatibility-контейнер."
        docker start "$LEGACY_CONTAINER_NAME"
        return 0
    fi
    if docker image inspect "$PREVIOUS_IMAGE_NAME" >/dev/null 2>&1; then
        echo "↩️ Возвращаем предыдущий Compose image."
        docker tag "$PREVIOUS_IMAGE_NAME" "$IMAGE_NAME"
        if compose_up; then
            return 0
        fi
        echo "❌ Предыдущий image тоже не прошёл process healthcheck."
        run_compose down
    fi
    return 1
}

case "${1:-help}" in
    "build")
        echo "🔨 Собираем Docker image бота..."
        docker build -t "$IMAGE_NAME" .
        echo "✅ Образ собран!"
        ;;

    "bootstrap")
        if docker volume inspect "$VOLUME_NAME" >/dev/null 2>&1; then
            echo "✅ MongoDB volume уже существует: $VOLUME_NAME"
            exit 0
        fi
        echo "📦 Создаём пустой MongoDB volume: $VOLUME_NAME"
        docker volume create "$VOLUME_NAME" >/dev/null
        echo "✅ Пустой volume создан. Для production восстановите backup до run."
        ;;

    "run")
        require_runtime_files
        if [ -n "$TOKEN_FILE" ]; then
            COMPOSE_FILES+=(-f compose.secret.yaml)
        fi
        if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
            echo "❌ Docker image $IMAGE_NAME не найден. Сначала выполните: $0 build"
            exit 1
        fi
        if ! docker volume inspect "$VOLUME_NAME" >/dev/null 2>&1; then
            echo "❌ MongoDB volume не найден: $VOLUME_NAME"
            echo "   Новая установка: $0 bootstrap"
            echo "   Production: не запускайте бота до восстановления нужного volume/backup."
            exit 1
        fi

        LEGACY_STOPPED=false
        if legacy_container_exists; then
            echo "⏸️ Останавливаем старый compatibility-контейнер без удаления..."
            docker stop "$LEGACY_CONTAINER_NAME"
            LEGACY_STOPPED=true
        fi

        echo "🚀 Запускаем отдельные сервисы MongoDB и бота..."
        if ! compose_up; then
            echo "❌ Сервисы не прошли healthcheck. Последние логи:"
            run_compose logs --tail 80 || true
            rollback_after_failed_deploy || true
            exit 1
        fi

        if ! BOT_CONTAINER_ID="$(run_compose ps -q bot)" || [ -z "$BOT_CONTAINER_ID" ]; then
            echo "❌ Не удалось определить container бота после deploy."
            rollback_after_failed_deploy || true
            exit 1
        fi
        if ! BOT_STATE="$(docker inspect -f '{{.State.Status}} {{.State.Health.Status}} {{.RestartCount}}' "$BOT_CONTAINER_ID")"; then
            echo "❌ Не удалось проверить состояние container бота после deploy."
            rollback_after_failed_deploy || true
            exit 1
        fi
        if [ "$BOT_STATE" != "running healthy 0" ]; then
            echo "❌ Process healthcheck бота не пройден: $BOT_STATE"
            run_compose logs --tail 80 || true
            rollback_after_failed_deploy || true
            exit 1
        fi

        if [ "$LEGACY_STOPPED" = "true" ]; then
            docker rm "$LEGACY_CONTAINER_NAME"
        fi
        if ! docker tag "$IMAGE_NAME" "$PREVIOUS_IMAGE_NAME"; then
            echo "⚠️ Сервисы здоровы, но не удалось обновить rollback tag $PREVIOUS_IMAGE_NAME."
        fi
        echo "✅ MongoDB здорова, process бота запущен без restart."
        echo "📝 Логи: $0 logs"
        echo "🛑 Остановить: $0 stop"
        ;;

    "stop")
        echo "🛑 Останавливаем сервисы без удаления данных..."
        run_compose down
        if legacy_container_exists; then
            docker stop "$LEGACY_CONTAINER_NAME"
            docker rm "$LEGACY_CONTAINER_NAME"
        fi
        echo "✅ Сервисы остановлены. MongoDB volume сохранён."
        ;;

    "logs")
        run_compose logs -f bot mongo
        ;;

    "status")
        run_compose ps
        ;;

    "restart")
        # run сам безопасно пересоздаёт Compose services и сохраняет
        # legacy container до успешного healthcheck нового stack.
        "$0" run
        ;;

    "clean")
        if [ "${MTLA_JOIN_BOT_CONFIRM_CLEAN:-}" != "YES" ]; then
            echo "❌ clean удаляет Docker volume со всей MongoDB."
            echo "После проверенного backup повторите с MTLA_JOIN_BOT_CONFIRM_CLEAN=YES."
            exit 1
        fi
        echo "🧹 Удаляем сервисы, MongoDB volume и локальный image..."
        run_compose down --remove-orphans
        if docker volume inspect "$VOLUME_NAME" >/dev/null 2>&1; then
            docker volume rm "$VOLUME_NAME"
        fi
        if docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
            docker image rm "$IMAGE_NAME"
        fi
        if docker image inspect "$PREVIOUS_IMAGE_NAME" >/dev/null 2>&1; then
            docker image rm "$PREVIOUS_IMAGE_NAME"
        fi
        echo "✅ Сервисы, данные и image удалены."
        ;;

    "shell")
        run_compose exec bot /bin/bash
        ;;

    "help"|*)
        echo "🐳 MTLA Join Bot — Docker Compose"
        echo "Использование: $0 <build|bootstrap|run|stop|logs|status|restart|clean|shell>"
        echo "bootstrap явно создаёт пустой MongoDB volume для новой установки."
        echo "clean требует MTLA_JOIN_BOT_CONFIRM_CLEAN=YES и удаляет MongoDB volume."
        ;;
esac
