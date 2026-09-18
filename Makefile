.PHONY: dev test lint

dev:
	streamlit run src/ui/app.py

test:
	pytest -v

lint:
	ruff check src tests scripts
	ruff format --check src tests scripts
