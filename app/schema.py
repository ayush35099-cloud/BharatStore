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
            latitude NUMERIC(10, 6),
            longitude NUMERIC(10, 6),
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
        """,

        # 24. Physical Stores (Phase 4)
        """
        CREATE TABLE IF NOT EXISTS stores (
            id SERIAL PRIMARY KEY,
            store_name VARCHAR(200) NOT NULL,
            store_slug VARCHAR(200) UNIQUE NOT NULL,
            store_description TEXT,
            store_logo TEXT,
            store_banner TEXT,
            owner_name VARCHAR(150),
            contact_phone VARCHAR(50),
            email VARCHAR(180),
            full_address TEXT NOT NULL,
            city VARCHAR(100) NOT NULL,
            area VARCHAR(100) NOT NULL,
            pincode VARCHAR(20) NOT NULL,
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            opening_time VARCHAR(20) DEFAULT '07:00 AM',
            closing_time VARCHAR(20) DEFAULT '11:00 PM',
            is_active BOOLEAN DEFAULT TRUE,
            accepts_delivery BOOLEAN DEFAULT TRUE,
            accepts_pickup BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 25. Store Inventory (Phase 4 Multi-Store Inventory & Pricing)
        """
        CREATE TABLE IF NOT EXISTS store_inventory (
            id SERIAL PRIMARY KEY,
            store_id INT NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            product_id INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            selling_price NUMERIC(10, 2) NOT NULL CHECK (selling_price >= 0),
            original_price NUMERIC(10, 2) CHECK (original_price >= selling_price OR original_price IS NULL),
            stock_quantity INT NOT NULL DEFAULT 0 CHECK (stock_quantity >= 0),
            reserved_quantity INT DEFAULT 0 CHECK (reserved_quantity >= 0),
            low_stock_threshold INT DEFAULT 5 CHECK (low_stock_threshold >= 0),
            is_available BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (store_id, product_id)
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
            latitude REAL,
            longitude REAL,
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
        """,

        # 24. Physical Stores (Phase 4)
        """
        CREATE TABLE IF NOT EXISTS stores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_name TEXT NOT NULL,
            store_slug TEXT UNIQUE NOT NULL,
            store_description TEXT,
            store_logo TEXT,
            store_banner TEXT,
            owner_name TEXT,
            contact_phone TEXT,
            email TEXT,
            full_address TEXT NOT NULL,
            city TEXT NOT NULL,
            area TEXT NOT NULL,
            pincode TEXT NOT NULL,
            latitude REAL,
            longitude REAL,
            opening_time TEXT DEFAULT '07:00 AM',
            closing_time TEXT DEFAULT '11:00 PM',
            is_active INTEGER DEFAULT 1,
            accepts_delivery INTEGER DEFAULT 1,
            accepts_pickup INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,

        # 25. Store Inventory (Phase 4 Multi-Store Inventory & Pricing)
        """
        CREATE TABLE IF NOT EXISTS store_inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            selling_price REAL NOT NULL CHECK (selling_price >= 0),
            original_price REAL CHECK (original_price >= selling_price OR original_price IS NULL),
            stock_quantity INTEGER NOT NULL DEFAULT 0 CHECK (stock_quantity >= 0),
            reserved_quantity INTEGER DEFAULT 0 CHECK (reserved_quantity >= 0),
            low_stock_threshold INTEGER DEFAULT 5 CHECK (low_stock_threshold >= 0),
            is_available INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (store_id, product_id)
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
    "CREATE INDEX IF NOT EXISTS idx_reviews_customer ON product_reviews(customer_id);",

    # Addresses (Phase 3)
    "CREATE INDEX IF NOT EXISTS idx_addresses_customer ON addresses(customer_id);",
    "CREATE INDEX IF NOT EXISTS idx_addresses_default ON addresses(customer_id, is_default);",

    # Stores & Multi-Store Inventory (Phase 4)
    "CREATE INDEX IF NOT EXISTS idx_stores_city_area ON stores(city, area);",
    "CREATE INDEX IF NOT EXISTS idx_stores_slug ON stores(store_slug);",
    "CREATE INDEX IF NOT EXISTS idx_stores_active ON stores(is_active);",
    "CREATE INDEX IF NOT EXISTS idx_store_inventory_store ON store_inventory(store_id);",
    "CREATE INDEX IF NOT EXISTS idx_store_inventory_product ON store_inventory(product_id);",
    "CREATE INDEX IF NOT EXISTS idx_store_inventory_avail ON store_inventory(store_id, is_available);"
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

SAMPLE_ADDRESSES = [
    {
        "customer_id": 1,
        "address_type": "HOME",
        "full_name": "Priya Sharma",
        "phone": "+91 98201 12345",
        "address_line1": "Flat 402, Sea Green Apts",
        "address_line2": "Worli Sea Face",
        "landmark": "Near Coast Guard Station",
        "city": "Mumbai",
        "state": "Maharashtra",
        "pincode": "400030",
        "latitude": 19.0178,
        "longitude": 72.8178,
        "is_default": True
    },
    {
        "customer_id": 1,
        "address_type": "WORK",
        "full_name": "Priya Sharma",
        "phone": "+91 98201 12345",
        "address_line1": "Bharat Retail Corp HQ, Level 7",
        "address_line2": "Linking Road, Bandra West",
        "landmark": "Opposite National College",
        "city": "Mumbai",
        "state": "Maharashtra",
        "pincode": "400050",
        "latitude": 19.0596,
        "longitude": 72.8295,
        "is_default": False
    },
    {
        "customer_id": 2,
        "address_type": "HOME",
        "full_name": "Arjun Patel",
        "phone": "+91 98450 67890",
        "address_line1": "Villa 18, Prestige Oasis",
        "address_line2": "Doddaballapur Road",
        "landmark": "Near Angsana Resort",
        "city": "Bengaluru",
        "state": "Karnataka",
        "pincode": "560064",
        "latitude": 12.9784,
        "longitude": 77.6408,
        "is_default": True
    },
    {
        "customer_id": 3,
        "address_type": "HOME",
        "full_name": "Simran Kaur",
        "phone": "+91 98110 54321",
        "address_line1": "C-4/12, Safdarjung Development Area",
        "address_line2": "Opposite IIT Main Gate",
        "landmark": "Near SDA Market",
        "city": "Delhi NCR",
        "state": "Delhi",
        "pincode": "110016",
        "latitude": 28.5494,
        "longitude": 77.2001,
        "is_default": True
    }
]

# -----------------------------------------------------------------------------
# Phase 4: Sample Physical Stores & Store-Specific Inventory
# -----------------------------------------------------------------------------

SAMPLE_STORES = [
    {
        "id": 1,
        "store_name": "BharatStore Bengaluru Tech Store",
        "store_slug": "bharatstore-bengaluru-tech-store",
        "store_description": "Flagship quick-commerce retail outlet in Indiranagar, stocking daily fresh produce, dairy, bakery, and FMCG essentials.",
        "store_logo": "https://images.unsplash.com/photo-1578916171728-46686eac8d58?w=200&auto=format&fit=crop&q=80",
        "store_banner": "https://images.unsplash.com/photo-1542838132-92c53300491e?w=800&auto=format&fit=crop&q=80",
        "owner_name": "Ramesh Gowda",
        "contact_phone": "+91 98450 12345",
        "email": "blr.tech@bharatstore.in",
        "full_address": "100 Feet Road, Indiranagar, Bengaluru 560038",
        "city": "Bengaluru",
        "area": "Indiranagar",
        "pincode": "560038",
        "latitude": 12.9784,
        "longitude": 77.6408,
        "opening_time": "06:30 AM",
        "closing_time": "11:30 PM",
        "is_active": True,
        "accepts_delivery": True,
        "accepts_pickup": True
    },
    {
        "id": 2,
        "store_name": "Fresh Mart Bengaluru",
        "store_slug": "fresh-mart-bengaluru",
        "store_description": "Neighborhood daily grocery store with fresh vegetables, dairy, pulses, and spices delivered in 15 minutes.",
        "store_logo": "https://images.unsplash.com/photo-1534723452862-4c874018d66d?w=200&auto=format&fit=crop&q=80",
        "store_banner": "https://images.unsplash.com/photo-1488459716781-31db52582fe9?w=800&auto=format&fit=crop&q=80",
        "owner_name": "Suresh Kumar",
        "contact_phone": "+91 98450 54321",
        "email": "freshmart.blr@gmail.com",
        "full_address": "80 Feet Road, 4th Block, Koramangala, Bengaluru 560034",
        "city": "Bengaluru",
        "area": "Koramangala",
        "pincode": "560034",
        "latitude": 12.9352,
        "longitude": 77.6245,
        "opening_time": "07:00 AM",
        "closing_time": "11:00 PM",
        "is_active": True,
        "accepts_delivery": True,
        "accepts_pickup": True
    },
    {
        "id": 3,
        "store_name": "BharatStore Mumbai Bandra",
        "store_slug": "bharatstore-mumbai-bandra",
        "store_description": "Premier West Mumbai retail storefront serving Bandra, Khar, and Santacruz with express delivery and curbside pickup.",
        "store_logo": "https://images.unsplash.com/photo-1604719312566-8912e9227c6a?w=200&auto=format&fit=crop&q=80",
        "store_banner": "https://images.unsplash.com/photo-1578916171728-46686eac8d58?w=800&auto=format&fit=crop&q=80",
        "owner_name": "Priya Sharma",
        "contact_phone": "+91 98201 23456",
        "email": "mumbai.bandra@bharatstore.in",
        "full_address": "Linking Road, Bandra West, Mumbai 400050",
        "city": "Mumbai",
        "area": "Bandra West",
        "pincode": "400050",
        "latitude": 19.0596,
        "longitude": 72.8295,
        "opening_time": "07:00 AM",
        "closing_time": "11:00 PM",
        "is_active": True,
        "accepts_delivery": True,
        "accepts_pickup": True
    },
    {
        "id": 4,
        "store_name": "QuickMart Mumbai",
        "store_slug": "quickmart-mumbai",
        "store_description": "Andheri West local partner grocery store stocking packaged foods, edible oils, dairy, and farm-fresh staples.",
        "store_logo": "https://images.unsplash.com/photo-1583258292688-d0213dc5a3a8?w=200&auto=format&fit=crop&q=80",
        "store_banner": "https://images.unsplash.com/photo-1542838132-92c53300491e?w=800&auto=format&fit=crop&q=80",
        "owner_name": "Vikram Mehta",
        "contact_phone": "+91 98201 65432",
        "email": "quickmart.mumbai@gmail.com",
        "full_address": "Veera Desai Road, Andheri West, Mumbai 400053",
        "city": "Mumbai",
        "area": "Andheri West",
        "pincode": "400053",
        "latitude": 19.1363,
        "longitude": 72.8277,
        "opening_time": "06:00 AM",
        "closing_time": "11:59 PM",
        "is_active": True,
        "accepts_delivery": True,
        "accepts_pickup": False
    }
]

EXTRA_GROCERY_PRODUCTS = [
    {"id": 61, "sku": "BK-GRO-MLK-01", "title": "Amul Taaza Homogenised Toned Milk 1L", "brand": "Amul", "category": "Daily Essentials & Groceries", "price": 60.00, "original_price": 64.00, "stock": 100, "rating": 4.8, "rating_count": 520, "description": "Long life toned milk, nutritious and ready to drink with zero preservatives.", "image_url": "https://images.unsplash.com/photo-1550583724-b2692b85b150?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 62, "sku": "BK-GRO-CRD-01", "title": "Mother Dairy Classic Dahi / Curd 500g Pouch", "brand": "Mother Dairy", "category": "Daily Essentials & Groceries", "price": 35.00, "original_price": 38.00, "stock": 50, "rating": 4.7, "rating_count": 310, "description": "Thick, creamy and delicious curd made from pasteurised milk.", "image_url": "https://images.unsplash.com/photo-1571212515416-fef01fc43637?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 63, "sku": "BK-GRO-PNR-01", "title": "Amul Fresh Malai Paneer 200g Pack", "brand": "Amul", "category": "Daily Essentials & Groceries", "price": 95.00, "original_price": 105.00, "stock": 40, "rating": 4.8, "rating_count": 410, "description": "Soft and succulent malai paneer packed with protein and calcium.", "image_url": "https://images.unsplash.com/photo-1631452180519-c014fe946bc7?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 64, "sku": "BK-GRO-BTR-01", "title": "Amul Pasteurised Salted Butter 100g", "brand": "Amul", "category": "Daily Essentials & Groceries", "price": 58.00, "original_price": 60.00, "stock": 60, "rating": 4.9, "rating_count": 890, "description": "Utterly butterly delicious classic salted table butter.", "image_url": "https://images.unsplash.com/photo-1589985270826-4b7bb135bc9d?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 65, "sku": "BK-GRO-RIC-01", "title": "India Gate Feast Rozzana Basmati Rice 1kg", "brand": "India Gate", "category": "Daily Essentials & Groceries", "price": 110.00, "original_price": 125.00, "stock": 45, "rating": 4.6, "rating_count": 640, "description": "Aged aromatic basmati rice with slender grains, ideal for everyday dining.", "image_url": "https://images.unsplash.com/photo-1586201375761-83865001e31c?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 66, "sku": "BK-GRO-RIC-02", "title": "Fortune Everyday Sona Masoori Rice 5kg Bag", "brand": "Fortune", "category": "Daily Essentials & Groceries", "price": 340.00, "original_price": 380.00, "stock": 35, "rating": 4.5, "rating_count": 280, "description": "Lightweight, aromatic medium-grain rice perfect for daily curries and dal.", "image_url": "https://images.unsplash.com/photo-1536304993881-ff6e9eefa2a6?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 67, "sku": "BK-GRO-BSN-01", "title": "Tata Sampann 100% Chana Dal Besan 1kg", "brand": "Tata Sampann", "category": "Daily Essentials & Groceries", "price": 115.00, "original_price": 130.00, "stock": 30, "rating": 4.7, "rating_count": 220, "description": "Made from unpolished chickpeas, naturally rich in dietary protein and fiber.", "image_url": "https://images.unsplash.com/photo-1627485937980-221c88ac04f9?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 68, "sku": "BK-GRO-DAL-01", "title": "Tata Sampann Unpolished Toor / Arhar Dal 1kg", "brand": "Tata Sampann", "category": "Daily Essentials & Groceries", "price": 175.00, "original_price": 195.00, "stock": 50, "rating": 4.7, "rating_count": 510, "description": "Unpolished toor dal retaining natural dietary nutrients and taste.", "image_url": "https://images.unsplash.com/photo-1585994192701-f1a505c817ea?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 69, "sku": "BK-GRO-DAL-02", "title": "Organic Tattva Yellow Moong Dal Split 1kg", "brand": "Organic Tattva", "category": "Daily Essentials & Groceries", "price": 165.00, "original_price": 185.00, "stock": 40, "rating": 4.6, "rating_count": 340, "description": "Certified organic yellow moong dal, easy to digest and rich in vitamins.", "image_url": "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 70, "sku": "BK-GRO-DAL-03", "title": "Tata Sampann Unpolished Chana Dal 1kg", "brand": "Tata Sampann", "category": "Daily Essentials & Groceries", "price": 120.00, "original_price": 135.00, "stock": 35, "rating": 4.5, "rating_count": 190, "description": "Unpolished, healthy chana dal sourced directly from select Indian farms.", "image_url": "https://images.unsplash.com/photo-1512621776951-a57141f2eefd?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 71, "sku": "BK-GRO-SGR-01", "title": "Madhur Pure & Hygienic Refined Sugar 1kg", "brand": "Madhur", "category": "Daily Essentials & Groceries", "price": 54.00, "original_price": 60.00, "stock": 80, "rating": 4.8, "rating_count": 720, "description": "Sulphur-free sparkling white refined sugar untouched by hand.", "image_url": "https://images.unsplash.com/photo-1581441363689-1f3c3c414635?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 72, "sku": "BK-GRO-POT-01", "title": "Fresh Farm Select New Crop Potato 1kg", "brand": "Fresh Farm", "category": "Daily Essentials & Groceries", "price": 38.00, "original_price": 45.00, "stock": 120, "rating": 4.4, "rating_count": 430, "description": "Cleaned, mud-free fresh farm potatoes ideal for boiling and curries.", "image_url": "https://images.unsplash.com/photo-1518977676601-b53f82aba655?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 73, "sku": "BK-GRO-ONN-01", "title": "Fresh Farm Nasik Red Onion 1kg", "brand": "Fresh Farm", "category": "Daily Essentials & Groceries", "price": 42.00, "original_price": 50.00, "stock": 100, "rating": 4.5, "rating_count": 610, "description": "Crisp and pungent premium Nasik red onions.", "image_url": "https://images.unsplash.com/photo-1618512496248-a07fe83aa8cb?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 74, "sku": "BK-GRO-TOM-01", "title": "Fresh Farm Ripe Hybrid Tomato 1kg", "brand": "Fresh Farm", "category": "Daily Essentials & Groceries", "price": 35.00, "original_price": 42.00, "stock": 90, "rating": 4.6, "rating_count": 520, "description": "Plump and juicy vine-ripened red hybrid tomatoes.", "image_url": "https://images.unsplash.com/photo-1592924357228-91a4daadcfea?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 75, "sku": "BK-GRO-BAN-01", "title": "Fresh Robusta Bananas 1 Dozen (approx 1.2kg)", "brand": "Fresh Farm", "category": "Daily Essentials & Groceries", "price": 65.00, "original_price": 75.00, "stock": 70, "rating": 4.7, "rating_count": 390, "description": "Sweet, naturally ripened golden yellow Robusta bananas.", "image_url": "https://images.unsplash.com/photo-1571771894821-ce9b6c11b08e?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]}
]

SAMPLE_STORE_INVENTORY = [
    # Store 1: BharatStore Bengaluru Tech Store
    {"store_id": 1, "product_id": 61, "selling_price": 60.00, "original_price": 64.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 62, "selling_price": 35.00, "original_price": 38.00, "stock_quantity": 10, "low_stock_threshold": 3, "is_available": True},
    {"store_id": 1, "product_id": 63, "selling_price": 95.00, "original_price": 105.00, "stock_quantity": 15, "low_stock_threshold": 4, "is_available": True},
    {"store_id": 1, "product_id": 64, "selling_price": 58.00, "original_price": 60.00, "stock_quantity": 25, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 65, "selling_price": 110.00, "original_price": 125.00, "stock_quantity": 15, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 66, "selling_price": 330.00, "original_price": 380.00, "stock_quantity": 8, "low_stock_threshold": 3, "is_available": True},
    {"store_id": 1, "product_id": 18, "selling_price": 260.00, "original_price": 315.00, "stock_quantity": 5, "low_stock_threshold": 2, "is_available": True},
    {"store_id": 1, "product_id": 17, "selling_price": 740.00, "original_price": 799.00, "stock_quantity": 12, "low_stock_threshold": 4, "is_available": True},
    {"store_id": 1, "product_id": 21, "selling_price": 380.00, "original_price": 389.00, "stock_quantity": 10, "low_stock_threshold": 3, "is_available": True},
    {"store_id": 1, "product_id": 68, "selling_price": 170.00, "original_price": 195.00, "stock_quantity": 18, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 69, "selling_price": 160.00, "original_price": 185.00, "stock_quantity": 15, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 70, "selling_price": 115.00, "original_price": 135.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 67, "selling_price": 110.00, "original_price": 130.00, "stock_quantity": 14, "low_stock_threshold": 4, "is_available": True},
    {"store_id": 1, "product_id": 71, "selling_price": 52.00, "original_price": 60.00, "stock_quantity": 30, "low_stock_threshold": 8, "is_available": True},
    {"store_id": 1, "product_id": 52, "selling_price": 145.00, "original_price": 149.00, "stock_quantity": 40, "low_stock_threshold": 10, "is_available": True},
    {"store_id": 1, "product_id": 72, "selling_price": 36.00, "original_price": 45.00, "stock_quantity": 50, "low_stock_threshold": 10, "is_available": True},
    {"store_id": 1, "product_id": 73, "selling_price": 40.00, "original_price": 50.00, "stock_quantity": 40, "low_stock_threshold": 10, "is_available": True},
    {"store_id": 1, "product_id": 74, "selling_price": 32.00, "original_price": 42.00, "stock_quantity": 35, "low_stock_threshold": 8, "is_available": True},
    {"store_id": 1, "product_id": 75, "selling_price": 60.00, "original_price": 75.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},

    # Store 2: Fresh Mart Bengaluru (Notice: Curd 62 & Salt 52 are Out of Stock; Prices differ from Store 1!)
    {"store_id": 2, "product_id": 61, "selling_price": 62.00, "original_price": 64.00, "stock_quantity": 8, "low_stock_threshold": 3, "is_available": True},
    {"store_id": 2, "product_id": 62, "selling_price": 38.00, "original_price": 38.00, "stock_quantity": 0, "low_stock_threshold": 3, "is_available": False},
    {"store_id": 2, "product_id": 63, "selling_price": 98.00, "original_price": 105.00, "stock_quantity": 6, "low_stock_threshold": 2, "is_available": True},
    {"store_id": 2, "product_id": 64, "selling_price": 59.00, "original_price": 60.00, "stock_quantity": 10, "low_stock_threshold": 3, "is_available": True},
    {"store_id": 2, "product_id": 65, "selling_price": 115.00, "original_price": 125.00, "stock_quantity": 25, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 66, "selling_price": 345.00, "original_price": 380.00, "stock_quantity": 14, "low_stock_threshold": 4, "is_available": True},
    {"store_id": 2, "product_id": 18, "selling_price": 250.00, "original_price": 315.00, "stock_quantity": 12, "low_stock_threshold": 3, "is_available": True},
    {"store_id": 2, "product_id": 17, "selling_price": 755.00, "original_price": 799.00, "stock_quantity": 6, "low_stock_threshold": 2, "is_available": True},
    {"store_id": 2, "product_id": 68, "selling_price": 175.00, "original_price": 195.00, "stock_quantity": 10, "low_stock_threshold": 3, "is_available": True},
    {"store_id": 2, "product_id": 69, "selling_price": 165.00, "original_price": 185.00, "stock_quantity": 12, "low_stock_threshold": 3, "is_available": True},
    {"store_id": 2, "product_id": 71, "selling_price": 55.00, "original_price": 60.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 52, "selling_price": 150.00, "original_price": 155.00, "stock_quantity": 0, "low_stock_threshold": 5, "is_available": False},
    {"store_id": 2, "product_id": 72, "selling_price": 38.00, "original_price": 45.00, "stock_quantity": 30, "low_stock_threshold": 8, "is_available": True},
    {"store_id": 2, "product_id": 73, "selling_price": 44.00, "original_price": 50.00, "stock_quantity": 25, "low_stock_threshold": 8, "is_available": True},
    {"store_id": 2, "product_id": 74, "selling_price": 36.00, "original_price": 42.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 75, "selling_price": 65.00, "original_price": 75.00, "stock_quantity": 15, "low_stock_threshold": 4, "is_available": True},

    # Store 3: BharatStore Mumbai Bandra
    {"store_id": 3, "product_id": 61, "selling_price": 61.00, "original_price": 64.00, "stock_quantity": 25, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 62, "selling_price": 36.00, "original_price": 38.00, "stock_quantity": 18, "low_stock_threshold": 4, "is_available": True},
    {"store_id": 3, "product_id": 63, "selling_price": 96.00, "original_price": 105.00, "stock_quantity": 20, "low_stock_threshold": 4, "is_available": True},
    {"store_id": 3, "product_id": 64, "selling_price": 58.00, "original_price": 60.00, "stock_quantity": 30, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 65, "selling_price": 112.00, "original_price": 125.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 18, "selling_price": 258.00, "original_price": 315.00, "stock_quantity": 15, "low_stock_threshold": 3, "is_available": True},
    {"store_id": 3, "product_id": 17, "selling_price": 745.00, "original_price": 799.00, "stock_quantity": 10, "low_stock_threshold": 3, "is_available": True},
    {"store_id": 3, "product_id": 21, "selling_price": 385.00, "original_price": 389.00, "stock_quantity": 8, "low_stock_threshold": 2, "is_available": True},
    {"store_id": 3, "product_id": 71, "selling_price": 53.00, "original_price": 60.00, "stock_quantity": 25, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 52, "selling_price": 148.00, "original_price": 149.00, "stock_quantity": 25, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 72, "selling_price": 35.00, "original_price": 45.00, "stock_quantity": 45, "low_stock_threshold": 8, "is_available": True},
    {"store_id": 3, "product_id": 73, "selling_price": 39.00, "original_price": 50.00, "stock_quantity": 50, "low_stock_threshold": 10, "is_available": True},
    {"store_id": 3, "product_id": 74, "selling_price": 34.00, "original_price": 42.00, "stock_quantity": 40, "low_stock_threshold": 8, "is_available": True},
    {"store_id": 3, "product_id": 75, "selling_price": 62.00, "original_price": 75.00, "stock_quantity": 30, "low_stock_threshold": 5, "is_available": True},

    # Store 4: QuickMart Mumbai (Notice: Paneer 63 is Out of Stock!)
    {"store_id": 4, "product_id": 61, "selling_price": 63.00, "original_price": 64.00, "stock_quantity": 12, "low_stock_threshold": 3, "is_available": True},
    {"store_id": 4, "product_id": 62, "selling_price": 37.00, "original_price": 38.00, "stock_quantity": 14, "low_stock_threshold": 3, "is_available": True},
    {"store_id": 4, "product_id": 63, "selling_price": 99.00, "original_price": 105.00, "stock_quantity": 0, "low_stock_threshold": 3, "is_available": False},
    {"store_id": 4, "product_id": 64, "selling_price": 60.00, "original_price": 60.00, "stock_quantity": 8, "low_stock_threshold": 2, "is_available": True},
    {"store_id": 4, "product_id": 65, "selling_price": 118.00, "original_price": 125.00, "stock_quantity": 10, "low_stock_threshold": 3, "is_available": True},
    {"store_id": 4, "product_id": 18, "selling_price": 262.00, "original_price": 315.00, "stock_quantity": 8, "low_stock_threshold": 2, "is_available": True},
    {"store_id": 4, "product_id": 17, "selling_price": 760.00, "original_price": 799.00, "stock_quantity": 5, "low_stock_threshold": 2, "is_available": True},
    {"store_id": 4, "product_id": 71, "selling_price": 56.00, "original_price": 60.00, "stock_quantity": 15, "low_stock_threshold": 3, "is_available": True},
    {"store_id": 4, "product_id": 72, "selling_price": 40.00, "original_price": 45.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 73, "selling_price": 45.00, "original_price": 50.00, "stock_quantity": 15, "low_stock_threshold": 4, "is_available": True},
    {"store_id": 4, "product_id": 74, "selling_price": 38.00, "original_price": 42.00, "stock_quantity": 10, "low_stock_threshold": 3, "is_available": True}
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
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS category_id INT REFERENCES categories(id) ON DELETE SET NULL;",
            "ALTER TABLE addresses ADD COLUMN IF NOT EXISTS latitude NUMERIC(10, 6);",
            "ALTER TABLE addresses ADD COLUMN IF NOT EXISTS longitude NUMERIC(10, 6);"
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
            ("products", "category_id", "INTEGER REFERENCES categories(id)"),
            ("addresses", "latitude", "REAL"),
            ("addresses", "longitude", "REAL")
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

    # Step 7: Seed sample customer addresses if empty
    cur.execute("SELECT COUNT(*) FROM addresses;")
    addr_count = cur.fetchone()[0]
    if addr_count == 0:
        for a in SAMPLE_ADDRESSES:
            if is_postgres:
                cur.execute("""
                INSERT INTO addresses (customer_id, address_type, full_name, phone, address_line1, address_line2, landmark, city, state, pincode, latitude, longitude, is_default)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                """, (a["customer_id"], a["address_type"], a["full_name"], a["phone"], a["address_line1"], a["address_line2"], a["landmark"], a["city"], a["state"], a["pincode"], a["latitude"], a["longitude"], a["is_default"]))
            else:
                cur.execute("""
                INSERT INTO addresses (customer_id, address_type, full_name, phone, address_line1, address_line2, landmark, city, state, pincode, latitude, longitude, is_default)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (a["customer_id"], a["address_type"], a["full_name"], a["phone"], a["address_line1"], a["address_line2"], a["landmark"], a["city"], a["state"], a["pincode"], a["latitude"], a["longitude"], 1 if a["is_default"] else 0))

    # Step 8: Ensure extra grocery products exist in products & global inventory (Phase 4)
    for p in EXTRA_GROCERY_PRODUCTS:
        if is_postgres:
            cur.execute("""
            INSERT INTO products (id, sku, title, brand, category, price, original_price, image_url, rating, rating_count, description, cities_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING;
            """, (p["id"], p["sku"], p["title"], p["brand"], p["category"], p["price"], p["original_price"], p["image_url"], p["rating"], p["rating_count"], p["description"], json.dumps(p["cities"])))
            cur.execute("""
            INSERT INTO inventory (product_id, stock_quantity, reserved_quantity)
            VALUES (%s, %s, 0)
            ON CONFLICT (product_id) DO NOTHING;
            """, (p["id"], p["stock"]))
        else:
            cur.execute("""
            INSERT OR IGNORE INTO products (id, sku, title, brand, category, price, original_price, image_url, rating, rating_count, description, cities_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (p["id"], p["sku"], p["title"], p["brand"], p["category"], p["price"], p["original_price"], p["image_url"], p["rating"], p["rating_count"], p["description"], json.dumps(p["cities"])))
            cur.execute("""
            INSERT OR IGNORE INTO inventory (product_id, stock_quantity, reserved_quantity)
            VALUES (?, ?, 0);
            """, (p["id"], p["stock"]))

    # Step 9: Seed physical stores if empty (Phase 4)
    cur.execute("SELECT COUNT(*) FROM stores;")
    store_count = cur.fetchone()[0]
    if store_count == 0:
        for s in SAMPLE_STORES:
            if is_postgres:
                cur.execute("""
                INSERT INTO stores (id, store_name, store_slug, store_description, store_logo, store_banner, owner_name, contact_phone, email, full_address, city, area, pincode, latitude, longitude, opening_time, closing_time, is_active, accepts_delivery, accepts_pickup)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING;
                """, (s["id"], s["store_name"], s["store_slug"], s["store_description"], s["store_logo"], s["store_banner"], s["owner_name"], s["contact_phone"], s["email"], s["full_address"], s["city"], s["area"], s["pincode"], s["latitude"], s["longitude"], s["opening_time"], s["closing_time"], s["is_active"], s["accepts_delivery"], s["accepts_pickup"]))
            else:
                cur.execute("""
                INSERT OR IGNORE INTO stores (id, store_name, store_slug, store_description, store_logo, store_banner, owner_name, contact_phone, email, full_address, city, area, pincode, latitude, longitude, opening_time, closing_time, is_active, accepts_delivery, accepts_pickup)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (s["id"], s["store_name"], s["store_slug"], s["store_description"], s["store_logo"], s["store_banner"], s["owner_name"], s["contact_phone"], s["email"], s["full_address"], s["city"], s["area"], s["pincode"], s["latitude"], s["longitude"], s["opening_time"], s["closing_time"], 1 if s["is_active"] else 0, 1 if s["accepts_delivery"] else 0, 1 if s["accepts_pickup"] else 0))

    # Step 10: Seed store inventory if empty (Phase 4)
    cur.execute("SELECT COUNT(*) FROM store_inventory;")
    inv_count = cur.fetchone()[0]
    if inv_count == 0:
        for item in SAMPLE_STORE_INVENTORY:
            if is_postgres:
                cur.execute("""
                INSERT INTO store_inventory (store_id, product_id, selling_price, original_price, stock_quantity, reserved_quantity, low_stock_threshold, is_available)
                VALUES (%s, %s, %s, %s, %s, 0, %s, %s)
                ON CONFLICT (store_id, product_id) DO NOTHING;
                """, (item["store_id"], item["product_id"], item["selling_price"], item.get("original_price"), item["stock_quantity"], item.get("low_stock_threshold", 5), item.get("is_available", True)))
            else:
                cur.execute("""
                INSERT OR IGNORE INTO store_inventory (store_id, product_id, selling_price, original_price, stock_quantity, reserved_quantity, low_stock_threshold, is_available)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?);
                """, (item["store_id"], item["product_id"], item["selling_price"], item.get("original_price"), item["stock_quantity"], item.get("low_stock_threshold", 5), 1 if item.get("is_available", True) else 0))

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

# -----------------------------------------------------------------------------
# Phase 4: Atomic Physical Store Stock Engine (Multi-Store Overselling Protection)
# -----------------------------------------------------------------------------

def atomic_reserve_store_stock(cur, is_postgres: bool, store_id: int, product_id: int, quantity: int, reference_type: str = "CART", reference_id: str = "0") -> Dict[str, Any]:
    """
    Atomically reserves store-specific inventory for an in-flight cart or checkout.
    Guarantees available_stock = (stock_quantity - reserved_quantity) >= requested quantity.
    Prevents negative stock and concurrent overselling at physical retail stores.
    """
    if quantity <= 0:
        raise ValueError(f"Reservation quantity must be strictly positive, got {quantity}")

    if is_postgres:
        cur.execute("""
        SELECT stock_quantity, reserved_quantity, low_stock_threshold, is_available
        FROM store_inventory
        WHERE store_id = %s AND product_id = %s
        FOR UPDATE;
        """, (store_id, product_id))
        row = cur.fetchone()
    else:
        cur.execute("""
        SELECT stock_quantity, reserved_quantity, low_stock_threshold, is_available
        FROM store_inventory
        WHERE store_id = ? AND product_id = ?;
        """, (store_id, product_id))
        row = cur.fetchone()

    if not row:
        raise ValueError(f"Product #{product_id} is not stocked at Store #{store_id}.")

    stock = row["stock_quantity"] if isinstance(row, dict) or hasattr(row, "keys") else row[0]
    reserved = row["reserved_quantity"] if isinstance(row, dict) or hasattr(row, "keys") else row[1]
    available = stock - reserved

    if available < quantity:
        raise ValueError(f"Insufficient stock at Store #{store_id} for Product #{product_id}. Available: {available}, Requested: {quantity}.")

    new_reserved = reserved + quantity

    if is_postgres:
        cur.execute("""
        UPDATE store_inventory
        SET reserved_quantity = %s, updated_at = CURRENT_TIMESTAMP
        WHERE store_id = %s AND product_id = %s;
        """, (new_reserved, store_id, product_id))
    else:
        cur.execute("""
        UPDATE store_inventory
        SET reserved_quantity = ?, updated_at = CURRENT_TIMESTAMP
        WHERE store_id = ? AND product_id = ?;
        """, (new_reserved, store_id, product_id))

    return {
        "store_id": store_id,
        "product_id": product_id,
        "quantity_reserved": quantity,
        "total_stock": stock,
        "total_reserved": new_reserved,
        "available_stock": stock - new_reserved
    }

def atomic_release_store_stock(cur, is_postgres: bool, store_id: int, product_id: int, quantity: int, reference_type: str = "CART_ABANDON", reference_id: str = "0") -> Dict[str, Any]:
    """
    Atomically releases a previously held store reservation back to store inventory.
    """
    if quantity <= 0:
        raise ValueError(f"Release quantity must be positive, got {quantity}")

    if is_postgres:
        cur.execute("""
        SELECT stock_quantity, reserved_quantity
        FROM store_inventory
        WHERE store_id = %s AND product_id = %s
        FOR UPDATE;
        """, (store_id, product_id))
        row = cur.fetchone()
    else:
        cur.execute("""
        SELECT stock_quantity, reserved_quantity
        FROM store_inventory
        WHERE store_id = ? AND product_id = ?;
        """, (store_id, product_id))
        row = cur.fetchone()

    if not row:
        raise ValueError(f"Product #{product_id} is not stocked at Store #{store_id}.")

    stock = row["stock_quantity"] if isinstance(row, dict) or hasattr(row, "keys") else row[0]
    reserved = row["reserved_quantity"] if isinstance(row, dict) or hasattr(row, "keys") else row[1]
    new_reserved = max(0, reserved - quantity)

    if is_postgres:
        cur.execute("""
        UPDATE store_inventory
        SET reserved_quantity = %s, updated_at = CURRENT_TIMESTAMP
        WHERE store_id = %s AND product_id = %s;
        """, (new_reserved, store_id, product_id))
    else:
        cur.execute("""
        UPDATE store_inventory
        SET reserved_quantity = ?, updated_at = CURRENT_TIMESTAMP
        WHERE store_id = ? AND product_id = ?;
        """, (new_reserved, store_id, product_id))

    return {
        "store_id": store_id,
        "product_id": product_id,
        "quantity_released": quantity,
        "total_stock": stock,
        "total_reserved": new_reserved,
        "available_stock": stock - new_reserved
    }

def atomic_commit_store_sale(cur, is_postgres: bool, store_id: int, product_id: int, quantity: int, reference_type: str = "ORDER", reference_id: str = "0") -> Dict[str, Any]:
    """
    Finalizes a physical store purchase: decrements actual stock and releases reserved allocation.
    Updates is_available status when stock hits zero.
    """
    if quantity <= 0:
        raise ValueError(f"Sale quantity must be positive, got {quantity}")

    if is_postgres:
        cur.execute("""
        SELECT stock_quantity, reserved_quantity
        FROM store_inventory
        WHERE store_id = %s AND product_id = %s
        FOR UPDATE;
        """, (store_id, product_id))
        row = cur.fetchone()
    else:
        cur.execute("""
        SELECT stock_quantity, reserved_quantity
        FROM store_inventory
        WHERE store_id = ? AND product_id = ?;
        """, (store_id, product_id))
        row = cur.fetchone()

    if not row:
        raise ValueError(f"Product #{product_id} is not stocked at Store #{store_id}.")

    stock = row["stock_quantity"] if isinstance(row, dict) or hasattr(row, "keys") else row[0]
    reserved = row["reserved_quantity"] if isinstance(row, dict) or hasattr(row, "keys") else row[1]

    if stock < quantity:
        raise ValueError(f"Cannot commit sale for Product #{product_id} at Store #{store_id}: requested {quantity} exceeds physical stock {stock}.")

    new_stock = stock - quantity
    new_reserved = max(0, reserved - quantity)
    is_avail = 1 if new_stock > 0 else 0

    if is_postgres:
        cur.execute("""
        UPDATE store_inventory
        SET stock_quantity = %s, reserved_quantity = %s, is_available = %s, updated_at = CURRENT_TIMESTAMP
        WHERE store_id = %s AND product_id = %s;
        """, (new_stock, new_reserved, bool(is_avail), store_id, product_id))
    else:
        cur.execute("""
        UPDATE store_inventory
        SET stock_quantity = ?, reserved_quantity = ?, is_available = ?, updated_at = CURRENT_TIMESTAMP
        WHERE store_id = ? AND product_id = ?;
        """, (new_stock, new_reserved, is_avail, store_id, product_id))

    return {
        "store_id": store_id,
        "product_id": product_id,
        "quantity_sold": quantity,
        "new_stock": new_stock,
        "new_reserved": new_reserved,
        "available_stock": new_stock - new_reserved,
        "is_available": bool(is_avail)
    }

