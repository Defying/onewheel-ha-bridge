FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/onewheel-ha-bridge-venv \
    PATH="/opt/onewheel-ha-bridge-venv/bin:$PATH"

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /uvx /usr/local/bin/
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv sync --no-dev --no-editable \
    && rm -rf /usr/local/lib/python*/site-packages/pip* /usr/local/bin/pip*

USER nobody
ENTRYPOINT ["onewheel-ha-bridge"]
CMD ["--config", "/config/config.toml"]
