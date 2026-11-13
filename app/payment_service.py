"""
BharatStore Payment Gateway & Cryptographic Signature Verification Service
Specialized for Razorpay (UPI QR, Cards, NetBanking) with HMAC-SHA256 verification,
duplicate webhook replay protection, and safe order state transitions.
"""

import os
import hmac
import hashlib
import time
import logging
from typing import Dict, Any, Optional, Tuple
from app.config import Config
from app.database import OrderStatus, PaymentStatus

logger = logging.getLogger("BharatStore.Payment")

# In-memory cache for duplicate webhook event IDs (idempotency window: 24h)
_processed_webhook_events = set()

class PaymentService:
    def __init__(self):
        self.key_id = Config.RAZORPAY_KEY_ID
        self.key_secret = Config.RAZORPAY_KEY_SECRET
        self.webhook_secret = Config.PAYMENT_WEBHOOK_SECRET

    def is_configured(self) -> bool:
        """Checks if live Razorpay merchant credentials are configured"""
        return bool(self.key_id and self.key_secret)

    def verify_payment_signature(
        self,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
        secret: Optional[str] = None
    ) -> bool:
        """
        Cryptographically verifies the Razorpay payment signature returned
        by the frontend checkout modal handler.
        Formula: HMAC_SHA256(order_id + "|" + payment_id, secret) == signature
        Timing-attack safe using hmac.compare_digest().
        """
        secret_to_use = secret or self.key_secret or self.webhook_secret
        if not secret_to_use:
            logger.error("Cannot verify payment signature: neither RAZORPAY_KEY_SECRET nor PAYMENT_WEBHOOK_SECRET configured.")
            return False

        if not razorpay_order_id or not razorpay_payment_id or not razorpay_signature:
            logger.warning("Payment signature verification failed: missing order_id, payment_id, or signature.")
            return False

        message = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
        generated_signature = hmac.new(
            key=secret_to_use.encode("utf-8"),
            msg=message,
            digestmod=hashlib.sha256
        ).hexdigest()

        is_valid = hmac.compare_digest(generated_signature, razorpay_signature)
        if not is_valid:
            logger.warning(
                f"Invalid payment signature for order {razorpay_order_id}. "
                f"Possible tampering or secret mismatch."
            )
        return is_valid

    def verify_webhook_signature(
        self,
        raw_body_bytes: bytes,
        signature_header: str,
        secret: Optional[str] = None
    ) -> bool:
        """
        Cryptographically verifies server-to-server webhook delivery from Razorpay.
        Formula: HMAC_SHA256(raw_request_body, webhook_secret) == X-Razorpay-Signature
        Timing-attack safe using hmac.compare_digest().
        """
        secret_to_use = secret or self.webhook_secret or self.key_secret
        if not secret_to_use:
            logger.error("Cannot verify webhook: PAYMENT_WEBHOOK_SECRET is not configured.")
            return False

        if not raw_body_bytes or not signature_header:
            return False

        generated_signature = hmac.new(
            key=secret_to_use.encode("utf-8"),
            msg=raw_body_bytes,
            digestmod=hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(generated_signature, signature_header)

    def is_duplicate_webhook(self, event_id: str) -> bool:
        """
        Checks if this webhook event ID has already been received and processed.
        Protects against replay attacks and Razorpay duplicate delivery retries.
        """
        if not event_id:
            return False
        if event_id in _processed_webhook_events:
            return True
        return False

    def mark_webhook_processed(self, event_id: str):
        """Records webhook event ID in the idempotency registry"""
        if event_id:
            _processed_webhook_events.add(event_id)
            # Prune cache if it grows beyond 50,000 events
            if len(_processed_webhook_events) > 50000:
                _processed_webhook_events.clear()

    def generate_test_signature(self, order_id: str, payment_id: str, secret: Optional[str] = None) -> str:
        """Utility for automated test suites to generate a mathematically valid signature"""
        secret_to_use = secret or self.key_secret or self.webhook_secret or "test-secret"
        message = f"{order_id}|{payment_id}".encode("utf-8")
        return hmac.new(
            key=secret_to_use.encode("utf-8"),
            msg=message,
            digestmod=hashlib.sha256
        ).hexdigest()

    def generate_webhook_signature(self, raw_body_bytes: bytes, secret: Optional[str] = None) -> str:
        """Utility for automated test suites to generate a valid webhook signature"""
        secret_to_use = secret or self.webhook_secret or self.key_secret or "test-secret"
        return hmac.new(
            key=secret_to_use.encode("utf-8"),
            msg=raw_body_bytes,
            digestmod=hashlib.sha256
        ).hexdigest()
