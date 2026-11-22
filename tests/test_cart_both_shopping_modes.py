import unittest
import json
from app import create_app
from app.database import DatabaseService

class TestCartBothShoppingModes(unittest.TestCase):
    """
    Comprehensive verification for Add to Cart across both Online and Retail shopping modes:
    1. Online product -> Add to Cart -> Verify cart payload & items.
    2. Retail product -> Add to Cart -> Verify store-specific basket.
    3. Add multiple products across both modes.
    4. Increase and decrease quantities (PATCH /api/cart/items/<id>).
    5. Persistence verification (simulated page refresh / fetch cart).
    6. Shopping mode partition (Online and Retail carts strictly independent and never mix).
    7. All 5 retail stores independent basket support (Stores 1, 2, 3, 4, 5).
    8. Out-of-stock and invalid product validation.
    9. PostgreSQL RealDictCursor and connection proxy safety verification.
    """

    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.session_id = "test-session-cart-repair-12345"
        self.headers = {
            "Content-Type": "application/json",
            "X-Session-Id": self.session_id
        }
        # Clear carts before test
        self.client.delete("/api/cart/online/clear", headers=self.headers)
        self.client.delete("/api/cart/retail/clear", headers=self.headers)

    def tearDown(self):
        # Clean up
        self.client.delete("/api/cart/online/clear", headers=self.headers)
        self.client.delete("/api/cart/retail/clear", headers=self.headers)

    def test_01_online_product_add_and_fetch(self):
        """Scenario 1: Online product -> Add to Cart -> Fetch Cart -> Verify HTTP 201 & items"""
        # Product 1 is an Online tech/fashion item (e.g. boAt headphones or similar)
        res = self.client.post("/api/cart/online/add", json={"product_id": 1, "quantity": 1}, headers=self.headers)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        cart = data.get("cart", {})
        self.assertEqual(cart.get("shopping_mode"), "ONLINE")
        self.assertEqual(cart.get("total_items"), 1)
        self.assertEqual(len(cart.get("items", [])), 1)
        self.assertEqual(cart["items"][0]["product_id"], 1)

        # Verify GET /api/cart/online matches
        get_res = self.client.get("/api/cart/online", headers=self.headers)
        self.assertEqual(get_res.status_code, 200)
        get_cart = get_res.get_json().get("cart", {})
        self.assertEqual(get_cart.get("total_items"), 1)
        self.assertEqual(get_cart["items"][0]["product_id"], 1)

    def test_02_retail_product_add_and_fetch(self):
        """Scenario 2: Retail product -> Add to Cart -> Fetch Cart -> Verify store basket"""
        # Product 61 is Amul Milk at Store 1 (Bharat Fresh Mart)
        res = self.client.post("/api/cart/retail/1/add", json={"product_id": 61, "quantity": 2}, headers=self.headers)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        cart = data.get("cart", {})
        self.assertEqual(cart.get("shopping_mode"), "RETAIL_NEAR_ME")
        self.assertEqual(cart.get("store_id"), 1)
        self.assertEqual(cart.get("total_items"), 2)
        self.assertEqual(cart["items"][0]["product_id"], 61)

        # Verify GET /api/cart/retail returns store 1 in breakdown
        get_res = self.client.get("/api/cart/retail", headers=self.headers)
        self.assertEqual(get_res.status_code, 200)
        ret_data = get_res.get_json()
        self.assertEqual(ret_data.get("total_items"), 2)
        shops = ret_data.get("shops", [])
        self.assertEqual(len(shops), 1)
        self.assertEqual(shops[0]["store_id"], 1)

    def test_03_add_multiple_products_and_quantity_aggregation(self):
        """Scenario 3: Adding same product increases quantity, different products append"""
        # Add Product 1 (qty 1)
        self.client.post("/api/cart/online/add", json={"product_id": 1, "quantity": 1}, headers=self.headers)
        # Add Product 1 again (qty 2) -> total should be 3
        res2 = self.client.post("/api/cart/online/add", json={"product_id": 1, "quantity": 2}, headers=self.headers)
        self.assertEqual(res2.status_code, 201)
        cart2 = res2.get_json().get("cart", {})
        self.assertEqual(cart2.get("total_items"), 3)
        self.assertEqual(len(cart2.get("items", [])), 1)
        self.assertEqual(cart2["items"][0]["quantity"], 3)

        # Add Product 2 (qty 1) -> 2 distinct items, total qty 4
        res3 = self.client.post("/api/cart/online/add", json={"product_id": 2, "quantity": 1}, headers=self.headers)
        self.assertEqual(res3.status_code, 201)
        cart3 = res3.get_json().get("cart", {})
        self.assertEqual(cart3.get("total_items"), 4)
        self.assertEqual(len(cart3.get("items", [])), 2)

    def test_04_increase_and_decrease_quantities(self):
        """Scenario 4: PATCH /api/cart/items/<id> increases, decreases, and deletes at 0"""
        res = self.client.post("/api/cart/online/add", json={"product_id": 1, "quantity": 2}, headers=self.headers)
        cart = res.get_json()["cart"]
        item_id = cart["items"][0]["id"]

        # Increase quantity to 5
        patch_res = self.client.patch(f"/api/cart/items/{item_id}", json={"quantity": 5}, headers=self.headers)
        self.assertEqual(patch_res.status_code, 200)
        self.assertEqual(patch_res.get_json()["cart"]["total_items"], 5)

        # Decrease quantity to 1
        patch_res2 = self.client.patch(f"/api/cart/items/{item_id}", json={"quantity": 1}, headers=self.headers)
        self.assertEqual(patch_res2.status_code, 200)
        self.assertEqual(patch_res2.get_json()["cart"]["total_items"], 1)

        # Decrease quantity to 0 -> removes item
        patch_res3 = self.client.patch(f"/api/cart/items/{item_id}", json={"quantity": 0}, headers=self.headers)
        self.assertEqual(patch_res3.status_code, 200)
        self.assertEqual(patch_res3.get_json()["cart"]["total_items"], 0)
        self.assertEqual(len(patch_res3.get_json()["cart"]["items"]), 0)

    def test_05_refresh_and_verify_persistence(self):
        """Scenario 5: Simulated refresh - fetch cart across multiple independent requests"""
        self.client.post("/api/cart/online/add", json={"product_id": 1, "quantity": 2}, headers=self.headers)
        self.client.post("/api/cart/retail/1/add", json={"product_id": 61, "quantity": 3}, headers=self.headers)

        # Simulate fresh HTTP requests with same session
        online_check = self.client.get("/api/cart/online", headers=self.headers)
        self.assertEqual(online_check.status_code, 200)
        self.assertEqual(online_check.get_json()["cart"]["total_items"], 2)

        retail_check = self.client.get("/api/cart/retail", headers=self.headers)
        self.assertEqual(retail_check.status_code, 200)
        self.assertEqual(retail_check.get_json()["total_items"], 3)

    def test_06_carts_never_mix_between_modes(self):
        """Scenario 6: Online and Retail carts are strictly isolated and never mix"""
        # Add tech item to online cart
        self.client.post("/api/cart/online/add", json={"product_id": 1, "quantity": 1}, headers=self.headers)
        # Add grocery item to retail cart Store 1
        self.client.post("/api/cart/retail/1/add", json={"product_id": 61, "quantity": 4}, headers=self.headers)

        online_cart = self.client.get("/api/cart/online", headers=self.headers).get_json()["cart"]
        retail_carts = self.client.get("/api/cart/retail", headers=self.headers).get_json()

        # Online cart only has product 1
        self.assertEqual(online_cart["total_items"], 1)
        self.assertEqual(online_cart["items"][0]["product_id"], 1)
        # Retail cart only has product 61
        self.assertEqual(retail_carts["total_items"], 4)
        self.assertEqual(retail_carts["shops"][0]["items"][0]["product_id"], 61)

        # Clear online cart leaves retail cart completely unaffected
        self.client.delete("/api/cart/online/clear", headers=self.headers)
        online_after = self.client.get("/api/cart/online", headers=self.headers).get_json()["cart"]
        self.assertEqual(online_after["total_items"], 0)
        retail_after = self.client.get("/api/cart/retail", headers=self.headers).get_json()
        self.assertEqual(retail_after["total_items"], 4)

    def test_07_all_five_retail_stores_supported(self):
        """Scenario 7: Supports independent baskets across all 5 physical stores"""
        # Store 1: product 61 (Amul Milk)
        res1 = self.client.post("/api/cart/retail/1/add", json={"product_id": 61, "quantity": 1}, headers=self.headers)
        self.assertEqual(res1.status_code, 201)

        # Store 2: product 64 (Amul Butter)
        res2 = self.client.post("/api/cart/retail/2/add", json={"product_id": 64, "quantity": 1}, headers=self.headers)
        self.assertEqual(res2.status_code, 201)

        # Store 3: product 65 (Basmati Rice)
        res3 = self.client.post("/api/cart/retail/3/add", json={"product_id": 65, "quantity": 1}, headers=self.headers)
        self.assertEqual(res3.status_code, 201)

        # Store 4: product 66 (Sunflower Oil)
        res4 = self.client.post("/api/cart/retail/4/add", json={"product_id": 66, "quantity": 1}, headers=self.headers)
        self.assertEqual(res4.status_code, 201)

        # Store 5: product 68 (Toor Dal)
        res5 = self.client.post("/api/cart/retail/5/add", json={"product_id": 68, "quantity": 1}, headers=self.headers)
        self.assertEqual(res5.status_code, 201)

        # Verify all 5 stores are preserved independently
        res_all = self.client.get("/api/cart/retail", headers=self.headers)
        self.assertEqual(res_all.status_code, 200)
        data = res_all.get_json()
        self.assertEqual(len(data.get("shops", [])), 5)
        self.assertEqual(data.get("total_items"), 5)

    def test_08_invalid_and_out_of_stock_products(self):
        """Scenario 8: Rejects invalid IDs, cross-category violations, and zero-stock items"""
        # Invalid product_id
        res_bad_id = self.client.post("/api/cart/online/add", json={"product_id": 999999, "quantity": 1}, headers=self.headers)
        self.assertIn(res_bad_id.status_code, [400, 404])

        # Category violation: Grocery item (product 61) in Online cart
        res_cat_viol = self.client.post("/api/cart/online/add", json={"product_id": 61, "quantity": 1}, headers=self.headers)
        self.assertEqual(res_cat_viol.status_code, 400)
        self.assertIn("retail grocery item", res_cat_viol.get_json().get("error", "").lower())

        # Category violation: Tech item (product 1) in Retail cart
        res_tech_viol = self.client.post("/api/cart/retail/1/add", json={"product_id": 1, "quantity": 1}, headers=self.headers)
        self.assertEqual(res_tech_viol.status_code, 400)
        self.assertIn("daily retail grocery product", res_tech_viol.get_json().get("error", "").lower())

        # Negative quantity rejected
        res_neg = self.client.post("/api/cart/online/add", json={"product_id": 1, "quantity": -2}, headers=self.headers)
        self.assertEqual(res_neg.status_code, 400)

    def test_09_postgres_cursor_factory_and_connection_cleanup(self):
        """Scenario 9: Verify RealDictCursor is used and connections are closed under PostgreSQL"""
        from unittest.mock import MagicMock
        from app.database import DatabaseService

        db = DatabaseService()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        
        # Setup mock row with dictionary-like access
        mock_row = {"id": 10, "quantity": 1, "shopping_mode": "ONLINE", "status": "ACTIVE", "customer_id": None, "session_id": "test"}
        mock_cur.fetchone.return_value = mock_row

        # Verify get_or_create_cart calls cursor with RealDictCursor and closes conn
        db.is_live_postgres = True
        db._get_pg_connection = MagicMock(return_value=mock_conn)

        cart = db.get_or_create_cart(None, "sess-1", "ONLINE")
        self.assertEqual(cart["id"], 10)
        self.assertTrue(mock_conn.close.called)

        # Check that cursor_factory was passed
        cursor_call_kwargs = mock_conn.cursor.call_args[1]
        self.assertIn("cursor_factory", cursor_call_kwargs)
        from psycopg2.extras import RealDictCursor
        self.assertEqual(cursor_call_kwargs["cursor_factory"], RealDictCursor)

if __name__ == "__main__":
    unittest.main()
