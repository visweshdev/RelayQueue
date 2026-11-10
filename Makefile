.PHONY: up down lint types unit test chaos bench demo
up:
	docker compose up -d --build
down:
	docker compose down
lint:
	python -m ruff check src tests bench migrations
	python -m ruff format --check src tests bench migrations
types:
	python -m mypy --strict src
unit:
	python -m pytest tests/unit -q
test:
	python -m pytest tests/unit tests/integration --cov=relayqueue --cov-report=term-missing --cov-fail-under=85
chaos:
	RUN_CHAOS=1 python -m pytest tests/chaos -v
bench:
	python -m bench.throughput --jobs 20000 --workers 4
demo:
	python -m bench.demo
