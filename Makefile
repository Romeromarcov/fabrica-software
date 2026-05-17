.PHONY: up down restart logs shell build openclaw-up openclaw-down openclaw-logs token

## Levantar todo: OpenClaw + Fábrica de Software
up:
	docker compose up -d --build
	@echo ""
	@echo "  Fábrica UI  → http://localhost:7860"
	@echo "  OpenClaw    → http://localhost:18789"
	@echo ""

## Parar todo
down:
	docker compose down

## Reiniciar solo el orquestador (tras cambiar .env)
restart:
	docker compose restart fabrica

## Logs en tiempo real de ambos servicios
logs:
	docker compose logs -f

## Shell dentro del orquestador
shell:
	docker compose exec fabrica /bin/bash

## Solo construir imágenes sin levantar
build:
	docker compose build --no-cache

## ── OpenClaw ──────────────────────────────────────────────────────────────────

## Solo levantar OpenClaw (útil para testear sin el orquestador)
openclaw-up:
	docker compose up -d openclaw
	@echo "OpenClaw → http://localhost:18789"

## Solo parar OpenClaw
openclaw-down:
	docker compose stop openclaw

## Logs de OpenClaw
openclaw-logs:
	docker compose logs -f openclaw

## ── Utilidades ────────────────────────────────────────────────────────────────

## Generar un OPENCLAW_GATEWAY_TOKEN aleatorio
token:
	@python -c "import secrets; print(secrets.token_hex(32))"
