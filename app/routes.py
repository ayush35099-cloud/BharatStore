"""
BharatKart API Routes & Web Endpoints
"""

import os
import math
import json
import time
import logging
import hmac
import uuid
import concurrent.futures
from typing import Optional, Dict, Any, List
from functools import wraps
from flask import Blueprint, request, jsonify, render_template, Response, session, redirect, url_for, flash
from app.config import Config
from app.database import DatabaseService, OrderStatus, PaymentStatus
from app.payment_service import PaymentService
from app.kafka_service import KafkaService
from app.opensearch_service import OpenSearchService
from app.seed_data import FULFILLMENT_HUBS, SAMPLE_CUSTOMERS

logger = logging.getLogger("BharatKart.Routes")
main_bp = Blueprint("main", __name__)

def require_admin_auth(f):
    """
    Protects administrative and stress-test endpoints.
    Requires a valid token via X-Admin-Token
    or Authorization: Bearer <token>.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Fail closed if the admin key is not configured.
        expected_token = Config.ADMIN_API_KEY
        if not expected_token:
            logger.error("ADMIN_API_KEY is not configured.")
            return jsonify({
                "success": False,
                "error": "Admin authentication is not configured."
            }), 503

        # Read authentication headers.
        token = request.headers.get(
            "X-Admin-Token", ""
        ).strip()
        auth_header = request.headers.get(
            "Authorization", ""
        ).strip()
        if not token and auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):].strip()

        # Reject missing or invalid credentials.
        if not token or not hmac.compare_digest(
            token, expected_token
        ):
            logger.warning(
                "Unauthorized admin access attempt to %s",
                request.path
            )
            return jsonify({
                "success": False,
                "error": "Unauthorized access."
            }), 403

        return f(*args, **kwargs)
    return decorated_function

# Initialize services
db_service = DatabaseService()
opensearch_service = OpenSearchService()
payment_service = PaymentService()

def on_kafka_order_consumed(event_payload):
    """Callback triggered whenever Kafka consumer processes an order event"""
    for item in event_payload.get("items", []):
        pid = item["product_id"]
        # Fetch updated stock from DB
        prod = db_service.get_product_by_id(pid)
        if prod:
            # Sync to OpenSearch
            opensearch_service.update_product_stock(pid, prod["stock"])

kafka_service = KafkaService(on_order_consumed_callback=on_kafka_order_consumed)

# Pre-populate OpenSearch index with all products and store inventory on startup
try:
    all_prods = db_service.get_all_products()
    opensearch_service.index_all_products(all_prods)
    stores = db_service.get_retail_stores("Bengaluru")
    for st in stores:
        s_inv = db_service.get_store_inventory(st["id"])
        opensearch_service.index_store_inventory(st["id"], s_inv)
except Exception as e:
    logger.error(f"Error seeding OpenSearch on launch: {e}")

# -------------------------------------------------------------------------
# Shopping Mode Constants & Persistence Helpers
# -------------------------------------------------------------------------
MODE_NORMALIZATION = {
    "RETAIL": "RETAIL_NEAR_ME",
    "RETAIL_NEAR_ME": "RETAIL_NEAR_ME",
    "ONLINE": "ONLINE",
    "MARKETPLACE": "ONLINE"
}
VALID_SHOPPING_MODES = {"RETAIL_NEAR_ME", "ONLINE", "RETAIL", "retail", "online", "retail_near_me"}
DEFAULT_SHOPPING_MODE = "ONLINE"

def normalize_shopping_mode(mode: Optional[str]) -> Optional[str]:
    """Normalizes mode strings like 'retail', 'online', 'RETAIL_NEAR_ME' to canonical mode."""
    if not mode or not isinstance(mode, str):
        return None
    cleaned = mode.strip().upper().replace("-", "_").replace(" ", "_")
    return MODE_NORMALIZATION.get(cleaned)

def get_current_shopping_mode() -> str:
    """Retrieves validated shopping mode from session, defaulting to ONLINE."""
    mode = session.get("shopping_mode")
    canonical = normalize_shopping_mode(mode)
    if canonical:
        return canonical
    return DEFAULT_SHOPPING_MODE

def set_current_shopping_mode(mode: str) -> bool:
    """Sets and validates shopping mode in the session."""
    canonical = normalize_shopping_mode(mode)
    if canonical:
        session["shopping_mode"] = canonical
        session.permanent = True
        return True
    return False

# -------------------------------------------------------------------------
# Phase 8: Strict Retail Category Isolation
# -------------------------------------------------------------------------
ALLOWED_RETAIL_CATEGORIES = {
    "Dairy & Breakfast",
    "Rice & Grains",
    "Cooking Essentials",
    "Fresh Produce",
    "Snacks & Beverages",
    "Household Essentials",
    "Personal Care",
    "Packaged Foods",
    "Daily Essentials & Groceries",
    "Beauty & Personal Care",
}

NON_GROCERY_CATEGORIES = {
    "Mobiles & Tablets",
    "Laptops & Computers",
    "Audio & Wearables",
    "Home & Kitchen",
    "Fashion & Apparel",
    "Electronics",
}

def resolve_shopping_mode(explicit_mode: Optional[str] = None) -> str:
    """Resolves shopping mode from explicit argument, request parameters, or session."""
    if explicit_mode:
        canonical = normalize_shopping_mode(explicit_mode)
        if canonical:
            return canonical
    try:
        from flask import request
        param = request.args.get("mode") or request.args.get("shopping_mode")
        if param:
            canonical = normalize_shopping_mode(param)
            if canonical:
                return canonical
    except Exception:
        pass
    return get_current_shopping_mode()

def is_retail_grocery_product(product: Optional[Dict[str, Any]]) -> bool:
    """Returns True if the product belongs strictly to grocery categories and not non-grocery."""
    if not product or not isinstance(product, dict):
        return False
    cat = (product.get("category") or "").strip()
    sub = (product.get("sub_category") or "").strip()
    if cat in NON_GROCERY_CATEGORIES or sub in NON_GROCERY_CATEGORIES:
        return False
    if cat == "Daily Essentials & Groceries" or cat in ALLOWED_RETAIL_CATEGORIES:
        return True
    if sub in ALLOWED_RETAIL_CATEGORIES:
        return True
    return False

# -------------------------------------------------------------------------
# Phase 3: Location Constants, Distance Calculation & Context Injector
# -------------------------------------------------------------------------
CITIES_AND_AREAS_DATA = [
    {
        "city": "Mumbai",
        "state": "Maharashtra",
        "hub_code": "HUB-MUM-01",
        "hub_name": "BharatStore Mumbai MegaHub",
        "hub_address": "Linking Road, Bandra West, Mumbai 400050",
        "hub_lat": 19.0596,
        "hub_lng": 72.8295,
        "default_pincode": "400050",
        "areas": [
            {"name": "Bandra West", "pincode": "400050", "lat": 19.0596, "lng": 72.8295, "distance_km": 0.5},
            {"name": "Andheri West", "pincode": "400058", "lat": 19.1363, "lng": 72.8277, "distance_km": 8.5},
            {"name": "Worli Sea Face", "pincode": "400030", "lat": 19.0178, "lng": 72.8178, "distance_km": 4.8},
            {"name": "Powai", "pincode": "400076", "lat": 19.1176, "lng": 72.9060, "distance_km": 11.2},
            {"name": "Dadar West", "pincode": "400028", "lat": 19.0178, "lng": 72.8478, "distance_km": 4.9},
            {"name": "Juhu", "pincode": "400049", "lat": 19.1075, "lng": 72.8263, "distance_km": 5.4},
            {"name": "Colaba", "pincode": "400005", "lat": 18.9067, "lng": 72.8147, "distance_km": 17.5}
        ]
    },
    {
        "city": "Bengaluru",
        "state": "Karnataka",
        "hub_code": "HUB-BLR-01",
        "hub_name": "BharatStore Bengaluru Tech Store",
        "hub_address": "100 Feet Road, Indiranagar, Bengaluru 560038",
        "hub_lat": 12.9784,
        "hub_lng": 77.6408,
        "default_pincode": "560038",
        "areas": [
            {"name": "Indiranagar", "pincode": "560038", "lat": 12.9784, "lng": 77.6408, "distance_km": 0.3},
            {"name": "Koramangala", "pincode": "560034", "lat": 12.9352, "lng": 77.6245, "distance_km": 5.1},
            {"name": "HSR Layout", "pincode": "560102", "lat": 12.9121, "lng": 77.6446, "distance_km": 7.4},
            {"name": "Whitefield", "pincode": "560066", "lat": 12.9698, "lng": 77.7500, "distance_km": 12.3},
            {"name": "Jayanagar", "pincode": "560011", "lat": 12.9308, "lng": 77.5838, "distance_km": 8.2},
            {"name": "Malleshwaram", "pincode": "560003", "lat": 13.0031, "lng": 77.5643, "distance_km": 9.5}
        ]
    },
    {
        "city": "Delhi NCR",
        "state": "Delhi",
        "hub_code": "HUB-DEL-01",
        "hub_name": "BharatStore Delhi NCR Flagship",
        "hub_address": "Connaught Place, Block C, New Delhi 110001",
        "hub_lat": 28.6315,
        "hub_lng": 77.2167,
        "default_pincode": "110001",
        "areas": [
            {"name": "Connaught Place", "pincode": "110001", "lat": 28.6315, "lng": 77.2167, "distance_km": 0.4},
            {"name": "Saket", "pincode": "110017", "lat": 28.5244, "lng": 77.2100, "distance_km": 12.0},
            {"name": "Hauz Khas", "pincode": "110016", "lat": 28.5494, "lng": 77.2001, "distance_km": 9.3},
            {"name": "Vasant Kunj", "pincode": "110070", "lat": 28.5293, "lng": 77.1539, "distance_km": 13.5},
            {"name": "Noida Sector 18", "pincode": "201301", "lat": 28.5708, "lng": 77.3260, "distance_km": 14.1},
            {"name": "Gurgaon DLF Phase 1", "pincode": "122002", "lat": 28.4790, "lng": 77.0980, "distance_km": 20.5}
        ]
    },
    {
        "city": "Hyderabad",
        "state": "Telangana",
        "hub_code": "HUB-HYD-01",
        "hub_name": "BharatStore Hyderabad Hub",
        "hub_address": "Road No. 36, Jubilee Hills, Hyderabad 500033",
        "hub_lat": 17.4319,
        "hub_lng": 78.4073,
        "default_pincode": "500033",
        "areas": [
            {"name": "Jubilee Hills", "pincode": "500033", "lat": 17.4319, "lng": 78.4073, "distance_km": 0.5},
            {"name": "Banjara Hills", "pincode": "500034", "lat": 17.4156, "lng": 78.4354, "distance_km": 3.8},
            {"name": "HITEC City", "pincode": "500081", "lat": 17.4435, "lng": 78.3772, "distance_km": 4.1},
            {"name": "Madhapur", "pincode": "500081", "lat": 17.4483, "lng": 78.3915, "distance_km": 2.9},
            {"name": "Gachibowli", "pincode": "500032", "lat": 17.4401, "lng": 78.3489, "distance_km": 6.8}
        ]
    },
    {
        "city": "Chennai",
        "state": "Tamil Nadu",
        "hub_code": "HUB-CHN-01",
        "hub_name": "BharatStore Chennai Marina Store",
        "hub_address": "T Nagar, Chennai 600017",
        "hub_lat": 13.0418,
        "hub_lng": 80.2341,
        "default_pincode": "600017",
        "areas": [
            {"name": "T Nagar", "pincode": "600017", "lat": 13.0418, "lng": 80.2341, "distance_km": 0.4},
            {"name": "Anna Nagar", "pincode": "600040", "lat": 13.0850, "lng": 80.2101, "distance_km": 5.6},
            {"name": "Adyar", "pincode": "600020", "lat": 13.0012, "lng": 80.2565, "distance_km": 5.2},
            {"name": "Mylapore", "pincode": "600004", "lat": 13.0368, "lng": 80.2676, "distance_km": 3.7},
            {"name": "Velachery", "pincode": "600042", "lat": 12.9815, "lng": 80.2180, "distance_km": 7.1}
        ]
    },
    {
        "city": "Kolkata",
        "state": "West Bengal",
        "hub_code": "HUB-KOL-01",
        "hub_name": "BharatStore Kolkata Hub",
        "hub_address": "Park Street, Kolkata 700016",
        "hub_lat": 22.5516,
        "hub_lng": 88.3524,
        "default_pincode": "700016",
        "areas": [
            {"name": "Park Street", "pincode": "700016", "lat": 22.5516, "lng": 88.3524, "distance_km": 0.4},
            {"name": "Salt Lake Sector 5", "pincode": "700091", "lat": 22.5867, "lng": 88.4178, "distance_km": 7.8},
            {"name": "New Town", "pincode": "700156", "lat": 22.5850, "lng": 88.4680, "distance_km": 13.2},
            {"name": "Ballygunge", "pincode": "700019", "lat": 22.5280, "lng": 88.3655, "distance_km": 3.1},
            {"name": "Alipore", "pincode": "700027", "lat": 22.5333, "lng": 88.3333, "distance_km": 3.0}
        ]
    }
]

def calculate_haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance between two GPS coordinates in kilometers."""
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2))
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(R * c, 1)

def get_current_delivery_location() -> Dict[str, Any]:
    """Retrieves current delivery location from session or returns default Mumbai location."""
    loc = session.get("customer_location")
    if loc and isinstance(loc, dict) and loc.get("city"):
        return loc
    return {
        "city": "Mumbai",
        "area": "Bandra West",
        "pincode": "400050",
        "address_line": "Flat 402, Sea Green Apts, Worli Sea Face",
        "latitude": 19.0178,
        "longitude": 72.8178,
        "source": "default",
        "formatted": "Bandra West, Mumbai",
        "nearest_hub": "BharatStore Mumbai MegaHub",
        "distance_km": 0.5,
        "is_within_delivery_radius": True,
        "is_fallback": True
    }

@main_bp.app_context_processor
def inject_shopping_mode():
    """Injects current shopping mode and delivery location into all Jinja2 templates."""
    return {
        "current_shopping_mode": get_current_shopping_mode(),
        "valid_shopping_modes": ["ONLINE", "RETAIL_NEAR_ME"],
        "current_delivery_location": get_current_delivery_location()
    }

# -------------------------------------------------------------------------
# Retail Near Me View Builder
# -------------------------------------------------------------------------
def build_retail_context() -> Dict[str, Any]:
    """
    Constructs high-performance context for Retail Near Me storefront.
    Loads the 5 Bengaluru retail shops, grocery-only catalog, and
    multi-shop price comparisons.
    """
    set_current_shopping_mode("RETAIL_NEAR_ME")
    hubs = db_service.get_store_hubs()

    # Resolve delivery city
    loc = session.get("delivery_location") or {}
    city = (loc.get("city") or request.cookies.get("bharatstore_city") or "Bengaluru").strip()

    # Get active retail stores for city (5 Bengaluru shops by default)
    stores = db_service.get_retail_stores(city)
    if not stores:
        stores = db_service.get_retail_stores("Bengaluru")

    # 1. Resolve selected physical store (Query Param -> Session -> Default Store 1)
    store_id_param = request.args.get("store_id")
    selected_store = None
    if store_id_param:
        try:
            selected_store = db_service.get_store_by_id(int(store_id_param))
        except (ValueError, TypeError):
            selected_store = None

    if not selected_store:
        sess_store_id = session.get("retail_store_id")
        if sess_store_id:
            try:
                selected_store = db_service.get_store_by_id(int(sess_store_id))
            except (ValueError, TypeError):
                selected_store = None

    if not selected_store:
        selected_store = stores[0] if stores else None

    if selected_store:
        selected_store = db_service._enrich_store_metadata(selected_store)
        session["retail_store_id"] = selected_store["id"]

    # 2. Retrieve store inventory strictly for grocery products
    raw_inventory = db_service.get_store_inventory(selected_store["id"]) if selected_store else []
    # Strict filter: strictly grocery items only!
    inventory_items = [p for p in raw_inventory if p.get("category") == "Daily Essentials & Groceries"]

    # Fallback to grocery catalog if store inventory empty
    if not inventory_items:
        raw_prods = [p for p in db_service.get_all_products() if p.get("category") == "Daily Essentials & Groceries"]
        inventory_items = []
        for p in raw_prods:
            item = dict(p)
            item["product_id"] = p["id"]
            item["selling_price"] = p["price"]
            item["stock_quantity"] = p.get("stock", 20)
            item["available_quantity"] = p.get("stock", 20)
            item["is_available"] = True
            inventory_items.append(item)

    # 3. Attach multi-shop price comparison metadata to each item
    for item in inventory_items:
        comp = db_service.get_product_price_comparison(item["product_id"], city)
        if comp:
            item["lowest_price"] = comp["lowest_price"] if comp["lowest_price"] is not None else item["selling_price"]
            item["highest_price"] = comp["highest_price"] if comp["highest_price"] is not None else item["selling_price"]
            item["lowest_store_name"] = comp["lowest_store_name"] or (selected_store["store_name"] if selected_store else "Local Shop")
            item["lowest_store_id"] = comp["lowest_store_id"] or (selected_store["id"] if selected_store else 1)
            item["max_savings"] = comp["max_savings"]
            item["stores_comparison"] = comp["stores_comparison"]
            item["in_stock_stores_count"] = comp["in_stock_stores_count"]
            item["is_store_lowest"] = (item["selling_price"] == item["lowest_price"] and item["is_available"])
        else:
            item["lowest_price"] = item["selling_price"]
            item["highest_price"] = item["selling_price"]
            item["lowest_store_name"] = selected_store["store_name"] if selected_store else "Local Shop"
            item["lowest_store_id"] = selected_store["id"] if selected_store else 1
            item["max_savings"] = 0.0
            item["stores_comparison"] = []
            item["in_stock_stores_count"] = 1 if item["is_available"] else 0
            item["is_store_lowest"] = item["is_available"]

    # 4. Categorize into essential departments
    dairy_items = []
    grains_items = []
    essentials_items = []
    produce_items = []
    household_items = []

    for item in inventory_items:
        sub = item.get("sub_category", "")
        t = (item.get("title") or "").lower()
        if sub == "Dairy & Breakfast" or any(k in t for k in ["milk", "curd", "dahi", "paneer", "butter", "ghee", "cheese", "bread", "egg", "flake", "oat"]):
            item["department"] = "Dairy & Breakfast"
            dairy_items.append(item)
        elif sub == "Rice & Grains" or any(k in t for k in ["rice", "atta", "wheat", "dal", "besan", "grain", "chana", "rajma", "poha"]):
            item["department"] = "Rice & Grains"
            grains_items.append(item)
        elif sub == "Cooking Essentials" or any(k in t for k in ["oil", "sugar", "salt", "masala", "spice", "turmeric", "chilli", "coriander", "tea", "coffee"]):
            item["department"] = "Cooking Essentials"
            essentials_items.append(item)
        elif sub == "Fresh Produce" or any(k in t for k in ["potato", "onion", "tomato", "banana", "apple", "orange", "capsicum", "chilli", "coriander", "ginger", "adrak", "fruit", "vegetable"]):
            item["department"] = "Fresh Produce"
            produce_items.append(item)
        elif sub == "Household Essentials" or any(k in t for k in ["surf", "vim", "lizol", "dettol", "harpic", "colin", "goodknight", "scrub", "detergent", "cleaner"]):
            item["department"] = "Household Essentials"
            household_items.append(item)
        else:
            item["department"] = "Cooking Essentials"
            essentials_items.append(item)

    ordered_products = dairy_items + grains_items + essentials_items + produce_items + household_items

    # Top deals highlight
    top_deals = sorted([p for p in ordered_products if p.get("max_savings", 0) > 0], key=lambda x: x.get("max_savings", 0), reverse=True)[:6]

    return {
        "hubs": hubs,
        "stores": stores,
        "current_store": selected_store,
        "selected_store_id": selected_store["id"] if selected_store else 1,
        "dairy_items": dairy_items,
        "grains_items": grains_items,
        "essentials_items": essentials_items,
        "produce_items": produce_items,
        "household_items": household_items,
        "products": ordered_products,
        "all_store_products": ordered_products,
        "top_deals": top_deals,
        "active_mode": "RETAIL_NEAR_ME"
    }

# -------------------------------------------------------------------------
# Web Views
# -------------------------------------------------------------------------
@main_bp.route("/")
def index():
    mode = get_current_shopping_mode()
    if mode == "RETAIL_NEAR_ME" and request.args.get("view") != "online":
        ctx = build_retail_context()
        return render_template("retail.html", **ctx)
    return render_template("index.html")

@main_bp.route("/retail")
def retail_page():
    ctx = build_retail_context()
    return render_template("retail.html", **ctx)

@main_bp.route("/retail/stores")
def retail_stores_page():
    """
    Phase 5: Nearby Store Discovery Directory.
    Displays physical retail grocery shops within 15 km of customer location.
    Supports distance calculation, sorting, and category/perk filtering.
    """
    set_current_shopping_mode("RETAIL_NEAR_ME")
    
    loc = session.get("delivery_location") or {}
    lat_param = request.args.get("lat")
    lng_param = request.args.get("lng")
    
    if lat_param and lng_param:
        try:
            cust_lat = float(lat_param)
            cust_lng = float(lng_param)
        except (ValueError, TypeError):
            cust_lat = float(loc.get("lat", 12.9716))
            cust_lng = float(loc.get("lng", 77.5946))
    else:
        cust_lat = float(loc.get("lat", 12.9716))
        cust_lng = float(loc.get("lng", 77.5946))
        
    sort_by = request.args.get("sort", "nearest")
    cat_filter = request.args.get("filter", "all")
    open_only = request.args.get("open_now") == "1"
    delivery_only = request.args.get("delivery") == "1"
    pickup_only = request.args.get("pickup") == "1"
    
    nearby_stores = db_service.get_nearby_stores(
        lat=cust_lat,
        lng=cust_lng,
        max_radius_km=15.0,
        sort_by=sort_by,
        category_filter=cat_filter if cat_filter != "all" else None,
        open_only=open_only,
        delivery_only=delivery_only,
        pickup_only=pickup_only
    )
    
    current_store_id = session.get("retail_store_id", 1)
    
    return render_template(
        "retail_stores.html",
        stores=nearby_stores,
        total_stores=len(nearby_stores),
        customer_location={
            "lat": cust_lat,
            "lng": cust_lng,
            "formatted": loc.get("formatted", "Bengaluru, Karnataka"),
            "city": loc.get("city", "Bengaluru")
        },
        active_sort=sort_by,
        active_filter=cat_filter,
        open_only=open_only,
        delivery_only=delivery_only,
        pickup_only=pickup_only,
        current_store_id=current_store_id
    )

@main_bp.route("/retail/store/<int:store_id>")
def retail_store_front_page(store_id: int):
    """
    Phase 5: Dynamic individual storefront for a physical grocery store.
    Displays store-specific inventory, independent pricing, and stock.
    """
    set_current_shopping_mode("RETAIL_NEAR_ME")
    
    loc = session.get("delivery_location") or {}
    cust_lat = loc.get("lat")
    cust_lng = loc.get("lng")
    
    store_catalog = db_service.get_store_detail_with_catalog(store_id, user_lat=cust_lat, user_lng=cust_lng)
    if not store_catalog:
        flash(f"Store #{store_id} could not be found.", "warning")
        return redirect(url_for("main.retail_stores_page"))
        
    session["retail_store_id"] = store_id
    session.modified = True
    
    return render_template(
        "retail_store_detail.html",
        store=store_catalog["store"],
        dairy_items=store_catalog["dairy_items"],
        grains_items=store_catalog["grains_items"],
        essentials_items=store_catalog["essentials_items"],
        produce_items=store_catalog["produce_items"],
        household_items=store_catalog["household_items"],
        all_products=store_catalog["all_products"],
        total_products=store_catalog["total_products_count"],
        current_store=store_catalog["store"],
        current_delivery_location=loc
    )

# -----------------------------------------------------------------------------
# Retail Near Me 5-Shop Price Comparison & Hyperlocal APIs
# -----------------------------------------------------------------------------

@main_bp.route("/api/retail/stores", methods=["GET"])
def get_retail_stores_api():
    """Returns the 5 Bengaluru retail shops with complete metadata."""
    city = request.args.get("city", "Bengaluru")
    stores = db_service.get_retail_stores(city)
    return jsonify({
        "success": True,
        "stores": stores,
        "total_stores": len(stores),
        "city": city
    })

@main_bp.route("/api/retail/stores/nearby", methods=["GET"])
def get_nearby_retail_stores_api():
    """
    Phase 5: Returns physical stores within a maximum 15 km radius
    calculated using Haversine great-circle distance from customer coordinates.
    """
    lat_param = request.args.get("lat")
    lng_param = request.args.get("lng")
    radius_param = request.args.get("radius", "15.0")
    sort_param = request.args.get("sort", "nearest")
    filter_param = request.args.get("filter")
    open_only = request.args.get("open_now", "").lower() in ["true", "1", "yes"]
    delivery_only = request.args.get("delivery", "").lower() in ["true", "1", "yes"]
    pickup_only = request.args.get("pickup", "").lower() in ["true", "1", "yes"]

    if not lat_param or not lng_param:
        loc = session.get("delivery_location") or {}
        if loc.get("lat") and loc.get("lng"):
            lat_param = loc["lat"]
            lng_param = loc["lng"]
        else:
            return jsonify({
                "success": False,
                "error": "Customer latitude ('lat') and longitude ('lng') query parameters are required."
            }), 400

    try:
        lat = float(lat_param)
        lng = float(lng_param)
        radius = float(radius_param)
    except (ValueError, TypeError):
        return jsonify({
            "success": False,
            "error": "Latitude, longitude, and radius must be valid numbers."
        }), 400

    if not (-90.0 <= lat <= 90.0):
        return jsonify({"success": False, "error": "Latitude must be between -90.0 and 90.0 degrees."}), 400
    if not (-180.0 <= lng <= 180.0):
        return jsonify({"success": False, "error": "Longitude must be between -180.0 and 180.0 degrees."}), 400
    if radius <= 0 or radius > 15.0:
        return jsonify({"success": False, "error": "Radius must be greater than 0 and cannot exceed 15 km."}), 400

    try:
        stores = db_service.get_nearby_stores(
            lat=lat,
            lng=lng,
            max_radius_km=radius,
            sort_by=sort_param,
            category_filter=filter_param,
            open_only=open_only,
            delivery_only=delivery_only,
            pickup_only=pickup_only
        )
        return jsonify({
            "success": True,
            "count": len(stores),
            "radius_km": radius,
            "customer_location": {
                "lat": lat,
                "lng": lng
            },
            "stores": stores
        })
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error finding nearby stores: {e}", exc_info=True)
        return jsonify({"success": False, "error": "Failed to discover nearby stores."}), 500

@main_bp.route("/api/retail/stores/<int:store_id>", methods=["GET"])
def get_retail_store_by_id_api(store_id: int):
    """Returns complete details for a specific retail store, enriched with distance if customer coordinates provided."""
    store = db_service.get_store_by_id(store_id)
    if not store:
        return jsonify({"success": False, "error": f"Store #{store_id} not found."}), 404

    user_lat = request.args.get("lat")
    user_lng = request.args.get("lng")
    if not user_lat or not user_lng:
        loc = session.get("delivery_location") or {}
        user_lat = loc.get("lat")
        user_lng = loc.get("lng")

    store_data = db_service.get_store_detail_with_catalog(store_id, user_lat=user_lat, user_lng=user_lng)
    return jsonify({
        "success": True,
        "store": store_data["store"],
        "total_products": store_data["total_products_count"]
    })

@main_bp.route("/api/retail/catalog", methods=["GET"])
def get_retail_catalog_api():
    """Returns dynamic retail grocery-only catalog grouped by department with 5-shop price comparisons."""
    ctx = build_retail_context()
    return jsonify({
        "success": True,
        "current_store": ctx["current_store"],
        "dairy_items": ctx["dairy_items"],
        "grains_items": ctx["grains_items"],
        "essentials_items": ctx["essentials_items"],
        "produce_items": ctx["produce_items"],
        "household_items": ctx.get("household_items", []),
        "all_products": ctx["products"],
        "top_deals": ctx.get("top_deals", []),
        "total_items": len(ctx["products"])
    })

@main_bp.route("/api/retail/products/<int:product_id>/compare", methods=["GET"])
@main_bp.route("/api/retail/compare/<int:product_id>", methods=["GET"])
def get_retail_product_compare_api(product_id: int):
    """Returns real-time 5-shop price comparison and stock status for a grocery product."""
    product = db_service.get_product_by_id(product_id)
    if not product or not is_retail_grocery_product(product):
        return jsonify({"success": False, "error": f"Grocery product #{product_id} not found."}), 404

    city = request.args.get("city", "Bengaluru")
    comparison = db_service.get_product_price_comparison(product_id, city)
    if not comparison:
        return jsonify({"success": False, "error": f"Grocery product #{product_id} not found."}), 404
    return jsonify({
        "success": True,
        **comparison
    })

@main_bp.route("/api/retail/stores/<int:store_id>/products", methods=["GET"])
def get_retail_store_products_api(store_id: int):
    """Returns grocery products available at a specific physical store."""
    store = db_service.get_store_by_id(store_id)
    if not store:
        return jsonify({"success": False, "error": f"Store #{store_id} not found."}), 404
    prods = db_service.get_available_store_products(store_id)
    grocery_prods = [p for p in prods if p.get("category") == "Daily Essentials & Groceries"]
    return jsonify({
        "success": True,
        "store": db_service._enrich_store_metadata(store),
        "products": grocery_prods,
        "total_products": len(grocery_prods)
    })

@main_bp.route("/api/retail/stores/<int:store_id>/products/<int:product_id>", methods=["GET"])
def get_retail_store_product_detail_api(store_id: int, product_id: int):
    """Returns grocery product availability, price, and stock for a specific store."""
    store = db_service.get_store_by_id(store_id)
    if not store:
        return jsonify({"success": False, "error": f"Store #{store_id} not found."}), 404
    item = db_service.get_store_product(store_id, product_id)
    if not item:
        return jsonify({"success": False, "error": f"Product #{product_id} not available at store #{store_id}."}), 404
    return jsonify({
        "success": True,
        "store": db_service._enrich_store_metadata(store),
        "product": item
    })

# -----------------------------------------------------------------------------
# Retail Shop-Aware Cart Management Endpoints
# -----------------------------------------------------------------------------

def _get_session_retail_cart() -> Dict[str, Any]:
    if "retail_cart" not in session or not isinstance(session["retail_cart"], dict):
        session["retail_cart"] = {}
    return session["retail_cart"]

def _calculate_retail_cart_summary(cart_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Computes shop-wise breakdown, subtotals, delivery fees and grand total."""
    shops_map = {}
    total_qty = 0
    grand_subtotal = 0.0

    for key, item in cart_dict.items():
        sid = item["store_id"]
        if sid not in shops_map:
            store_obj = db_service.get_store_by_id(sid)
            s_name = store_obj["store_name"] if store_obj else item.get("store_name", f"Store #{sid}")
            s_area = store_obj["area"] if store_obj else item.get("area", "")
            min_ord = 99.0
            del_fee = 15.0
            if store_obj:
                enriched = db_service._enrich_store_metadata(store_obj)
                min_ord = enriched.get("min_order", 99.0)
                del_fee = enriched.get("delivery_fee", 15.0)

            shops_map[sid] = {
                "store_id": sid,
                "store_name": s_name,
                "area": s_area,
                "min_order": min_ord,
                "base_delivery_fee": del_fee,
                "items": [],
                "subtotal": 0.0,
                "delivery_fee": del_fee,
                "fulfillment": item.get("fulfillment", "delivery"),
                "fulfillment_type": item.get("fulfillment", "delivery")
            }

        item_subtotal = round(float(item["price"]) * int(item["quantity"]), 2)
        item["subtotal"] = item_subtotal
        shops_map[sid]["items"].append(item)
        shops_map[sid]["subtotal"] = round(shops_map[sid]["subtotal"] + item_subtotal, 2)
        total_qty += int(item["quantity"])
        grand_subtotal = round(grand_subtotal + item_subtotal, 2)

    shops_list = []
    total_delivery_fee = 0.0

    for sid, sdata in shops_map.items():
        if sdata["fulfillment_type"] == "pickup" or sdata["subtotal"] >= sdata["min_order"]:
            sdata["delivery_fee"] = 0.0
        else:
            sdata["delivery_fee"] = sdata["base_delivery_fee"]
        total_delivery_fee += sdata["delivery_fee"]
        shops_list.append(sdata)

    grand_total = round(grand_subtotal + total_delivery_fee, 2)

    return {
        "items": list(cart_dict.values()),
        "shops": shops_list,
        "total_items": total_qty,
        "subtotal": grand_subtotal,
        "delivery_fee": round(total_delivery_fee, 2),
        "grand_total": grand_total
    }

@main_bp.route("/api/retail/cart", methods=["GET"])
def get_retail_cart_api():
    """Returns current retail cart with shop-wise breakdown."""
    cart_dict = _get_session_retail_cart()
    summary = _calculate_retail_cart_summary(cart_dict)
    return jsonify({
        "success": True,
        **summary
    })

@main_bp.route("/api/retail/cart/add", methods=["POST"])
def add_to_retail_cart_api():
    """Adds a product to retail cart associated with a specific store."""
    data = request.get_json() or {}
    product_id = data.get("product_id")
    store_id = data.get("store_id")
    quantity = data.get("quantity", 1)
    fulfillment = data.get("fulfillment", "delivery")

    if not product_id:
        return jsonify({"success": False, "error": "Product ID is required."}), 400
    if not store_id:
        return jsonify({"success": False, "error": "Store ID is required for Retail mode."}), 400

    try:
        pid = int(product_id)
        sid = int(store_id)
        qty = int(quantity)
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid IDs or quantity format."}), 400

    if qty <= 0:
        return jsonify({"success": False, "error": "Quantity must be at least 1."}), 400

    store = db_service.get_store_by_id(sid)
    if not store:
        return jsonify({"success": False, "error": f"Store #{sid} not found."}), 404

    inv = db_service.get_store_product(sid, pid)
    if not inv or not inv.get("is_available") or inv.get("stock_quantity", 0) <= 0:
        return jsonify({"success": False, "error": f"Sorry, this item is Out of Stock at {store['store_name']}."}), 400

    available_stock = int(inv["stock_quantity"])

    cust_id, sess_id = _get_cart_auth()
    try:
        db_service.add_to_cart(cust_id, sess_id, "RETAIL_NEAR_ME", pid, qty, store_id=sid, fulfillment=fulfillment)
    except Exception as e:
        logger.warning(f"DB add_to_cart sync notice in legacy endpoint: {e}")

    cart_dict = _get_session_retail_cart()
    item_key = f"{sid}_{pid}"
    existing_qty = cart_dict[item_key]["quantity"] if item_key in cart_dict else 0
    new_qty = existing_qty + qty

    if new_qty > available_stock:
        return jsonify({
            "success": False,
            "error": f"Requested quantity ({new_qty}) exceeds available stock ({available_stock}) at {store['store_name']}."
        }), 400

    cart_dict[item_key] = {
        "item_key": item_key,
        "store_id": sid,
        "store_name": store["store_name"],
        "area": store["area"],
        "product_id": pid,
        "title": inv["title"],
        "brand": inv.get("brand", ""),
        "sub_category": inv.get("sub_category", ""),
        "price": float(inv["selling_price"]),
        "original_price": float(inv["original_price"]) if inv.get("original_price") else float(inv["selling_price"]),
        "image_url": inv.get("image_url", ""),
        "quantity": new_qty,
        "fulfillment": fulfillment
    }

    session["retail_cart"] = cart_dict
    session.modified = True
    summary = _calculate_retail_cart_summary(cart_dict)

    return jsonify({
        "success": True,
        "message": f"Added {inv['title']} from {store['store_name']} to basket.",
        "added_item": cart_dict[item_key],
        **summary
    }), 201

@main_bp.route("/api/retail/cart/update", methods=["PUT"])
def update_retail_cart_api():
    """Updates quantity or fulfillment type for an item in the retail cart."""
    data = request.get_json() or {}
    product_id = data.get("product_id")
    store_id = data.get("store_id")
    quantity = data.get("quantity")
    fulfillment = data.get("fulfillment")

    if not product_id or not store_id:
        return jsonify({"success": False, "error": "product_id and store_id are required."}), 400

    try:
        pid = int(product_id)
        sid = int(store_id)
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid parameters."}), 400

    cart_dict = _get_session_retail_cart()
    item_key = f"{sid}_{pid}"

    if quantity is None:
        qty = cart_dict.get(item_key, {}).get("quantity", 1)
    else:
        try:
            qty = int(quantity)
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "Invalid quantity."}), 400

    if qty <= 0:
        cart_dict.pop(item_key, None)
    else:
        inv = db_service.get_store_product(sid, pid)
        if not inv or not inv.get("is_available"):
            cart_dict.pop(item_key, None)
            return jsonify({"success": False, "error": "Item is no longer available at this store."}), 400

        avail = int(inv["stock_quantity"])
        if qty > avail:
            qty = avail

        if item_key in cart_dict:
            cart_dict[item_key]["quantity"] = qty
            if fulfillment:
                cart_dict[item_key]["fulfillment"] = fulfillment
        else:
            store = db_service.get_store_by_id(sid)
            cart_dict[item_key] = {
                "item_key": item_key,
                "store_id": sid,
                "store_name": store["store_name"] if store else f"Store #{sid}",
                "area": store["area"] if store else "",
                "product_id": pid,
                "title": inv["title"],
                "price": float(inv["selling_price"]),
                "image_url": inv.get("image_url", ""),
                "quantity": qty,
                "fulfillment": fulfillment or "delivery"
            }

    session["retail_cart"] = cart_dict
    session.modified = True
    summary = _calculate_retail_cart_summary(cart_dict)

    return jsonify({
        "success": True,
        **summary
    })

@main_bp.route("/api/retail/cart/remove", methods=["DELETE"])
def remove_from_retail_cart_api():
    """Removes an item from the retail cart."""
    data = request.get_json() or {}
    product_id = data.get("product_id") or request.args.get("product_id")
    store_id = data.get("store_id") or request.args.get("store_id")

    if not product_id or not store_id:
        return jsonify({"success": False, "error": "product_id and store_id are required."}), 400

    try:
        pid = int(product_id)
        sid = int(store_id)
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid parameters."}), 400

    cart_dict = _get_session_retail_cart()
    item_key = f"{sid}_{pid}"
    cart_dict.pop(item_key, None)

    session["retail_cart"] = cart_dict
    session.modified = True
    summary = _calculate_retail_cart_summary(cart_dict)

    return jsonify({
        "success": True,
        "message": "Item removed from basket.",
        **summary
    })


def _get_cart_auth():
    """Returns (customer_id, session_id) for the current request."""
    sess_id = request.args.get("session_id") or request.headers.get("X-Session-Id") or session.get("session_id")
    if not sess_id:
        sess_id = str(uuid.uuid4())
        session["session_id"] = sess_id
        session.permanent = True

    cust_id = None
    if session.get("customer_id"):
        try:
            cust_id = int(session["customer_id"])
        except (ValueError, TypeError):
            pass
    elif request.headers.get("X-Customer-Id"):
        try:
            cust_id = int(request.headers["X-Customer-Id"])
        except (ValueError, TypeError):
            pass
    elif request.args.get("customer_id"):
        try:
            cust_id = int(request.args["customer_id"])
        except (ValueError, TypeError):
            pass
    return cust_id, sess_id

# -----------------------------------------------------------------------------
# Phase 7: Advanced Multi-Store Cart & Checkout APIs
# -----------------------------------------------------------------------------

@main_bp.route("/api/cart/online", methods=["GET"])
def get_cart_online_api():
    """Returns independent Online Shopping marketplace cart."""
    cust_id, sess_id = _get_cart_auth()
    cart = db_service.get_cart(cust_id, sess_id, shopping_mode="ONLINE")
    return jsonify({"success": True, "cart": cart})

@main_bp.route("/api/cart/retail", methods=["GET"])
def get_cart_retail_api():
    """Returns central Retail master cart grouped by shop."""
    cust_id, sess_id = _get_cart_auth()
    loc = session.get("delivery_location") or {}
    cust_lat = request.args.get("lat", loc.get("lat"))
    cust_lng = request.args.get("lng", loc.get("lng"))
    retail_carts = db_service.get_all_retail_carts(cust_id, sess_id, customer_lat=cust_lat, customer_lng=cust_lng)
    return jsonify(retail_carts)

@main_bp.route("/api/cart/retail/<int:store_id>", methods=["GET"])
def get_cart_retail_store_api(store_id: int):
    """Returns single physical store basket."""
    cust_id, sess_id = _get_cart_auth()
    cart = db_service.get_cart(cust_id, sess_id, shopping_mode="RETAIL_NEAR_ME", store_id=store_id)
    return jsonify({"success": True, "cart": cart})

@main_bp.route("/api/cart/summary", methods=["GET"])
def get_cart_summary_api():
    """Returns global cart summary and counts across shopping modes."""
    cust_id, sess_id = _get_cart_auth()
    mode = get_current_shopping_mode()
    online_cart = db_service.get_cart(cust_id, sess_id, shopping_mode="ONLINE")
    retail_carts = db_service.get_all_retail_carts(cust_id, sess_id)

    curr_total = online_cart["total_items"] if mode == "ONLINE" else retail_carts["total_items"]
    curr_subtotal = online_cart["subtotal"] if mode == "ONLINE" else retail_carts["subtotal"]

    return jsonify({
        "success": True,
        "shopping_mode": mode,
        "total_items": online_cart["total_items"] + retail_carts["total_items"],
        "subtotal": round(online_cart["subtotal"] + retail_carts["subtotal"], 2),
        "grand_total": round(online_cart["subtotal"] + retail_carts["grand_total"], 2),
        "online": {
            "total_items": online_cart["total_items"],
            "subtotal": online_cart["subtotal"]
        },
        "retail": {
            "total_items": retail_carts["total_items"],
            "subtotal": retail_carts["subtotal"],
            "shops_count": len(retail_carts["shops"])
        },
        "current": {
            "total_items": curr_total,
            "subtotal": curr_subtotal
        }
    })

@main_bp.route("/api/cart/online/add", methods=["POST"])
def add_to_cart_online_api():
    """Adds a product to independent Online Shopping cart."""
    cust_id, sess_id = _get_cart_auth()
    data = request.get_json() or {}
    pid = data.get("product_id")
    qty = data.get("quantity", 1)

    if not pid:
        return jsonify({"success": False, "error": "product_id is required."}), 400
    try:
        pid = int(pid)
        qty = int(qty)
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid product_id or quantity format."}), 400

    try:
        updated_cart = db_service.add_to_cart(cust_id, sess_id, "ONLINE", pid, qty)
        return jsonify({
            "success": True,
            "message": "Added item to Online cart.",
            "cart": updated_cart
        }), 201
    except ValueError as e:
        status_code = 404 if ("not found" in str(e).lower() or "does not exist" in str(e).lower()) else 400
        return jsonify({"success": False, "error": str(e)}), status_code
    except Exception as e:
        logger.error(f"Error in add_to_cart_online: {e}")
        return jsonify({"success": False, "error": "Failed to add item to online cart."}), 500

@main_bp.route("/api/cart/retail/<int:store_id>/add", methods=["POST"])
def add_to_cart_retail_store_api(store_id: int):
    """Adds a grocery product to specific retail store basket."""
    cust_id, sess_id = _get_cart_auth()
    data = request.get_json() or {}
    pid = data.get("product_id")
    qty = data.get("quantity", 1)
    fulfillment = data.get("fulfillment", "delivery")

    if not pid:
        return jsonify({"success": False, "error": "product_id is required."}), 400
    try:
        pid = int(pid)
        qty = int(qty)
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid parameters format."}), 400

    try:
        updated_cart = db_service.add_to_cart(cust_id, sess_id, "RETAIL_NEAR_ME", pid, qty, store_id=store_id, fulfillment=fulfillment)
        # Also sync session retail cart dictionary
        cart_dict = _get_session_retail_cart()
        item_key = f"{store_id}_{pid}"
        item_id = None
        if updated_cart.get("items"):
            item_obj = next((it for it in updated_cart["items"] if it["product_id"] == pid), None)
            if item_obj:
                item_id = item_obj.get("item_id") or item_obj.get("id")
                cart_dict[item_key] = {
                    "item_key": item_key,
                    "store_id": store_id,
                    "store_name": updated_cart.get("store_name", f"Store #{store_id}"),
                    "product_id": pid,
                    "title": item_obj["title"],
                    "price": item_obj["price"],
                    "quantity": item_obj["quantity"],
                    "image_url": item_obj.get("image_url", ""),
                    "fulfillment": item_obj.get("fulfillment", "delivery")
                }
                session["retail_cart"] = cart_dict
                session.modified = True

        return jsonify({
            "success": True,
            "message": f"Added item to Store #{store_id} basket.",
            "cart": updated_cart,
            "cart_item_id": item_id
        }), 201
    except ValueError as e:
        status_code = 404 if ("not found" in str(e).lower() or "does not exist" in str(e).lower()) else 400
        return jsonify({"success": False, "error": str(e)}), status_code
    except Exception as e:
        logger.error(f"Error in add_to_cart_retail_store: {e}")
        return jsonify({"success": False, "error": "Failed to add item to retail store basket."}), 500

@main_bp.route("/api/cart/items/<int:item_id>", methods=["PATCH", "PUT"])
def update_cart_item_api(item_id: int):
    """Updates item quantity or fulfillment option."""
    cust_id, sess_id = _get_cart_auth()
    data = request.get_json() or {}
    qty = data.get("quantity")
    fulfillment = data.get("fulfillment")

    if qty is not None:
        try:
            qty = int(qty)
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "Invalid quantity format."}), 400

    try:
        updated_cart = db_service.update_cart_item(item_id, quantity=qty, fulfillment=fulfillment, customer_id=cust_id, session_id=sess_id)
        return jsonify({"success": True, "cart": updated_cart})
    except ValueError as e:
        status_code = 404 if ("not found" in str(e).lower() or "does not exist" in str(e).lower()) else 400
        return jsonify({"success": False, "error": str(e)}), status_code
    except PermissionError as e:
        return jsonify({"success": False, "error": str(e)}), 403
    except Exception as e:
        logger.error(f"Error updating cart item {item_id}: {e}")
        return jsonify({"success": False, "error": "Failed to update cart item."}), 500

@main_bp.route("/api/cart/items/<int:item_id>", methods=["DELETE"])
def delete_cart_item_api(item_id: int):
    """Removes an item from cart."""
    cust_id, sess_id = _get_cart_auth()
    try:
        updated_cart = db_service.remove_cart_item(item_id, customer_id=cust_id, session_id=sess_id)
        return jsonify({"success": True, "message": "Item removed from basket.", "cart": updated_cart})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except PermissionError as e:
        return jsonify({"success": False, "error": str(e)}), 403
    except Exception as e:
        logger.error(f"Error removing cart item {item_id}: {e}")
        return jsonify({"success": False, "error": "Failed to remove cart item."}), 500

@main_bp.route("/api/cart/online/clear", methods=["DELETE"])
def clear_cart_online_api():
    """Clears entire Online Shopping marketplace cart."""
    cust_id, sess_id = _get_cart_auth()
    db_service.clear_cart(cust_id, sess_id, shopping_mode="ONLINE")
    return jsonify({"success": True, "message": "Online Shopping cart cleared."})

@main_bp.route("/api/cart/retail/<int:store_id>/clear", methods=["DELETE"])
def clear_cart_retail_store_api(store_id: int):
    """Clears specific store basket."""
    cust_id, sess_id = _get_cart_auth()
    db_service.clear_cart(cust_id, sess_id, shopping_mode="RETAIL_NEAR_ME", store_id=store_id)
    cart_dict = _get_session_retail_cart()
    keys_to_del = [k for k in cart_dict.keys() if k.startswith(f"{store_id}_")]
    for k in keys_to_del:
        cart_dict.pop(k, None)
    session["retail_cart"] = cart_dict
    session.modified = True
    return jsonify({"success": True, "message": f"Store #{store_id} basket cleared."})

@main_bp.route("/api/cart/retail/clear", methods=["DELETE"])
def clear_all_retail_carts_api():
    """Clears all active Retail store baskets."""
    cust_id, sess_id = _get_cart_auth()
    db_service.clear_all_retail_carts(cust_id, sess_id)
    session["retail_cart"] = {}
    session.modified = True
    return jsonify({"success": True, "message": "All retail store baskets cleared."})

@main_bp.route("/api/checkout/online", methods=["POST"])
def checkout_online_api():
    """Executes checkout for Online Shopping cart."""
    cust_id, sess_id = _get_cart_auth()
    data = request.get_json() or {}
    cust_info = data.get("customer_info") or {
        "name": "Priya Sharma",
        "email": "priya.sharma@example.in",
        "phone": "+91 98201 12345",
        "address": "Flat 402, Sea Green Apts, Worli Sea Face",
        "city": "Mumbai"
    }
    payment_method = data.get("payment_method", "UPI")
    try:
        order = db_service.checkout_online_cart(cust_id or 1, sess_id, cust_info, payment_method)
        kafka_ev = None
        try:
            kafka_ev = kafka_service.produce_order_created_event(
                order_id=order.get("order_id") or order.get("id", 1),
                order_number=order.get("order_number", "BK-ORD-ONLINE"),
                customer_email=cust_info.get("email", "priya.sharma@example.in"),
                total_amount=order.get("total_amount", 0.0),
                items_count=len(order.get("items", []))
            )
        except Exception as ke:
            logger.debug(f"Kafka produce notice: {ke}")
        order["kafka_event"] = kafka_ev
        placed = session.setdefault("placed_order_ids", [])
        if order.get("order_id"):
            placed.append(order["order_id"])
        if order.get("id"):
            placed.append(order["id"])
        session.modified = True
        return jsonify({"success": True, "order": order}), 201
    except ValueError as e:
        status_code = 404 if ("not found" in str(e).lower() or "does not exist" in str(e).lower()) else 400
        return jsonify({"success": False, "error": str(e)}), status_code
    except Exception as e:
        logger.error(f"Checkout online error: {e}")
        return jsonify({"success": False, "error": "Checkout failed."}), 500

@main_bp.route("/api/checkout/retail", methods=["POST"])
@main_bp.route("/api/checkout/retail/multi-store", methods=["POST"])
def checkout_retail_multi_store_api():
    """Executes multi-store checkout for selected Retail baskets."""
    cust_id, sess_id = _get_cart_auth()
    data = request.get_json() or {}
    selected_store_ids = data.get("selected_store_ids") or data.get("store_ids")
    if not selected_store_ids and data.get("store_id"):
        selected_store_ids = [data.get("store_id")]

    if not selected_store_ids:
        all_carts = db_service.get_all_retail_carts(cust_id, sess_id)
        selected_store_ids = [s["store_id"] for s in all_carts.get("shops", [])]

    if not selected_store_ids:
        return jsonify({"success": False, "error": "No retail store baskets selected for checkout."}), 400

    try:
        selected_store_ids = [int(s) for s in selected_store_ids]
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid store ID format."}), 400

    cust_info = data.get("customer_info") or {
        "name": "Priya Sharma",
        "email": "priya.sharma@example.in",
        "phone": "+91 98201 12345",
        "address": "Flat 402, Sea Green Apts, Worli Sea Face",
        "city": "Bengaluru"
    }
    delivery_address = data.get("delivery_address") or session.get("delivery_location") or {
        "latitude": 12.9784,
        "longitude": 77.6408,
        "city": "Bengaluru",
        "formatted": "CMH Road, Indiranagar, Bengaluru"
    }
    payment_method = data.get("payment_method", "UPI")

    try:
        summary = db_service.checkout_retail_multi_store(
            customer_id=cust_id or 1,
            session_id=sess_id,
            selected_store_ids=selected_store_ids,
            customer_info=cust_info,
            delivery_address=delivery_address,
            payment_method=payment_method
        )
        kafka_ev = None
        try:
            kafka_ev = kafka_service.produce_order_created_event(
                order_id=summary.get("parent_order_id") or summary.get("order_id"),
                order_number=summary.get("parent_order_number") or summary.get("order_number"),
                customer_email=cust_info.get("email", "priya.sharma@example.in"),
                total_amount=summary.get("grand_total") or summary.get("total_amount"),
                items_count=sum(s["items_count"] for s in summary.get("suborders", [])) if summary.get("suborders") else summary.get("items_count", 1)
            )
        except Exception as ke:
            logger.debug(f"Kafka retail produce notice: {ke}")
        summary["kafka_event"] = kafka_ev
        cart_dict = _get_session_retail_cart()
        for sid in selected_store_ids:
            keys_to_del = [k for k in cart_dict.keys() if k.startswith(f"{sid}_")]
            for k in keys_to_del:
                cart_dict.pop(k, None)
        session["retail_cart"] = cart_dict

        placed = session.setdefault("placed_order_ids", [])
        if summary.get("parent_order_id"):
            placed.append(summary["parent_order_id"])
        if summary.get("order_id"):
            placed.append(summary["order_id"])
        for sub in summary.get("suborders", []):
            if sub.get("suborder_id"):
                placed.append(sub["suborder_id"])
        session.modified = True

        return jsonify(summary), 201
    except ValueError as e:
        status_code = 404 if ("not found" in str(e).lower() or "does not exist" in str(e).lower()) else 400
        return jsonify({"success": False, "error": str(e)}), status_code
    except Exception as e:
        logger.error(f"Multi-store checkout error: {e}")
        return jsonify({"success": False, "error": "Multi-store checkout failed."}), 500

def _check_order_access(order: Dict[str, Any]) -> bool:
    """
    Validates that the current user/session is authorized to view the given order:
    - Admin users (header or role) have full access.
    - Authenticated customers can view their own orders.
    - Guest sessions can view orders placed in this session.
    - Order access token matches order_number.
    Prevents IDOR (Insecure Direct Object Reference) access.
    """
    if not order:
        return False

    admin_token = request.headers.get("X-Admin-Token")
    if admin_token and admin_token == Config.ADMIN_API_KEY:
        return True
    if session.get("is_admin") or session.get("user_role") == "ADMIN":
        return True

    cust_id, sess_id = _get_cart_auth()
    order_cust_id = order.get("customer_id")
    if cust_id and order_cust_id:
        if int(cust_id) == int(order_cust_id):
            return True
        else:
            return False

    placed = session.get("placed_order_ids") or []
    order_id = order.get("id") or order.get("order_id")
    parent_id = order.get("parent_order_id")
    if order_id in placed or (parent_id and parent_id in placed):
        return True

    token = request.args.get("token") or request.headers.get("X-Order-Token")
    if token and token == order.get("order_number"):
        return True

    if getattr(Config, "ALLOW_INSECURE_TEST_ENDPOINTS", False):
        return True

    return False

@main_bp.route("/online")
def online_page():
    set_current_shopping_mode("ONLINE")
    return render_template("index.html")

@main_bp.route("/select-mode")
def select_mode_page():
    return render_template("select_mode.html", current_mode=get_current_shopping_mode())

@main_bp.route("/architecture")
def architecture():
    return render_template("architecture.html")

@main_bp.route("/orders")
def orders_page():
    return render_template("orders.html")

@main_bp.route("/order/<int:order_id>")
@main_bp.route("/orders/<int:order_id>")
def order_detail_page(order_id: int):
    order = db_service.get_order_by_id(order_id)
    if not order:
        return render_template("order_detail.html", order=None, error=f"Order #{order_id} was not found."), 404

    if not _check_order_access(order):
        return render_template("order_detail.html", order=None, error="Unauthorized: You do not have permission to view this order.", forbidden=True), 403

    tracking = db_service.get_shipment_tracking(order_id)
    if tracking and "shipment" not in tracking:
        tracking["shipment"] = tracking
    return render_template("order_detail.html", order=order, tracking=tracking)

@main_bp.route("/products")
def products_page():
    category = request.args.get("category", "")
    query = request.args.get("q", "")
    return render_template("products.html", active_category=category, search_query=query)

@main_bp.route("/category/<string:category_slug>")
def category_page(category_slug: str):
    cat_map = {
        "groceries": "Daily Essentials & Groceries",
        "foods": "Daily Essentials & Groceries",
        "mobiles": "Mobiles & Tablets",
        "laptops": "Laptops & Computers",
        "audio": "Audio & Wearables",
        "home": "Home & Kitchen",
        "fashion": "Fashion & Apparel",
        "beauty": "Beauty & Personal Care"
    }
    cat_name = cat_map.get(category_slug.lower(), category_slug)
    return render_template("products.html", active_category=cat_name, search_query="")

@main_bp.route("/product/<int:product_id>")
def product_detail_page(product_id: int):
    product = db_service.get_product_by_id(product_id)
    if not product:
        return render_template("products.html", error=f"Product #{product_id} was not found in our catalog.", not_found_id=product_id), 404
    related_products = db_service.get_related_products(product_id, product.get("category"), limit=4)
    reviews = db_service.get_product_reviews(product_id)
    review_stats = db_service.get_review_statistics(product_id)
    return render_template(
        "product_detail.html",
        product=product,
        related_products=related_products,
        reviews=reviews,
        review_stats=review_stats
    )

@main_bp.route("/cart")
def cart_page():
    return render_template("cart.html")

@main_bp.route("/wishlist")
def wishlist_page():
    return render_template("wishlist.html")

@main_bp.route("/checkout")
def checkout_page():
    return render_template("checkout.html")

@main_bp.route("/login")
def login_page():
    return render_template("auth_login.html")

@main_bp.route("/api/auth/login", methods=["POST"])
def auth_login_api():
    data = request.get_json(silent=True) or {}
    customer_id = data.get("customer_id") or 1
    session["customer_id"] = int(customer_id)
    session.modified = True
    return jsonify({"success": True, "customer_id": int(customer_id), "message": "Logged in successfully."})

@main_bp.route("/api/auth/logout", methods=["POST", "GET"])
@main_bp.route("/logout", methods=["POST", "GET"])
def auth_logout_api():
    session.pop("customer_id", None)
    session["session_id"] = str(uuid.uuid4())
    session.pop("retail_cart", None)
    session.modified = True
    if request.path == "/logout" and request.method == "GET":
        from flask import redirect
        return redirect("/login")
    return jsonify({"success": True, "message": "Logged out successfully."})

@main_bp.route("/register")
def register_page():
    return render_template("auth_register.html")

@main_bp.route("/profile")
def profile_page():
    return render_template("profile.html")

@main_bp.route("/admin")
def admin_dashboard():
    return render_template("admin_dashboard.html")

@main_bp.route("/admin/products")
def admin_products():
    return render_template("admin_products.html")

@main_bp.route("/admin/inventory")
def admin_inventory():
    return render_template("admin_inventory.html")

@main_bp.route("/admin/orders")
def admin_orders():
    return render_template("admin_orders.html")

@main_bp.route("/download-pitch-deck")
def download_pitch_deck():
    from flask import send_file
    pdf_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "BharatStore_Pitch_Deck.pdf"))
    return send_file(pdf_path, as_attachment=False, mimetype="application/pdf")

@main_bp.route("/download-zip")
def download_zip():
    from flask import send_file
    zip_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "BharatStore_Project.zip"))
    return send_file(zip_path, as_attachment=True, download_name="BharatStore_Project.zip", mimetype="application/zip")

# -------------------------------------------------------------------------
# Health & Status API
# -------------------------------------------------------------------------
@main_bp.route("/api/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "healthy",
        "app": "BharatKart E-Commerce Platform",
        "services": {
            "postgresql": {
                "configured": Config.is_pg_configured(),
                "is_live": db_service.is_live_postgres,
                "label": "Aiven for PostgreSQL (Live)" if db_service.is_live_postgres else "Local ACID Engine (Row-Locked)",
                "details": f"Database: {Config.AIVEN_PG_DATABASE}" if db_service.is_live_postgres else "SQLite in WAL/Immediate mode",
                "error": db_service.connection_error
            },
            "kafka": {
                "configured": Config.is_kafka_configured(),
                "is_live": kafka_service.is_live_kafka,
                "label": "Aiven for Apache Kafka (Live)" if kafka_service.is_live_kafka else "Local Apache Kafka Broker",
                "topic": kafka_service.topic,
                "consumer_group": kafka_service.consumer_group,
                "security_protocol": Config.AIVEN_KAFKA_SECURITY_PROTOCOL if kafka_service.is_live_kafka else "In-Memory Event Bus"
            },
            "opensearch": {
                "configured": Config.is_opensearch_configured(),
                "is_live": opensearch_service.is_live_opensearch,
                "label": "Aiven for OpenSearch (Live)" if opensearch_service.is_live_opensearch else "Local OpenSearch Fuzzy Engine",
                "index": opensearch_service.index_name,
                "features": ["Typo-Tolerant Fuzzy Search (AUTO)", "Category & City Facets", "Price Range Filtering"]
            }
        },
        "all_aiven_live": db_service.is_live_postgres and kafka_service.is_live_kafka and opensearch_service.is_live_opensearch
    })

# -------------------------------------------------------------------------
# Shopping Mode APIs
# -------------------------------------------------------------------------
@main_bp.route("/api/shopping-mode", methods=["GET"])
def get_shopping_mode_api():
    """Returns the customer's active shopping mode from session."""
    mode = get_current_shopping_mode()
    return jsonify({
        "success": True,
        "mode": mode,
        "supported_modes": sorted(list(VALID_SHOPPING_MODES))
    })

@main_bp.route("/api/shopping-mode", methods=["POST"])
def set_shopping_mode_api():
    """
    Validates and updates customer shopping mode in session.
    Guarantees strict server-side validation against unauthorized or arbitrary mode identifiers.
    Accepts 'retail', 'online', 'RETAIL_NEAR_ME', 'ONLINE'.
    """
    data = request.get_json(silent=True) or {}
    mode = data.get("mode")
    if not mode or not isinstance(mode, str):
        return jsonify({
            "success": False,
            "error": "A valid 'mode' string is required."
        }), 400

    canonical = normalize_shopping_mode(mode)
    if not canonical:
        return jsonify({
            "success": False,
            "error": f"Invalid shopping mode '{mode}'. Must be one of: ONLINE, RETAIL_NEAR_ME (or 'retail', 'online')."
        }), 400

    set_current_shopping_mode(canonical)
    logger.info(f"Shopping mode successfully set to '{canonical}'")
    return jsonify({
        "success": True,
        "mode": canonical,
        "message": f"Shopping mode successfully switched to {canonical}."
    })

# -------------------------------------------------------------------------
# Phase 3: Location & Saved Address Management Endpoints
# -------------------------------------------------------------------------
def get_auth_customer_id() -> int:
    """
    Resolves the authenticated customer ID from session, request headers, or query/body params.
    Default fallback is customer 1 (Priya Sharma).
    """
    if session.get("customer_id"):
        try:
            return int(session["customer_id"])
        except (ValueError, TypeError):
            pass
    header_id = request.headers.get("X-Customer-Id")
    if header_id:
        try:
            return int(header_id)
        except (ValueError, TypeError):
            pass
    q_id = request.args.get("customer_id")
    if q_id:
        try:
            return int(q_id)
        except (ValueError, TypeError):
            pass
    data = request.get_json(silent=True) or {}
    if data.get("customer_id"):
        try:
            return int(data["customer_id"])
        except (ValueError, TypeError):
            pass
    return 1

@main_bp.route("/api/location/validate-coords", methods=["POST"])
def validate_coordinates_api():
    """
    Strict server-side coordinate validation.
    Latitude: -90.0 to 90.0, Longitude: -180.0 to 180.0.
    Rejects missing, non-numeric and out-of-bounds coordinates with HTTP 400.
    Finds nearest physical store hub and verifies 15 km delivery radius.
    """
    data = request.get_json(silent=True) or {}
    lat = data.get("latitude") if "latitude" in data else data.get("lat")
    lng = data.get("longitude") if "longitude" in data else data.get("lng")

    if lat is None or lng is None or str(lat).strip() == "" or str(lng).strip() == "":
        return jsonify({
            "success": False,
            "valid": False,
            "error": "Missing coordinates. 'latitude' and 'longitude' are required."
        }), 400

    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except (ValueError, TypeError):
        return jsonify({
            "success": False,
            "valid": False,
            "error": "Non-numeric coordinates. Latitude and longitude must be valid floating-point numbers."
        }), 400

    if not (-90.0 <= lat_f <= 90.0) or not (-180.0 <= lng_f <= 180.0):
        return jsonify({
            "success": False,
            "valid": False,
            "error": "Coordinates out of bounds (-90.0 <= latitude <= 90.0, -180.0 <= longitude <= 180.0)."
        }), 400

    closest_hub = None
    min_dist = float("inf")
    for city_item in CITIES_AND_AREAS_DATA:
        dist = calculate_haversine_distance(lat_f, lng_f, city_item["hub_lat"], city_item["hub_lng"])
        if dist < min_dist:
            min_dist = dist
            closest_hub = city_item

    return jsonify({
        "success": True,
        "valid": True,
        "latitude": lat_f,
        "longitude": lng_f,
        "nearest_city": closest_hub["city"],
        "nearest_hub": closest_hub["hub_name"],
        "hub_address": closest_hub["hub_address"],
        "distance_km": min_dist,
        "is_within_delivery_radius": min_dist <= 15.0,
        "message": f"Coordinates verified. Nearest physical store is {closest_hub['hub_name']} ({min_dist} km away)."
    })

@main_bp.route("/api/location/cities-areas", methods=["GET"])
def get_cities_areas_api():
    """
    Retrieves supported metro cities and their neighbourhoods/areas with demo coordinates.
    """
    return jsonify({
        "success": True,
        "demo_mode": True,
        "delivery_radius_km": 15,
        "cities": CITIES_AND_AREAS_DATA,
        "note": "Demo geographic reference data for BharatStore retail discovery."
    })

@main_bp.route("/api/location/set-current", methods=["POST"])
def set_current_location_api():
    """
    Updates the customer's active delivery location in the session.
    Calculates physical store hub distance and updates shopping context.
    """
    data = request.get_json(silent=True) or {}
    city = str(data.get("city") or "Mumbai").strip()
    area = str(data.get("area") or "").strip()
    pincode = str(data.get("pincode") or "").strip()
    address_line = str(data.get("address_line") or "").strip()
    lat = data.get("latitude")
    lng = data.get("longitude")
    source = data.get("source", "manual")

    lat_f = None
    lng_f = None
    if lat is not None and lng is not None and str(lat).strip() != "" and str(lng).strip() != "":
        try:
            lat_f = float(lat)
            lng_f = float(lng)
            if not (-90.0 <= lat_f <= 90.0) or not (-180.0 <= lng_f <= 180.0):
                return jsonify({"success": False, "error": "Coordinates out of bounds (-90 to 90 lat, -180 to 180 lng)."}), 400
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "Non-numeric coordinates."}), 400

    matching_city = next((c for c in CITIES_AND_AREAS_DATA if c["city"].lower() == city.lower()), None)
    dist_km = 1.8
    hub_name = "BharatStore Mumbai MegaHub"
    if matching_city:
        hub_name = matching_city["hub_name"]
        if lat_f is not None and lng_f is not None:
            dist_km = calculate_haversine_distance(lat_f, lng_f, matching_city["hub_lat"], matching_city["hub_lng"])
        elif area:
            area_match = next((a for a in matching_city["areas"] if a["name"].lower() == area.lower()), None)
            if area_match:
                dist_km = area_match.get("distance_km", 2.0)

    formatted = f"{area}, {city}" if area else city

    location_data = {
        "city": city,
        "area": area,
        "pincode": pincode,
        "address_line": address_line,
        "latitude": lat_f,
        "longitude": lng_f,
        "source": source,
        "formatted": formatted,
        "nearest_hub": hub_name,
        "distance_km": dist_km,
        "is_within_delivery_radius": dist_km <= 15.0,
        "is_fallback": False,
        "updated_at": time.time()
    }

    session["customer_location"] = location_data
    session["shopping_city"] = city
    session.permanent = True

    return jsonify({
        "success": True,
        "location": location_data,
        "message": f"Delivery location set to {formatted}."
    })

@main_bp.route("/api/location/current", methods=["GET"])
def get_current_location_api():
    """
    Returns the active delivery location for the session.
    """
    loc = session.get("customer_location")
    if loc:
        return jsonify({"success": True, "location": loc, "is_fallback": False})
    fallback = get_current_delivery_location()
    return jsonify({"success": True, "location": fallback, "is_fallback": True})

@main_bp.route("/api/customer/addresses", methods=["GET"])
def api_get_customer_addresses():
    """
    Retrieves all saved addresses for the authenticated customer.
    """
    customer_id = get_auth_customer_id()
    addresses = db_service.get_customer_addresses(customer_id)
    return jsonify({
        "success": True,
        "customer_id": customer_id,
        "total": len(addresses),
        "addresses": addresses
    })

@main_bp.route("/api/customer/addresses", methods=["POST"])
def api_add_customer_address():
    """
    Creates a new delivery address for the customer with server-side validation.
    """
    customer_id = get_auth_customer_id()
    data = request.get_json(silent=True) or {}
    try:
        new_addr = db_service.add_customer_address(customer_id, data)
        return jsonify({
            "success": True,
            "message": "Delivery address added successfully.",
            "address": new_addr
        }), 201
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error adding customer address: {e}")
        return jsonify({"success": False, "error": "Internal server error saving address."}), 500

@main_bp.route("/api/customer/addresses/<int:address_id>", methods=["PUT"])
def api_update_customer_address(address_id: int):
    """
    Updates an address belonging to the authenticated customer.
    """
    customer_id = get_auth_customer_id()
    data = request.get_json(silent=True) or {}
    try:
        updated = db_service.update_customer_address(address_id, customer_id, data)
        if not updated:
            return jsonify({
                "success": False,
                "error": f"Address #{address_id} not found or does not belong to the current customer."
            }), 404
        return jsonify({
            "success": True,
            "message": "Delivery address updated successfully.",
            "address": updated
        })
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error updating customer address: {e}")
        return jsonify({"success": False, "error": "Internal server error updating address."}), 500

@main_bp.route("/api/customer/addresses/<int:address_id>", methods=["DELETE"])
def api_delete_customer_address(address_id: int):
    """
    Deletes an address belonging to the authenticated customer.
    """
    customer_id = get_auth_customer_id()
    try:
        deleted = db_service.delete_customer_address(address_id, customer_id)
        if not deleted:
            return jsonify({
                "success": False,
                "error": f"Address #{address_id} not found or unauthorized."
            }), 404
        return jsonify({
            "success": True,
            "message": f"Address #{address_id} successfully deleted."
        })
    except Exception as e:
        logger.error(f"Error deleting customer address: {e}")
        return jsonify({"success": False, "error": "Internal server error deleting address."}), 500

@main_bp.route("/api/customer/addresses/<int:address_id>/default", methods=["POST", "PUT"])
def api_set_default_customer_address(address_id: int):
    """
    Atomically sets the specified address as the customer's sole default address.
    """
    customer_id = get_auth_customer_id()
    try:
        success = db_service.set_default_customer_address(address_id, customer_id)
        if not success:
            return jsonify({
                "success": False,
                "error": f"Address #{address_id} not found or unauthorized."
            }), 404
        return jsonify({
            "success": True,
            "message": f"Address #{address_id} is now set as your primary default address."
        })
    except Exception as e:
        logger.error(f"Error setting default address: {e}")
        return jsonify({"success": False, "error": "Internal server error setting default address."}), 500

# -------------------------------------------------------------------------
# Catalog & OpenSearch APIs
# -------------------------------------------------------------------------
@main_bp.route("/api/fulfillment-hubs", methods=["GET"])
def get_hubs():
    return jsonify(FULFILLMENT_HUBS)

@main_bp.route("/api/products", methods=["GET"])
def list_products():
    category = request.args.get("category")
    city = request.args.get("city")
    mode = resolve_shopping_mode()

    if mode == "RETAIL_NEAR_ME":
        if category and category in NON_GROCERY_CATEGORIES:
            return jsonify({"total": 0, "products": []})
        products = db_service.get_all_products(category=category, city=city)
        filtered = [p for p in products if is_retail_grocery_product(p)]
        if category and category in ALLOWED_RETAIL_CATEGORIES and category != "Daily Essentials & Groceries":
            filtered = [
                p for p in filtered
                if (p.get("sub_category") == category) or (p.get("category") == category)
            ]
        return jsonify({"total": len(filtered), "products": filtered})

    products = db_service.get_all_products(category=category, city=city)
    return jsonify({"total": len(products), "products": products})

@main_bp.route("/api/products/<int:product_id>", methods=["GET"])
def get_product(product_id: int):
    prod = db_service.get_product_by_id(product_id)
    if not prod:
        return jsonify({"error": "Product not found"}), 404
    mode = resolve_shopping_mode()
    if mode == "RETAIL_NEAR_ME" and not is_retail_grocery_product(prod):
        return jsonify({"error": "Product not available in Retail Near Me mode"}), 404

    related = db_service.get_related_products(product_id, prod.get("category"), limit=4)
    if mode == "RETAIL_NEAR_ME":
        related = [p for p in related if is_retail_grocery_product(p)]
    prod["related_products"] = related
    return jsonify(prod)

@main_bp.route("/api/cart/validate", methods=["POST"])
def api_validate_cart_item():
    """
    Validates cart item against real backend database stock.
    Prevents adding out-of-stock items or exceeding available inventory.
    """
    data = request.get_json() or {}
    product_id = data.get("product_id")
    quantity = data.get("quantity", 1)

    if not product_id:
        return jsonify({"valid": False, "error": "Product ID is required"}), 400
    try:
        quantity = int(quantity)
    except (ValueError, TypeError):
        return jsonify({"valid": False, "error": "Quantity must be an integer"}), 400

    if quantity <= 0:
        return jsonify({"valid": False, "error": "Quantity must be at least 1"}), 400

    product = db_service.get_product_by_id(product_id)
    if not product:
        return jsonify({"valid": False, "error": f"Product #{product_id} does not exist"}), 404

    store_id = data.get("store_id")
    if store_id:
        try:
            sid = int(store_id)
            inv = db_service.get_store_product(sid, product_id)
            if inv:
                avail_store = int(inv.get("stock_quantity", 0))
                if not inv.get("is_available") or avail_store <= 0:
                    return jsonify({
                        "valid": False,
                        "error": f"'{inv['title']}' is currently Out of Stock at this store",
                        "available_stock": 0,
                        "product_id": product_id,
                        "store_id": sid
                    }), 400
                if quantity > avail_store:
                    return jsonify({
                        "valid": False,
                        "error": f"Requested quantity ({quantity}) exceeds store stock ({avail_store})",
                        "available_stock": avail_store,
                        "product_id": product_id,
                        "store_id": sid
                    }), 400
                return jsonify({
                    "valid": True,
                    "product_id": product_id,
                    "store_id": sid,
                    "title": inv["title"],
                    "price": float(inv["selling_price"]),
                    "requested_quantity": quantity,
                    "available_stock": avail_store,
                    "subtotal": float(inv["selling_price"]) * quantity
                })
        except Exception:
            pass

    available_stock = int(product.get("stock", 0))
    if available_stock <= 0:
        return jsonify({
            "valid": False,
            "error": f"'{product['title']}' is currently Out of Stock",
            "available_stock": 0,
            "product_id": product_id
        }), 400

    if quantity > available_stock:
        return jsonify({
            "valid": False,
            "error": f"Requested quantity ({quantity}) exceeds available stock ({available_stock})",
            "available_stock": available_stock,
            "product_id": product_id
        }), 400

    return jsonify({
        "valid": True,
        "product_id": product_id,
        "title": product["title"],
        "price": float(product["price"]),
        "requested_quantity": quantity,
        "available_stock": available_stock,
        "subtotal": float(product["price"]) * quantity
    })


@main_bp.route("/api/search", methods=["GET"])
def search_catalog():
    """
    Search endpoint powered by Mode-Aware OpenSearch:
    - In ONLINE Mode: searches entire marketplace with brand, category, city, price range, sorting, pagination.
    - In RETAIL_NEAR_ME Mode: strictly returns grocery items, incorporates store-specific selling prices and stock levels.
    """
    query = request.args.get("q", "").strip()
    category = request.args.get("category")
    brand = request.args.get("brand")
    city = request.args.get("city")
    min_price = request.args.get("min_price", type=float)
    max_price = request.args.get("max_price", type=float)
    store_id = request.args.get("store_id", type=int)
    sort_by = request.args.get("sort") or request.args.get("sort_by")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    in_stock_param = request.args.get("in_stock") or request.args.get("in_stock_only")
    in_stock_only = in_stock_param.lower() in ("true", "1", "yes") if in_stock_param else False

    mode = resolve_shopping_mode()

    search_result = opensearch_service.search(
        query_text=query,
        category=category,
        brand=brand,
        city=city,
        min_price=min_price,
        max_price=max_price,
        shopping_mode=mode,
        store_id=store_id,
        sort_by=sort_by,
        page=page,
        per_page=per_page,
        in_stock_only=in_stock_only
    )
    return jsonify(search_result)


@main_bp.route("/api/search/suggestions", methods=["GET"])
def search_suggestions():
    """
    Mode-Aware Search Autocomplete Suggestions:
    - In RETAIL_NEAR_ME Mode: strictly grocery products only.
    - In ONLINE Mode: catalog-wide suggestions.
    """
    query = request.args.get("q", "").strip()
    mode = resolve_shopping_mode()
    store_id = request.args.get("store_id", type=int)
    limit = request.args.get("limit", 5, type=int)

    suggestions = opensearch_service.get_suggestions(
        prefix_or_typo=query,
        limit=limit,
        shopping_mode=mode,
        store_id=store_id
    )

    return jsonify({
        "query": query,
        "shopping_mode": mode,
        "store_id": store_id,
        "suggestions": suggestions
    })

# -------------------------------------------------------------------------
# Transactional Checkout & Kafka Producer API
# -------------------------------------------------------------------------
@main_bp.route("/api/checkout", methods=["POST"])
def checkout():
    """
    Core Order Placement Flow:
    1. PostgreSQL executes atomic transaction with row-level stock locks.
    2. Produces event to Kafka topic 'order-events'.
    3. Returns order confirmation details to shopper.
    """
    data = request.get_json() or {}
    items = data.get("items", [])
    shipping_city = data.get("shipping_city", "Mumbai")
    shipping_address = data.get("shipping_address", "Flat 101, Express Towers, Nariman Point, Mumbai 400021")
    payment_info = data.get("payment", {
        "method": "UPI",
        "payment_id": f"pay_live_{int(time.time()*1000)}",
        "status": "PAID"
    })
    customer_info = data.get("customer", {
        "name": "Priya Sharma",
        "email": "priya.sharma@example.in",
        "phone": "+91 98201 12345"
    })

    if not items:
        return jsonify({"error": "Cart cannot be empty"}), 400

    try:
        # Step 1: Database transaction with locking
        tx_start = time.time()
        order_result = db_service.process_checkout_transaction(
            customer_info=customer_info,
            items=items,
            shipping_city=shipping_city,
            shipping_address=shipping_address,
            payment_info=payment_info
        )
        tx_duration_ms = round((time.time() - tx_start) * 1000, 2)

        # Step 2: Produce event to Apache Kafka topic
        kafka_audit = kafka_service.produce_order_event(order_result)

        placed = session.setdefault("placed_order_ids", [])
        if order_result.get("order_id"):
            placed.append(order_result["order_id"])
        if order_result.get("id"):
            placed.append(order_result["id"])
        session.modified = True

        return jsonify({
            "success": True,
            "order": order_result,
            "kafka_event": kafka_audit,
            "tx_duration_ms": tx_duration_ms,
            "message": f"Order #{order_result['order_number']} placed successfully and broadcast to Apache Kafka!"
        })

    except ValueError as ve:
        return jsonify({
            "success": False,
            "error": str(ve),
            "type": "STOCK_VALIDATION_ROLLBACK"
        }), 400
    except Exception as e:
        logger.error(f"Checkout error: {e}")
        return jsonify({
            "success": False,
            "error": f"Transaction failed: {str(e)}",
            "type": "TRANSACTION_ROLLBACK"
        }), 500

# -------------------------------------------------------------------------
# Real-Time Kafka Event Inspector APIs
# -------------------------------------------------------------------------
@main_bp.route("/api/events/recent", methods=["GET"])
def get_recent_events():
    limit = request.args.get("limit", default=25, type=int)
    return jsonify(kafka_service.event_log.get_recent(limit=limit))

@main_bp.route("/api/events/stream")
def sse_event_stream():
    """Server-Sent Events endpoint streaming real-time Kafka produce & consume events"""
    def event_stream():
        q = kafka_service.event_log.subscribe()
        try:
            # First send existing recent events
            recent = kafka_service.event_log.get_recent(10)
            for evt in recent:
                yield f"data: {json.dumps(evt)}\n\n"

            while True:
                evt = q.get()
                yield f"data: {json.dumps(evt)}\n\n"
        except GeneratorExit:
            kafka_service.event_log.unsubscribe(q)

    return Response(event_stream(), mimetype="text/event-stream")

# -------------------------------------------------------------------------
# Concurrency Stress Test Endpoint (Hackathon Demo Proof)
# -------------------------------------------------------------------------
@main_bp.route("/api/test/concurrency", methods=["POST"])
@require_admin_auth
def test_concurrency():
    """
    Simulates a race condition: 10 concurrent customer threads simultaneously
    attempting to buy the last 1 remaining unit of a product.
    Proves that PostgreSQL row-locking prevents stock from dropping below zero!
    Protected by admin authorization.
    """
    target_product_id = 4 # MacBook Air or custom
    requested_qty = 1

    # Temporarily set stock to exactly 1
    db_service.update_stock(target_product_id, 1)
    opensearch_service.update_product_stock(target_product_id, 1)

    threads_count = 10
    results = []

    def attempt_purchase(thread_idx: int):
        customer = {
            "name": f"Concurrent Shopper #{thread_idx}",
            "email": f"shopper{thread_idx}@racecondition.test",
            "phone": f"+91 90000 000{thread_idx:02d}"
        }
        item = [{"product_id": target_product_id, "quantity": requested_qty}]
        try:
            res = db_service.process_checkout_transaction(
                customer_info=customer,
                items=item,
                shipping_city="Bengaluru",
                shipping_address="Race Condition Lab, Indiranagar"
            )
            # Produce Kafka event for the winner
            kafka_service.produce_order_event(res)
            return {"thread": thread_idx, "status": "SUCCESS (COMMITTED)", "order_number": res["order_number"]}
        except ValueError as ve:
            return {"thread": thread_idx, "status": "REJECTED (ROLLED BACK)", "reason": str(ve)}
        except Exception as e:
            return {"thread": thread_idx, "status": "ERROR", "reason": str(e)}

    # Fire all 10 threads concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=threads_count) as executor:
        futures = [executor.submit(attempt_purchase, i + 1) for i in range(threads_count)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    # Verify final stock
    final_prod = db_service.get_product_by_id(target_product_id)
    final_stock = final_prod["stock"] if final_prod else -1

    success_count = sum(1 for r in results if "SUCCESS" in r["status"])
    rejected_count = sum(1 for r in results if "REJECTED" in r["status"])

    # Reset stock back to standard seed value for that product
    db_service.update_stock(target_product_id, 6)
    opensearch_service.update_product_stock(target_product_id, 6)

    return jsonify({
        "test_name": "Concurrent Last-Item Race Condition Test",
        "product_tested": "Apple MacBook Air M2",
        "initial_stock": 1,
        "concurrent_buyers": threads_count,
        "successful_purchases": success_count,
        "rejected_transactions": rejected_count,
        "final_stock_in_db": final_stock,
        "stock_dropped_below_zero": final_stock < 0,
        "verdict": "PASSED: ACID row locking prevented overselling. Stock invariant maintained!" if success_count == 1 and final_stock == 0 else "FAILED",
        "thread_results": sorted(results, key=lambda x: x["thread"])
    })

@main_bp.route("/api/admin/reset-inventory", methods=["POST"])
@require_admin_auth
def reset_inventory():
    """Protected endpoint to reset catalog stock to initial seed values"""
    db_service.reset_inventory()
    all_p = db_service.get_all_products()
    opensearch_service.index_all_products(all_p)
    return jsonify({"success": True, "message": "Catalog inventory restored to initial values."})

# -------------------------------------------------------------------------
# Order Lifecycle Management APIs (States: PENDING_PAYMENT, PAID, CONFIRMED, CANCELLED)
# -------------------------------------------------------------------------
@main_bp.route("/api/orders", methods=["GET"])
def list_orders():
    """Retrieve orders with their operational, store metadata, and payment statuses"""
    limit = request.args.get("limit", default=50, type=int)
    status_filter = request.args.get("status")
    cust_id, sess_id = _get_cart_auth()

    # If customer is explicitly authenticated, scope to customer
    if cust_id:
        orders = db_service.get_orders_for_customer(customer_id=cust_id, status_filter=status_filter, limit=limit)
    else:
        placed = session.get("placed_order_ids", [])
        if placed and not request.headers.get("X-Admin-Token"):
            all_cust_orders = db_service.get_orders_for_customer(status_filter=status_filter, limit=limit)
            orders = [o for o in all_cust_orders if o["id"] in placed or (o.get("parent_order_id") and o.get("parent_order_id") in placed)]
            if not orders:
                orders = db_service.get_orders_for_customer(status_filter=status_filter, limit=limit)
        else:
            orders = db_service.get_orders_for_customer(status_filter=status_filter, limit=limit)

    return jsonify({"total": len(orders), "orders": orders})

@main_bp.route("/api/orders/<int:order_id>", methods=["GET"])
def get_order_details(order_id: int):
    """Retrieve complete details for a specific order by ID with IDOR protection"""
    order = db_service.get_order_by_id(order_id)
    if not order:
        return jsonify({"success": False, "error": f"Order #{order_id} not found"}), 404

    if not _check_order_access(order):
        return jsonify({
            "success": False,
            "error": "Forbidden: You are not authorized to view this order.",
            "code": "IDOR_FORBIDDEN"
        }), 403

    return jsonify({"success": True, "order": order})

@main_bp.route("/api/payment/config", methods=["GET"])
def get_payment_config():
    """Provides public gateway credentials for frontend checkout initialization"""
    return jsonify({
        "gateway": "RAZORPAY",
        "key_id": Config.RAZORPAY_KEY_ID or "rzp_test_simulated_bharatstore",
        "is_live": bool(Config.RAZORPAY_KEY_ID and Config.RAZORPAY_KEY_SECRET),
        "currency": "INR",
        "name": "BharatStore"
    })

@main_bp.route("/api/orders/<int:order_id>/simulate-razorpay-signature", methods=["POST"])
def simulate_razorpay_signature(order_id: int):
    """
    Developer / Demo mode helper to generate authentic Razorpay HMAC-SHA256 signatures
    without leaking secrets to client JavaScript. Active for test/sandbox simulations.
    """
    order = db_service.get_order_by_id(order_id)
    if not order:
        return jsonify({"success": False, "error": f"Order #{order_id} not found."}), 404

    data = request.get_json() or {}
    payment_id = data.get("payment_id") or f"pay_rzp_{uuid.uuid4().hex[:12]}"
    order_token = data.get("razorpay_order_id") or order["order_number"]

    signature = payment_service.generate_test_signature(
        order_id=order_token,
        payment_id=payment_id
    )

    return jsonify({
        "success": True,
        "razorpay_payment_id": payment_id,
        "razorpay_order_id": order_token,
        "razorpay_signature": signature
    })

@main_bp.route("/api/orders/<int:order_id>/payment", methods=["POST"])
def process_order_payment(order_id: int):
    """
    Secure Payment Verification Endpoint (Razorpay Standard Checkout Callback):
    Rejects raw unauthenticated "status": "PAID" payloads.
    Requires cryptographic proof of payment via HMAC-SHA256 signature verification.
    """
    data = request.get_json() or {}
    razorpay_payment_id = (data.get("razorpay_payment_id") or data.get("payment_id", "")).strip()
    razorpay_order_id = (data.get("razorpay_order_id") or data.get("gateway_order_id", "")).strip()
    razorpay_signature = (data.get("razorpay_signature") or data.get("signature", "")).strip()

    # Reject missing cryptographic credentials
    if not razorpay_payment_id or not razorpay_signature:
        logger.warning(f"Rejected unverified payment attempt on Order #{order_id}: Missing payment ID or cryptographic signature.")
        return jsonify({
            "success": False,
            "error": "Payment verification failed: Cryptographic gateway signature and payment ID are required.",
            "code": "MISSING_PAYMENT_SIGNATURE"
        }), 400

    order = db_service.get_order_by_id(order_id)
    if not order:
        return jsonify({"success": False, "error": f"Order #{order_id} not found."}), 404

    if order["status"] == OrderStatus.CANCELLED:
        return jsonify({"success": False, "error": f"Cannot accept payment for CANCELLED Order #{order_id}."}), 400

    # Idempotent return if order is already marked PAID and CONFIRMED
    if order["status"] == OrderStatus.CONFIRMED and order.get("payment_status") == PaymentStatus.PAID:
        return jsonify({
            "success": True,
            "message": f"Order #{order_id} is already confirmed and paid.",
            "order": order
        })

    # Verify that the order ID in the payload matches this specific order (prevents cross-order replays)
    expected_order_number = order["order_number"]
    expected_gateway_id = order.get("gateway_order_id") or ""
    if razorpay_order_id and razorpay_order_id not in (expected_order_number, expected_gateway_id):
        logger.warning(
            f"Payment verification failed for Order #{order_id}: "
            f"razorpay_order_id '{razorpay_order_id}' does not match order '{expected_order_number}'."
        )
        return jsonify({
            "success": False,
            "error": "Payment order ID mismatch. Payload does not belong to this order.",
            "code": "INVALID_SIGNATURE"
        }), 400

    # Verify signature
    target_order_token = razorpay_order_id or expected_order_number
    is_valid = payment_service.verify_payment_signature(
        razorpay_order_id=target_order_token,
        razorpay_payment_id=razorpay_payment_id,
        razorpay_signature=razorpay_signature
    )

    if not is_valid:
        logger.error(f"Cryptographic signature mismatch for Order #{order_id}. Possible fraud or payload tampering.")
        return jsonify({
            "success": False,
            "error": "Invalid payment signature. Payment could not be authenticated.",
            "code": "INVALID_SIGNATURE"
        }), 400

    try:
        updated_order = db_service.update_order_payment_status(
            order_id=order_id,
            payment_status=PaymentStatus.PAID,
            payment_id=razorpay_payment_id
        )
        # Broadcast status transition event to Apache Kafka
        kafka_audit = kafka_service.produce_order_event(updated_order, event_type="ORDER_PAID")
        return jsonify({
            "success": True,
            "message": f"Payment verified via Razorpay HMAC-SHA256! Order #{order_id} is now CONFIRMED.",
            "order": updated_order,
            "kafka_event": kafka_audit
        })
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error updating order payment: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@main_bp.route("/api/webhooks/razorpay", methods=["POST"])
def razorpay_webhook():
    """
    Razorpay Server-to-Server Webhook Endpoint:
    1. Verifies X-Razorpay-Signature header with PAYMENT_WEBHOOK_SECRET
    2. Protects against duplicate webhook delivery retries (idempotency check)
    3. Handles payment.captured, payment.failed, and refund.processed events safely
    """
    raw_body = request.get_data()
    signature_header = request.headers.get("X-Razorpay-Signature", "").strip()

    if not signature_header:
        logger.warning("Razorpay webhook rejected: Missing X-Razorpay-Signature header.")
        return jsonify({"success": False, "error": "Missing X-Razorpay-Signature header."}), 400

    if not payment_service.verify_webhook_signature(raw_body, signature_header):
        logger.error("Razorpay webhook verification failed: Cryptographic signature mismatch.")
        return jsonify({"success": False, "error": "Invalid webhook signature."}), 400

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return jsonify({"success": False, "error": "Malformed JSON payload."}), 400

    event_id = payload.get("id") or payload.get("event_id") or f"evt_{int(time.time()*1000)}"
    event_type = payload.get("event", "")

    # Duplicate webhook protection
    if payment_service.is_duplicate_webhook(event_id):
        logger.info(f"Duplicate Razorpay webhook ignored ({event_id}), acknowledging 200 OK.")
        return jsonify({"success": True, "status": "duplicate_ignored"}), 200

    payment_service.mark_webhook_processed(event_id)
    logger.info(f"Processing verified Razorpay webhook: {event_type} ({event_id})")

    if event_type == "payment.captured":
        payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        notes = payment_entity.get("notes", {})
        order_id_str = notes.get("order_id")
        payment_id = payment_entity.get("id")

        if order_id_str:
            try:
                order_id = int(order_id_str)
                updated_order = db_service.update_order_payment_status(
                    order_id=order_id,
                    payment_status=PaymentStatus.PAID,
                    payment_id=payment_id
                )
                kafka_service.produce_order_event(updated_order, event_type="ORDER_PAID")
            except Exception as e:
                logger.error(f"Error applying webhook payment to order {order_id_str}: {e}")

    elif event_type == "payment.failed":
        payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        notes = payment_entity.get("notes", {})
        order_id_str = notes.get("order_id")
        if order_id_str:
            try:
                order_id = int(order_id_str)
                db_service.cancel_order(order_id, reason="Payment failed at Razorpay gateway")
            except Exception as e:
                logger.error(f"Error handling payment failure for order {order_id_str}: {e}")

    return jsonify({"success": True, "event": event_type, "status": "processed"}), 200

@main_bp.route("/api/orders/<int:order_id>/cancel", methods=["POST"])
def cancel_order(order_id: int):
    """
    Cancels an order and executes a compensating transaction:
    Restores reserved inventory in DB & updates OpenSearch catalog indices.
    """
    data = request.get_json() or {}
    reason = data.get("reason", "Customer requested cancellation")

    try:
        cancelled_order = db_service.cancel_order(order_id=order_id, reason=reason)

        # Sync restored stock back to OpenSearch
        for restored in cancelled_order.get("restored_stock", []):
            opensearch_service.update_product_stock(restored["product_id"], restored["new_stock"])

        # Broadcast cancellation event to Apache Kafka
        kafka_audit = kafka_service.produce_order_event(cancelled_order)

        return jsonify({
            "success": True,
            "message": f"Order #{order_id} cancelled successfully and inventory replenished.",
            "order": cancelled_order,
            "kafka_event": kafka_audit
        })
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error cancelling order: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# -------------------------------------------------------------------------
# Admin Management & Review APIs
# -------------------------------------------------------------------------
@main_bp.route("/api/admin/stats", methods=["GET"])
@require_admin_auth
def get_admin_stats():
    """Retrieve storewide metrics for admin dashboard"""
    stats = db_service.get_admin_metrics()
    return jsonify({"success": True, "stats": stats})

@main_bp.route("/api/admin/products", methods=["POST"])
@require_admin_auth
def api_create_product():
    """Creates a new catalog product"""
    data = request.get_json() or {}
    try:
        new_prod = db_service.create_product(data)
        opensearch_service.update_product_stock(new_prod["id"], new_prod["stock"])
        return jsonify({"success": True, "product": new_prod}), 201
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@main_bp.route("/api/admin/products/<int:product_id>", methods=["PUT"])
@require_admin_auth
def api_update_product(product_id: int):
    """Updates product details or pricing"""
    data = request.get_json() or {}
    try:
        updated = db_service.update_product(product_id, data)
        if not updated:
            return jsonify({"success": False, "error": f"Product #{product_id} not found."}), 404
        opensearch_service.update_product_stock(product_id, updated["stock"])
        return jsonify({"success": True, "product": updated})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@main_bp.route("/api/admin/products/<int:product_id>", methods=["DELETE"])
@require_admin_auth
def api_delete_product(product_id: int):
    """Deletes a product from catalog"""
    try:
        db_service.delete_product(product_id)
        return jsonify({"success": True, "message": f"Product #{product_id} deleted."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@main_bp.route("/api/admin/inventory/update", methods=["POST"])
@require_admin_auth
def api_update_inventory():
    """Quick inventory stock count update"""
    data = request.get_json() or {}
    product_id = int(data.get("product_id", 0))
    new_stock = int(data.get("stock", 0))
    db_service.update_stock(product_id, new_stock)
    opensearch_service.update_product_stock(product_id, new_stock)
    return jsonify({"success": True, "product_id": product_id, "stock": new_stock})

@main_bp.route("/api/admin/orders/<int:order_id>/status", methods=["POST", "PUT"])
@main_bp.route("/api/orders/<int:order_id>/status", methods=["POST", "PUT"])
@require_admin_auth
def api_update_order_status(order_id: int):
    """Updates operational order status (CONFIRMED, PROCESSING, DISPATCHED, DELIVERED, CANCELLED)"""
    data = request.get_json() or {}
    status = data.get("status", "")
    notes = data.get("notes") or data.get("reason")
    if not status:
        return jsonify({"success": False, "error": "New status is required."}), 400

    try:
        updated_order = db_service.update_order_status(order_id, status, notes=notes, changed_by="ADMIN")
        if not updated_order:
            return jsonify({"success": False, "error": f"Order #{order_id} not found."}), 404
        kafka_service.produce_order_event(updated_order, event_type=f"ORDER_{status.upper()}")
        return jsonify({"success": True, "order": updated_order})
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error updating order status: {e}")
        return jsonify({"success": False, "error": "Internal server error"}), 500

@main_bp.route("/api/products/<int:product_id>/reviews", methods=["POST"])
def api_add_review(product_id: int):
    """Customer submits a verified product review with duplicate prevention"""
    data = request.get_json() or {}
    customer_id = data.get("customer_id")
    try:
        rating = int(data.get("rating", 5))
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid rating format"}), 400

    title = (data.get("title") or "").strip()
    comment = (data.get("comment") or "").strip()

    if not title:
        return jsonify({"success": False, "error": "Review headline/title is required"}), 400
    if not comment:
        return jsonify({"success": False, "error": "Review feedback comment is required"}), 400
    if rating < 1 or rating > 5:
        return jsonify({"success": False, "error": "Rating must be between 1 and 5 stars"}), 400

    prod = db_service.get_product_by_id(product_id)
    if not prod:
        return jsonify({"success": False, "error": "Product not found"}), 404

    try:
        review = db_service.add_product_review(product_id, customer_id, rating, title, comment, check_duplicate=True)
        return jsonify({"success": True, "review": review}), 201
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error submitting review for product #{product_id}: {e}")
        return jsonify({"success": False, "error": "Failed to submit review"}), 500

@main_bp.route("/api/products/<int:product_id>/reviews", methods=["GET"])
def api_get_reviews(product_id: int):
    """Retrieves customer reviews and rating statistics for a product"""
    reviews = db_service.get_product_reviews(product_id)
    stats = db_service.get_review_statistics(product_id)
    return jsonify({"success": True, "reviews": reviews, "stats": stats})

# =============================================================================
# Phase 4: Physical Stores & Multi-Store Inventory Endpoints
# =============================================================================

@main_bp.route("/api/stores", methods=["GET"])
def api_get_stores():
    """
    Public customer API: Returns active physical retail stores with optional city/area filtering.
    """
    city = request.args.get("city")
    area = request.args.get("area")
    active_param = request.args.get("active_only", "true").lower()
    active_only = active_param in ("true", "1", "yes")

    stores = db_service.get_all_stores(active_only=active_only, city=city, area=area)
    return jsonify({
        "success": True,
        "stores": stores,
        "count": len(stores)
    })

@main_bp.route("/api/stores/<int:store_id>", methods=["GET"])
def api_get_store(store_id: int):
    """
    Public customer API: Returns details of a specific physical store.
    """
    store = db_service.get_store_by_id(store_id)
    if not store:
        return jsonify({
            "success": False,
            "error": f"Store #{store_id} not found."
        }), 404

    return jsonify({
        "success": True,
        "store": store
    })

@main_bp.route("/api/stores/<int:store_id>/inventory", methods=["GET"])
def api_get_store_inventory(store_id: int):
    """
    Public customer API: Returns full inventory list for a specific store.
    """
    store = db_service.get_store_by_id(store_id)
    if not store:
        return jsonify({
            "success": False,
            "error": f"Store #{store_id} not found."
        }), 404

    items = db_service.get_store_inventory(store_id)
    return jsonify({
        "success": True,
        "store_id": store_id,
        "store_name": store["store_name"],
        "inventory": items,
        "count": len(items)
    })

@main_bp.route("/api/stores/<int:store_id>/products", methods=["GET"])
def api_get_store_products(store_id: int):
    """
    Public customer API: Returns only currently available products at the store (stock > 0).
    """
    store = db_service.get_store_by_id(store_id)
    if not store:
        return jsonify({
            "success": False,
            "error": f"Store #{store_id} not found."
        }), 404

    products = db_service.get_available_store_products(store_id)
    return jsonify({
        "success": True,
        "store_id": store_id,
        "store_name": store["store_name"],
        "products": products,
        "count": len(products)
    })

@main_bp.route("/api/stores/<int:store_id>/products/<int:product_id>", methods=["GET"])
def api_get_store_product_detail(store_id: int, product_id: int):
    """
    Public customer API: Returns product availability, price and stock at a specific store.
    """
    store = db_service.get_store_by_id(store_id)
    if not store:
        return jsonify({
            "success": False,
            "error": f"Store #{store_id} not found."
        }), 404

    product = db_service.get_store_product(store_id, product_id)
    if not product:
        return jsonify({
            "success": False,
            "error": f"Product #{product_id} is not stocked at Store #{store_id}."
        }), 404

    return jsonify({
        "success": True,
        "store_id": store_id,
        "product": product
    })

@main_bp.route("/api/stores/<int:store_id>/inventory/low-stock", methods=["GET"])
@require_admin_auth
def api_get_store_low_stock(store_id: int):
    """
    Admin API: Returns products running low on stock at a specific store.
    """
    store = db_service.get_store_by_id(store_id)
    if not store:
        return jsonify({
            "success": False,
            "error": f"Store #{store_id} not found."
        }), 404

    items = db_service.get_low_stock_products(store_id)
    return jsonify({
        "success": True,
        "store_id": store_id,
        "low_stock_products": items,
        "count": len(items)
    })

@main_bp.route("/api/stores/<int:store_id>/inventory/out-of-stock", methods=["GET"])
@require_admin_auth
def api_get_store_out_of_stock(store_id: int):
    """
    Admin API: Returns products that are out of stock (stock <= 0 or is_available = False) at a store.
    """
    store = db_service.get_store_by_id(store_id)
    if not store:
        return jsonify({
            "success": False,
            "error": f"Store #{store_id} not found."
        }), 404

    items = db_service.get_out_of_stock_products(store_id)
    return jsonify({
        "success": True,
        "store_id": store_id,
        "out_of_stock_products": items,
        "count": len(items)
    })

@main_bp.route("/api/stores/<int:store_id>/inventory/movements", methods=["GET"])
@require_admin_auth
def api_get_store_movements(store_id: int):
    """
    Admin API: Returns immutable inventory stock movements for a physical retail store.
    """
    store = db_service.get_store_by_id(store_id)
    if not store:
        return jsonify({
            "success": False,
            "error": f"Store #{store_id} not found."
        }), 404

    limit = request.args.get("limit", 50, type=int)
    movements = db_service.get_store_stock_movements(store_id=store_id, limit=limit)
    return jsonify({
        "success": True,
        "store_id": store_id,
        "movements": movements,
        "count": len(movements)
    })

@main_bp.route("/api/stores/<int:store_id>/inventory/<int:product_id>/movements", methods=["GET"])
@require_admin_auth
def api_get_store_product_movements(store_id: int, product_id: int):
    """
    Admin API: Returns immutable inventory stock movements for a specific product at a store.
    """
    store = db_service.get_store_by_id(store_id)
    if not store:
        return jsonify({
            "success": False,
            "error": f"Store #{store_id} not found."
        }), 404

    limit = request.args.get("limit", 50, type=int)
    movements = db_service.get_store_stock_movements(store_id=store_id, product_id=product_id, limit=limit)
    return jsonify({
        "success": True,
        "store_id": store_id,
        "product_id": product_id,
        "movements": movements,
        "count": len(movements)
    })

@main_bp.route("/api/stores/<int:store_id>/inventory", methods=["POST"])
@require_admin_auth
def api_add_store_inventory(store_id: int):
    """
    Admin API: Adds a product to store inventory with custom selling price and stock.
    """
    store = db_service.get_store_by_id(store_id)
    if not store:
        return jsonify({"success": False, "error": f"Store #{store_id} not found."}), 404

    data = request.get_json() or {}
    product_id = data.get("product_id")
    if not product_id:
        return jsonify({"success": False, "error": "product_id is required."}), 400

    try:
        p_id = int(product_id)
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid product_id format."}), 400

    product = db_service.get_product_by_id(p_id)
    if not product:
        return jsonify({"success": False, "error": f"Product #{p_id} not found in catalog."}), 404

    # Check for existing inventory (duplicate prevention)
    existing = db_service.get_store_product(store_id, p_id)
    if existing:
        return jsonify({
            "success": False,
            "error": f"Product #{p_id} is already registered in Store #{store_id} inventory. Use PUT to update."
        }), 409

    try:
        created = db_service.add_store_inventory(store_id, p_id, data)
        return jsonify({
            "success": True,
            "message": "Product successfully added to store inventory.",
            "inventory": created
        }), 201
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error adding store inventory: {e}")
        return jsonify({"success": False, "error": "Failed to add store inventory."}), 500

@main_bp.route("/api/stores/<int:store_id>/inventory/<int:product_id>", methods=["PUT"])
@require_admin_auth
def api_update_store_inventory(store_id: int, product_id: int):
    """
    Admin API: Updates price, stock, or threshold for a product at a store.
    """
    store = db_service.get_store_by_id(store_id)
    if not store:
        return jsonify({"success": False, "error": f"Store #{store_id} not found."}), 404

    existing = db_service.get_store_product(store_id, product_id)
    if not existing:
        return jsonify({"success": False, "error": f"Product #{product_id} is not stocked at Store #{store_id}."}), 404

    data = request.get_json() or {}
    try:
        updated = db_service.update_store_inventory(store_id, product_id, data)
        if updated:
            opensearch_service.update_store_inventory_item(
                store_id=store_id,
                product_id=product_id,
                selling_price=updated.get("selling_price"),
                original_price=updated.get("original_price"),
                stock_quantity=updated.get("stock_quantity"),
                is_available=updated.get("is_available")
            )
        return jsonify({
            "success": True,
            "message": "Store inventory updated successfully.",
            "inventory": updated
        })
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error updating store inventory: {e}")
        return jsonify({"success": False, "error": "Failed to update store inventory."}), 500

@main_bp.route("/api/stores/<int:store_id>/inventory/<int:product_id>", methods=["DELETE"])
@require_admin_auth
def api_remove_store_inventory(store_id: int, product_id: int):
    """
    Admin API: Removes a product from a store's inventory.
    """
    store = db_service.get_store_by_id(store_id)
    if not store:
        return jsonify({"success": False, "error": f"Store #{store_id} not found."}), 404

    existing = db_service.get_store_product(store_id, product_id)
    if not existing:
        return jsonify({"success": False, "error": f"Product #{product_id} not found in Store #{store_id}."}), 404

    deleted = db_service.remove_store_inventory(store_id, product_id)
    if deleted:
        opensearch_service.remove_store_inventory_item(store_id, product_id)
        return jsonify({
            "success": True,
            "message": f"Product #{product_id} successfully removed from Store #{store_id} inventory."
        })
    return jsonify({"success": False, "error": "Failed to remove product from store."}), 500

# Admin Store Management Endpoints
@main_bp.route("/api/admin/stores", methods=["POST"])
@require_admin_auth
def api_admin_create_store():
    """Admin API: Creates a new physical retail store."""
    data = request.get_json() or {}
    try:
        created = db_service.create_store(data)
        return jsonify({
            "success": True,
            "message": "Store created successfully.",
            "store": created
        }), 201
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error creating store: {e}")
        return jsonify({"success": False, "error": "Failed to create store."}), 500

@main_bp.route("/api/admin/stores/<int:store_id>", methods=["PUT"])
@require_admin_auth
def api_admin_update_store(store_id: int):
    """Admin API: Updates an existing physical store."""
    data = request.get_json() or {}
    store = db_service.get_store_by_id(store_id)
    if not store:
        return jsonify({"success": False, "error": f"Store #{store_id} not found."}), 404

    try:
        updated = db_service.update_store(store_id, data)
        return jsonify({
            "success": True,
            "message": "Store updated successfully.",
            "store": updated
        })
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error updating store: {e}")
        return jsonify({"success": False, "error": "Failed to update store."}), 500

@main_bp.route("/api/admin/stores/<int:store_id>/status", methods=["POST"])
@require_admin_auth
def api_admin_set_store_status(store_id: int):
    """Admin API: Activates or deactivates a physical store."""
    data = request.get_json() or {}
    is_active = bool(data.get("is_active", True))
    store = db_service.get_store_by_id(store_id)
    if not store:
        return jsonify({"success": False, "error": f"Store #{store_id} not found."}), 404

    if is_active:
        ok = db_service.activate_store(store_id)
    else:
        ok = db_service.deactivate_store(store_id)

    if ok:
        status_str = "activated" if is_active else "deactivated"
        return jsonify({
            "success": True,
            "message": f"Store #{store_id} has been {status_str}.",
            "is_active": is_active
        })
    return jsonify({"success": False, "error": "Failed to update store status."}), 500

