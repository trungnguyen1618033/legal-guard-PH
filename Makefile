.DEFAULT_GOAL := help
COMPOSE := docker compose

.PHONY: help env up down clean logs migrate psql sh test lint smoke run build

help:  ## Liệt kê các lệnh
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n",$$1,$$2}'

env:  ## Tạo .env từ .env.example nếu chưa có
	@test -f .env || cp .env.example .env

up: env  ## Build + chạy app + postgres (http://localhost:8000)
	$(COMPOSE) up --build

down:  ## Dừng và xóa container (giữ volume DB)
	$(COMPOSE) down

clean:  ## Dừng và XÓA luôn volume DB
	$(COMPOSE) down -v

logs:  ## Theo dõi log app
	$(COMPOSE) logs -f app

migrate:  ## Chạy alembic upgrade trong container
	$(COMPOSE) exec app alembic upgrade head

psql:  ## Mở psql vào postgres
	$(COMPOSE) exec db psql -U legalguard

redis-cli:  ## Mở redis-cli
	$(COMPOSE) exec redis redis-cli

sh:  ## Mở shell vào container app
	$(COMPOSE) exec app sh

test:  ## Chạy test (local, sqlite stub)
	uv run pytest -q

lint:  ## Lint (local)
	uv run ruff check .

smoke:  ## Live smoke test — gọi endpoint THẬT trên deploy (BASE=... đổi URL, SKIP_LLM=1 bỏ endpoint chậm)
	bash scripts/live_smoke.sh

run:  ## Chạy local KHÔNG docker (sqlite mặc định)
	uv run uvicorn app:app --reload

mcp:  ## Chạy MCP server (stdio) — cho Qwen-Agent/Claude/IDE dùng tool analyze_contract
	uv run python -m legalguard.adapters.inbound.mcp_server
