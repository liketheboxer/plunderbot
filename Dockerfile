FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Run as a non-root user that owns /data (Exocomp mounts the unit's volume there).
RUN useradd --create-home --uid 10001 plunderbot \
    && mkdir -p /data \
    && chown plunderbot:plunderbot /data
USER plunderbot

# on_ready touches /tmp/ready; a bot that starts but never connects fails the deploy.
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s CMD test -f /tmp/ready

CMD ["python", "bot.py"]
