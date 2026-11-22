"""
Gunicorn Production Server Configuration for Render & BharatStore
Ensures fail-safe port binding to 0.0.0.0:$PORT with optimal gthread worker pooling.
"""
import os

# Render dynamically assigns the PORT environment variable (e.g. 10000)
port = os.environ.get("PORT", "10000").strip()
bind = f"0.0.0.0:{port}"

# Worker & Thread Architecture:
# Engineered for Aiven PostgreSQL capacity (20 total max connections, 3 superuser reserved = 17 slots).
# Render sets WEB_CONCURRENCY=2 by default on standard dynos, which would double connection pools.
# During zero-downtime rolling deploys, 2 containers run in parallel.
# Running 1 worker process with 4 gthread threads guarantees:
# 2 containers * 1 worker * 3 maxconn = 6 connections total (well under 17).
raw_workers = os.environ.get("GUNICORN_WORKERS") or os.environ.get("WEB_CONCURRENCY") or "1"
try:
    workers = min(int(raw_workers), 2)
except (ValueError, TypeError):
    workers = 1

# Enforce 1 worker by default on Render unless explicitly overridden via GUNICORN_WORKERS
if not os.environ.get("GUNICORN_WORKERS"):
    workers = 1

worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", "4"))

# Timeouts: allow ample time for graceful shutdowns without hanging
timeout = 120
graceful_timeout = 30
keepalive = 5

# Logging: output stdout/stderr directly to Render log streams
accesslog = "-"
errorlog = "-"
loglevel = "info"

def post_fork(server, worker):
    """
    Hook called immediately after a worker process is forked.
    Ensures that each worker initializes an isolated PostgreSQL connection pool
    instead of inheriting parent sockets across fork.
    """
    try:
        from app.routes import db_service
        db_service.reset_connection_pool()
    except Exception:
        pass
