import os
import gzip
import logging
from flask import Flask, request
from flask_cors import CORS
from app.config import Config

def create_app():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    app = Flask(
        __name__,
        template_folder=os.path.join(base_dir, "templates"),
        static_folder=os.path.join(base_dir, "static")
    )
    app.config.from_object(Config)
    
    is_prod = Config.is_production()
    app.config["TEMPLATES_AUTO_RELOAD"] = not is_prod
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 31536000 if is_prod else 0
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if is_prod:
        app.config["SESSION_COOKIE_SECURE"] = True
    
    CORS(app)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    @app.after_request
    def optimize_response(response):
        # 1. High-efficiency browser caching for static assets
        if request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"

        # 2. Skip compression for streaming responses, non-200, or pre-encoded content
        if response.direct_passthrough or response.mimetype == "text/event-stream":
            return response
        if response.status_code not in (200, 201) or "Content-Encoding" in response.headers:
            return response

        # 3. Dynamic HTTP Gzip compression
        accept_encoding = request.headers.get("Accept-Encoding", "")
        if "gzip" in accept_encoding:
            ct = response.content_type or ""
            if any(t in ct for t in ["text/", "application/json", "application/javascript", "application/xml", "image/svg+xml"]):
                data = response.get_data()
                if len(data) >= 500:
                    compressed = gzip.compress(data, 6)
                    response.set_data(compressed)
                    response.headers["Content-Encoding"] = "gzip"
                    response.headers["Content-Length"] = len(compressed)
                    response.headers["Vary"] = "Accept-Encoding"

        return response

    @app.teardown_appcontext
    def cleanup_request_db_resources(exception=None):
        """
        Guarantees that any database connection checked out during the request lifecycle
        is safely returned to the connection pool, even if an unhandled exception occurred.
        """
        from flask import g
        conn = getattr(g, "db_conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception as e:
                logging.getLogger("BharatKart.App").warning(f"Error closing request-scoped DB connection: {e}")
            finally:
                g.db_conn = None

    from app.routes import main_bp
    app.register_blueprint(main_bp)

    return app
