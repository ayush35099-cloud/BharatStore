"""
Automated Concurrency Stress Test for BharatKart
Verifies that PostgreSQL ACID transactions & row-locking (SELECT FOR UPDATE)
prevent overselling when multiple threads attempt to purchase the last remaining item.
"""

import sys
import os
import concurrent.futures

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import DatabaseService

def test_last_item_race_condition():
    db = DatabaseService()
    test_product_id = 1 # iPhone 15
    initial_stock = 1

    print("=" * 60)
    print(" BHARATKART CONCURRENCY & ACID ROW-LOCKING VERIFICATION")
    print("=" * 60)
    print(f"Setting product ID #{test_product_id} stock to exactly: {initial_stock} unit")
    db.update_stock(test_product_id, initial_stock)

    num_threads = 10
    print(f"Spawning {num_threads} simultaneous buyer threads trying to buy 1 unit each...")

    results = []

    def purchase_attempt(buyer_id: int):
        customer = {
            "name": f"Tester #{buyer_id}",
            "email": f"tester{buyer_id}@concurrency.local",
            "phone": "+91 99999 00000"
        }
        item = [{"product_id": test_product_id, "quantity": 1}]
        try:
            order = db.process_checkout_transaction(
                customer_info=customer,
                items=item,
                shipping_city="Mumbai",
                shipping_address="Race Test Hub, Andheri"
            )
            return (buyer_id, True, f"COMMITTED - Order {order['order_number']}")
        except ValueError as ve:
            return (buyer_id, False, f"ROLLED BACK - {str(ve)}")
        except Exception as e:
            return (buyer_id, False, f"ERROR - {str(e)}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(purchase_attempt, i + 1) for i in range(num_threads)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    # Sort by buyer_id
    results.sort(key=lambda x: x[0])

    success_count = sum(1 for _, ok, _ in results if ok)
    fail_count = sum(1 for _, ok, _ in results if not ok)

    final_prod = db.get_product_by_id(test_product_id)
    final_stock = final_prod["stock"]

    print("\n--- Thread Execution Results ---")
    for buyer_id, ok, msg in results:
        status_label = "[SUCCESS]" if ok else "[ROLLBACK]"
        print(f" Buyer #{buyer_id:02d}: {status_label} {msg}")

    print("\n--- Invariant Verification ---")
    print(f" Total Threads:            {num_threads}")
    print(f" Successful Purchases:    {success_count}")
    print(f" Rejected (Rolled Back):  {fail_count}")
    print(f" Final Stock in Database: {final_stock}")

    # Assertions
    assert success_count == 1, f"Expected exactly 1 success, but got {success_count}"
    assert fail_count == num_threads - 1, f"Expected {num_threads - 1} rollbacks, but got {fail_count}"
    assert final_stock == 0, f"Expected final stock 0, but got {final_stock}"
    assert final_stock >= 0, "CRITICAL ERROR: Stock dropped below zero!"

    print("\nVERDICT: [PASSED] PostgreSQL transactional row-locking verified 100% safe!")
    print("=" * 60)

    # Restore stock
    db.update_stock(test_product_id, 14)

if __name__ == "__main__":
    test_last_item_race_condition()
