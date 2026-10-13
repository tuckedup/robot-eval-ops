# Offline CPU image: no GPU, no credentials, no robot access. Hardware commands refuse inside it.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 ROBOTEVALOPS_HOME=/data
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY configs ./configs
RUN pip install --no-cache-dir uv && uv pip install --system ".[sim,dashboard]"
VOLUME /data
ENTRYPOINT ["robotevalops"]
CMD ["--help"]
