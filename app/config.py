import os
import secrets
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger("BharatStore.Config")

def _resolve_secret_key() -> str:
    key = os.getenv("SECRET_KEY", "").strip()
    # Check if missing, empty, or using the default predictable placeholder
    if not key or key == "bharatkart-super-secret-key-2026":
        # Generate a cryptographically strong 256-bit random hex key
        secure_key = secrets.token_hex(32)
        logger.warning("Predictable or empty SECRET_KEY detected. Automatically generated a cryptographically secure 256-bit key.")
        return secure_key
    return key

class Config:
    PORT = int(os.getenv("PORT", 5000))
    SECRET_KEY = _resolve_secret_key()
    
    # --- Security & Checkout Controls ---
    ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "").strip()
    MAX_QUANTITY_PER_ITEM = int(os.getenv("MAX_QUANTITY_PER_ITEM", 50))
    # Test endpoints must remain disabled unless explicitly enabled.
    ALLOW_INSECURE_TEST_ENDPOINTS = (
        os.getenv("ALLOW_INSECURE_TEST_ENDPOINTS", "false").lower()
        in ("true", "1", "yes")
    )
    
    # --- Razorpay Payment Gateway ---
    RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "").strip()
    RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    PAYMENT_WEBHOOK_SECRET = os.getenv("PAYMENT_WEBHOOK_SECRET", "").strip()
    
    # --- Aiven PostgreSQL ---
    AIVEN_PG_URL = os.getenv("AIVEN_PG_URL", "").strip()
    AIVEN_PG_HOST = os.getenv("AIVEN_PG_HOST", "").strip()
    AIVEN_PG_PORT = os.getenv("AIVEN_PG_PORT", "").strip()
    AIVEN_PG_USER = os.getenv("AIVEN_PG_USER", "").strip()
    AIVEN_PG_PASSWORD = os.getenv("AIVEN_PG_PASSWORD", "").strip()
    AIVEN_PG_DATABASE = os.getenv("AIVEN_PG_DATABASE", "defaultdb").strip()
    AIVEN_PG_SSLMODE = os.getenv("AIVEN_PG_SSLMODE", "require").strip()
    
    # --- Aiven Apache Kafka ---
    AIVEN_KAFKA_BOOTSTRAP_SERVERS = os.getenv("AIVEN_KAFKA_BOOTSTRAP_SERVERS", "").strip()
    AIVEN_KAFKA_TOPIC = os.getenv("AIVEN_KAFKA_TOPIC", "order-events").strip()
    AIVEN_KAFKA_CONSUMER_GROUP = os.getenv("AIVEN_KAFKA_CONSUMER_GROUP", "bharatkart-inventory-group").strip()
    AIVEN_KAFKA_SECURITY_PROTOCOL = os.getenv("AIVEN_KAFKA_SECURITY_PROTOCOL", "SASL_SSL").strip()
    AIVEN_KAFKA_SASL_MECHANISM = os.getenv("AIVEN_KAFKA_SASL_MECHANISM", "SCRAM-SHA-256").strip()
    AIVEN_KAFKA_USERNAME = os.getenv("AIVEN_KAFKA_USERNAME", "").strip()
    AIVEN_KAFKA_PASSWORD = os.getenv("AIVEN_KAFKA_PASSWORD", "").strip()
    AIVEN_KAFKA_CA_CERT = os.getenv("AIVEN_KAFKA_CA_CERT", "").strip()
    AIVEN_KAFKA_ACCESS_CERT = os.getenv("AIVEN_KAFKA_ACCESS_CERT", "").strip()
    AIVEN_KAFKA_ACCESS_KEY = os.getenv("AIVEN_KAFKA_ACCESS_KEY", "").strip()
    
    # --- Aiven OpenSearch ---
    AIVEN_OPENSEARCH_URL = os.getenv("AIVEN_OPENSEARCH_URL", "").strip()
    AIVEN_OPENSEARCH_INDEX = os.getenv("AIVEN_OPENSEARCH_INDEX", "bharatkart-products").strip()
    AIVEN_OPENSEARCH_USER = os.getenv("AIVEN_OPENSEARCH_USER", "").strip()
    AIVEN_OPENSEARCH_PASSWORD = os.getenv("AIVEN_OPENSEARCH_PASSWORD", "").strip()

    @classmethod
    def is_pg_configured(cls) -> bool:
        return bool(cls.AIVEN_PG_URL or (cls.AIVEN_PG_HOST and cls.AIVEN_PG_USER))

    @classmethod
    def is_kafka_configured(cls) -> bool:
        return bool(cls.AIVEN_KAFKA_BOOTSTRAP_SERVERS)

    @classmethod
    def is_opensearch_configured(cls) -> bool:
        return bool(cls.AIVEN_OPENSEARCH_URL)
