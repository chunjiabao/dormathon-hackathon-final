FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 \
    EMBEDDING_CACHE_DIR=/app/.models HF_HUB_DISABLE_TELEMETRY=1
COPY --from=ghcr.io/astral-sh/uv:0.8.0 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project
COPY . .
# Bake the local embedding model (all-MiniLM-L6-v2, ONNX) into the image: no runtime download.
RUN uv run --no-dev python -c "from app.services.embeddings import warm; warm()"
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser
EXPOSE 8000
CMD ["sh", "-c", "uv run --no-dev alembic upgrade head && uv run --no-dev python -m app.jobs.bootstrap && uv run --no-dev uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
