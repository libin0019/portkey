FROM python:3.12-slim

ARG APP_VERSION=0.3.0

LABEL org.opencontainers.image.title="WeCom to Feishu Router" \
    org.opencontainers.image.version="${APP_VERSION}" \
    org.opencontainers.image.description="WeCom group bot compatible webhook router for Feishu" \
    org.opencontainers.image.source="https://github.com/libin0019/portkey"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml requirements.lock README.md ./
COPY src ./src
RUN pip install --no-cache-dir --requirement requirements.lock \
    && pip install --no-cache-dir --no-deps .

RUN useradd --create-home --uid 10001 router \
    && mkdir -p /app/data \
    && chown -R router:router /app

USER router
EXPOSE 8000

CMD ["uvicorn", "wecom_feishu_router.main:build_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
