FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.20 /uv /uvx /bin/

WORKDIR /code

# 先只裝依賴，程式碼改動時可以沿用這一層快取
COPY ./pyproject.toml ./README.md ./uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY ./pricing_advisor ./pricing_advisor
RUN uv sync --frozen --no-dev

ARG AGENT_VERSION=0.0.0
# 知識庫由 docker-compose.advisor.yml 以唯讀方式掛到 /knowledge/ezstore
ENV AGENT_VERSION=${AGENT_VERSION} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OKF_BUNDLE=/knowledge/ezstore

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=10 \
  CMD uv run --no-sync python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/list-apps', timeout=4).status == 200 else 1)"

CMD ["uv", "run", "--no-sync", "uvicorn", "pricing_advisor.fast_api_app:app", "--host", "0.0.0.0", "--port", "8080"]
