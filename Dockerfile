# InvoiceAI — single container running both the API and the Streamlit UI.
#
# The API always binds 127.0.0.1 inside the container (see src/launcher.py): it is never
# reachable from outside it, on purpose. A container's 127.0.0.1 is only reachable from
# *inside* that same container though, so the UI alone is widened to 0.0.0.0 here — otherwise
# Docker's own port publishing (`-p`) could never reach it either. What actually controls
# exposure to the host is the `-p 127.0.0.1:...` mapping at `docker run`/compose time, not
# this bind address: run it any other way and the UI would be reachable from the network.
FROM python:3.11-slim AS base

# Keeps builds reproducible and Python from writing .pyc files / buffering logs.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UI_HOST=0.0.0.0

WORKDIR /app

# Dependencies first: this layer is only rebuilt when requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY scripts ./scripts
COPY .streamlit ./.streamlit
COPY pyproject.toml .

# Least privilege: the app never runs as root.
RUN useradd --create-home --uid 1000 invoiceai \
    && mkdir -p /app/data \
    && chown -R invoiceai:invoiceai /app
USER invoiceai

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

# --no-browser: there is no display in a container. Secrets come from --env-file at `docker run`,
# never baked into the image (see .dockerignore).
CMD ["python", "scripts/run.py", "--no-browser"]
