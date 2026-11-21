web: gunicorn run:app --bind 0.0.0.0:$PORT --workers 2 --worker-class gthread --threads 8 --timeout 120 --graceful-timeout 30 --access-logfile - --error-logfile -
