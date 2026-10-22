# 交付镜像：前端（Vite 构建）+ 后端（FastAPI）+ EPUBCheck
FROM node:22-slim AS web
WORKDIR /w
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim-trixie
ARG EPUBCHECK_VERSION=5.4.0
RUN apt-get update \
 && apt-get install -y --no-install-recommends default-jre-headless curl unzip \
 && curl -fsSL -o /tmp/epubcheck.zip \
      https://github.com/w3c/epubcheck/releases/download/v${EPUBCHECK_VERSION}/epubcheck-${EPUBCHECK_VERSION}.zip \
 && unzip -q /tmp/epubcheck.zip -d /opt \
 && mv /opt/epubcheck-${EPUBCHECK_VERSION} /opt/epubcheck \
 && printf '#!/bin/sh\nexec java -jar /opt/epubcheck/epubcheck.jar "$@"\n' > /usr/local/bin/epubcheck \
 && chmod +x /usr/local/bin/epubcheck \
 && rm /tmp/epubcheck.zip && apt-get purge -y curl unzip && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd -u 1000 -m app && mkdir -p /data && chown app /data
COPY --from=web /w/dist /app/static

# UTF-8 locale：否则 epubcheck(Java) 打不开中文文件名且不报错
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8 EPUBTS_DATA=/data EPUBTS_STATIC=/app/static
USER app
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["uvicorn", "epub_typesetter.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
