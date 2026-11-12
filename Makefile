.PHONY: lint test

lint:
	uv run ruff check .
	uv run mypy -p lake_core -p lake_ingest -p lake_parsers -p lake_processors -p lake_code -p lake_retrieval -p lake_server -p lake_cli
	uv run lint-imports

test: lint
	uv run pytest
