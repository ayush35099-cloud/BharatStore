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
from flask import Blueprint, request, jsonify, render_template, Response, session, redirect, url_for
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

# Pre-populate OpenSearch index with all products on startup
try:
    all_prods = db_service.get_all_products()
    opensearch_service.index_all_products(all_prods)
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
# Web Views
# -------------------------------------------------------------------------
@main_bp.route("/")
def index():
    mode = get_current_shopping_mode()
    if mode == "RETAIL_NEAR_ME" and request.args.get("view") != "online":
        hubs = db_service.get_store_hubs()
        products = db_service.get_all_products()
        return render_template("retail.html", hubs=hubs, products=products, active_mode="RETAIL_NEAR_ME")
    return render_template("index.html")

@main_bp.route("/retail")
def retail_page():
    set_current_shopping_mode("RETAIL_NEAR_ME")
    hubs = db_service.get_store_hubs()
    products = db_service.get_all_products()
    return render_template("retail.html", hubs=hubs, products=products, active_mode="RETAIL_NEAR_ME")

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
def order_detail_page(order_id: int):
    order = db_service.get_order_by_id(order_id)
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
    products = db_service.get_all_products(category=category, city=city)
    return jsonify({"total": len(products), "products": products})

@main_bp.route("/api/products/<int:product_id>", methods=["GET"])
def get_product(product_id: int):
    prod = db_service.get_product_by_id(product_id)
    if not prod:
        return jsonify({"error": "Product not found"}), 404
    prod["related_products"] = db_service.get_related_products(product_id, prod.get("category"), limit=4)
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
    Search bar endpoint powered by OpenSearch with typo tolerance:
    handles queries like 'lapop', 'bluetoth', 'samsng' and filters by category, city, price.
    """
    query = request.args.get("q", "").strip()
    category = request.args.get("category")
    city = request.args.get("city")
    min_price = request.args.get("min_price", type=float)
    max_price = request.args.get("max_price", type=float)

    search_result = opensearch_service.search(
        query_text=query,
        category=category,
        city=city,
        min_price=min_price,
        max_price=max_price
    )
    return jsonify(search_result)

@main_bp.route("/api/search/suggestions", methods=["GET"])
def search_suggestions():
    query = request.args.get("q", "").strip()
    suggestions = opensearch_service.get_suggestions(query, limit=5)
    return jsonify({"query": query, "suggestions": suggestions})

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
    """Retrieve recent orders with their operational and payment statuses"""
    limit = request.args.get("limit", default=25, type=int)
    orders = db_service.get_recent_orders(limit=limit)
    return jsonify({"total": len(orders), "orders": orders})

@main_bp.route("/api/orders/<int:order_id>", methods=["GET"])
def get_order_details(order_id: int):
    """Retrieve complete details for a specific order by ID"""
    order = db_service.get_order_by_id(order_id)
    if not order:
        return jsonify({"success": False, "error": f"Order #{order_id} not found"}), 404
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

@main_bp.route("/api/admin/orders/<int:order_id>/status", methods=["POST"])
@require_admin_auth
def api_update_order_status(order_id: int):
    """Updates operational order status (CONFIRMED, SHIPPED, DELIVERED, CANCELLED)"""
    data = request.get_json() or {}
    status = data.get("status", "")
    updated_order = db_service.update_order_status(order_id, status)
    if not updated_order:
        return jsonify({"success": False, "error": "Order not found"}), 404
    kafka_service.produce_order_event(updated_order, event_type=f"ORDER_{status.upper()}")
    return jsonify({"success": True, "order": updated_order})

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
