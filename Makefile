# The API listens on 127.0.0.1 only (V1 = one local user): never expose it as is.
# --no-access-log: searches travel in the URL (?q=Orange), the access log would record them.
.PHONY: dev api test lint

dev:
	streamlit run src/ui/app.py

api:
	uvicorn src.api.app:app --host 127.0.0.1 --port 8000 --no-access-log --no-server-header

test:
	pytest -v

lint:
	ruff check src tests scripts
	ruff format --check src tests scripts
