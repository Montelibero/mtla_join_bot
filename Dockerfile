FROM python:3.11-slim-bookworm@sha256:b18992999dbe963a45a8a4da40ac2b1975be1a776d939d098c647482bcad5cba

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system mtla \
    && useradd --system --gid mtla --home-dir /app mtla

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py ./
COPY src ./src

RUN mkdir -p /run/secrets \
    && chown -R mtla:mtla /app /run/secrets

USER mtla

HEALTHCHECK --interval=5s --timeout=2s --start-period=10s --retries=3 \
    CMD ["python", "-c", "from pathlib import Path; raise SystemExit(0 if b'main.py' in Path('/proc/1/cmdline').read_bytes() else 1)"]

CMD ["python", "main.py"]
