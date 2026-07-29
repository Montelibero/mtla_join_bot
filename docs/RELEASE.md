# Релиз и миграция production

Production обычно запускает `ghcr.io/montelibero/mtla_join_bot:latest`. Каждый
релиз также публикуется с неизменяемыми тегами версии и коммита, поэтому для
отката не нужно полагаться на изменяемый `latest`.

## Однократная настройка GitHub

1. Установить read-only права workflow по умолчанию.
2. После успешного запуска CI сделать workflow `CI` обязательным для `main`.
3. Отправить первый release tag и дождаться завершения
   `Release container image`.
4. Открыть настройки нового package `montelibero/mtla_join_bot` и сделать его
   публичным. Если package должен остаться приватным, вместо этого добавить в
   Portainer read-only учётные данные GHCR.

Для релиза `v0.2.0` workflow публикует:

- `latest` для обычного production deployment;
- `v0.2.0` и `0.2.0` для явного deployment и отката;
- `sha-<commit>` для точной связи образа с исходным кодом.

## Создание релиза

Начать с актуальной и проверенной ветки `main`:

```bash
git switch main
git pull --ff-only
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -q
git tag -a v0.2.0 -m "Release v0.2.0"
git push origin v0.2.0
```

Дождаться завершения workflow `Release container image`. До deployment записать
digest образа, показанный workflow.

## Первая миграция со старого all-in-one образа

Старый контейнер запускает одновременно бота и MongoDB. Нельзя запускать новый
сервис MongoDB с volume `mtla_join_bot_data`, пока старый контейнер работает.

До окна обслуживания:

1. Убедиться, что volume `mtla_join_bot_data` существует на узле `docker3`.
2. Убедиться, что существует внешний secret
   `MTLA_JOIN_BOT_TELEGRAM_TOKEN`.
3. Задать `ADMIN_IDS` в environment variables стека Portainer.
4. Опубликовать и проверить новый GHCR image.
5. Сохранить старый образ под отдельным rollback-тегом:

   ```bash
   docker tag mtla_join_bot:latest mtla_join_bot:legacy-2025
   ```

6. При необходимости сделать логический backup, пока старый сервис ещё
   работает:

   ```bash
   OLD_CONTAINER_ID="$(docker ps --filter name=mtla_join_bot_mtla_join_bot --format '{{.ID}}' | head -n 1)"
   test -n "$OLD_CONTAINER_ID"
   docker exec "$OLD_CONTAINER_ID" mongodump \
     --db mtla_join_bot --archive --gzip \
     > "mtla_join_bot-before-split.archive.gz"
   test -s "mtla_join_bot-before-split.archive.gz"
   gzip -t "mtla_join_bot-before-split.archive.gz"
   ```

Во время окна обслуживания:

1. Масштабировать старый сервис `mtla_join_bot_mtla_join_bot` до нуля и
   дождаться остановки его task. Это корректно остановит встроенный `mongod`.
2. Заменить определение стека в Portainer содержимым
   `deploy/portainer-stack.yml`.
3. Оставить `image: ghcr.io/montelibero/mtla_join_bot:latest` и обновить стек.
4. Дождаться состояния `1/1` у обоих сервисов.
5. Проверить healthcheck MongoDB, restart count и логи бота, затем выполнить
   одно реальное действие в Telegram.

Отдельный сервис MongoDB напрямую использует прежний внешний volume, поэтому
restore не требуется. Пока MongoDB запускается, бот может один раз
перезапуститься.

## Обычный deployment

После того как release workflow обновил `latest`, обновить стек в Portainer,
чтобы Swarm получил новый digest из registry. В stack-файле остаётся:

```yaml
image: ghcr.io/montelibero/mtla_join_bot:latest
```

Проверить, что task использует digest из release workflow, сервис имеет `1/1`
реплику и restart count не растёт. Затем проверить `/start` в Telegram.

## Откат обычного релиза

Заменить в Portainer образ бота с `latest` на предыдущий неизменяемый тег:

```yaml
image: ghcr.io/montelibero/mtla_join_bot:v0.1.0
```

Обновить стек и проверить digest, реплики, restart count, логи и одно действие
в Telegram. Не перемещать и не перезаписывать старый version tag.

## Откат во время первого разделения MongoDB

Если первый deployment с отдельной MongoDB не принят:

1. Масштабировать новые сервисы бота и MongoDB до нуля и дождаться их остановки.
2. Вернуть прежнее односервисное определение стека.
3. Указать образ `mtla_join_bot:legacy-2025`.
4. Сохранить тот же внешний volume `mtla_join_bot_data` и внешний Telegram
   secret.
5. Развернуть старый стек и проверить бота до удаления каких-либо ресурсов.

Никогда не запускать встроенный старый `mongod` и отдельный сервис MongoDB с
одним и тем же volume одновременно.
