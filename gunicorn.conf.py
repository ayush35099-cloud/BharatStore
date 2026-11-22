"""
Gunicorn Production Server Configuration for Render & BharatStore
Ensures fail-safe port binding to 0.0.0.0:$PORT with optimal gthread worker pooling.
"""
import os

# Render dynamically assigns the PORT environment variable (e.g. 10000)
port = os.environ.get("PORT", "10000").strip()
bind = f"0.0.0.0:{port}"

# High-concurrency threaded workers for real-time SSE streams and fast responses
workers = 2
worker_class = "gthread"
threads = 8

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
