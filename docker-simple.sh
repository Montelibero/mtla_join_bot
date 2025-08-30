#!/bin/bash

# Простой скрипт для работы с MTLA Join Bot в Docker

set -e

CONTAINER_NAME="mtla-join-bot"
IMAGE_NAME="mtla-join-bot"
VOLUME_NAME="mtla_join_bot_data"

case "${1:-help}" in
    "build")
        echo "🔨 Собираем Docker образ..."
        docker build -t $IMAGE_NAME .
        echo "✅ Образ собран!"
        ;;
    
    "run")
        echo "🚀 Запускаем контейнер..."
        
        # Останавливаем существующий контейнер если есть
        docker stop $CONTAINER_NAME 2>/dev/null || true
        docker rm $CONTAINER_NAME 2>/dev/null || true
        
        # Запускаем контейнер
        docker run -d \
            --name $CONTAINER_NAME \
            --restart unless-stopped \
            -v $VOLUME_NAME:/data/db \
            -w /app \
            $IMAGE_NAME
        
        echo "✅ Контейнер запущен!"
        echo "📝 Логи: $0 logs"
        echo "🛑 Остановить: $0 stop"
        ;;
    
    "stop")
        echo "🛑 Останавливаем контейнер..."
        docker stop $CONTAINER_NAME 2>/dev/null || true
        docker rm $CONTAINER_NAME 2>/dev/null || true
        echo "✅ Контейнер остановлен!"
        ;;
    
    "logs")
        echo "📝 Показываем логи..."
        docker logs -f $CONTAINER_NAME
        ;;
    
    "status")
        echo "📊 Статус контейнера:"
        docker ps -a --filter name=$CONTAINER_NAME
        ;;
    
    "restart")
        echo "🔄 Перезапускаем контейнер..."
        $0 stop
        $0 run
        ;;
    
    "clean")
        echo "🧹 Очищаем всё..."
        $0 stop
        docker volume rm $VOLUME_NAME 2>/dev/null || true
        docker rmi $IMAGE_NAME 2>/dev/null || true
        echo "✅ Всё очищено!"
        ;;
    
    "shell")
        echo "🐚 Заходим в контейнер..."
        docker exec -it $CONTAINER_NAME /bin/bash
        ;;
    
    "help"|*)
        echo "🐳 MTLA Join Bot - простые Docker команды"
        echo ""
        echo "Использование: $0 <команда>"
        echo ""
        echo "Команды:"
        echo "  build   - собрать образ"
        echo "  run     - запустить контейнер"
        echo "  stop    - остановить контейнер"
        echo "  logs    - показать логи"
        echo "  status  - статус контейнера"
        echo "  restart - перезапустить"
        echo "  clean   - очистить всё (образ + данные)"
        echo "  shell   - войти в контейнер"
        echo "  help    - показать эту справку"
        echo ""
        echo "Примеры:"
        echo "  $0 build && $0 run    # собрать и запустить"
        echo "  $0 logs               # смотреть логи"
        echo "  $0 stop               # остановить"
        ;;
esac
