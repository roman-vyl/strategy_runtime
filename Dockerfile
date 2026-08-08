FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system strategy-runtime \
    && adduser --system --ingroup strategy-runtime --home /nonexistent --shell /usr/sbin/nologin strategy-runtime

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --upgrade pip \
    && pip install .

USER strategy-runtime

EXPOSE 8093

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 CMD python -c "import os, urllib.request; port = os.environ.get('RUNTIME_PORT', '8093'); urllib.request.urlopen(f'http://127.0.0.1:{port}/health/ready', timeout=2).read()"

ENTRYPOINT ["strategy-runtime"]
