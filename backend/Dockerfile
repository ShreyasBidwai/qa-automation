# syntax=docker/dockerfile:1
# Multi-stage build (Engineering Standards §17): install dependencies into an
# isolated venv in a builder stage, then copy only the venv + app into a minimal
# runtime image that runs as a non-root user.

# ---- builder ---------------------------------------------------------------
FROM python:3.12.7-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app
RUN python -m venv /opt/venv
COPY requirements.txt ./
RUN pip install -r requirements.txt

# ---- runtime ---------------------------------------------------------------
FROM python:3.12.7-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Non-root system user (Standards §17).
RUN groupadd --system app \
    && useradd --system --gid app --no-create-home --home-dir /app app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app app ./app

USER app
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
