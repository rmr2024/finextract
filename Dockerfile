# finextract API + dashboard.
#   docker build -t finextract .
#   docker run --rm -p 127.0.0.1:8000:8000 -v "${PWD}/data:/app/data" finextract
# The container binds 0.0.0.0 (required inside Docker); publishing to 127.0.0.1 on the host keeps it
# reachable from this machine only. There is no auth, so don't publish it on a public interface.
# Secrets are never baked in: pass provider keys at run time with --env-file .env if you need them.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install ".[api]" && useradd --create-home app && mkdir -p /app/data && chown app /app/data
USER app

EXPOSE 8000
CMD ["finextract", "--data-dir", "/app/data", "serve", "--host", "0.0.0.0", "--port", "8000"]
