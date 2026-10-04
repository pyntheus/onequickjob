# API production-style image: the same Python and dependencies as the dev image, with the
# code and seed data baked in (no bind mounts, no auto-reload). One worker, because the
# periodic tasks run inside the API process (app.core.tasks).
FROM ghcr.io/astral-sh/uv:0.12.22-trixie-slim
ENV UV_PYTHON_PREFERENCE=only-managed \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    SEED_DIR=/app/seed \
    FILES_DIR=/data/files
WORKDIR /app/api
COPY api/pyproject.toml api/uv.lock api/.python-version ./
RUN uv python install && uv sync --frozen --no-install-project --no-dev
COPY api/app ./app
COPY seed /app/seed
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
