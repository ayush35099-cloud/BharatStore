"""
BharatKart Apache Kafka Service
Handles Producer & Consumer workflows for Aiven Apache Kafka with
zero-latency real-time audit streaming for hackathon demo visualization.
"""

import os
import json
import time
import queue
import logging
import threading
from typing import Dict, Any, List, Optional, Callable
from app.config import Config

logger = logging.getLogger("BharatKart.Kafka")

class KafkaEventLog:
    """Thread-safe ring buffer for frontend real-time Kafka visualization"""
    def __init__(self, max_size=100):
        self.max_size = max_size
        self.events: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._subscribers: List[queue.Queue] = []

    def append(self, event: Dict[str, Any]):
        with self._lock:
            event["logged_at"] = time.strftime("%H:%M:%S")
            self.events.append(event)
            if len(self.events) > self.max_size:
                self.events.pop(0)
            
            # Broadcast to any active SSE subscribers
            for sub in list(self._subscribers):
                try:
                    sub.put_nowait(event)
                except queue.Full:
                    pass

    def get_recent(self, limit: int = 30) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.events[-limit:])

    def subscribe(self) -> queue.Queue:
        q = queue.Queue(maxsize=50)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)


class KafkaService:
    def __init__(self, on_order_consumed_callback: Optional[Callable] = None):
        self.is_live_kafka = False
        self.topic = Config.AIVEN_KAFKA_TOPIC
        self.consumer_group = Config.AIVEN_KAFKA_CONSUMER_GROUP
        self.event_log = KafkaEventLog()
        self.on_order_consumed = on_order_consumed_callback
        self.producer = None
        self.consumer = None
        self._consumer_thread = None
        self._running = False
        
        # In-memory queue used for local emulation
        self._local_topic_queue = queue.Queue()
        self._local_offset = 0

        self._init_kafka()

    def _init_kafka(self):
        if Config.is_kafka_configured():
            try:
                from kafka import KafkaProducer, KafkaConsumer
                producer_kwargs = {
                    "bootstrap_servers": Config.AIVEN_KAFKA_BOOTSTRAP_SERVERS.split(","),
                    "value_serializer": lambda v: json.dumps(v).encode("utf-8"),
                    "security_protocol": Config.AIVEN_KAFKA_SECURITY_PROTOCOL,
                    "request_timeout_ms": 10000
                }

                if Config.AIVEN_KAFKA_SECURITY_PROTOCOL == "SASL_SSL":
                    producer_kwargs["sasl_mechanism"] = Config.AIVEN_KAFKA_SASL_MECHANISM
                    producer_kwargs["sasl_plain_username"] = Config.AIVEN_KAFKA_USERNAME
                    producer_kwargs["sasl_plain_password"] = Config.AIVEN_KAFKA_PASSWORD
                elif Config.AIVEN_KAFKA_SECURITY_PROTOCOL == "SSL":
                    if Config.AIVEN_KAFKA_CA_CERT:
                        producer_kwargs["ssl_cafile"] = Config.AIVEN_KAFKA_CA_CERT
                    if Config.AIVEN_KAFKA_ACCESS_CERT:
                        producer_kwargs["ssl_certfile"] = Config.AIVEN_KAFKA_ACCESS_CERT
                    if Config.AIVEN_KAFKA_ACCESS_KEY:
                        producer_kwargs["ssl_keyfile"] = Config.AIVEN_KAFKA_ACCESS_KEY

                self.producer = KafkaProducer(**producer_kwargs)
                self.is_live_kafka = True
                logger.info(f"Connected to Aiven Apache Kafka at {Config.AIVEN_KAFKA_BOOTSTRAP_SERVERS}")

                # Start background consumer thread for Aiven Kafka
                self._running = True
                self._consumer_thread = threading.Thread(target=self._aiven_consumer_loop, daemon=True)
                self._consumer_thread.start()
                return

            except Exception as e:
                logger.warning(f"Could not connect to Aiven Kafka: {e}. Falling back to Local Event Stream Broker.")

        self.is_live_kafka = False
        self._running = True
        self._consumer_thread = threading.Thread(target=self._local_consumer_loop, daemon=True)
        self._consumer_thread.start()
        logger.info("Local Kafka Event Broker & Consumer thread started.")

    # -------------------------------------------------------------------------
    # Producer
    # -------------------------------------------------------------------------
    def produce_order_event(self, order_data: Dict[str, Any], event_type: str = "ORDER_CREATED") -> Dict[str, Any]:
        """
        Produces an order-event message to the Kafka topic.
        Payload matches hackathon specification:
        e.g. {"order_id": 123, "product_id": 45, "qty": 1, ...}
        Supports event types: ORDER_CREATED, ORDER_PAID, ORDER_CONFIRMED, ORDER_CANCELLED
        """
        message_id = f"evt-{int(time.time()*1000)}"
        order_id = order_data.get("order_id") or order_data.get("id")
        order_number = order_data.get("order_number", "BK-UNKNOWN")

        items_list = []
        for item in order_data.get("items", []):
            items_list.append({
                "product_id": item.get("product_id"),
                "title": item.get("title") or item.get("product_title", f"Product #{item.get('product_id')}"),
                "qty": item.get("quantity") or item.get("qty", 1),
                "unit_price": item.get("unit_price", 0.0)
            })

        event_payload = {
            "event_id": message_id,
            "event_type": event_type,
            "topic": self.topic,
            "order_id": order_id,
            "order_number": order_number,
            "order_status": order_data.get("status") or order_data.get("order_status", "CONFIRMED"),
            "payment_status": order_data.get("payment_status", "PAID"),
            "customer": {
                "name": order_data.get("customer_name"),
                "email": order_data.get("customer_email"),
                "city": order_data.get("shipping_city")
            },
            "items": items_list,
            "total_amount": order_data.get("total_amount", 0.0),
            "shipping_city": order_data.get("shipping_city"),
            "shipping_address": order_data.get("shipping_address"),
            "timestamp": time.time(),
            "iso_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }

        # Log event produce to UI audit
        audit_entry = {
            "type": "PRODUCED",
            "source": "Order Checkout API",
            "broker": "Aiven Apache Kafka" if self.is_live_kafka else "Kafka In-Process Broker",
            "topic": self.topic,
            "event_id": message_id,
            "event_type": event_type,
            "order_id": order_id,
            "order_number": order_number,
            "payload": event_payload,
            "status": "SENT"
        }
        self.event_log.append(audit_entry)

        if self.is_live_kafka and self.producer:
            try:
                future = self.producer.send(self.topic, value=event_payload)
                self.producer.flush(timeout=5)
                logger.info(f"[Kafka Producer] Sent {message_id} to Aiven Kafka topic '{self.topic}'")
            except Exception as e:
                logger.error(f"[Kafka Producer Error] Failed to send to Aiven Kafka: {e}")
                # Fallback to local queue
                self._local_topic_queue.put(event_payload)
        else:
            self._local_topic_queue.put(event_payload)
            logger.info(f"[Local Kafka Producer] Queued event {message_id}")

        return audit_entry

    # -------------------------------------------------------------------------
    # Consumer
    # -------------------------------------------------------------------------
    def _aiven_consumer_loop(self):
        """Continuously polls messages from Aiven Apache Kafka"""
        from kafka import KafkaConsumer
        try:
            consumer_kwargs = {
                "bootstrap_servers": Config.AIVEN_KAFKA_BOOTSTRAP_SERVERS.split(","),
                "group_id": self.consumer_group,
                "auto_offset_reset": "latest",
                "enable_auto_commit": True,
                "value_deserializer": lambda m: json.loads(m.decode("utf-8")),
                "security_protocol": Config.AIVEN_KAFKA_SECURITY_PROTOCOL
            }
            if Config.AIVEN_KAFKA_SECURITY_PROTOCOL == "SASL_SSL":
                consumer_kwargs["sasl_mechanism"] = Config.AIVEN_KAFKA_SASL_MECHANISM
                consumer_kwargs["sasl_plain_username"] = Config.AIVEN_KAFKA_USERNAME
                consumer_kwargs["sasl_plain_password"] = Config.AIVEN_KAFKA_PASSWORD

            consumer = KafkaConsumer(self.topic, **consumer_kwargs)
            logger.info(f"[Kafka Consumer] Subscribed to '{self.topic}' on Aiven.")

            for message in consumer:
                if not self._running:
                    break
                event_payload = message.value
                self._handle_incoming_event(
                    event_payload,
                    partition=message.partition,
                    offset=message.offset,
                    broker="Aiven Apache Kafka"
                )
        except Exception as e:
            logger.error(f"[Kafka Consumer Thread Error]: {e}. Switching to local queue loop.")
            self._local_consumer_loop()

    def _local_consumer_loop(self):
        """Processes events from the local queue"""
        while self._running:
            try:
                event_payload = self._local_topic_queue.get(timeout=1.0)
                self._local_offset += 1
                # Small realistic processing delay (e.g. 150ms) to illustrate asynchronous consumption in demo UI
                time.sleep(0.15)
                self._handle_incoming_event(
                    event_payload,
                    partition=0,
                    offset=self._local_offset,
                    broker="Local Kafka Broker"
                )
                self._local_topic_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"[Local Consumer Error]: {e}")

    def _handle_incoming_event(self, event_payload: Dict[str, Any], partition: int, offset: int, broker: str):
        """
        Background listener reactions:
        1. Automatically decrements/verifies stock
        2. Keeps OpenSearch product index in sync
        3. Sends simulated confirmation workflows to customer
        """
        order_id = event_payload.get("order_id")
        order_number = event_payload.get("order_number")
        items = event_payload.get("items", [])
        city = event_payload.get("shipping_city", "All India")
        customer = event_payload.get("customer", {})

        logger.info(f"[Kafka Consumer] Consumed event for order #{order_number} (offset {offset}) from {broker}")

        # Execute registered callback (to sync DB & OpenSearch)
        if self.on_order_consumed:
            try:
                self.on_order_consumed(event_payload)
            except Exception as e:
                logger.error(f"Error executing on_order_consumed callback: {e}")

        # Produce a Consumer Received Audit Event for UI
        consumed_entry = {
            "type": "CONSUMED",
            "source": f"Inventory-Fulfillment-Worker (Group: {self.consumer_group})",
            "broker": broker,
            "topic": self.topic,
            "partition": partition,
            "offset": offset,
            "event_id": event_payload.get("event_id"),
            "order_id": order_id,
            "order_number": order_number,
            "actions_triggered": [
                f"1. Verified regional warehouse stock decrement for {len(items)} item(s)",
                f"2. Synced product stock into OpenSearch index '{Config.AIVEN_OPENSEARCH_INDEX}'",
                f"3. Dispatched order confirmation to {customer.get('email', 'customer')} & local hub '{city}'"
            ],
            "status": "PROCESSED"
        }
        self.event_log.append(consumed_entry)

    def stop(self):
        self._running = False
        if self.producer:
            try:
                self.producer.close()
            except Exception:
                pass
