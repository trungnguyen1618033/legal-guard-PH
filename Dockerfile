# syntax=docker/dockerfile:1
FROM python:3.12-slim

# uv — trình quản lý dependency
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

# antiword: bóc text Word 97–2003 (.doc) — SME VN gửi định dạng này rất nhiều
RUN apt-get update && apt-get install -y --no-install-recommends antiword \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cài deps trước (tận dụng cache layer khi code đổi mà deps không đổi)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy mã nguồn
COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 8000

# Migrate schema rồi chạy API (prod). Compose override khi dev (thêm --reload).
CMD ["sh", "-c", "alembic upgrade head && uvicorn app:app --host 0.0.0.0 --port 8000"]
