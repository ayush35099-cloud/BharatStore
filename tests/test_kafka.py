"""
Automated Kafka Stream & Consumer Reaction Test
Verifies that when an order is placed, a Kafka event is produced,
and the background consumer processes it, decrementing stock and syncing OpenSearch.
"""

import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import DatabaseService
from app.kafka_service import KafkaService
from app.opensearch_service import OpenSearchService

def test_kafka_order_event_flow():
    db = DatabaseService()
    os_service = OpenSearchService()
    # Ingest products into OpenSearch first
    os_service.index_all_products(db.get_all_products())
    
    print("=" * 60)
    print(" APACHE KAFKA PRODUCER & CONSUMER REACTION VERIFICATION")
    print("=" * 60)

    consumed_events = []

    def on_consumed(event_payload):
        consumed_events.append(event_payload)
        for item in event_payload.get("items", []):
            pid = item["product_id"]
            prod = db.get_product_by_id(pid)
            if prod:
                os_service.update_product_stock(pid, prod["stock"])

    kafka = KafkaService(on_order_consumed_callback=on_consumed)

    # 1. Place an order through DB transaction
    customer = {
        "name": "Aarav Sharma",
        "email": "aarav.sharma@example.in",
        "phone": "+91 98450 11223"
    }
    item = [{"product_id": 8, "quantity": 2}] # boAt Rockerz 450
    
    initial_prod = db.get_product_by_id(8)
    initial_stock = initial_prod["stock"]
    print(f"Initial boAt Headphones Stock: {initial_stock} units")

    order_result = db.process_checkout_transaction(
        customer_info=customer,
        items=item,
        shipping_city="Bengaluru",
        shipping_address="Indiranagar 100ft Road, Bengaluru"
    )
    print(f"Order #{order_result['order_number']} committed in PostgreSQL!")

    # 2. Produce Kafka event
    audit_event = kafka.produce_order_event(order_result)
    print(f"Produced event {audit_event['event_id']} to topic '{kafka.topic}' via {audit_event['broker']}")

    # 3. Wait for consumer thread reaction
    print("Waiting for background Kafka consumer thread to pick up event...")
    max_wait = 5.0
    start = time.time()
    while time.time() - start < max_wait:
        if len(consumed_events) > 0:
            break
        time.sleep(0.1)

    assert len(consumed_events) > 0, "Kafka consumer failed to process event within timeout!"
    consumed = consumed_events[0]
    print(f"Consumer successfully processed Order #{consumed['order_number']}!")

    # 4. Verify stock and OpenSearch sync
    updated_prod = db.get_product_by_id(8)
    assert updated_prod["stock"] == initial_stock - 2, f"Stock did not decrement! Found {updated_prod['stock']}"
    print(f"Verified Database stock decremented to: {updated_prod['stock']} units")

    # Verify OpenSearch search returns updated stock
    os_res = os_service.search(query_text="boAt")
    os_boat = next((p for p in os_res["results"] if p["id"] == 8), None)
    assert os_boat is not None
    assert os_boat["stock"] == updated_prod["stock"]
    print(f"Verified OpenSearch index synchronized with real-time stock ({os_boat['stock']} units)!")

    print("\nVERDICT: [PASSED] Apache Kafka Produce -> Consume -> OpenSearch Sync verified!")
    print("=" * 60)

    kafka.stop()

if __name__ == "__main__":
    test_kafka_order_event_flow()
