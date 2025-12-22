.PHONY: help build up down restart migrate seed logs shell test

help:
	@echo "available targets: build up down restart migrate seed logs shell"

build:
	docker-compose build

up:
	docker-compose up -d --build

up-db:
	docker-compose up -d --build db

down:
	docker-compose down

down-v:
	docker-compose down -v

restart:
	docker-compose down
	docker-compose up -d --build
	docker-compose logs -f 

restart-app:
	docker-compose down app
	docker-compose up -d --build app
	docker-compose logs -f app


migrate:
# 	docker-compose run --rm app python -m alembic upgrade head
	docker-compose run --rm app alembic upgrade head

db-shell:
	docker-compose exec db psql -U postgres -d crm_bot
# \dt        -- список таблиц
# \du        -- пользователи
# \l         -- базы
# \q         -- выйти


seed:
	docker-compose run --rm app python -m crm_bot.scripts.seed_admin

logs:
	docker-compose logs -f app
ps:
	docker-compose ps 

shell:
	docker-compose run --rm app sh

close-shifts:
	docker-compose run --rm app python -m crm_bot.scripts.close_shifts

test:
	docker-compose build app
	docker-compose run --rm \
		-e TEST_DATABASE_URL=sqlite:///./tmp_test.db \
		-e PYTHONPATH=/usr/src/app \
		app pytest -vv
