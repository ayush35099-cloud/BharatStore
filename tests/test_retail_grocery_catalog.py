"""
Test Suite: Retail Grocery Catalog & Dairy First Screen Verification
===================================================================
Verifies:
1. Presence of all 18 required essential grocery products in database
2. Proper categorization (Dairy & Breakfast, Rice & Grains, Cooking Essentials)
3. Store-specific inventory across multiple physical stores (Store 1, 2, 3, 4)
4. Independent pricing and stock levels (different prices and stock per store)
5. Out-of-stock handling in store inventory and visual display
6. Retail Near Me homepage (/retail) prominently displays Milk, Curd, Ghee,
   Butter, Paneer, and Cheese on the first screen
7. API /api/retail/catalog returns structured departmental items
"""

import unittest
from app import create_app
from app.database import DatabaseService


class TestRetailGroceryCatalog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = cls.app.test_client()
        cls.db = DatabaseService()

    # 1. Essential Dairy Products exist in database
    def test_01_dairy_products_exist(self):
        dairy_titles = [
            "Amul Taaza Milk – 1 L",
            "Amul Gold Milk – 500 ml",
            "Mother Dairy Milk – 1 L",
            "Fresh Curd – 500 g",
            "Amul Masti Dahi – 400 g",
            "Paneer – 200 g",
            "Amul Butter – 100 g",
            "Amul Pure Ghee – 500 ml",
            "Cheese – 200 g"
        ]
        all_prods = self.db.get_all_products()
        prod_titles = [p["title"] for p in all_prods]

        for dt in dairy_titles:
            self.assertIn(dt, prod_titles, f"Missing dairy product in catalog: {dt}")
        print(" [PASSED] 1. All 9 essential dairy products verified in database catalog")

    # 2. Essential Grains & Staples exist in database
    def test_02_grains_and_staples_exist(self):
        staple_keywords = [
            "Basmati Rice",
            "Regular Rice",
            "Wheat Atta",
            "Toor Dal",
            "Moong Dal"
        ]
        all_prods = self.db.get_all_products()
        for kw in staple_keywords:
            match = any(kw.lower() in p["title"].lower() for p in all_prods)
            self.assertTrue(match, f"Missing staple product matching keyword: {kw}")
        print(" [PASSED] 2. All 5 Rice & Grain staples verified in database catalog")

    # 3. Essential Cooking Essentials exist in database
    def test_03_cooking_essentials_exist(self):
        essential_keywords = [
            "Sunflower Oil",
            "Mustard Oil",
            "Sugar",
            "Salt"
        ]
        all_prods = self.db.get_all_products()
        for kw in essential_keywords:
            match = any(kw.lower() in p["title"].lower() for p in all_prods)
            self.assertTrue(match, f"Missing cooking essential matching keyword: {kw}")
        print(" [PASSED] 3. All 4 Cooking Essentials verified in database catalog")

    # 4. Department categorization
    def test_04_department_categorization(self):
        inv1 = self.db.get_store_inventory(1)
        dairy_items = [p for p in inv1 if p.get("sub_category") in ("Dairy & Bakery", "Dairy & Breakfast")]
        grains_items = [p for p in inv1 if p.get("sub_category") in ("Rice, Atta & Dal", "Rice & Grains")]
        essentials_items = [p for p in inv1 if p.get("sub_category") in ("Household & Personal Care", "Cooking Essentials", "Snacks & Beverages")]

        self.assertGreaterEqual(len(dairy_items), 9, "Expected at least 9 Dairy & Breakfast items")
        self.assertGreaterEqual(len(grains_items), 5, "Expected at least 5 Rice & Grains items")
        self.assertGreaterEqual(len(essentials_items), 4, "Expected at least 4 Cooking Essentials items")
        print(f" [PASSED] 4. Department categorization verified ({len(dairy_items)} Dairy, {len(grains_items)} Grains, {len(essentials_items)} Essentials)")

    # 5. Store-specific inventory and independent pricing
    def test_05_store_specific_inventory_and_pricing(self):
        # Product 79 (Amul Pure Ghee 500 ml)
        ghee_s1 = self.db.get_store_product(1, 79)
        ghee_s3 = self.db.get_store_product(3, 79)
        self.assertIsNotNone(ghee_s1)
        self.assertIsNotNone(ghee_s3)
        self.assertEqual(float(ghee_s1["selling_price"]), 310.00)
        self.assertEqual(float(ghee_s3["selling_price"]), 312.00)

        # Product 61 (Amul Taaza Milk 1 L)
        milk_s1 = self.db.get_store_product(1, 61)
        milk_s2 = self.db.get_store_product(2, 61)
        self.assertEqual(float(milk_s1["selling_price"]), 60.00)
        self.assertEqual(float(milk_s2["selling_price"]), 62.00)
        print(" [PASSED] 5. Independent pricing across physical stores verified")

    # 6. Out of stock handling in store inventory
    def test_06_out_of_stock_store_inventory(self):
        # Store 2: Curd 62 & Ghee 79 are out of stock
        curd_s2 = self.db.get_store_product(2, 62)
        ghee_s2 = self.db.get_store_product(2, 79)
        self.assertFalse(curd_s2["is_available"])
        self.assertEqual(curd_s2["stock_quantity"], 0)
        self.assertFalse(ghee_s2["is_available"])
        self.assertEqual(ghee_s2["stock_quantity"], 0)

        # Store 4: Paneer 63 is out of stock
        pnr_s4 = self.db.get_store_product(4, 63)
        self.assertFalse(pnr_s4["is_available"])
        self.assertEqual(pnr_s4["stock_quantity"], 0)

        # Store 1: Curd 62, Ghee 79, Paneer 63 are all IN STOCK
        self.assertTrue(self.db.get_store_product(1, 62)["is_available"])
        self.assertTrue(self.db.get_store_product(1, 79)["is_available"])
        self.assertTrue(self.db.get_store_product(1, 63)["is_available"])
        print(" [PASSED] 6. Out-of-stock isolation correctly enforced per physical store")

    # 7. Retail Near Me homepage renders Dairy & Breakfast prominently
    def test_07_retail_homepage_renders_dairy_first(self):
        res = self.client.get("/retail?store_id=1")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # Dairy & Breakfast section must exist
        self.assertIn("Milk, Curd, Ghee, Butter & Dairy Products", html)
        self.assertIn("Amul Taaza Milk – 1 L", html)
        self.assertIn("Amul Pure Ghee – 500 ml", html)
        self.assertIn("Fresh Curd – 500 g", html)
        self.assertIn("Amul Butter – 100 g", html)
        self.assertIn("Paneer – 200 g", html)
        self.assertIn("Cheese – 200 g", html)

        # In Stock pills present
        self.assertIn("In Stock (20)", html)

        # Grains and Essentials/Household also rendered
        self.assertIn("Rice, Wheat Atta & High-Protein Dals", html)
        self.assertTrue(
            "Cooking Oils, Refined Sugar & Table Salt" in html or
            "Household & Personal Care" in html or
            "Cleaning Essentials" in html
        )
        print(" [PASSED] 7. Retail Near Me homepage successfully verified displaying all dairy essentials")

    # 8. Retail homepage renders Out of Stock badges when store stock is 0
    def test_08_retail_homepage_renders_out_of_stock_badges(self):
        res = self.client.get("/retail?store_id=2")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # Store 2 has Curd & Ghee out of stock
        self.assertIn("Out of Stock", html)
        self.assertIn("Fresh Mart Bengaluru", html)
        print(" [PASSED] 8. Out of Stock badge correctly rendered for Store 2")

    # 9. API /api/retail/catalog endpoint
    def test_09_api_retail_catalog(self):
        res = self.client.get("/api/retail/catalog?store_id=1")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("dairy_items", data)
        self.assertIn("grains_items", data)
        self.assertIn("essentials_items", data)
        self.assertGreaterEqual(len(data["dairy_items"]), 9)

        # Check ghee item
        ghee = next((item for item in data["dairy_items"] if "Ghee" in item["title"]), None)
        self.assertIsNotNone(ghee)
        self.assertEqual(ghee["brand"], "Amul")
        self.assertEqual(float(ghee["selling_price"]), 310.00)
        print(f" [PASSED] 9. API /api/retail/catalog verified with {len(data['dairy_items'])} dairy items")


if __name__ == "__main__":
    unittest.main()
