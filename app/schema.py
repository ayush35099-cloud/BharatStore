"""
BharatStore Relational Database Schema & Migration Engine
Production-grade DDL, constraints, indexes, migrations, and atomic stock management
Supporting both Aiven PostgreSQL and ACID-compliant SQLite.
"""

import os
import json
import time
import logging
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger("BharatStore.Schema")

# -----------------------------------------------------------------------------
# DDL Schema Definitions (PostgreSQL & SQLite)
# -----------------------------------------------------------------------------

def get_pg_schema_ddl() -> List[str]:
    """Returns PostgreSQL DDL statements with strict constraints and types"""
    return [
        # 1. Users & Authentication
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(180) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(50) DEFAULT 'CUSTOMER' CHECK (role IN ('CUSTOMER', 'SELLER', 'ADMIN', 'OPERATOR')),
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 2. Customers
        """
        CREATE TABLE IF NOT EXISTS customers (
            id SERIAL PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE SET NULL,
            name VARCHAR(150) NOT NULL,
            email VARCHAR(180) UNIQUE NOT NULL,
            phone VARCHAR(50),
            city VARCHAR(100),
            address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 3. Customer Profiles
        """
        CREATE TABLE IF NOT EXISTS customer_profiles (
            id SERIAL PRIMARY KEY,
            customer_id INT UNIQUE NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            default_city VARCHAR(100) DEFAULT 'Mumbai',
            loyalty_points INT DEFAULT 100 CHECK (loyalty_points >= 0),
            preferences_json TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 4. Customer Addresses
        """
        CREATE TABLE IF NOT EXISTS addresses (
            id SERIAL PRIMARY KEY,
            customer_id INT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            address_type VARCHAR(50) DEFAULT 'HOME' CHECK (address_type IN ('HOME', 'WORK', 'OTHER')),
            full_name VARCHAR(150) NOT NULL,
            phone VARCHAR(50) NOT NULL,
            address_line1 TEXT NOT NULL,
            address_line2 TEXT,
            landmark VARCHAR(150),
            city VARCHAR(100) NOT NULL,
            state VARCHAR(100) NOT NULL,
            pincode VARCHAR(20) NOT NULL,
            is_default BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 5. Physical Store Fulfillment Hubs
        """
        CREATE TABLE IF NOT EXISTS store_hubs (
            id SERIAL PRIMARY KEY,
            hub_code VARCHAR(50) UNIQUE NOT NULL,
            name VARCHAR(150) NOT NULL,
            city VARCHAR(100) NOT NULL,
            state VARCHAR(100) NOT NULL,
            address TEXT,
            pincode VARCHAR(20),
            delivery_radius_km INT DEFAULT 45,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 6. Sellers
        """
        CREATE TABLE IF NOT EXISTS sellers (
            id SERIAL PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE SET NULL,
            business_name VARCHAR(200) NOT NULL,
            gst_number VARCHAR(50) UNIQUE,
            pan_number VARCHAR(50),
            contact_email VARCHAR(180) NOT NULL,
            phone VARCHAR(50),
            city VARCHAR(100) NOT NULL,
            rating NUMERIC(3, 2) DEFAULT 4.8 CHECK (rating >= 1.0 AND rating <= 5.0),
            rating_count INT DEFAULT 1,
            is_verified BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 7. Seller Profiles
        """
        CREATE TABLE IF NOT EXISTS seller_profiles (
            id SERIAL PRIMARY KEY,
            seller_id INT UNIQUE NOT NULL REFERENCES sellers(id) ON DELETE CASCADE,
            store_name VARCHAR(200) NOT NULL,
            description TEXT,
            logo_url TEXT,
            banner_url TEXT,
            return_policy_days INT DEFAULT 7,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 8. Product Categories
        """
        CREATE TABLE IF NOT EXISTS categories (
            id SERIAL PRIMARY KEY,
            slug VARCHAR(100) UNIQUE NOT NULL,
            name VARCHAR(100) NOT NULL,
            parent_id INT REFERENCES categories(id) ON DELETE SET NULL,
            icon VARCHAR(50),
            display_order INT DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE
        );
        """,

        # 9. Products
        """
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            sku VARCHAR(64) UNIQUE NOT NULL,
            title VARCHAR(255) NOT NULL,
            brand VARCHAR(100) NOT NULL,
            category VARCHAR(100) NOT NULL,
            category_id INT REFERENCES categories(id) ON DELETE SET NULL,
            seller_id INT REFERENCES sellers(id) ON DELETE SET NULL,
            price NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
            original_price NUMERIC(10, 2) CHECK (original_price >= price OR original_price IS NULL),
            image_url TEXT,
            rating NUMERIC(3, 2) DEFAULT 4.5 CHECK (rating >= 1.0 AND rating <= 5.0),
            rating_count INT DEFAULT 0 CHECK (rating_count >= 0),
            description TEXT,
            cities_json TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 10. Product Images
        """
        CREATE TABLE IF NOT EXISTS product_images (
            id SERIAL PRIMARY KEY,
            product_id INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            image_url TEXT NOT NULL,
            is_primary BOOLEAN DEFAULT FALSE,
            display_order INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 11. Product Specifications
        """
        CREATE TABLE IF NOT EXISTS product_specifications (
            id SERIAL PRIMARY KEY,
            product_id INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            spec_group VARCHAR(100) DEFAULT 'General',
            spec_key VARCHAR(100) NOT NULL,
            spec_value TEXT NOT NULL
        );
        """,

        # 12. Carts
        """
        CREATE TABLE IF NOT EXISTS carts (
            id SERIAL PRIMARY KEY,
            customer_id INT REFERENCES customers(id) ON DELETE CASCADE,
            session_id VARCHAR(100) UNIQUE,
            status VARCHAR(50) DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'ABANDONED', 'CONVERTED')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 13. Cart Items
        """
        CREATE TABLE IF NOT EXISTS cart_items (
            id SERIAL PRIMARY KEY,
            cart_id INT NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
            product_id INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            quantity INT NOT NULL CHECK (quantity > 0),
            unit_price NUMERIC(10, 2) NOT NULL,
            reserved_until TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (cart_id, product_id)
        );
        """,

        # 14. Orders
        """
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            order_number VARCHAR(64) UNIQUE NOT NULL,
            customer_id INT REFERENCES customers(id),
            total_amount NUMERIC(10, 2) NOT NULL CHECK (total_amount >= 0),
            discount_amount NUMERIC(10, 2) DEFAULT 0.0,
            shipping_fee NUMERIC(10, 2) DEFAULT 0.0,
            status VARCHAR(50) DEFAULT 'PENDING_PAYMENT' CHECK (status IN ('PENDING_PAYMENT', 'PAID', 'CONFIRMED', 'PROCESSING', 'SHIPPED', 'DELIVERED', 'CANCELLED', 'REFUNDED')),
            payment_method VARCHAR(50) DEFAULT 'UPI',
            payment_id VARCHAR(100),
            payment_status VARCHAR(50) DEFAULT 'PENDING' CHECK (payment_status IN ('PENDING', 'AUTHORIZED', 'PAID', 'FAILED', 'REFUNDED')),
            shipping_city VARCHAR(100) NOT NULL,
            shipping_address TEXT,
            hub_id INT REFERENCES store_hubs(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 15. Order Items
        """
        CREATE TABLE IF NOT EXISTS order_items (
            id SERIAL PRIMARY KEY,
            order_id INT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            product_id INT NOT NULL REFERENCES products(id),
            seller_id INT REFERENCES sellers(id) ON DELETE SET NULL,
            quantity INT NOT NULL CHECK (quantity > 0),
            unit_price NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0),
            subtotal NUMERIC(10, 2) NOT NULL CHECK (subtotal >= 0)
        );
        """,

        # 16. Payments
        """
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            order_id INT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            payment_method VARCHAR(50) NOT NULL,
            transaction_id VARCHAR(100) UNIQUE NOT NULL,
            gateway VARCHAR(50) DEFAULT 'RAZORPAY_EMULATOR',
            amount NUMERIC(10, 2) NOT NULL CHECK (amount >= 0),
            currency VARCHAR(10) DEFAULT 'INR',
            status VARCHAR(50) DEFAULT 'PAID' CHECK (status IN ('PENDING', 'PAID', 'FAILED', 'REFUNDED')),
            payment_metadata_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 17. Refunds
        """
        CREATE TABLE IF NOT EXISTS refunds (
            id SERIAL PRIMARY KEY,
            payment_id INT REFERENCES payments(id) ON DELETE SET NULL,
            order_id INT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            amount NUMERIC(10, 2) NOT NULL CHECK (amount > 0),
            reason TEXT,
            gateway_refund_id VARCHAR(100),
            status VARCHAR(50) DEFAULT 'PROCESSED' CHECK (status IN ('PENDING', 'PROCESSED', 'FAILED')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 18. Inventory
        """
        CREATE TABLE IF NOT EXISTS inventory (
            id SERIAL PRIMARY KEY,
            product_id INT UNIQUE NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            hub_id INT REFERENCES store_hubs(id) ON DELETE SET NULL,
            stock_quantity INT NOT NULL CHECK (stock_quantity >= 0),
            reserved_quantity INT DEFAULT 0 CHECK (reserved_quantity >= 0),
            min_threshold INT DEFAULT 5 CHECK (min_threshold >= 0),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 19. Inventory Movements (Immutable Double-Entry Stock Ledger)
        """
        CREATE TABLE IF NOT EXISTS inventory_movements (
            id SERIAL PRIMARY KEY,
            product_id INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            movement_type VARCHAR(50) NOT NULL CHECK (movement_type IN ('RESERVED', 'RELEASED', 'SOLD', 'RESTOCKED', 'CANCELLED_RETURN', 'ADJUSTED')),
            quantity INT NOT NULL,
            balance_after INT NOT NULL,
            reference_type VARCHAR(50) NOT NULL,
            reference_id VARCHAR(100) NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 20. Shipments
        """
        CREATE TABLE IF NOT EXISTS shipments (
            id SERIAL PRIMARY KEY,
            order_id INT UNIQUE NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            hub_id INT REFERENCES store_hubs(id) ON DELETE SET NULL,
            courier_name VARCHAR(100) DEFAULT 'BlueDart Express',
            tracking_number VARCHAR(100) UNIQUE NOT NULL,
            status VARCHAR(50) DEFAULT 'DISPATCHED' CHECK (status IN ('DISPATCHED', 'IN_TRANSIT', 'OUT_FOR_DELIVERY', 'DELIVERED', 'RETURNED')),
            estimated_delivery TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 21. Shipment Tracking Events
        """
        CREATE TABLE IF NOT EXISTS tracking_events (
            id SERIAL PRIMARY KEY,
            shipment_id INT NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
            status VARCHAR(50) NOT NULL,
            location VARCHAR(100) NOT NULL,
            description TEXT NOT NULL,
            event_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 22. Product Reviews
        """
        CREATE TABLE IF NOT EXISTS product_reviews (
            id SERIAL PRIMARY KEY,
            product_id INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            customer_id INT REFERENCES customers(id) ON DELETE SET NULL,
            order_id INT REFERENCES orders(id) ON DELETE SET NULL,
            rating INT NOT NULL CHECK (rating >= 1 AND rating <= 5),
            title VARCHAR(150),
            comment TEXT,
            is_verified_purchase BOOLEAN DEFAULT TRUE,
            helpful_count INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 23. Review Votes
        """
        CREATE TABLE IF NOT EXISTS review_votes (
            id SERIAL PRIMARY KEY,
            review_id INT NOT NULL REFERENCES product_reviews(id) ON DELETE CASCADE,
            customer_id INT REFERENCES customers(id) ON DELETE CASCADE,
            vote_type VARCHAR(20) CHECK (vote_type IN ('HELPFUL', 'UNHELPFUL')),
            UNIQUE (review_id, customer_id)
        );
        """
    ]

def get_sqlite_schema_ddl() -> List[str]:
    """Returns SQLite DDL statements compatible with ACID SQLite 3 engine"""
    return [
        # 1. Users
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'CUSTOMER' CHECK (role IN ('CUSTOMER', 'SELLER', 'ADMIN', 'OPERATOR')),
            is_active INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 2. Customers
        """
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            city TEXT,
            address TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 3. Customer Profiles
        """
        CREATE TABLE IF NOT EXISTS customer_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER UNIQUE NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            default_city TEXT DEFAULT 'Mumbai',
            loyalty_points INTEGER DEFAULT 100 CHECK (loyalty_points >= 0),
            preferences_json TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 4. Addresses
        """
        CREATE TABLE IF NOT EXISTS addresses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            address_type TEXT DEFAULT 'HOME' CHECK (address_type IN ('HOME', 'WORK', 'OTHER')),
            full_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            address_line1 TEXT NOT NULL,
            address_line2 TEXT,
            landmark TEXT,
            city TEXT NOT NULL,
            state TEXT NOT NULL,
            pincode TEXT NOT NULL,
            is_default INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 5. Store Hubs
        """
        CREATE TABLE IF NOT EXISTS store_hubs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hub_code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            city TEXT NOT NULL,
            state TEXT NOT NULL,
            address TEXT,
            pincode TEXT,
            delivery_radius_km INTEGER DEFAULT 45,
            is_active INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 6. Sellers
        """
        CREATE TABLE IF NOT EXISTS sellers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            business_name TEXT NOT NULL,
            gst_number TEXT UNIQUE,
            pan_number TEXT,
            contact_email TEXT NOT NULL,
            phone TEXT,
            city TEXT NOT NULL,
            rating REAL DEFAULT 4.8 CHECK (rating >= 1.0 AND rating <= 5.0),
            rating_count INTEGER DEFAULT 1,
            is_verified INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 7. Seller Profiles
        """
        CREATE TABLE IF NOT EXISTS seller_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seller_id INTEGER UNIQUE NOT NULL REFERENCES sellers(id) ON DELETE CASCADE,
            store_name TEXT NOT NULL,
            description TEXT,
            logo_url TEXT,
            banner_url TEXT,
            return_policy_days INTEGER DEFAULT 7,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 8. Categories
        """
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            parent_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            icon TEXT,
            display_order INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        );
        """,

        # 9. Products
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY,
            sku TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            brand TEXT NOT NULL,
            category TEXT NOT NULL,
            category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            seller_id INTEGER REFERENCES sellers(id) ON DELETE SET NULL,
            price REAL NOT NULL CHECK (price >= 0),
            original_price REAL CHECK (original_price >= price OR original_price IS NULL),
            image_url TEXT,
            rating REAL DEFAULT 4.5 CHECK (rating >= 1.0 AND rating <= 5.0),
            rating_count INTEGER DEFAULT 0 CHECK (rating_count >= 0),
            description TEXT,
            cities_json TEXT,
            is_active INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 10. Product Images
        """
        CREATE TABLE IF NOT EXISTS product_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            image_url TEXT NOT NULL,
            is_primary INTEGER DEFAULT 0,
            display_order INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 11. Product Specifications
        """
        CREATE TABLE IF NOT EXISTS product_specifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            spec_group TEXT DEFAULT 'General',
            spec_key TEXT NOT NULL,
            spec_value TEXT NOT NULL
        );
        """,

        # 12. Carts
        """
        CREATE TABLE IF NOT EXISTS carts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER REFERENCES customers(id) ON DELETE CASCADE,
            session_id TEXT UNIQUE,
            status TEXT DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'ABANDONED', 'CONVERTED')),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 13. Cart Items
        """
        CREATE TABLE IF NOT EXISTS cart_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cart_id INTEGER NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            unit_price REAL NOT NULL,
            reserved_until DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (cart_id, product_id)
        );
        """,

        # 14. Orders
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT UNIQUE NOT NULL,
            customer_id INTEGER REFERENCES customers(id),
            total_amount REAL NOT NULL CHECK (total_amount >= 0),
            discount_amount REAL DEFAULT 0.0,
            shipping_fee REAL DEFAULT 0.0,
            status TEXT DEFAULT 'PENDING_PAYMENT' CHECK (status IN ('PENDING_PAYMENT', 'PAID', 'CONFIRMED', 'PROCESSING', 'SHIPPED', 'DELIVERED', 'CANCELLED', 'REFUNDED')),
            payment_method TEXT DEFAULT 'UPI',
            payment_id TEXT,
            payment_status TEXT DEFAULT 'PENDING' CHECK (payment_status IN ('PENDING', 'AUTHORIZED', 'PAID', 'FAILED', 'REFUNDED')),
            shipping_city TEXT NOT NULL,
            shipping_address TEXT,
            hub_id INTEGER REFERENCES store_hubs(id) ON DELETE SET NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 15. Order Items
        """
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL REFERENCES products(id),
            seller_id INTEGER REFERENCES sellers(id) ON DELETE SET NULL,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            unit_price REAL NOT NULL CHECK (unit_price >= 0),
            subtotal REAL NOT NULL CHECK (subtotal >= 0)
        );
        """,

        # 16. Payments
        """
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            payment_method TEXT NOT NULL,
            transaction_id TEXT UNIQUE NOT NULL,
            gateway TEXT DEFAULT 'RAZORPAY_EMULATOR',
            amount REAL NOT NULL CHECK (amount >= 0),
            currency TEXT DEFAULT 'INR',
            status TEXT DEFAULT 'PAID' CHECK (status IN ('PENDING', 'PAID', 'FAILED', 'REFUNDED')),
            payment_metadata_json TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 17. Refunds
        """
        CREATE TABLE IF NOT EXISTS refunds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_id INTEGER REFERENCES payments(id) ON DELETE SET NULL,
            order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            amount REAL NOT NULL CHECK (amount > 0),
            reason TEXT,
            gateway_refund_id TEXT,
            status TEXT DEFAULT 'PROCESSED' CHECK (status IN ('PENDING', 'PROCESSED', 'FAILED')),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 18. Inventory
        """
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER UNIQUE NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            hub_id INTEGER REFERENCES store_hubs(id) ON DELETE SET NULL,
            stock_quantity INTEGER NOT NULL CHECK (stock_quantity >= 0),
            reserved_quantity INTEGER DEFAULT 0 CHECK (reserved_quantity >= 0),
            min_threshold INTEGER DEFAULT 5 CHECK (min_threshold >= 0),
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 19. Inventory Movements
        """
        CREATE TABLE IF NOT EXISTS inventory_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            movement_type TEXT NOT NULL CHECK (movement_type IN ('RESERVED', 'RELEASED', 'SOLD', 'RESTOCKED', 'CANCELLED_RETURN', 'ADJUSTED')),
            quantity INTEGER NOT NULL,
            balance_after INTEGER NOT NULL,
            reference_type TEXT NOT NULL,
            reference_id TEXT NOT NULL,
            notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 20. Shipments
        """
        CREATE TABLE IF NOT EXISTS shipments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER UNIQUE NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            hub_id INTEGER REFERENCES store_hubs(id) ON DELETE SET NULL,
            courier_name TEXT DEFAULT 'BlueDart Express',
            tracking_number TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'DISPATCHED' CHECK (status IN ('DISPATCHED', 'IN_TRANSIT', 'OUT_FOR_DELIVERY', 'DELIVERED', 'RETURNED')),
            estimated_delivery DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 21. Tracking Events
        """
        CREATE TABLE IF NOT EXISTS tracking_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_id INTEGER NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            location TEXT NOT NULL,
            description TEXT NOT NULL,
            event_time DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 22. Product Reviews
        """
        CREATE TABLE IF NOT EXISTS product_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
            order_id INTEGER REFERENCES orders(id) ON DELETE SET NULL,
            rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
            title TEXT,
            comment TEXT,
            is_verified_purchase INTEGER DEFAULT 1,
            helpful_count INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 23. Review Votes
        """
        CREATE TABLE IF NOT EXISTS review_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id INTEGER NOT NULL REFERENCES product_reviews(id) ON DELETE CASCADE,
            customer_id INTEGER REFERENCES customers(id) ON DELETE CASCADE,
            vote_type TEXT CHECK (vote_type IN ('HELPFUL', 'UNHELPFUL')),
            UNIQUE (review_id, customer_id)
        );
        """
    ]

# -----------------------------------------------------------------------------
# Database Indexes
# -----------------------------------------------------------------------------

INDEXES_DDL = [
    # Products & Catalog
    "CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);",
    "CREATE INDEX IF NOT EXISTS idx_products_category_id ON products(category_id);",
    "CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand);",
    "CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku);",
    "CREATE INDEX IF NOT EXISTS idx_products_price ON products(price);",
    "CREATE INDEX IF NOT EXISTS idx_products_seller ON products(seller_id);",

    # Orders & Items
    "CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);",
    "CREATE INDEX IF NOT EXISTS idx_orders_number ON orders(order_number);",
    "CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);",
    "CREATE INDEX IF NOT EXISTS idx_orders_payment_status ON orders(payment_status);",
    "CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);",
    "CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);",
    "CREATE INDEX IF NOT EXISTS idx_order_items_product ON order_items(product_id);",

    # Inventory & Movements
    "CREATE INDEX IF NOT EXISTS idx_inventory_product ON inventory(product_id);",
    "CREATE INDEX IF NOT EXISTS idx_inventory_hub ON inventory(hub_id);",
    "CREATE INDEX IF NOT EXISTS idx_inv_movements_product ON inventory_movements(product_id);",
    "CREATE INDEX IF NOT EXISTS idx_inv_movements_ref ON inventory_movements(reference_type, reference_id);",
    "CREATE INDEX IF NOT EXISTS idx_inv_movements_created ON inventory_movements(created_at);",

    # Carts
    "CREATE INDEX IF NOT EXISTS idx_carts_customer ON carts(customer_id);",
    "CREATE INDEX IF NOT EXISTS idx_carts_session ON carts(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_cart_items_cart ON cart_items(cart_id);",
    "CREATE INDEX IF NOT EXISTS idx_cart_items_product ON cart_items(product_id);",

    # Payments & Refunds
    "CREATE INDEX IF NOT EXISTS idx_payments_order ON payments(order_id);",
    "CREATE INDEX IF NOT EXISTS idx_payments_txn ON payments(transaction_id);",
    "CREATE INDEX IF NOT EXISTS idx_refunds_order ON refunds(order_id);",

    # Shipments & Reviews
    "CREATE INDEX IF NOT EXISTS idx_shipments_order ON shipments(order_id);",
    "CREATE INDEX IF NOT EXISTS idx_shipments_tracking ON shipments(tracking_number);",
    "CREATE INDEX IF NOT EXISTS idx_reviews_product ON product_reviews(product_id);",
    "CREATE INDEX IF NOT EXISTS idx_reviews_customer ON product_reviews(customer_id);"
]

# -----------------------------------------------------------------------------
# Database Seed Data for Extended Tables
# -----------------------------------------------------------------------------

SAMPLE_STORE_HUBS = [
    {"hub_code": "HUB-MUM-01", "name": "BharatStore Mumbai Central Store", "city": "Mumbai", "state": "Maharashtra", "address": "Linking Road, Bandra West, Mumbai 400050", "pincode": "400050"},
    {"hub_code": "HUB-BLR-01", "name": "BharatStore Bengaluru Tech Store", "city": "Bengaluru", "state": "Karnataka", "address": "100 Feet Road, Indiranagar, Bengaluru 560038", "pincode": "560038"},
    {"hub_code": "HUB-DEL-01", "name": "BharatStore Delhi NCR Flagship", "city": "Delhi NCR", "state": "Delhi", "address": "Connaught Place, Block C, New Delhi 110001", "pincode": "110001"},
    {"hub_code": "HUB-HYD-01", "name": "BharatStore Hyderabad Hub", "city": "Hyderabad", "state": "Telangana", "address": "Road No. 36, Jubilee Hills, Hyderabad 500033", "pincode": "500033"},
    {"hub_code": "HUB-CHN-01", "name": "BharatStore Chennai Marina Store", "city": "Chennai", "state": "Tamil Nadu", "address": "T Nagar, Chennai 600017", "pincode": "600017"},
    {"hub_code": "HUB-KOL-01", "name": "BharatStore Kolkata Hub", "city": "Kolkata", "state": "West Bengal", "address": "Park Street, Kolkata 700016", "pincode": "700016"}
]

SAMPLE_SELLERS = [
    {"id": 1, "business_name": "Bharat Retail Corp Ltd", "gst_number": "27AAACB1234F1Z0", "contact_email": "retail@bharatstore.in", "city": "Mumbai", "rating": 4.9},
    {"id": 2, "business_name": "Apex Electronics India", "gst_number": "29AABCA5678G2Z1", "contact_email": "sales@apexelectronics.in", "city": "Bengaluru", "rating": 4.8},
    {"id": 3, "business_name": "Metro Heritage Appliances", "gst_number": "07AABCM9012H3Z2", "contact_email": "contact@metroheritage.in", "city": "Delhi NCR", "rating": 4.7}
]

SAMPLE_CATEGORIES = [
    {"id": 1, "slug": "electronics", "name": "Electronics", "icon": "fa-mobile-screen"},
    {"id": 2, "slug": "laptops", "name": "Laptops & Computers", "icon": "fa-laptop"},
    {"id": 3, "slug": "audio", "name": "Headphones & Audio", "icon": "fa-headphones"},
    {"id": 4, "slug": "wearables", "name": "Wearable Tech", "icon": "fa-clock"},
    {"id": 5, "slug": "appliances", "name": "Home & Kitchen", "icon": "fa-blender"}
]

# -----------------------------------------------------------------------------
# Safe Non-Destructive Migration Runner
# -----------------------------------------------------------------------------

def run_migrations(conn, is_postgres: bool = False):
    """
    Executes non-destructive schema migrations:
    1. Creates all 23 domain tables with constraints
    2. Applies all indexes for query optimization
    3. Non-destructively migrates existing tables with ALTER statements
    4. Seeds extended hub, category, and seller reference records
    """
    cur = conn.cursor()

    # Step 1: Execute Table DDLs
    ddl_list = get_pg_schema_ddl() if is_postgres else get_sqlite_schema_ddl()
    for ddl in ddl_list:
        cur.execute(ddl)

    # Step 2: Non-destructive column alterations for existing tables
    if is_postgres:
        alter_queries = [
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method VARCHAR(50) DEFAULT 'UPI';",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_id VARCHAR(100);",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_status VARCHAR(50) DEFAULT 'PAID';",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS hub_id INT REFERENCES store_hubs(id) ON DELETE SET NULL;",
            "ALTER TABLE inventory ADD COLUMN IF NOT EXISTS reserved_quantity INT DEFAULT 0;",
            "ALTER TABLE inventory ADD COLUMN IF NOT EXISTS hub_id INT REFERENCES store_hubs(id) ON DELETE SET NULL;",
            "ALTER TABLE inventory ADD COLUMN IF NOT EXISTS min_threshold INT DEFAULT 5;",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS seller_id INT REFERENCES sellers(id) ON DELETE SET NULL;",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS category_id INT REFERENCES categories(id) ON DELETE SET NULL;"
        ]
        for q in alter_queries:
            try:
                cur.execute(q)
            except Exception as e:
                logger.debug(f"PG Alter notice: {e}")
    else:
        sqlite_alters = [
            ("orders", "payment_method", "TEXT DEFAULT 'UPI'"),
            ("orders", "payment_id", "TEXT"),
            ("orders", "payment_status", "TEXT DEFAULT 'PAID'"),
            ("orders", "hub_id", "INTEGER REFERENCES store_hubs(id)"),
            ("inventory", "reserved_quantity", "INTEGER DEFAULT 0"),
            ("inventory", "hub_id", "INTEGER REFERENCES store_hubs(id)"),
            ("inventory", "min_threshold", "INTEGER DEFAULT 5"),
            ("products", "seller_id", "INTEGER REFERENCES sellers(id)"),
            ("products", "category_id", "INTEGER REFERENCES categories(id)")
        ]
        for tbl, col, col_def in sqlite_alters:
            try:
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {col_def};")
            except Exception:
                pass # Already exists in SQLite

    # Step 3: Apply Indexes
    for idx_sql in INDEXES_DDL:
        try:
            cur.execute(idx_sql)
        except Exception as e:
            logger.debug(f"Index creation notice: {e}")

    # Step 4: Seed reference hubs if empty
    cur.execute("SELECT COUNT(*) FROM store_hubs;")
    hub_count = cur.fetchone()[0]
    if hub_count == 0:
        for h in SAMPLE_STORE_HUBS:
            if is_postgres:
                cur.execute("""
                INSERT INTO store_hubs (hub_code, name, city, state, address, pincode)
                VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (hub_code) DO NOTHING;
                """, (h["hub_code"], h["name"], h["city"], h["state"], h["address"], h["pincode"]))
            else:
                cur.execute("""
                INSERT OR IGNORE INTO store_hubs (hub_code, name, city, state, address, pincode)
                VALUES (?, ?, ?, ?, ?, ?);
                """, (h["hub_code"], h["name"], h["city"], h["state"], h["address"], h["pincode"]))

    # Step 5: Seed reference sellers if empty
    cur.execute("SELECT COUNT(*) FROM sellers;")
    seller_count = cur.fetchone()[0]
    if seller_count == 0:
        for s in SAMPLE_SELLERS:
            if is_postgres:
                cur.execute("""
                INSERT INTO sellers (id, business_name, gst_number, contact_email, city, rating)
                VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING;
                """, (s["id"], s["business_name"], s["gst_number"], s["contact_email"], s["city"], s["rating"]))
            else:
                cur.execute("""
                INSERT OR IGNORE INTO sellers (id, business_name, gst_number, contact_email, city, rating)
                VALUES (?, ?, ?, ?, ?, ?);
                """, (s["id"], s["business_name"], s["gst_number"], s["contact_email"], s["city"], s["rating"]))

    # Step 6: Seed categories if empty
    cur.execute("SELECT COUNT(*) FROM categories;")
    cat_count = cur.fetchone()[0]
    if cat_count == 0:
        for c in SAMPLE_CATEGORIES:
            if is_postgres:
                cur.execute("""
                INSERT INTO categories (id, slug, name, icon)
                VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING;
                """, (c["id"], c["slug"], c["name"], c["icon"]))
            else:
                cur.execute("""
                INSERT OR IGNORE INTO categories (id, slug, name, icon)
                VALUES (?, ?, ?, ?);
                """, (c["id"], c["slug"], c["name"], c["icon"]))

    conn.commit()
    logger.info(f"Database schema migrations successfully verified on {'PostgreSQL' if is_postgres else 'SQLite'}.")

# -----------------------------------------------------------------------------
# Atomic Stock Reservation & Release Engine
# -----------------------------------------------------------------------------

def atomic_reserve_stock(cur, is_postgres: bool, product_id: int, quantity: int, reference_type: str, reference_id: str) -> Dict[str, Any]:
    """
    Atomically reserves inventory for an in-flight cart or checkout.
    Guarantees available_stock = (stock_quantity - reserved_quantity) >= requested quantity.
    Logs movement to immutable inventory_movements ledger.
    """
    if quantity <= 0:
        raise ValueError(f"Reservation quantity must be strictly positive, got {quantity}")

    # Row lock inventory row
    if is_postgres:
        cur.execute("""
        SELECT stock_quantity, reserved_quantity, min_threshold
        FROM inventory
        WHERE product_id = %s
        FOR UPDATE;
        """, (product_id,))
        row = cur.fetchone()
    else:
        cur.execute("""
        SELECT stock_quantity, reserved_quantity, min_threshold
        FROM inventory
        WHERE product_id = ?;
        """, (product_id,))
        row = cur.fetchone()

    if not row:
        raise ValueError(f"Product ID {product_id} has no inventory entry.")

    stock = row["stock_quantity"] if isinstance(row, dict) or hasattr(row, "keys") else row[0]
    reserved = row["reserved_quantity"] if isinstance(row, dict) or hasattr(row, "keys") else row[1]
    available = stock - reserved

    if available < quantity:
        raise ValueError(f"Insufficient unreserved stock for Product #{product_id}. Available: {available}, Requested: {quantity}.")

    new_reserved = reserved + quantity

    if is_postgres:
        cur.execute("""
        UPDATE inventory
        SET reserved_quantity = %s, updated_at = CURRENT_TIMESTAMP
        WHERE product_id = %s;
        """, (new_reserved, product_id))
        cur.execute("""
        INSERT INTO inventory_movements (product_id, movement_type, quantity, balance_after, reference_type, reference_id, notes)
        VALUES (%s, 'RESERVED', %s, %s, %s, %s, %s);
        """, (product_id, quantity, stock - new_reserved, reference_type, str(reference_id), f"Reserved {quantity} units for {reference_type} #{reference_id}"))
    else:
        cur.execute("""
        UPDATE inventory
        SET reserved_quantity = ?, updated_at = CURRENT_TIMESTAMP
        WHERE product_id = ?;
        """, (new_reserved, product_id))
        cur.execute("""
        INSERT INTO inventory_movements (product_id, movement_type, quantity, balance_after, reference_type, reference_id, notes)
        VALUES (?, 'RESERVED', ?, ?, ?, ?, ?);
        """, (product_id, quantity, stock - new_reserved, reference_type, str(reference_id), f"Reserved {quantity} units for {reference_type} #{reference_id}"))

    return {
        "product_id": product_id,
        "quantity_reserved": quantity,
        "total_stock": stock,
        "total_reserved": new_reserved,
        "available_stock": stock - new_reserved
    }

def atomic_release_stock(cur, is_postgres: bool, product_id: int, quantity: int, reference_type: str, reference_id: str) -> Dict[str, Any]:
    """
    Atomically releases a previously held reservation back to general inventory.
    """
    if quantity <= 0:
        raise ValueError(f"Release quantity must be positive, got {quantity}")

    if is_postgres:
        cur.execute("""
        SELECT stock_quantity, reserved_quantity
        FROM inventory
        WHERE product_id = %s
        FOR UPDATE;
        """, (product_id,))
        row = cur.fetchone()
    else:
        cur.execute("""
        SELECT stock_quantity, reserved_quantity
        FROM inventory
        WHERE product_id = ?;
        """, (product_id,))
        row = cur.fetchone()

    if not row:
        raise ValueError(f"Product ID {product_id} has no inventory entry.")

    stock = row["stock_quantity"] if isinstance(row, dict) or hasattr(row, "keys") else row[0]
    reserved = row["reserved_quantity"] if isinstance(row, dict) or hasattr(row, "keys") else row[1]
    new_reserved = max(0, reserved - quantity)

    if is_postgres:
        cur.execute("""
        UPDATE inventory
        SET reserved_quantity = %s, updated_at = CURRENT_TIMESTAMP
        WHERE product_id = %s;
        """, (new_reserved, product_id))
        cur.execute("""
        INSERT INTO inventory_movements (product_id, movement_type, quantity, balance_after, reference_type, reference_id, notes)
        VALUES (%s, 'RELEASED', %s, %s, %s, %s, %s);
        """, (product_id, quantity, stock - new_reserved, reference_type, str(reference_id), f"Released {quantity} units for {reference_type} #{reference_id}"))
    else:
        cur.execute("""
        UPDATE inventory
        SET reserved_quantity = ?, updated_at = CURRENT_TIMESTAMP
        WHERE product_id = ?;
        """, (new_reserved, product_id))
        cur.execute("""
        INSERT INTO inventory_movements (product_id, movement_type, quantity, balance_after, reference_type, reference_id, notes)
        VALUES (?, 'RELEASED', ?, ?, ?, ?, ?);
        """, (product_id, quantity, stock - new_reserved, reference_type, str(reference_id), f"Released {quantity} units for {reference_type} #{reference_id}"))

    return {
        "product_id": product_id,
        "quantity_released": quantity,
        "total_stock": stock,
        "total_reserved": new_reserved,
        "available_stock": stock - new_reserved
    }

def atomic_commit_reserved_stock(cur, is_postgres: bool, product_id: int, quantity: int, reference_type: str, reference_id: str) -> Dict[str, Any]:
    """
    Finalizes an order purchase: decrements actual stock and releases reserved allocation.
    """
    if is_postgres:
        cur.execute("""
        SELECT stock_quantity, reserved_quantity
        FROM inventory
        WHERE product_id = %s
        FOR UPDATE;
        """, (product_id,))
        row = cur.fetchone()
    else:
        cur.execute("""
        SELECT stock_quantity, reserved_quantity
        FROM inventory
        WHERE product_id = ?;
        """, (product_id,))
        row = cur.fetchone()

    stock = row["stock_quantity"] if isinstance(row, dict) or hasattr(row, "keys") else row[0]
    reserved = row["reserved_quantity"] if isinstance(row, dict) or hasattr(row, "keys") else row[1]

    if stock < quantity:
        raise ValueError(f"Cannot commit sale for Product #{product_id}: requested {quantity} exceeds actual stock {stock}.")

    new_stock = stock - quantity
    new_reserved = max(0, reserved - quantity)

    if is_postgres:
        cur.execute("""
        UPDATE inventory
        SET stock_quantity = %s, reserved_quantity = %s, updated_at = CURRENT_TIMESTAMP
        WHERE product_id = %s;
        """, (new_stock, new_reserved, product_id))
        cur.execute("""
        INSERT INTO inventory_movements (product_id, movement_type, quantity, balance_after, reference_type, reference_id, notes)
        VALUES (%s, 'SOLD', %s, %s, %s, %s, %s);
        """, (product_id, quantity, new_stock - new_reserved, reference_type, str(reference_id), f"Sold {quantity} units for {reference_type} #{reference_id}"))
    else:
        cur.execute("""
        UPDATE inventory
        SET stock_quantity = ?, reserved_quantity = ?, updated_at = CURRENT_TIMESTAMP
        WHERE product_id = ?;
        """, (new_stock, new_reserved, product_id))
        cur.execute("""
        INSERT INTO inventory_movements (product_id, movement_type, quantity, balance_after, reference_type, reference_id, notes)
        VALUES (?, 'SOLD', ?, ?, ?, ?, ?);
        """, (product_id, quantity, new_stock - new_reserved, reference_type, str(reference_id), f"Sold {quantity} units for {reference_type} #{reference_id}"))

    return {
        "product_id": product_id,
        "quantity_sold": quantity,
        "new_stock": new_stock,
        "new_reserved": new_reserved,
        "available_stock": new_stock - new_reserved
    }
