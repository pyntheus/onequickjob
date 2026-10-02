# API dev image: Python 3.14 installed and pinned by uv (api/.python-version), deps from
# uv.lock into /opt/venv. Source is bind-mounted at /app/api; nothing is written into it
# (no bytecode, no pytest cache), so the worktree never gets root-owned files.
FROM ghcr.io/astral-sh/uv:0.12.22-trixie-slim
ENV UV_PYTHON_PREFERENCE=only-managed \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH
WORKDIR /app/api
COPY api/pyproject.toml api/uv.lock api/.python-version ./
RUN uv python install && uv sync --frozen --no-install-project
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
