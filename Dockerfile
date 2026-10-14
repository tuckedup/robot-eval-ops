# Offline CPU image: no GPU, no credentials, no robot access. Hardware commands refuse inside it.
# Dependencies come from uv.lock (--locked: the build FAILS if the lock is stale); the project is installed
# NON-editable so the container exercises the same packaged code a wheel user gets.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 ROBOTEVALOPS_HOME=/data UV_COMPILE_BYTECODE=0 PATH="/app/.venv/bin:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable --extra sim --extra dashboard
VOLUME /data
ENTRYPOINT ["robotevalops"]
CMD ["--help"]
