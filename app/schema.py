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
            sub_category VARCHAR(100),
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
            session_id VARCHAR(100),
            shopping_mode VARCHAR(50) DEFAULT 'ONLINE' CHECK (shopping_mode IN ('ONLINE', 'RETAIL_NEAR_ME')),
            store_id INT REFERENCES stores(id) ON DELETE CASCADE,
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
            store_id INT REFERENCES stores(id) ON DELETE CASCADE,
            quantity INT NOT NULL CHECK (quantity > 0),
            unit_price NUMERIC(10, 2) NOT NULL,
            fulfillment VARCHAR(20) DEFAULT 'delivery' CHECK (fulfillment IN ('delivery', 'pickup')),
            reserved_until TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
            status VARCHAR(50) DEFAULT 'PENDING_PAYMENT' CHECK (status IN ('PENDING', 'PENDING_PAYMENT', 'PAID', 'CONFIRMED', 'PROCESSING', 'DISPATCHED', 'SHIPPED', 'OUT_FOR_DELIVERY', 'DELIVERED', 'CANCELLED', 'REFUNDED')),
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
        """,

        # 26. Order Status History (Phase 13 Lifecycle Audit Trail)
        """
        CREATE TABLE IF NOT EXISTS order_status_history (
            id SERIAL PRIMARY KEY,
            order_id INT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            from_status VARCHAR(50),
            to_status VARCHAR(50) NOT NULL,
            notes TEXT,
            changed_by VARCHAR(100) DEFAULT 'SYSTEM',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
            sub_category TEXT,
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
            session_id TEXT,
            shopping_mode TEXT DEFAULT 'ONLINE' CHECK (shopping_mode IN ('ONLINE', 'RETAIL_NEAR_ME')),
            store_id INTEGER REFERENCES stores(id) ON DELETE CASCADE,
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
            store_id INTEGER REFERENCES stores(id) ON DELETE CASCADE,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            unit_price REAL NOT NULL,
            fulfillment TEXT DEFAULT 'delivery' CHECK (fulfillment IN ('delivery', 'pickup')),
            reserved_until DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
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
            status TEXT DEFAULT 'PENDING_PAYMENT' CHECK (status IN ('PENDING', 'PENDING_PAYMENT', 'PAID', 'CONFIRMED', 'PROCESSING', 'DISPATCHED', 'SHIPPED', 'OUT_FOR_DELIVERY', 'DELIVERED', 'CANCELLED', 'REFUNDED')),
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
        """,

        # 26. Order Status History (Phase 13 Lifecycle Audit Trail)
        """
        CREATE TABLE IF NOT EXISTS order_status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            from_status TEXT,
            to_status TEXT NOT NULL,
            notes TEXT,
            changed_by TEXT DEFAULT 'SYSTEM',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """
    ]

# -----------------------------------------------------------------------------
# Database Indexes
# -----------------------------------------------------------------------------

INDEXES_DDL = [
    # Orders Lifecycle & Status History
    "CREATE INDEX IF NOT EXISTS idx_order_status_history_order_id ON order_status_history(order_id);",
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
    "CREATE INDEX IF NOT EXISTS idx_carts_mode_status ON carts(shopping_mode, status);",
    "CREATE INDEX IF NOT EXISTS idx_carts_store ON carts(store_id);",
    "CREATE INDEX IF NOT EXISTS idx_cart_items_cart ON cart_items(cart_id);",
    "CREATE INDEX IF NOT EXISTS idx_cart_items_product ON cart_items(product_id);",
    "CREATE INDEX IF NOT EXISTS idx_cart_items_store ON cart_items(store_id);",

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
        "store_name": "Bharat Fresh Mart",
        "store_slug": "bharat-fresh-mart",
        "store_description": "Flagship quick-commerce neighbourhood grocery store in Indiranagar stocking daily farm-fresh milk, organic produce, dairy, bakery, and FMCG essentials.",
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
        "store_name": "Daily Needs Supermarket",
        "store_slug": "daily-needs-supermarket",
        "store_description": "Daily Needs Supermarket (Fresh Mart Bengaluru) – Neighborhood daily grocery store with fresh vegetables, dairy, pulses, and spices delivered in 15 minutes.",
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
        "store_name": "Green Basket Grocery",
        "store_slug": "green-basket-grocery",
        "store_description": "Farm-fresh organic supermarket in HSR Layout known for lowest prices on farm vegetables, fresh paneer, and natural cooking oils.",
        "store_logo": "https://images.unsplash.com/photo-1604719312566-8912e9227c6a?w=200&auto=format&fit=crop&q=80",
        "store_banner": "https://images.unsplash.com/photo-1578916171728-46686eac8d58?w=800&auto=format&fit=crop&q=80",
        "owner_name": "Ananya Rao",
        "contact_phone": "+91 98450 33445",
        "email": "hsr@greenbasket.in",
        "full_address": "27th Main Road, Sector 1, HSR Layout, Bengaluru 560102",
        "city": "Bengaluru",
        "area": "HSR Layout",
        "pincode": "560102",
        "latitude": 12.9121,
        "longitude": 77.6446,
        "opening_time": "07:00 AM",
        "closing_time": "10:30 PM",
        "is_active": True,
        "accepts_delivery": True,
        "accepts_pickup": True
    },
    {
        "id": 4,
        "store_name": "Sri Lakshmi Stores",
        "store_slug": "sri-lakshmi-stores",
        "store_description": "Trusted heritage provision store in Jayanagar featuring purest cow ghee, whole spices, traditional unpolished dals, and cold-pressed oils.",
        "store_logo": "https://images.unsplash.com/photo-1583258292688-d0213dc5a3a8?w=200&auto=format&fit=crop&q=80",
        "store_banner": "https://images.unsplash.com/photo-1542838132-92c53300491e?w=800&auto=format&fit=crop&q=80",
        "owner_name": "K. Venkatesh",
        "contact_phone": "+91 98450 77889",
        "email": "jayanagar@srilakshmistores.in",
        "full_address": "11th Main Road, 4th Block, Jayanagar, Bengaluru 560011",
        "city": "Bengaluru",
        "area": "Jayanagar",
        "pincode": "560011",
        "latitude": 12.9308,
        "longitude": 77.5838,
        "opening_time": "06:30 AM",
        "closing_time": "10:00 PM",
        "is_active": True,
        "accepts_delivery": True,
        "accepts_pickup": True
    },
    {
        "id": 5,
        "store_name": "Smart Choice Supermarket",
        "store_slug": "smart-choice-supermarket",
        "store_description": "Tech hub mega supermarket in Whitefield offering huge multi-buy discounts, imported dry fruits, and bulk pantry savings.",
        "store_logo": "https://images.unsplash.com/photo-1578916171728-46686eac8d58?w=200&auto=format&fit=crop&q=80",
        "store_banner": "https://images.unsplash.com/photo-1488459716781-31db52582fe9?w=800&auto=format&fit=crop&q=80",
        "owner_name": "Rajeev Nair",
        "contact_phone": "+91 98450 99001",
        "email": "whitefield@smartchoice.in",
        "full_address": "ITPL Main Road, Whitefield, Bengaluru 560066",
        "city": "Bengaluru",
        "area": "Whitefield",
        "pincode": "560066",
        "latitude": 12.9698,
        "longitude": 77.7500,
        "opening_time": "07:00 AM",
        "closing_time": "11:00 PM",
        "is_active": True,
        "accepts_delivery": True,
        "accepts_pickup": True
    },
    {
        "id": 6,
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
        "id": 7,
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
    # 1. Milk & Dairy (Requested Essentials - 13 items)
    {"id": 61, "sku": "BK-GRO-MLK-01", "title": "Amul Taaza Milk – 1 L", "brand": "Amul", "category": "Daily Essentials & Groceries", "sub_category": "Dairy & Breakfast", "price": 60.00, "original_price": 64.00, "stock": 100, "rating": 4.8, "rating_count": 520, "description": "Long life pasteurised toned milk, rich in nutrients and ready to drink with zero preservatives.", "image_url": "https://images.unsplash.com/photo-1550583724-b2692b85b150?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 76, "sku": "BK-GRO-MLK-02", "title": "Amul Gold Milk – 500 ml", "brand": "Amul", "category": "Daily Essentials & Groceries", "sub_category": "Dairy & Breakfast", "price": 33.00, "original_price": 35.00, "stock": 80, "rating": 4.9, "rating_count": 410, "description": "Standardised pasteurised fresh full cream milk with 6.0% fat and 9.0% SNF.", "image_url": "https://images.unsplash.com/photo-1563636619-e9143da7973b?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 77, "sku": "BK-GRO-MLK-03", "title": "Mother Dairy Milk – 1 L", "brand": "Mother Dairy", "category": "Daily Essentials & Groceries", "sub_category": "Dairy & Breakfast", "price": 66.00, "original_price": 68.00, "stock": 90, "rating": 4.7, "rating_count": 380, "description": "Full cream wholesome pasteurised milk, rich in calcium and natural vitamin A.", "image_url": "https://images.unsplash.com/photo-1528750997573-59b89d56f4f7?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 62, "sku": "BK-GRO-CRD-01", "title": "Fresh Curd – 500 g", "brand": "Mother Dairy", "category": "Daily Essentials & Groceries", "sub_category": "Dairy & Breakfast", "price": 35.00, "original_price": 38.00, "stock": 50, "rating": 4.7, "rating_count": 310, "description": "Thick, creamy and delicious dahi made from pasteurised toned milk.", "image_url": "https://images.unsplash.com/photo-1571212515416-fef01fc43637?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 78, "sku": "BK-GRO-CRD-02", "title": "Amul Masti Dahi – 400 g", "brand": "Amul", "category": "Daily Essentials & Groceries", "sub_category": "Dairy & Breakfast", "price": 35.00, "original_price": 38.00, "stock": 60, "rating": 4.8, "rating_count": 490, "description": "Creamy, smooth probiotic curd made under the highest hygienic dairy standards.", "image_url": "https://images.unsplash.com/photo-1488477181946-6428a0291777?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 63, "sku": "BK-GRO-PNR-01", "title": "Paneer – 200 g", "brand": "Amul", "category": "Daily Essentials & Groceries", "sub_category": "Dairy & Breakfast", "price": 95.00, "original_price": 105.00, "stock": 40, "rating": 4.8, "rating_count": 410, "description": "Soft and succulent fresh malai paneer packed with high-grade dairy protein.", "image_url": "https://images.unsplash.com/photo-1631452180519-c014fe946bc7?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 64, "sku": "BK-GRO-BTR-01", "title": "Amul Butter – 100 g", "brand": "Amul", "category": "Daily Essentials & Groceries", "sub_category": "Dairy & Breakfast", "price": 58.00, "original_price": 60.00, "stock": 60, "rating": 4.9, "rating_count": 890, "description": "Utterly butterly delicious classic pasteurised salted table butter.", "image_url": "https://images.unsplash.com/photo-1589985270826-4b7bb135bc9d?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 79, "sku": "BK-GRO-GHE-01", "title": "Amul Pure Ghee – 500 ml", "brand": "Amul", "category": "Daily Essentials & Groceries", "sub_category": "Dairy & Breakfast", "price": 310.00, "original_price": 330.00, "stock": 55, "rating": 4.9, "rating_count": 760, "description": "Pure aromatic cow ghee prepared with traditional methods for cooking and sweets.", "image_url": "https://images.unsplash.com/photo-1628088062854-d1870b4553da?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 80, "sku": "BK-GRO-CHS-01", "title": "Cheese – 200 g", "brand": "Amul", "category": "Daily Essentials & Groceries", "sub_category": "Dairy & Breakfast", "price": 135.00, "original_price": 145.00, "stock": 45, "rating": 4.8, "rating_count": 520, "description": "Classic 100% vegetarian processed cheese block, perfect for grating and melting.", "image_url": "https://images.unsplash.com/photo-1618060932014-4deda4932554?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 83, "sku": "BK-GRO-BRD-01", "title": "Britannia Bread – 400 g", "brand": "Britannia", "category": "Daily Essentials & Groceries", "sub_category": "Dairy & Breakfast", "price": 40.00, "original_price": 45.00, "stock": 50, "rating": 4.6, "rating_count": 310, "description": "Daily fresh, soft sandwich bread baked to golden perfection.", "image_url": "https://images.unsplash.com/photo-1509440159596-0249088772ff?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 84, "sku": "BK-GRO-EGG-01", "title": "Farm Fresh Eggs (6 Pack)", "brand": "Farm Fresh", "category": "Daily Essentials & Groceries", "sub_category": "Dairy & Breakfast", "price": 55.00, "original_price": 65.00, "stock": 60, "rating": 4.8, "rating_count": 420, "description": "High-protein, cleaned and sanitised farm fresh white eggs.", "image_url": "https://images.unsplash.com/photo-1506976785307-8732e854ad03?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 85, "sku": "BK-GRO-BRK-01", "title": "Kellogg's Corn Flakes – 475 g", "brand": "Kellogg's", "category": "Daily Essentials & Groceries", "sub_category": "Dairy & Breakfast", "price": 195.00, "original_price": 220.00, "stock": 40, "rating": 4.7, "rating_count": 310, "description": "Crisp golden flakes made from sun-ripened corn, fortified with 8 essential vitamins.", "image_url": "https://images.unsplash.com/photo-1521483451569-e33803c0330c?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 86, "sku": "BK-GRO-BRK-02", "title": "Quaker Rolled Oats – 1 kg", "brand": "Quaker", "category": "Daily Essentials & Groceries", "sub_category": "Dairy & Breakfast", "price": 190.00, "original_price": 210.00, "stock": 45, "rating": 4.8, "rating_count": 420, "description": "100% whole grain rolled oats rich in soluble beta-glucan fiber for daily heart health.", "image_url": "https://images.unsplash.com/photo-1586444248902-2f64eddc13df?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},

    # 2. Rice & Grains (Requested Essentials - 10 items; Atta 18 synced in DB)
    {"id": 65, "sku": "BK-GRO-RIC-01", "title": "Basmati Rice – 1 kg", "brand": "India Gate", "category": "Daily Essentials & Groceries", "sub_category": "Rice & Grains", "price": 110.00, "original_price": 125.00, "stock": 45, "rating": 4.6, "rating_count": 640, "description": "Aged aromatic basmati rice with slender grains, ideal for everyday dining.", "image_url": "https://images.unsplash.com/photo-1586201375761-83865001e31c?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 66, "sku": "BK-GRO-RIC-02", "title": "Regular Rice – 5 kg", "brand": "Fortune", "category": "Daily Essentials & Groceries", "sub_category": "Rice & Grains", "price": 340.00, "original_price": 380.00, "stock": 35, "rating": 4.5, "rating_count": 280, "description": "Lightweight, aromatic medium-grain rice perfect for daily curries and dal.", "image_url": "https://images.unsplash.com/photo-1536304993881-ff6e9eefa2a6?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 67, "sku": "BK-GRO-BSN-01", "title": "Tata Sampann 100% Chana Dal Besan 1kg", "brand": "Tata Sampann", "category": "Daily Essentials & Groceries", "sub_category": "Rice & Grains", "price": 115.00, "original_price": 130.00, "stock": 30, "rating": 4.7, "rating_count": 220, "description": "Made from unpolished chickpeas, naturally rich in dietary protein and fiber.", "image_url": "https://images.unsplash.com/photo-1627485937980-221c88ac04f9?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 68, "sku": "BK-GRO-DAL-01", "title": "Toor Dal – 1 kg", "brand": "Tata Sampann", "category": "Daily Essentials & Groceries", "sub_category": "Rice & Grains", "price": 175.00, "original_price": 195.00, "stock": 50, "rating": 4.7, "rating_count": 510, "description": "Unpolished toor dal retaining natural dietary nutrients and taste.", "image_url": "https://images.unsplash.com/photo-1585994192701-f1a505c817ea?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 69, "sku": "BK-GRO-DAL-02", "title": "Moong Dal – 1 kg", "brand": "Organic Tattva", "category": "Daily Essentials & Groceries", "sub_category": "Rice & Grains", "price": 165.00, "original_price": 185.00, "stock": 40, "rating": 4.6, "rating_count": 340, "description": "Certified organic yellow moong dal, easy to digest and rich in vitamins.", "image_url": "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 70, "sku": "BK-GRO-DAL-03", "title": "Tata Sampann Unpolished Chana Dal 1kg", "brand": "Tata Sampann", "category": "Daily Essentials & Groceries", "sub_category": "Rice & Grains", "price": 120.00, "original_price": 135.00, "stock": 35, "rating": 4.5, "rating_count": 190, "description": "Unpolished, healthy chana dal sourced directly from select Indian farms.", "image_url": "https://images.unsplash.com/photo-1512621776951-a57141f2eefd?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 87, "sku": "BK-GRO-DAL-04", "title": "Urad Dal (Split) – 1 kg", "brand": "Tata Sampann", "category": "Daily Essentials & Groceries", "sub_category": "Rice & Grains", "price": 160.00, "original_price": 180.00, "stock": 35, "rating": 4.6, "rating_count": 250, "description": "Unpolished split black gram (urad chilka) retaining its wholesome earthy flavour and high protein.", "image_url": "https://images.unsplash.com/photo-1585994192701-f1a505c817ea?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 88, "sku": "BK-GRO-DAL-05", "title": "Rajma Chitra – 1 kg", "brand": "Organic Tattva", "category": "Daily Essentials & Groceries", "sub_category": "Rice & Grains", "price": 180.00, "original_price": 200.00, "stock": 40, "rating": 4.7, "rating_count": 380, "description": "Naturally grown Himalayan Chitra red kidney beans that cook tender and absorb spices richly.", "image_url": "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 89, "sku": "BK-GRO-DAL-06", "title": "Kabuli Chana – 1 kg", "brand": "Organic Tattva", "category": "Daily Essentials & Groceries", "sub_category": "Rice & Grains", "price": 170.00, "original_price": 190.00, "stock": 35, "rating": 4.6, "rating_count": 290, "description": "Large, certified organic white chickpeas perfect for North Indian Chole and hummus.", "image_url": "https://images.unsplash.com/photo-1512621776951-a57141f2eefd?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 90, "sku": "BK-GRO-POH-01", "title": "Poha (Thick Flattened Rice) – 500 g", "brand": "Tata Sampann", "category": "Daily Essentials & Groceries", "sub_category": "Rice & Grains", "price": 55.00, "original_price": 65.00, "stock": 60, "rating": 4.8, "rating_count": 510, "description": "Thick rice flakes made from premium paddy, perfect for breakfast Kanda Poha.", "image_url": "https://images.unsplash.com/photo-1536304993881-ff6e9eefa2a6?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},

    # 3. Cooking Essentials (Requested Essentials - 9 items; Oils 17, 21 & Pink Salt 52 synced in DB)
    {"id": 81, "sku": "BK-GRO-OIL-01", "title": "Sunflower Oil – 1 L", "brand": "Fortune", "category": "Daily Essentials & Groceries", "sub_category": "Cooking Essentials", "price": 145.00, "original_price": 160.00, "stock": 75, "rating": 4.6, "rating_count": 390, "description": "Refined light sunflower cooking oil with Vitamin A & D for daily healthy meals.", "image_url": "https://images.unsplash.com/photo-1474979266404-7eaacbcd87c5?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 71, "sku": "BK-GRO-SGR-01", "title": "Sugar – 1 kg", "brand": "Madhur", "category": "Daily Essentials & Groceries", "sub_category": "Cooking Essentials", "price": 54.00, "original_price": 60.00, "stock": 80, "rating": 4.8, "rating_count": 720, "description": "Sulphur-free sparkling white refined sugar untouched by hand.", "image_url": "https://images.unsplash.com/photo-1581441363689-1f3c3c414635?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 82, "sku": "BK-GRO-SLT-01", "title": "Salt – 1 kg", "brand": "Tata Salt", "category": "Daily Essentials & Groceries", "sub_category": "Cooking Essentials", "price": 28.00, "original_price": 30.00, "stock": 90, "rating": 4.9, "rating_count": 910, "description": "Vacuum evaporated iodised edible table salt - Desh ka namak.", "image_url": "https://images.unsplash.com/photo-1518843875459-f738682238a6?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 91, "sku": "BK-GRO-OIL-02", "title": "Saffola Gold Pro Healthy Lifestyle Oil – 1 L", "brand": "Saffola", "category": "Daily Essentials & Groceries", "sub_category": "Cooking Essentials", "price": 165.00, "original_price": 185.00, "stock": 50, "rating": 4.8, "rating_count": 460, "description": "Multisource edible oil blended with rice bran and sunflower oil with natural Oryzanol.", "image_url": "https://images.unsplash.com/photo-1474979266404-7eaacbcd87c5?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 92, "sku": "BK-GRO-MAS-01", "title": "Everest Turmeric Powder – 200 g", "brand": "Everest", "category": "Daily Essentials & Groceries", "sub_category": "Cooking Essentials", "price": 45.00, "original_price": 52.00, "stock": 70, "rating": 4.7, "rating_count": 680, "description": "Finely ground pure haldi powder with high natural curcumin content for authentic Indian curries.", "image_url": "https://images.unsplash.com/photo-1615485290382-441e4d049cb5?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 93, "sku": "BK-GRO-MAS-02", "title": "Everest Red Chilli Powder – 200 g", "brand": "Everest", "category": "Daily Essentials & Groceries", "sub_category": "Cooking Essentials", "price": 65.00, "original_price": 75.00, "stock": 65, "rating": 4.7, "rating_count": 720, "description": "Pure sun-dried Guntur red chillies ground to rich vibrant red color and pungent taste.", "image_url": "https://images.unsplash.com/photo-1596040033229-a9821ebd058d?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 94, "sku": "BK-GRO-MAS-03", "title": "Catch Coriander Powder – 200 g", "brand": "Catch", "category": "Daily Essentials & Groceries", "sub_category": "Cooking Essentials", "price": 48.00, "original_price": 55.00, "stock": 60, "rating": 4.6, "rating_count": 410, "description": "Cold-ground dhaniya powder retaining essential aromatic oils and refreshing aroma.", "image_url": "https://images.unsplash.com/photo-1509358271058-acd22cc93898?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 95, "sku": "BK-GRO-TEA-01", "title": "Tata Tea Premium – 500 g", "brand": "Tata Tea", "category": "Daily Essentials & Groceries", "sub_category": "Cooking Essentials", "price": 260.00, "original_price": 290.00, "stock": 55, "rating": 4.9, "rating_count": 850, "description": "Desh ki Chai - Unique blend of medium grains and strong leaves for Kadak aroma.", "image_url": "https://images.unsplash.com/photo-1576092768241-dec231879fc3?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 96, "sku": "BK-GRO-COF-01", "title": "Bru Instant Coffee – 100 g", "brand": "Bru", "category": "Daily Essentials & Groceries", "sub_category": "Cooking Essentials", "price": 185.00, "original_price": 205.00, "stock": 45, "rating": 4.8, "rating_count": 620, "description": "Fine blend of 70% coffee and 30% chicory roasted slowly for rich aroma and taste.", "image_url": "https://images.unsplash.com/photo-1514432324607-a09d9b4aefdd?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},

    # 4. Fresh Farm Produce (10 items)
    {"id": 72, "sku": "BK-GRO-POT-01", "title": "Fresh Farm Select New Crop Potato 1kg", "brand": "Fresh Farm", "category": "Daily Essentials & Groceries", "sub_category": "Fresh Produce", "price": 38.00, "original_price": 45.00, "stock": 120, "rating": 4.4, "rating_count": 430, "description": "Cleaned, mud-free fresh farm potatoes ideal for boiling and curries.", "image_url": "https://images.unsplash.com/photo-1518977676601-b53f82aba655?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 73, "sku": "BK-GRO-ONN-01", "title": "Fresh Farm Nasik Red Onion 1kg", "brand": "Fresh Farm", "category": "Daily Essentials & Groceries", "sub_category": "Fresh Produce", "price": 42.00, "original_price": 50.00, "stock": 100, "rating": 4.5, "rating_count": 610, "description": "Crisp and pungent premium Nasik red onions.", "image_url": "https://images.unsplash.com/photo-1618512496248-a07fe83aa8cb?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 74, "sku": "BK-GRO-TOM-01", "title": "Fresh Farm Ripe Hybrid Tomato 1kg", "brand": "Fresh Farm", "category": "Daily Essentials & Groceries", "sub_category": "Fresh Produce", "price": 35.00, "original_price": 42.00, "stock": 90, "rating": 4.6, "rating_count": 520, "description": "Plump and juicy vine-ripened red hybrid tomatoes.", "image_url": "https://images.unsplash.com/photo-1592924357228-91a4daadcfea?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 75, "sku": "BK-GRO-BAN-01", "title": "Fresh Robusta Bananas 1 Dozen (approx 1.2kg)", "brand": "Fresh Farm", "category": "Daily Essentials & Groceries", "sub_category": "Fresh Produce", "price": 65.00, "original_price": 75.00, "stock": 70, "rating": 4.7, "rating_count": 390, "description": "Sweet, naturally ripened golden yellow Robusta bananas.", "image_url": "https://images.unsplash.com/photo-1571771894821-ce9b6c11b08e?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 97, "sku": "BK-GRO-VEG-01", "title": "Fresh Green Coriander Bunch – 100 g", "brand": "Fresh Farm", "category": "Daily Essentials & Groceries", "sub_category": "Fresh Produce", "price": 15.00, "original_price": 20.00, "stock": 80, "rating": 4.5, "rating_count": 310, "description": "Crisp aromatic green coriander leaves harvested daily morning from local farms.", "image_url": "https://images.unsplash.com/photo-1589135233689-d5621a28a38b?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 98, "sku": "BK-GRO-VEG-02", "title": "Fresh Green Chillies – 200 g", "brand": "Fresh Farm", "category": "Daily Essentials & Groceries", "sub_category": "Fresh Produce", "price": 22.00, "original_price": 30.00, "stock": 70, "rating": 4.6, "rating_count": 290, "description": "Spicy, fresh bright green chillies essential for daily tempering and tadka.", "image_url": "https://images.unsplash.com/photo-1525607551316-4a8e16d1f9ba?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 99, "sku": "BK-GRO-VEG-03", "title": "Fresh Ginger (Adrak) – 250 g", "brand": "Fresh Farm", "category": "Daily Essentials & Groceries", "sub_category": "Fresh Produce", "price": 35.00, "original_price": 45.00, "stock": 60, "rating": 4.7, "rating_count": 340, "description": "Unwashed firm ginger rhizomes packed with natural spicy gingerol flavor.", "image_url": "https://images.unsplash.com/photo-1615485500704-8e990f9900f7?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 100, "sku": "BK-GRO-FRU-01", "title": "Fresh Shimla Apples – 1 kg", "brand": "Fresh Farm", "category": "Daily Essentials & Groceries", "sub_category": "Fresh Produce", "price": 180.00, "original_price": 210.00, "stock": 50, "rating": 4.8, "rating_count": 560, "description": "Sweet, crisp red apples directly handpicked from Himachal Pradesh orchards.", "image_url": "https://images.unsplash.com/photo-1560806887-1e4cd0b6cbd6?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 101, "sku": "BK-GRO-FRU-02", "title": "Fresh Nagpur Oranges – 1 kg", "brand": "Fresh Farm", "category": "Daily Essentials & Groceries", "sub_category": "Fresh Produce", "price": 95.00, "original_price": 115.00, "stock": 45, "rating": 4.6, "rating_count": 390, "description": "Juicy sweet-tangy Nagpur mandarin oranges, rich in natural Vitamin C.", "image_url": "https://images.unsplash.com/photo-1547514701-42782101795e?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 102, "sku": "BK-GRO-VEG-04", "title": "Fresh Green Capsicum – 500 g", "brand": "Fresh Farm", "category": "Daily Essentials & Groceries", "sub_category": "Fresh Produce", "price": 40.00, "original_price": 50.00, "stock": 50, "rating": 4.6, "rating_count": 310, "description": "Crunchy thick-walled green bell peppers ideal for stir-fries, pizza and curries.", "image_url": "https://images.unsplash.com/photo-1563565375-f3fdfdbefa83?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},

    # 5. Household Essentials (8 items)
    {"id": 103, "sku": "BK-GRO-HOU-01", "title": "Surf Excel Easy Wash Detergent Powder – 1 kg", "brand": "Surf Excel", "category": "Daily Essentials & Groceries", "sub_category": "Household Essentials", "price": 140.00, "original_price": 155.00, "stock": 60, "rating": 4.8, "rating_count": 780, "description": "Superior stain removal power with quick dissolution in hard or soft water.", "image_url": "https://images.unsplash.com/photo-1585421514738-01798e348b17?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 104, "sku": "BK-GRO-HOU-02", "title": "Vim Dishwash Liquid Gel – 500 ml", "brand": "Vim", "category": "Daily Essentials & Groceries", "sub_category": "Household Essentials", "price": 105.00, "original_price": 120.00, "stock": 70, "rating": 4.8, "rating_count": 890, "description": "Concentrated lemon gel power that removes tough grease from 100 utensils with one spoon.", "image_url": "https://images.unsplash.com/photo-1585421514284-efb74c2b69ba?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 105, "sku": "BK-GRO-HOU-03", "title": "Lizol Disinfectant Floor Cleaner (Citrus) – 1 L", "brand": "Lizol", "category": "Daily Essentials & Groceries", "sub_category": "Household Essentials", "price": 199.00, "original_price": 220.00, "stock": 50, "rating": 4.9, "rating_count": 650, "description": "Kills 99.9% of germs and leaves floors sparkling clean with long-lasting citrus fragrance.", "image_url": "https://images.unsplash.com/photo-1584813470613-5b1c1cad3d69?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 106, "sku": "BK-GRO-HOU-04", "title": "Dettol Original Liquid Handwash Refill – 675 ml", "brand": "Dettol", "category": "Daily Essentials & Groceries", "sub_category": "Household Essentials", "price": 119.00, "original_price": 135.00, "stock": 65, "rating": 4.9, "rating_count": 920, "description": "Trusted 100% germ protection formula enriched with moisturizers to keep hands soft.", "image_url": "https://images.unsplash.com/photo-1584308666744-24d5c474f2ae?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 107, "sku": "BK-GRO-HOU-05", "title": "Harpic Power Plus Toilet Cleaner – 1 L", "brand": "Harpic", "category": "Daily Essentials & Groceries", "sub_category": "Household Essentials", "price": 195.00, "original_price": 215.00, "stock": 55, "rating": 4.8, "rating_count": 710, "description": "Thick blue liquid formula for 10x better limescale removal and deep germ kill.", "image_url": "https://images.unsplash.com/photo-1583947215259-38e31be8751f?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 108, "sku": "BK-GRO-HOU-06", "title": "Colin Glass & Surface Cleaner Spray – 500 ml", "brand": "Colin", "category": "Daily Essentials & Groceries", "sub_category": "Household Essentials", "price": 110.00, "original_price": 125.00, "stock": 45, "rating": 4.7, "rating_count": 480, "description": "Instant streak-free shine on glass, mirrors, tabletops, and vehicle windshields.", "image_url": "https://images.unsplash.com/photo-1585421514284-efb74c2b69ba?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 109, "sku": "BK-GRO-HOU-07", "title": "Goodknight Gold Flash Mosquito Repellent Refill (2 Pack)", "brand": "Goodknight", "category": "Daily Essentials & Groceries", "sub_category": "Household Essentials", "price": 150.00, "original_price": 168.00, "stock": 50, "rating": 4.7, "rating_count": 530, "description": "Advanced flash vapors for powerful protection against mosquitoes and dengue vectors.", "image_url": "https://images.unsplash.com/photo-1583947215259-38e31be8751f?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]},
    {"id": 110, "sku": "BK-GRO-HOU-08", "title": "Scotch-Brite Scrub Sponge (Pack of 3)", "brand": "Scotch-Brite", "category": "Daily Essentials & Groceries", "sub_category": "Household Essentials", "price": 75.00, "original_price": 85.00, "stock": 80, "rating": 4.8, "rating_count": 640, "description": "Dual-action scrub pad and sponge for effortless utensil cleaning without scratches.", "image_url": "https://images.unsplash.com/photo-1585421514738-01798e348b17?w=500&auto=format&fit=crop&q=80", "cities": ["Mumbai", "Bengaluru", "Delhi NCR"]}
]

SAMPLE_STORE_INVENTORY = [
    {"store_id": 1, "product_id": 61, "selling_price": 60.00, "original_price": 64.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 76, "selling_price": 33.00, "original_price": 35.00, "stock_quantity": 15, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 77, "selling_price": 66.00, "original_price": 68.00, "stock_quantity": 18, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 62, "selling_price": 35.00, "original_price": 38.00, "stock_quantity": 10, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 78, "selling_price": 35.00, "original_price": 38.00, "stock_quantity": 14, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 63, "selling_price": 95.00, "original_price": 105.00, "stock_quantity": 15, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 64, "selling_price": 58.00, "original_price": 60.00, "stock_quantity": 25, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 79, "selling_price": 310.00, "original_price": 330.00, "stock_quantity": 12, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 80, "selling_price": 135.00, "original_price": 145.00, "stock_quantity": 10, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 83, "selling_price": 40.00, "original_price": 45.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 84, "selling_price": 55.00, "original_price": 65.00, "stock_quantity": 25, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 85, "selling_price": 195.00, "original_price": 220.00, "stock_quantity": 38, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 86, "selling_price": 190.00, "original_price": 210.00, "stock_quantity": 43, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 65, "selling_price": 110.00, "original_price": 125.00, "stock_quantity": 15, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 66, "selling_price": 330.00, "original_price": 380.00, "stock_quantity": 8, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 67, "selling_price": 110.00, "original_price": 130.00, "stock_quantity": 14, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 68, "selling_price": 170.00, "original_price": 195.00, "stock_quantity": 18, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 69, "selling_price": 160.00, "original_price": 185.00, "stock_quantity": 15, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 70, "selling_price": 115.00, "original_price": 135.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 87, "selling_price": 160.00, "original_price": 180.00, "stock_quantity": 33, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 88, "selling_price": 180.00, "original_price": 200.00, "stock_quantity": 38, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 89, "selling_price": 170.00, "original_price": 190.00, "stock_quantity": 33, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 90, "selling_price": 55.00, "original_price": 65.00, "stock_quantity": 58, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 81, "selling_price": 145.00, "original_price": 160.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 71, "selling_price": 52.00, "original_price": 60.00, "stock_quantity": 30, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 82, "selling_price": 28.00, "original_price": 30.00, "stock_quantity": 40, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 91, "selling_price": 165.00, "original_price": 185.00, "stock_quantity": 48, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 92, "selling_price": 45.00, "original_price": 52.00, "stock_quantity": 68, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 93, "selling_price": 65.00, "original_price": 75.00, "stock_quantity": 63, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 94, "selling_price": 48.00, "original_price": 55.00, "stock_quantity": 58, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 95, "selling_price": 260.00, "original_price": 290.00, "stock_quantity": 53, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 96, "selling_price": 185.00, "original_price": 205.00, "stock_quantity": 43, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 72, "selling_price": 36.00, "original_price": 45.00, "stock_quantity": 50, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 73, "selling_price": 40.00, "original_price": 50.00, "stock_quantity": 40, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 74, "selling_price": 32.00, "original_price": 42.00, "stock_quantity": 35, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 75, "selling_price": 60.00, "original_price": 75.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 97, "selling_price": 15.00, "original_price": 20.00, "stock_quantity": 78, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 98, "selling_price": 22.00, "original_price": 30.00, "stock_quantity": 68, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 99, "selling_price": 35.00, "original_price": 45.00, "stock_quantity": 58, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 100, "selling_price": 180.00, "original_price": 210.00, "stock_quantity": 48, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 101, "selling_price": 95.00, "original_price": 115.00, "stock_quantity": 43, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 102, "selling_price": 40.00, "original_price": 50.00, "stock_quantity": 48, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 103, "selling_price": 140.00, "original_price": 155.00, "stock_quantity": 58, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 104, "selling_price": 105.00, "original_price": 120.00, "stock_quantity": 68, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 105, "selling_price": 199.00, "original_price": 220.00, "stock_quantity": 48, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 106, "selling_price": 119.00, "original_price": 135.00, "stock_quantity": 63, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 107, "selling_price": 195.00, "original_price": 215.00, "stock_quantity": 53, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 108, "selling_price": 110.00, "original_price": 125.00, "stock_quantity": 43, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 109, "selling_price": 150.00, "original_price": 168.00, "stock_quantity": 48, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 110, "selling_price": 75.00, "original_price": 85.00, "stock_quantity": 78, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 18, "selling_price": 260.00, "original_price": 315.00, "stock_quantity": 5, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 17, "selling_price": 740.00, "original_price": 799.00, "stock_quantity": 12, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 21, "selling_price": 380.00, "original_price": 389.00, "stock_quantity": 10, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 1, "product_id": 52, "selling_price": 145.00, "original_price": 149.00, "stock_quantity": 40, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 61, "selling_price": 62.00, "original_price": 64.00, "stock_quantity": 8, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 76, "selling_price": 34.00, "original_price": 35.00, "stock_quantity": 10, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 77, "selling_price": 67.00, "original_price": 68.00, "stock_quantity": 6, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 62, "selling_price": 38.00, "original_price": 38.00, "stock_quantity": 0, "low_stock_threshold": 5, "is_available": False},
    {"store_id": 2, "product_id": 78, "selling_price": 36.00, "original_price": 38.00, "stock_quantity": 8, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 63, "selling_price": 98.00, "original_price": 105.00, "stock_quantity": 6, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 64, "selling_price": 59.00, "original_price": 60.00, "stock_quantity": 10, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 79, "selling_price": 320.00, "original_price": 330.00, "stock_quantity": 0, "low_stock_threshold": 5, "is_available": False},
    {"store_id": 2, "product_id": 80, "selling_price": 138.00, "original_price": 145.00, "stock_quantity": 8, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 83, "selling_price": 42.00, "original_price": 45.00, "stock_quantity": 12, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 84, "selling_price": 58.00, "original_price": 65.00, "stock_quantity": 15, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 85, "selling_price": 196.50, "original_price": 220.00, "stock_quantity": 36, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 86, "selling_price": 191.50, "original_price": 210.00, "stock_quantity": 41, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 65, "selling_price": 108.00, "original_price": 125.00, "stock_quantity": 25, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 66, "selling_price": 345.00, "original_price": 380.00, "stock_quantity": 14, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 67, "selling_price": 116.50, "original_price": 130.00, "stock_quantity": 26, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 68, "selling_price": 175.00, "original_price": 195.00, "stock_quantity": 10, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 69, "selling_price": 165.00, "original_price": 185.00, "stock_quantity": 12, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 70, "selling_price": 121.50, "original_price": 135.00, "stock_quantity": 31, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 87, "selling_price": 161.50, "original_price": 180.00, "stock_quantity": 31, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 88, "selling_price": 181.50, "original_price": 200.00, "stock_quantity": 36, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 89, "selling_price": 171.50, "original_price": 190.00, "stock_quantity": 31, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 90, "selling_price": 56.50, "original_price": 65.00, "stock_quantity": 56, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 81, "selling_price": 148.00, "original_price": 160.00, "stock_quantity": 15, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 71, "selling_price": 55.00, "original_price": 60.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 82, "selling_price": 30.00, "original_price": 30.00, "stock_quantity": 0, "low_stock_threshold": 5, "is_available": False},
    {"store_id": 2, "product_id": 91, "selling_price": 166.50, "original_price": 185.00, "stock_quantity": 46, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 92, "selling_price": 46.50, "original_price": 52.00, "stock_quantity": 66, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 93, "selling_price": 66.50, "original_price": 75.00, "stock_quantity": 61, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 94, "selling_price": 49.50, "original_price": 55.00, "stock_quantity": 56, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 95, "selling_price": 261.50, "original_price": 290.00, "stock_quantity": 51, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 96, "selling_price": 186.50, "original_price": 205.00, "stock_quantity": 41, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 72, "selling_price": 38.00, "original_price": 45.00, "stock_quantity": 30, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 73, "selling_price": 44.00, "original_price": 50.00, "stock_quantity": 25, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 74, "selling_price": 36.00, "original_price": 42.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 75, "selling_price": 65.00, "original_price": 75.00, "stock_quantity": 15, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 97, "selling_price": 16.50, "original_price": 20.00, "stock_quantity": 76, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 98, "selling_price": 23.50, "original_price": 30.00, "stock_quantity": 66, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 99, "selling_price": 36.50, "original_price": 45.00, "stock_quantity": 56, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 100, "selling_price": 181.50, "original_price": 210.00, "stock_quantity": 46, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 101, "selling_price": 96.50, "original_price": 115.00, "stock_quantity": 41, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 102, "selling_price": 41.50, "original_price": 50.00, "stock_quantity": 46, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 103, "selling_price": 141.50, "original_price": 155.00, "stock_quantity": 56, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 104, "selling_price": 106.50, "original_price": 120.00, "stock_quantity": 66, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 105, "selling_price": 200.50, "original_price": 220.00, "stock_quantity": 46, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 106, "selling_price": 120.50, "original_price": 135.00, "stock_quantity": 61, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 107, "selling_price": 196.50, "original_price": 215.00, "stock_quantity": 51, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 108, "selling_price": 111.50, "original_price": 125.00, "stock_quantity": 41, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 109, "selling_price": 151.50, "original_price": 168.00, "stock_quantity": 46, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 110, "selling_price": 76.50, "original_price": 85.00, "stock_quantity": 76, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 18, "selling_price": 250.00, "original_price": 315.00, "stock_quantity": 12, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 17, "selling_price": 755.00, "original_price": 799.00, "stock_quantity": 6, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 21, "selling_price": 381.50, "original_price": 389.00, "stock_quantity": 31, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 2, "product_id": 52, "selling_price": 150.00, "original_price": 155.00, "stock_quantity": 0, "low_stock_threshold": 5, "is_available": False},
    {"store_id": 3, "product_id": 61, "selling_price": 61.00, "original_price": 64.00, "stock_quantity": 25, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 76, "selling_price": 33.00, "original_price": 35.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 77, "selling_price": 66.00, "original_price": 68.00, "stock_quantity": 15, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 62, "selling_price": 34.00, "original_price": 38.00, "stock_quantity": 18, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 78, "selling_price": 34.00, "original_price": 38.00, "stock_quantity": 16, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 63, "selling_price": 92.00, "original_price": 105.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 64, "selling_price": 58.00, "original_price": 60.00, "stock_quantity": 30, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 79, "selling_price": 312.00, "original_price": 330.00, "stock_quantity": 16, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 80, "selling_price": 134.00, "original_price": 145.00, "stock_quantity": 14, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 83, "selling_price": 39.00, "original_price": 45.00, "stock_quantity": 22, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 84, "selling_price": 54.00, "original_price": 65.00, "stock_quantity": 28, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 85, "selling_price": 194.00, "original_price": 220.00, "stock_quantity": 34, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 86, "selling_price": 189.00, "original_price": 210.00, "stock_quantity": 39, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 65, "selling_price": 111.00, "original_price": 125.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 66, "selling_price": 335.00, "original_price": 380.00, "stock_quantity": 10, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 67, "selling_price": 114.00, "original_price": 130.00, "stock_quantity": 24, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 68, "selling_price": 172.00, "original_price": 195.00, "stock_quantity": 16, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 69, "selling_price": 162.00, "original_price": 185.00, "stock_quantity": 14, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 70, "selling_price": 119.00, "original_price": 135.00, "stock_quantity": 29, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 87, "selling_price": 159.00, "original_price": 180.00, "stock_quantity": 29, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 88, "selling_price": 179.00, "original_price": 200.00, "stock_quantity": 34, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 89, "selling_price": 169.00, "original_price": 190.00, "stock_quantity": 29, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 90, "selling_price": 54.00, "original_price": 65.00, "stock_quantity": 54, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 81, "selling_price": 146.00, "original_price": 160.00, "stock_quantity": 22, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 71, "selling_price": 53.00, "original_price": 60.00, "stock_quantity": 25, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 82, "selling_price": 28.00, "original_price": 30.00, "stock_quantity": 35, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 91, "selling_price": 164.00, "original_price": 185.00, "stock_quantity": 44, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 92, "selling_price": 44.00, "original_price": 52.00, "stock_quantity": 64, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 93, "selling_price": 64.00, "original_price": 75.00, "stock_quantity": 59, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 94, "selling_price": 47.00, "original_price": 55.00, "stock_quantity": 54, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 95, "selling_price": 259.00, "original_price": 290.00, "stock_quantity": 49, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 96, "selling_price": 184.00, "original_price": 205.00, "stock_quantity": 39, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 72, "selling_price": 34.00, "original_price": 45.00, "stock_quantity": 45, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 73, "selling_price": 38.00, "original_price": 50.00, "stock_quantity": 50, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 74, "selling_price": 34.00, "original_price": 42.00, "stock_quantity": 40, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 75, "selling_price": 58.00, "original_price": 75.00, "stock_quantity": 30, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 97, "selling_price": 14.00, "original_price": 20.00, "stock_quantity": 74, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 98, "selling_price": 21.00, "original_price": 30.00, "stock_quantity": 64, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 99, "selling_price": 34.00, "original_price": 45.00, "stock_quantity": 54, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 100, "selling_price": 168.00, "original_price": 210.00, "stock_quantity": 35, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 101, "selling_price": 94.00, "original_price": 115.00, "stock_quantity": 39, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 102, "selling_price": 39.00, "original_price": 50.00, "stock_quantity": 44, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 103, "selling_price": 139.00, "original_price": 155.00, "stock_quantity": 54, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 104, "selling_price": 104.00, "original_price": 120.00, "stock_quantity": 64, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 105, "selling_price": 198.00, "original_price": 220.00, "stock_quantity": 44, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 106, "selling_price": 118.00, "original_price": 135.00, "stock_quantity": 59, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 107, "selling_price": 194.00, "original_price": 215.00, "stock_quantity": 49, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 108, "selling_price": 109.00, "original_price": 125.00, "stock_quantity": 39, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 109, "selling_price": 149.00, "original_price": 168.00, "stock_quantity": 44, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 110, "selling_price": 74.00, "original_price": 85.00, "stock_quantity": 74, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 18, "selling_price": 255.00, "original_price": 315.00, "stock_quantity": 15, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 17, "selling_price": 745.00, "original_price": 799.00, "stock_quantity": 10, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 21, "selling_price": 385.00, "original_price": 389.00, "stock_quantity": 8, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 3, "product_id": 52, "selling_price": 148.00, "original_price": 149.00, "stock_quantity": 25, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 61, "selling_price": 63.00, "original_price": 64.00, "stock_quantity": 12, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 76, "selling_price": 34.00, "original_price": 35.00, "stock_quantity": 0, "low_stock_threshold": 5, "is_available": False},
    {"store_id": 4, "product_id": 77, "selling_price": 67.00, "original_price": 68.00, "stock_quantity": 10, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 62, "selling_price": 36.00, "original_price": 38.00, "stock_quantity": 14, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 78, "selling_price": 36.00, "original_price": 38.00, "stock_quantity": 12, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 63, "selling_price": 99.00, "original_price": 105.00, "stock_quantity": 0, "low_stock_threshold": 5, "is_available": False},
    {"store_id": 4, "product_id": 64, "selling_price": 57.00, "original_price": 60.00, "stock_quantity": 18, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 79, "selling_price": 309.00, "original_price": 330.00, "stock_quantity": 14, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 80, "selling_price": 136.00, "original_price": 145.00, "stock_quantity": 8, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 83, "selling_price": 41.00, "original_price": 45.00, "stock_quantity": 10, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 84, "selling_price": 56.00, "original_price": 65.00, "stock_quantity": 16, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 85, "selling_price": 197.00, "original_price": 220.00, "stock_quantity": 32, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 86, "selling_price": 192.00, "original_price": 210.00, "stock_quantity": 37, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 65, "selling_price": 113.00, "original_price": 125.00, "stock_quantity": 15, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 66, "selling_price": 332.00, "original_price": 380.00, "stock_quantity": 8, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 67, "selling_price": 117.00, "original_price": 130.00, "stock_quantity": 22, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 68, "selling_price": 168.00, "original_price": 195.00, "stock_quantity": 25, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 69, "selling_price": 158.00, "original_price": 185.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 70, "selling_price": 112.00, "original_price": 135.00, "stock_quantity": 22, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 87, "selling_price": 162.00, "original_price": 180.00, "stock_quantity": 27, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 88, "selling_price": 182.00, "original_price": 200.00, "stock_quantity": 32, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 89, "selling_price": 172.00, "original_price": 190.00, "stock_quantity": 27, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 90, "selling_price": 57.00, "original_price": 65.00, "stock_quantity": 52, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 81, "selling_price": 146.00, "original_price": 160.00, "stock_quantity": 16, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 71, "selling_price": 51.00, "original_price": 60.00, "stock_quantity": 28, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 82, "selling_price": 27.00, "original_price": 30.00, "stock_quantity": 30, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 91, "selling_price": 167.00, "original_price": 185.00, "stock_quantity": 42, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 92, "selling_price": 47.00, "original_price": 52.00, "stock_quantity": 62, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 93, "selling_price": 67.00, "original_price": 75.00, "stock_quantity": 57, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 94, "selling_price": 50.00, "original_price": 55.00, "stock_quantity": 52, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 95, "selling_price": 262.00, "original_price": 290.00, "stock_quantity": 47, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 96, "selling_price": 187.00, "original_price": 205.00, "stock_quantity": 37, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 72, "selling_price": 37.00, "original_price": 45.00, "stock_quantity": 25, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 73, "selling_price": 41.00, "original_price": 50.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 74, "selling_price": 35.00, "original_price": 42.00, "stock_quantity": 22, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 75, "selling_price": 67.00, "original_price": 75.00, "stock_quantity": 62, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 97, "selling_price": 17.00, "original_price": 20.00, "stock_quantity": 72, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 98, "selling_price": 24.00, "original_price": 30.00, "stock_quantity": 62, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 99, "selling_price": 37.00, "original_price": 45.00, "stock_quantity": 52, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 100, "selling_price": 182.00, "original_price": 210.00, "stock_quantity": 42, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 101, "selling_price": 97.00, "original_price": 115.00, "stock_quantity": 37, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 102, "selling_price": 42.00, "original_price": 50.00, "stock_quantity": 42, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 103, "selling_price": 142.00, "original_price": 155.00, "stock_quantity": 52, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 104, "selling_price": 107.00, "original_price": 120.00, "stock_quantity": 62, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 105, "selling_price": 201.00, "original_price": 220.00, "stock_quantity": 42, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 106, "selling_price": 121.00, "original_price": 135.00, "stock_quantity": 57, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 107, "selling_price": 197.00, "original_price": 215.00, "stock_quantity": 47, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 108, "selling_price": 112.00, "original_price": 125.00, "stock_quantity": 37, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 109, "selling_price": 152.00, "original_price": 168.00, "stock_quantity": 42, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 110, "selling_price": 77.00, "original_price": 85.00, "stock_quantity": 72, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 18, "selling_price": 258.00, "original_price": 315.00, "stock_quantity": 10, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 17, "selling_price": 750.00, "original_price": 799.00, "stock_quantity": 8, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 21, "selling_price": 382.00, "original_price": 389.00, "stock_quantity": 27, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 4, "product_id": 52, "selling_price": 147.00, "original_price": 149.00, "stock_quantity": 37, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 61, "selling_price": 61.50, "original_price": 64.00, "stock_quantity": 22, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 76, "selling_price": 33.00, "original_price": 35.00, "stock_quantity": 18, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 77, "selling_price": 65.50, "original_price": 68.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 62, "selling_price": 35.50, "original_price": 38.00, "stock_quantity": 15, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 78, "selling_price": 35.00, "original_price": 38.00, "stock_quantity": 18, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 63, "selling_price": 94.00, "original_price": 105.00, "stock_quantity": 18, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 64, "selling_price": 57.50, "original_price": 60.00, "stock_quantity": 22, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 79, "selling_price": 314.00, "original_price": 330.00, "stock_quantity": 15, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 80, "selling_price": 133.00, "original_price": 145.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 83, "selling_price": 39.50, "original_price": 45.00, "stock_quantity": 25, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 84, "selling_price": 52.00, "original_price": 65.00, "stock_quantity": 30, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 85, "selling_price": 185.00, "original_price": 220.00, "stock_quantity": 25, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 86, "selling_price": 180.00, "original_price": 210.00, "stock_quantity": 25, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 65, "selling_price": 109.00, "original_price": 125.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 66, "selling_price": 335.00, "original_price": 380.00, "stock_quantity": 12, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 67, "selling_price": 113.50, "original_price": 130.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 68, "selling_price": 173.50, "original_price": 195.00, "stock_quantity": 40, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 69, "selling_price": 163.50, "original_price": 185.00, "stock_quantity": 30, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 70, "selling_price": 118.50, "original_price": 135.00, "stock_quantity": 25, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 87, "selling_price": 158.50, "original_price": 180.00, "stock_quantity": 25, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 88, "selling_price": 178.50, "original_price": 200.00, "stock_quantity": 30, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 89, "selling_price": 168.50, "original_price": 190.00, "stock_quantity": 25, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 90, "selling_price": 53.50, "original_price": 65.00, "stock_quantity": 50, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 81, "selling_price": 142.00, "original_price": 160.00, "stock_quantity": 25, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 71, "selling_price": 50.00, "original_price": 60.00, "stock_quantity": 40, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 82, "selling_price": 26.50, "original_price": 30.00, "stock_quantity": 50, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 91, "selling_price": 163.50, "original_price": 185.00, "stock_quantity": 40, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 92, "selling_price": 43.50, "original_price": 52.00, "stock_quantity": 60, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 93, "selling_price": 63.50, "original_price": 75.00, "stock_quantity": 55, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 94, "selling_price": 46.50, "original_price": 55.00, "stock_quantity": 50, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 95, "selling_price": 258.50, "original_price": 290.00, "stock_quantity": 45, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 96, "selling_price": 183.50, "original_price": 205.00, "stock_quantity": 35, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 72, "selling_price": 36.50, "original_price": 45.00, "stock_quantity": 110, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 73, "selling_price": 40.50, "original_price": 50.00, "stock_quantity": 90, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 74, "selling_price": 33.50, "original_price": 42.00, "stock_quantity": 80, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 75, "selling_price": 63.50, "original_price": 75.00, "stock_quantity": 60, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 97, "selling_price": 13.50, "original_price": 20.00, "stock_quantity": 70, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 98, "selling_price": 20.50, "original_price": 30.00, "stock_quantity": 60, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 99, "selling_price": 33.50, "original_price": 45.00, "stock_quantity": 50, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 100, "selling_price": 178.50, "original_price": 210.00, "stock_quantity": 40, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 101, "selling_price": 93.50, "original_price": 115.00, "stock_quantity": 35, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 102, "selling_price": 38.50, "original_price": 50.00, "stock_quantity": 40, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 103, "selling_price": 134.00, "original_price": 155.00, "stock_quantity": 35, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 104, "selling_price": 99.00, "original_price": 120.00, "stock_quantity": 40, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 105, "selling_price": 189.00, "original_price": 220.00, "stock_quantity": 30, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 106, "selling_price": 112.00, "original_price": 135.00, "stock_quantity": 35, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 107, "selling_price": 193.50, "original_price": 215.00, "stock_quantity": 45, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 108, "selling_price": 108.50, "original_price": 125.00, "stock_quantity": 35, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 109, "selling_price": 148.50, "original_price": 168.00, "stock_quantity": 40, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 110, "selling_price": 73.50, "original_price": 85.00, "stock_quantity": 70, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 18, "selling_price": 248.00, "original_price": 315.00, "stock_quantity": 20, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 17, "selling_price": 735.00, "original_price": 799.00, "stock_quantity": 15, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 21, "selling_price": 375.00, "original_price": 389.00, "stock_quantity": 15, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 5, "product_id": 52, "selling_price": 143.50, "original_price": 149.00, "stock_quantity": 35, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 61, "selling_price": 61.00, "original_price": 64.00, "stock_quantity": 88, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 76, "selling_price": 34.00, "original_price": 35.00, "stock_quantity": 68, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 77, "selling_price": 67.00, "original_price": 68.00, "stock_quantity": 78, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 62, "selling_price": 36.00, "original_price": 38.00, "stock_quantity": 38, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 78, "selling_price": 36.00, "original_price": 38.00, "stock_quantity": 48, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 63, "selling_price": 96.00, "original_price": 105.00, "stock_quantity": 28, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 64, "selling_price": 59.00, "original_price": 60.00, "stock_quantity": 48, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 79, "selling_price": 311.00, "original_price": 330.00, "stock_quantity": 43, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 80, "selling_price": 136.00, "original_price": 145.00, "stock_quantity": 33, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 83, "selling_price": 41.00, "original_price": 45.00, "stock_quantity": 38, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 84, "selling_price": 56.00, "original_price": 65.00, "stock_quantity": 48, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 85, "selling_price": 196.00, "original_price": 220.00, "stock_quantity": 28, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 86, "selling_price": 191.00, "original_price": 210.00, "stock_quantity": 33, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 65, "selling_price": 111.00, "original_price": 125.00, "stock_quantity": 33, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 66, "selling_price": 341.00, "original_price": 380.00, "stock_quantity": 23, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 67, "selling_price": 116.00, "original_price": 130.00, "stock_quantity": 18, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 68, "selling_price": 176.00, "original_price": 195.00, "stock_quantity": 38, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 69, "selling_price": 166.00, "original_price": 185.00, "stock_quantity": 28, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 70, "selling_price": 121.00, "original_price": 135.00, "stock_quantity": 23, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 87, "selling_price": 161.00, "original_price": 180.00, "stock_quantity": 23, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 88, "selling_price": 181.00, "original_price": 200.00, "stock_quantity": 28, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 89, "selling_price": 171.00, "original_price": 190.00, "stock_quantity": 23, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 90, "selling_price": 56.00, "original_price": 65.00, "stock_quantity": 48, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 81, "selling_price": 146.00, "original_price": 160.00, "stock_quantity": 63, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 71, "selling_price": 55.00, "original_price": 60.00, "stock_quantity": 68, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 82, "selling_price": 29.00, "original_price": 30.00, "stock_quantity": 78, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 91, "selling_price": 166.00, "original_price": 185.00, "stock_quantity": 38, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 92, "selling_price": 46.00, "original_price": 52.00, "stock_quantity": 58, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 93, "selling_price": 66.00, "original_price": 75.00, "stock_quantity": 53, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 94, "selling_price": 49.00, "original_price": 55.00, "stock_quantity": 48, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 95, "selling_price": 261.00, "original_price": 290.00, "stock_quantity": 43, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 96, "selling_price": 186.00, "original_price": 205.00, "stock_quantity": 33, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 72, "selling_price": 39.00, "original_price": 45.00, "stock_quantity": 108, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 73, "selling_price": 43.00, "original_price": 50.00, "stock_quantity": 88, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 74, "selling_price": 36.00, "original_price": 42.00, "stock_quantity": 78, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 75, "selling_price": 66.00, "original_price": 75.00, "stock_quantity": 58, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 97, "selling_price": 16.00, "original_price": 20.00, "stock_quantity": 68, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 98, "selling_price": 23.00, "original_price": 30.00, "stock_quantity": 58, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 99, "selling_price": 36.00, "original_price": 45.00, "stock_quantity": 48, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 100, "selling_price": 181.00, "original_price": 210.00, "stock_quantity": 38, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 101, "selling_price": 96.00, "original_price": 115.00, "stock_quantity": 33, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 102, "selling_price": 41.00, "original_price": 50.00, "stock_quantity": 38, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 103, "selling_price": 141.00, "original_price": 155.00, "stock_quantity": 48, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 104, "selling_price": 106.00, "original_price": 120.00, "stock_quantity": 58, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 105, "selling_price": 200.00, "original_price": 220.00, "stock_quantity": 38, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 106, "selling_price": 120.00, "original_price": 135.00, "stock_quantity": 53, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 107, "selling_price": 196.00, "original_price": 215.00, "stock_quantity": 43, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 108, "selling_price": 111.00, "original_price": 125.00, "stock_quantity": 33, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 109, "selling_price": 151.00, "original_price": 168.00, "stock_quantity": 38, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 110, "selling_price": 76.00, "original_price": 85.00, "stock_quantity": 68, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 18, "selling_price": 261.00, "original_price": 315.00, "stock_quantity": 28, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 17, "selling_price": 741.00, "original_price": 799.00, "stock_quantity": 18, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 21, "selling_price": 381.00, "original_price": 389.00, "stock_quantity": 23, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 6, "product_id": 52, "selling_price": 146.00, "original_price": 149.00, "stock_quantity": 33, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 61, "selling_price": 62.50, "original_price": 64.00, "stock_quantity": 86, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 76, "selling_price": 35.50, "original_price": 35.50, "stock_quantity": 66, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 77, "selling_price": 68.50, "original_price": 68.50, "stock_quantity": 76, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 62, "selling_price": 37.50, "original_price": 38.00, "stock_quantity": 36, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 78, "selling_price": 37.50, "original_price": 38.00, "stock_quantity": 46, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 63, "selling_price": 97.50, "original_price": 105.00, "stock_quantity": 26, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 64, "selling_price": 60.50, "original_price": 60.50, "stock_quantity": 46, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 79, "selling_price": 312.50, "original_price": 330.00, "stock_quantity": 41, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 80, "selling_price": 137.50, "original_price": 145.00, "stock_quantity": 31, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 83, "selling_price": 42.50, "original_price": 45.00, "stock_quantity": 36, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 84, "selling_price": 57.50, "original_price": 65.00, "stock_quantity": 46, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 85, "selling_price": 197.50, "original_price": 220.00, "stock_quantity": 26, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 86, "selling_price": 192.50, "original_price": 210.00, "stock_quantity": 31, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 65, "selling_price": 112.50, "original_price": 125.00, "stock_quantity": 31, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 66, "selling_price": 342.50, "original_price": 380.00, "stock_quantity": 21, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 67, "selling_price": 117.50, "original_price": 130.00, "stock_quantity": 16, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 68, "selling_price": 177.50, "original_price": 195.00, "stock_quantity": 36, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 69, "selling_price": 167.50, "original_price": 185.00, "stock_quantity": 26, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 70, "selling_price": 122.50, "original_price": 135.00, "stock_quantity": 21, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 87, "selling_price": 162.50, "original_price": 180.00, "stock_quantity": 21, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 88, "selling_price": 182.50, "original_price": 200.00, "stock_quantity": 26, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 89, "selling_price": 172.50, "original_price": 190.00, "stock_quantity": 21, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 90, "selling_price": 57.50, "original_price": 65.00, "stock_quantity": 46, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 81, "selling_price": 147.50, "original_price": 160.00, "stock_quantity": 61, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 71, "selling_price": 56.50, "original_price": 60.00, "stock_quantity": 66, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 82, "selling_price": 30.50, "original_price": 30.50, "stock_quantity": 76, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 91, "selling_price": 167.50, "original_price": 185.00, "stock_quantity": 36, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 92, "selling_price": 47.50, "original_price": 52.00, "stock_quantity": 56, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 93, "selling_price": 67.50, "original_price": 75.00, "stock_quantity": 51, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 94, "selling_price": 50.50, "original_price": 55.00, "stock_quantity": 46, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 95, "selling_price": 262.50, "original_price": 290.00, "stock_quantity": 41, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 96, "selling_price": 187.50, "original_price": 205.00, "stock_quantity": 31, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 72, "selling_price": 40.50, "original_price": 45.00, "stock_quantity": 106, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 73, "selling_price": 44.50, "original_price": 50.00, "stock_quantity": 86, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 74, "selling_price": 37.50, "original_price": 42.00, "stock_quantity": 76, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 75, "selling_price": 67.50, "original_price": 75.00, "stock_quantity": 56, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 97, "selling_price": 17.50, "original_price": 20.00, "stock_quantity": 66, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 98, "selling_price": 24.50, "original_price": 30.00, "stock_quantity": 56, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 99, "selling_price": 37.50, "original_price": 45.00, "stock_quantity": 46, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 100, "selling_price": 182.50, "original_price": 210.00, "stock_quantity": 36, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 101, "selling_price": 97.50, "original_price": 115.00, "stock_quantity": 31, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 102, "selling_price": 42.50, "original_price": 50.00, "stock_quantity": 36, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 103, "selling_price": 142.50, "original_price": 155.00, "stock_quantity": 46, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 104, "selling_price": 107.50, "original_price": 120.00, "stock_quantity": 56, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 105, "selling_price": 201.50, "original_price": 220.00, "stock_quantity": 36, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 106, "selling_price": 121.50, "original_price": 135.00, "stock_quantity": 51, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 107, "selling_price": 197.50, "original_price": 215.00, "stock_quantity": 41, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 108, "selling_price": 112.50, "original_price": 125.00, "stock_quantity": 31, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 109, "selling_price": 152.50, "original_price": 168.00, "stock_quantity": 36, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 110, "selling_price": 77.50, "original_price": 85.00, "stock_quantity": 66, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 18, "selling_price": 262.50, "original_price": 315.00, "stock_quantity": 26, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 17, "selling_price": 742.50, "original_price": 799.00, "stock_quantity": 16, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 21, "selling_price": 382.50, "original_price": 389.00, "stock_quantity": 21, "low_stock_threshold": 5, "is_available": True},
    {"store_id": 7, "product_id": 52, "selling_price": 147.50, "original_price": 149.00, "stock_quantity": 31, "low_stock_threshold": 5, "is_available": True}
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
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_fee NUMERIC(10, 2) DEFAULT 0.0;",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_amount NUMERIC(10, 2) DEFAULT 0.0;",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method VARCHAR(50) DEFAULT 'UPI';",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_id VARCHAR(100);",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_status VARCHAR(50) DEFAULT 'PAID';",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS hub_id INT REFERENCES store_hubs(id) ON DELETE SET NULL;",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS shopping_mode VARCHAR(50) DEFAULT 'ONLINE';",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS store_id INT REFERENCES stores(id);",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS parent_order_id INT REFERENCES orders(id);",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS fulfillment_type VARCHAR(20) DEFAULT 'delivery';",
            "ALTER TABLE inventory ADD COLUMN IF NOT EXISTS reserved_quantity INT DEFAULT 0;",
            "ALTER TABLE inventory ADD COLUMN IF NOT EXISTS hub_id INT REFERENCES store_hubs(id) ON DELETE SET NULL;",
            "ALTER TABLE inventory ADD COLUMN IF NOT EXISTS min_threshold INT DEFAULT 5;",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS seller_id INT REFERENCES sellers(id) ON DELETE SET NULL;",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS category_id INT REFERENCES categories(id) ON DELETE SET NULL;",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS sub_category VARCHAR(100);",
            "ALTER TABLE addresses ADD COLUMN IF NOT EXISTS latitude NUMERIC(10, 6);",
            "ALTER TABLE addresses ADD COLUMN IF NOT EXISTS longitude NUMERIC(10, 6);",
            "ALTER TABLE carts ADD COLUMN IF NOT EXISTS shopping_mode VARCHAR(50) DEFAULT 'ONLINE';",
            "ALTER TABLE carts ADD COLUMN IF NOT EXISTS store_id INT REFERENCES stores(id) ON DELETE CASCADE;",
            "ALTER TABLE carts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
            "ALTER TABLE cart_items ADD COLUMN IF NOT EXISTS store_id INT REFERENCES stores(id) ON DELETE CASCADE;",
            "ALTER TABLE cart_items ADD COLUMN IF NOT EXISTS fulfillment VARCHAR(20) DEFAULT 'delivery';",
            "ALTER TABLE cart_items ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"
        ]
        for q in alter_queries:
            try:
                cur.execute(q)
            except Exception as e:
                logger.debug(f"PG Alter notice: {e}")
    else:
        sqlite_alters = [
            ("orders", "shipping_fee", "REAL DEFAULT 0.0"),
            ("orders", "discount_amount", "REAL DEFAULT 0.0"),
            ("orders", "payment_method", "TEXT DEFAULT 'UPI'"),
            ("orders", "payment_id", "TEXT"),
            ("orders", "payment_status", "TEXT DEFAULT 'PAID'"),
            ("orders", "hub_id", "INTEGER REFERENCES store_hubs(id)"),
            ("orders", "shopping_mode", "TEXT DEFAULT 'ONLINE'"),
            ("orders", "store_id", "INTEGER REFERENCES stores(id)"),
            ("orders", "parent_order_id", "INTEGER REFERENCES orders(id)"),
            ("orders", "fulfillment_type", "TEXT DEFAULT 'delivery'"),
            ("inventory", "reserved_quantity", "INTEGER DEFAULT 0"),
            ("inventory", "hub_id", "INTEGER REFERENCES store_hubs(id)"),
            ("inventory", "min_threshold", "INTEGER DEFAULT 5"),
            ("products", "seller_id", "INTEGER REFERENCES sellers(id)"),
            ("products", "category_id", "INTEGER REFERENCES categories(id)"),
            ("products", "sub_category", "TEXT"),
            ("addresses", "latitude", "REAL"),
            ("addresses", "longitude", "REAL"),
            ("carts", "shopping_mode", "TEXT DEFAULT 'ONLINE'"),
            ("carts", "store_id", "INTEGER REFERENCES stores(id)"),
            ("carts", "updated_at", "DATETIME DEFAULT CURRENT_TIMESTAMP"),
            ("cart_items", "store_id", "INTEGER REFERENCES stores(id)"),
            ("cart_items", "fulfillment", "TEXT DEFAULT 'delivery'"),
            ("cart_items", "updated_at", "DATETIME DEFAULT CURRENT_TIMESTAMP")
        ]
        for tbl, col, col_def in sqlite_alters:
            try:
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {col_def};")
            except Exception:
                pass # Already exists in SQLite

        # Step 2b: Remove legacy UNIQUE constraint on carts.session_id in SQLite
        try:
            cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='carts';")
            cart_sql_row = cur.fetchone()
            if cart_sql_row and "session_id TEXT UNIQUE" in cart_sql_row[0]:
                logger.info("Migrating SQLite carts table to remove legacy UNIQUE constraint on session_id")
                cur.execute("PRAGMA foreign_keys=OFF;")
                cur.execute("""
                    CREATE TABLE carts_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        customer_id INTEGER REFERENCES customers(id) ON DELETE CASCADE,
                        session_id TEXT,
                        shopping_mode TEXT DEFAULT 'ONLINE' CHECK (shopping_mode IN ('ONLINE', 'RETAIL_NEAR_ME')),
                        store_id INTEGER REFERENCES stores(id) ON DELETE CASCADE,
                        status TEXT DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'ABANDONED', 'CONVERTED')),
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                cur.execute("""
                    INSERT INTO carts_new (id, customer_id, session_id, shopping_mode, store_id, status, created_at, updated_at)
                    SELECT id, customer_id, session_id,
                           COALESCE(shopping_mode, 'ONLINE'),
                           store_id,
                           COALESCE(status, 'ACTIVE'),
                           COALESCE(created_at, CURRENT_TIMESTAMP),
                           COALESCE(updated_at, CURRENT_TIMESTAMP)
                    FROM carts;
                """)
                cur.execute("DROP TABLE carts;")
                cur.execute("ALTER TABLE carts_new RENAME TO carts;")
                cur.execute("PRAGMA foreign_keys=ON;")
        except Exception as e:
            logger.warning(f"SQLite carts migration note: {e}")

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
        subcat = p.get("sub_category", "Daily Essentials & Groceries")
        if is_postgres:
            cur.execute("""
            INSERT INTO products (id, sku, title, brand, category, sub_category, price, original_price, image_url, rating, rating_count, description, cities_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                brand = EXCLUDED.brand,
                sub_category = EXCLUDED.sub_category,
                price = EXCLUDED.price,
                original_price = EXCLUDED.original_price,
                image_url = EXCLUDED.image_url,
                description = EXCLUDED.description;
            """, (p["id"], p["sku"], p["title"], p["brand"], p["category"], subcat, p["price"], p["original_price"], p["image_url"], p["rating"], p["rating_count"], p["description"], json.dumps(p["cities"])))
            cur.execute("""
            INSERT INTO inventory (product_id, stock_quantity, reserved_quantity)
            VALUES (%s, %s, 0)
            ON CONFLICT (product_id) DO NOTHING;
            """, (p["id"], p["stock"]))
        else:
            cur.execute("""
            INSERT INTO products (id, sku, title, brand, category, sub_category, price, original_price, image_url, rating, rating_count, description, cities_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                title = excluded.title,
                brand = excluded.brand,
                sub_category = excluded.sub_category,
                price = excluded.price,
                original_price = excluded.original_price,
                image_url = excluded.image_url,
                description = excluded.description;
            """, (p["id"], p["sku"], p["title"], p["brand"], p["category"], subcat, p["price"], p["original_price"], p["image_url"], p["rating"], p["rating_count"], p["description"], json.dumps(p["cities"])))
            cur.execute("""
            INSERT OR IGNORE INTO inventory (product_id, stock_quantity, reserved_quantity)
            VALUES (?, ?, 0);
            """, (p["id"], p["stock"]))

    # Synchronize staple product names & sub_categories
    staples_sync = [
        (18, "Wheat Atta – 5 kg", "Rice & Grains"),
        (21, "Mustard Oil – 1 L", "Cooking Essentials"),
        (17, "Sunflower Oil – 5 L", "Cooking Essentials"),
        (52, "Pink Rock Salt – 1 kg", "Cooking Essentials"),
    ]
    for s_id, s_title, s_sub in staples_sync:
        if is_postgres:
            cur.execute("UPDATE products SET title = %s, sub_category = %s WHERE id = %s;", (s_title, s_sub, s_id))
        else:
            cur.execute("UPDATE products SET title = ?, sub_category = ? WHERE id = ?;", (s_title, s_sub, s_id))

    # Step 9: Seed and synchronize physical stores (Phase 4 & Retail 5-Shop Marketplace)
    for s in SAMPLE_STORES:
        if is_postgres:
            cur.execute("""
            INSERT INTO stores (id, store_name, store_slug, store_description, store_logo, store_banner, owner_name, contact_phone, email, full_address, city, area, pincode, latitude, longitude, opening_time, closing_time, is_active, accepts_delivery, accepts_pickup)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                store_name = EXCLUDED.store_name,
                store_slug = EXCLUDED.store_slug,
                store_description = EXCLUDED.store_description,
                store_logo = EXCLUDED.store_logo,
                store_banner = EXCLUDED.store_banner,
                owner_name = EXCLUDED.owner_name,
                contact_phone = EXCLUDED.contact_phone,
                email = EXCLUDED.email,
                full_address = EXCLUDED.full_address,
                city = EXCLUDED.city,
                area = EXCLUDED.area,
                pincode = EXCLUDED.pincode,
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude,
                opening_time = EXCLUDED.opening_time,
                closing_time = EXCLUDED.closing_time,
                is_active = EXCLUDED.is_active,
                accepts_delivery = EXCLUDED.accepts_delivery,
                accepts_pickup = EXCLUDED.accepts_pickup;
            """, (s["id"], s["store_name"], s["store_slug"], s["store_description"], s["store_logo"], s["store_banner"], s["owner_name"], s["contact_phone"], s["email"], s["full_address"], s["city"], s["area"], s["pincode"], s["latitude"], s["longitude"], s["opening_time"], s["closing_time"], s["is_active"], s["accepts_delivery"], s["accepts_pickup"]))
        else:
            cur.execute("""
            INSERT INTO stores (id, store_name, store_slug, store_description, store_logo, store_banner, owner_name, contact_phone, email, full_address, city, area, pincode, latitude, longitude, opening_time, closing_time, is_active, accepts_delivery, accepts_pickup)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                store_name = excluded.store_name,
                store_slug = excluded.store_slug,
                store_description = excluded.store_description,
                store_logo = excluded.store_logo,
                store_banner = excluded.store_banner,
                owner_name = excluded.owner_name,
                contact_phone = excluded.contact_phone,
                email = excluded.email,
                full_address = excluded.full_address,
                city = excluded.city,
                area = excluded.area,
                pincode = excluded.pincode,
                latitude = excluded.latitude,
                longitude = excluded.longitude,
                opening_time = excluded.opening_time,
                closing_time = excluded.closing_time,
                is_active = excluded.is_active,
                accepts_delivery = excluded.accepts_delivery,
                accepts_pickup = excluded.accepts_pickup;
            """, (s["id"], s["store_name"], s["store_slug"], s["store_description"], s["store_logo"], s["store_banner"], s["owner_name"], s["contact_phone"], s["email"], s["full_address"], s["city"], s["area"], s["pincode"], s["latitude"], s["longitude"], s["opening_time"], s["closing_time"], 1 if s["is_active"] else 0, 1 if s["accepts_delivery"] else 0, 1 if s["accepts_pickup"] else 0))

    # Step 10: Seed / synchronize store inventory with complete essential items (Phase 4)
    for item in SAMPLE_STORE_INVENTORY:
        if is_postgres:
            cur.execute("""
            INSERT INTO store_inventory (store_id, product_id, selling_price, original_price, stock_quantity, reserved_quantity, low_stock_threshold, is_available)
            VALUES (%s, %s, %s, %s, %s, 0, %s, %s)
            ON CONFLICT (store_id, product_id) DO UPDATE SET
                selling_price = EXCLUDED.selling_price,
                original_price = EXCLUDED.original_price,
                stock_quantity = EXCLUDED.stock_quantity,
                is_available = EXCLUDED.is_available,
                low_stock_threshold = EXCLUDED.low_stock_threshold;
            """, (item["store_id"], item["product_id"], item["selling_price"], item.get("original_price"), item["stock_quantity"], item.get("low_stock_threshold", 5), item.get("is_available", True)))
        else:
            cur.execute("""
            INSERT INTO store_inventory (store_id, product_id, selling_price, original_price, stock_quantity, reserved_quantity, low_stock_threshold, is_available)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            ON CONFLICT (store_id, product_id) DO UPDATE SET
                selling_price = excluded.selling_price,
                original_price = excluded.original_price,
                stock_quantity = excluded.stock_quantity,
                is_available = excluded.is_available,
                low_stock_threshold = excluded.low_stock_threshold;
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

    try:
        ref_id_str = f"store_{store_id}:{reference_id}"
        detailed_notes = f"[Store #{store_id}] Customer Order Sale"
        if is_postgres:
            cur.execute("""
                INSERT INTO inventory_movements (product_id, movement_type, quantity, balance_after, reference_type, reference_id, notes)
                VALUES (%s, 'SOLD', %s, %s, %s, %s, %s);
            """, (product_id, -quantity, new_stock, reference_type, ref_id_str, detailed_notes))
        else:
            cur.execute("""
                INSERT INTO inventory_movements (product_id, movement_type, quantity, balance_after, reference_type, reference_id, notes)
                VALUES (?, 'SOLD', ?, ?, ?, ?, ?);
            """, (product_id, -quantity, new_stock, reference_type, ref_id_str, detailed_notes))
    except Exception as me:
        logger.warning(f"Failed to record inventory movement in store sale: {me}")

    return {
        "store_id": store_id,
        "product_id": product_id,
        "quantity_sold": quantity,
        "new_stock": new_stock,
        "new_reserved": new_reserved,
        "available_stock": new_stock - new_reserved,
        "is_available": bool(is_avail)
    }

