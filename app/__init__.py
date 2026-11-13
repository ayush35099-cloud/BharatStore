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
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    CORS(app)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    from app.routes import main_bp
    app.register_blueprint(main_bp)

    return app
