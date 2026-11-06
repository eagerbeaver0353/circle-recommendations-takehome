# Lean In Circle Recommendations — simple production-style API image.
# Does not seed the database at build or container start.
FROM python:3.12-slim

WORKDIR /app

# Non-root runtime user. /app/state is the SQLite volume mount point and must
# remain writable without host-side permission fixes.
RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /app/state \
    && chown app:app /app/state

# Dependency layer first for better build caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application package and committed JSON fixtures (not a generated SQLite DB).
COPY app/ ./app/
COPY data/*.json ./data/

USER app

EXPOSE 8000

# /health returns 503 until the database has been seeded explicitly.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
