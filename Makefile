# TODO 13b: add an `api` target: uvicorn src.api.app:app --host 127.0.0.1 (V1 = one local user,
# never expose it as is).
.PHONY: dev test lint

dev:
	streamlit run src/ui/app.py

test:
	pytest -v

lint:
	ruff check src tests scripts
	ruff format --check src tests scripts
