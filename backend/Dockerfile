FROM python:3.12-slim

# Set by the release workflow, shown in the portal footer
ARG APP_VERSION=dev

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    DATA_DIR=/data \
    APP_VERSION=${APP_VERSION}

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Run as an unprivileged user that owns only the data folder.
RUN useradd --system --uid 1000 --create-home officehub \
    && mkdir -p /data \
    && chown officehub:officehub /data

COPY app ./app

USER officehub
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
