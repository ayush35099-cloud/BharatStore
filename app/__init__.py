import os
import logging
from flask import Flask
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
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 86400 if is_prod else 0
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if is_prod:
        app.config["SESSION_COOKIE_SECURE"] = True
    
    CORS(app)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    from app.routes import main_bp
    app.register_blueprint(main_bp)

    return app
