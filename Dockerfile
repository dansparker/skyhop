FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt requirements-postgres.txt ./
RUN pip install -r requirements.txt -r requirements-postgres.txt

COPY . .
RUN useradd --create-home --uid 10001 skyhop \
    && mkdir -p /app/instance/uploads \
    && chown -R skyhop:skyhop /app/instance \
    && chmod +x deploy/docker/entrypoint.sh

USER skyhop
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"

ENTRYPOINT ["deploy/docker/entrypoint.sh"]
CMD ["gunicorn", "--workers", "3", "--bind", "0.0.0.0:8000", "--access-logfile", "-", "--forwarded-allow-ips", "*", "wsgi:app"]
