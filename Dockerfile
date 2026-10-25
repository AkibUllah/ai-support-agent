# syntax=docker/dockerfile:1.6
# Stage 1: build the React chat UI
FROM node:26-alpine AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY ui/ ./
RUN npm run build

# Stage 2: API + built UI
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000
WORKDIR /srv/agent

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY pyproject.toml README.md ./
COPY support_agent ./support_agent
COPY data/faq.json ./data/faq.json
COPY evals ./evals
COPY --from=ui /ui/dist ./ui/dist
RUN pip install --no-deps . \
    && addgroup --system agent && adduser --system --ingroup agent agent \
    && mkdir -p /srv/agent/var && chown -R agent:agent /srv/agent

USER agent
ENV AGENT_DATABASE_PATH=/srv/agent/var/shop.db \
    AGENT_FAQ_PATH=/srv/agent/data/faq.json \
    AGENT_UI_DIR=/srv/agent/ui/dist \
    AGENT_CORS_ORIGINS=[]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/health', timeout=2).status == 200 else 1)"

CMD ["sh", "-c", "uvicorn support_agent.api.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers"]
