# BharatStore 🇮🇳 | Physical Stores Across India, Now Online

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Flask 3.0](https://img.shields.io/badge/framework-Flask%203.0-orange.svg)](https://palletsprojects.com/p/flask/)
[![Database](https://img.shields.io/badge/database-PostgreSQL%20%7C%20SQLite-blue)](https://aiven.io/postgresql)
[![Streaming](https://img.shields.io/badge/streaming-Apache%20Kafka-red)](https://aiven.io/kafka)
[![Search](https://img.shields.io/badge/search-OpenSearch%202.x-teal)](https://aiven.io/opensearch)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**BharatStore** (`bharatstore.`) is a cloud-native, event-driven enterprise e-commerce platform and omni-channel marketplace. It represents the digital expansion of an established Indian physical retail store chain, seamlessly connecting regional mega-stores and fulfillment hubs across **Mumbai, Bengaluru, Delhi NCR, Hyderabad, Chennai, and Kolkata** directly to shoppers nationwide.

The platform combines the warm, artisanal visual identity of **[Rosier Foods](https://www.rosierfoods.com/)** (natural earth brown, linen cream, royal deep navy, and sage) with the marketplace navigation, discovery patterns, and shopping features inspired by **Amazon.in** and **Flipkart**.

---

## 📑 Table of Contents

- [Visual Identity & Design System](#-visual-identity--design-system)
- [Key Features](#-key-features)
- [Architecture & Tech Stack](#-architecture--tech-stack)
- [Project Directory Structure](#-project-directory-structure)
- [Getting Started](#-getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Environment Variables Setup](#environment-variables-setup)
  - [Database Setup & Migrations](#database-setup--migrations)
  - [Running the Application](#running-the-application)
- [Running Test Suites](#-running-test-suites)
- [Git Branching & Team Collaboration Guide](#-git-branching--team-collaboration-guide)
  - [Branching Model](#branching-model)
  - [Collaboration Workflow](#collaboration-workflow)
  - [Pull Request & Merge Protocol](#pull-request--merge-protocol)
- [Security Guidelines](#-security-guidelines)
- [License & Contributors](#-license--contributors)

---

## 🎨 Visual Identity & Design System

BharatStore features an editorial, high-end D2C aesthetic inspired by Rosier Foods:

| Role | Color Name | Hex Code | Visual Application |
| :--- | :--- | :--- | :--- |
| **Canvas Background** | Linen Cream | `#FEFDF7` | Page body, natural warm canvas |
| **Primary Brand** | Warm Honey Gold / Earth Amber | `#A56211` | Primary CTA buttons, brand badges, active states |
| **Primary Dark** | Deep Roasted Caramel | `#8B4B08` | Hover states, active links |
| **Primary Light** | Soft Amber Glow | `#F7EFE1` | Subtle chip backgrounds, highlights |
| **Royal Accent** | Deep Navy Blue | `#004B8D` | Secondary CTAs, badges, trust indicators |
| **Natural Accent** | Organic Sage Green | `#3D5A45` | In-stock badges, organic food highlights |
| **Text Primary** | Deep Charcoal Espresso | `#2C2621` | High-contrast readable typography |
| **Typography** | Editorial Serif & Clean Sans | `Playfair Display` + `Plus Jakarta Sans` |

### Light & Dark Theme Toggle
BharatStore supports persistent Light and Dark themes. The theme toggle is accessible directly in the top navigation bar, automatically detects system `prefers-color-scheme`, and saves preference in `localStorage`.

---

## ✨ Key Features

### 1. Comprehensive 18-Section Homepage
1. **Announcement Bar:** Dynamic dispatch updates, free shipping countdown (`BHARAT10`), and customer helpline.
2. **Main Header:** Sticky navigation with logo, location hub selector, search bar, account dropdown, wishlist & cart counters, and theme toggle.
3. **Smart OpenSearch Bar:** Live fuzzy autocomplete suggestions with product thumbnails and category badges.
4. **Login / Account Section:** Customer and administrator sign-in with 1-click demo switcher.
5. **Wishlist Counter:** Real-time badge tracking saved items across browser sessions.
6. **Cart Drawer & Counter:** Slide-out drawer with free shipping progress bar, promo code validation, and subtotal calculation.
7. **Category Navigation:** Horizontal pill navigation across 6 distinct retail categories.
8. **Hero Carousel:** High-impact editorial banners showcasing cold-pressed oils, artisanal ghee, and organic staples.
9. **Shop by Category:** Circular category grid with product counts and curated lifestyle imagery.
10. **Trending Products:** Dynamic showcase of the week's highest velocity items.
11. **Today’s Deals:** Live countdown timer (`HH:MM:SS`) with discount ribbons up to 60% off.
12. **Best-Selling Products:** Customer-favorite items with star ratings and verified review counts.
13. **Recommended For You:** Algorithmic product recommendations with instant "Add to Basket".
14. **Promotional Split Banners:** Editorial banners highlighting direct farmer sourcing and 24-hour city fulfillment.
15. **Brand / About Story:** Farm-to-table traceability, 6 physical fulfillment hubs, and zero-preservative promise.
16. **Customer Testimonials:** Multi-column verified customer reviews with city tags and star ratings.
17. **Newsletter Subscription:** Email capture with discount code incentive.
18. **Comprehensive Footer:** 4-column layout with hub directory, customer service, policies, and trust badges (FSSAI, ISO 9001, 100% Organic).

### 2. 52-Product Authentic Catalog
Spans 6 core categories with realistic Indian retail pricing, high-resolution imagery, and specs:
- **Groceries & Gourmet (Rosier Foods range):** A2 Gir Cow Bilona Ghee, Raw Forest Honey, Cold-Pressed Mustard Oil, Kashmiri Mongra Saffron, Lakadong Turmeric, Himalayan Pink Salt, Certified Organic Quinoa, Cold-Pressed Virgin Coconut Oil, etc.
- **Smartphones & Tech:** iPhone 15, Samsung Galaxy S24, OnePlus 12 5G, Google Pixel 8, etc.
- **Laptops & Computing:** MacBook Air M2, Dell XPS 13, ThinkPad X1 Carbon, HP Envy x360, etc.
- **Audio & Wearables:** Sony WH-1000XM5, boAt Rockerz 550, Apple AirPods Pro 2, Bose QC45, etc.
- **Kitchen & Appliances:** Prestige Pressure Cooker, Philips Air Fryer XXL, Dyson V11, Instant Pot, etc.
- **Heritage Fashion:** Pure Mulberry Silk Kanjivaram Saree, Khadi Cotton Kurta, Pashmina Shawl, etc.

### 3. All 17 Core Pages
- **Homepage** (`/`)
- **All Products Catalog** (`/products`) with multi-faceted category, price, rating, and city hub filters
- **Category Products** (`/category/<slug>`)
- **Product Details** (`/product/<id>`) with multi-thumbnail gallery, technical specs, and verified review form
- **Search Results** (`/products?q=...`) with OpenSearch typo tolerance
- **Shopping Cart** (`/cart`) with free shipping bar and promo code support
- **Wishlist** (`/wishlist`) with 1-click move to cart
- **Checkout** (`/checkout`) with address entry, hub dispatch selector, and live order processing
- **Order History** (`/orders`)
- **Order Details** (`/order/<id>`) with BlueDart shipment timeline and printable tax invoice
- **Customer Authentication** (`/login` & `/register`) with 1-click demo switcher
- **Customer Profile** (`/profile`)
- **Admin Dashboard** (`/admin`) with real-time GMV KPIs, stock health indicators, and inventory reset
- **Admin Product Management** (`/admin/products`) with modal for Add / Edit / Delete products
- **Admin Inventory Management** (`/admin/inventory`) with quick inline stock count adjuster
- **Admin Order Management** (`/admin/orders`) with status transition updater
- **Architecture & Pitch** (`/architecture`) with interactive Kafka stream inspector and OpenSearch DSL playground

---

## 🏛️ Architecture & Tech Stack

```text
[ Shopper Browser (HTML5 / Vanilla JS / CSS3) ]
                       │
                       │ REST / JSON
                       ▼
[ Flask 3.0 Backend Application (Python 3.10+) ]
        │                       │                      │
        ▼                       ▼                      ▼
┌──────────────────┐   ┌───────────────────┐   ┌───────────────────┐
│ Aiven PostgreSQL │   │ Aiven Apache Kafka│   │  Aiven OpenSearch │
│ (or SQLite local)│   │ (or In-Memory Hub)│   │(or Local Fuzzy DSL│
│                  │   │                   │   │                   │
│ • ACID Row Locks │   │ • order-events    │   │ • Typo Tolerance  │
│ • 23 Relational  │   │ • Real-time SSE   │   │ • Multi-Match DSL │
│   Domain Tables  │   │ • Async Inventory │   │ • Faceted Filters │
└──────────────────┘   └───────────────────┘   └───────────────────┘
```

- **Backend:** Python 3.10+, Flask 3.0, Flask-CORS
- **Database:** Dual-Engine architecture (PostgreSQL on Aiven Cloud / SQLite3 zero-config local fallback)
- **Streaming:** Apache Kafka (`kafka-python-ng`) with Server-Sent Events (SSE) live browser broadcasting
- **Search:** OpenSearch 2.x (`opensearch-py`) with typo-tolerant fuzzy matching (`fuzziness: "AUTO"`)
- **Security:** Timing-safe HMAC token comparison (`hmac.compare_digest`), cryptographic 256-bit `SECRET_KEY`, input validation, strict row-level lock concurrency protection.

---

## 📁 Project Directory Structure

```text
bharatstore/
├── .env.example                 # Safe environment template with placeholders
├── .gitignore                   # Excludes .env, secrets, *.db, venv, caches
├── README.md                    # Project overview and collaboration guide
├── requirements.txt             # Production Python dependencies
├── run.py                       # Application runner & port detector
├── BharatStore_Pitch_Deck.pdf   # Executive pitch presentation
├── PRESENTATION_PITCH_DECK.md   # Markdown presentation source
├── app/
│   ├── __init__.py              # Flask app factory
│   ├── config.py                # Environment configuration & validation
│   ├── database.py              # Dual PostgreSQL/SQLite engine & ACID locks
│   ├── kafka_service.py         # Kafka producer, consumer thread & SSE emitter
│   ├── opensearch_service.py    # OpenSearch fuzzy search & indexing
│   ├── payment_service.py       # Cryptographic webhook signature verification
│   ├── routes.py                # Web pages & REST API endpoints
│   ├── schema.py                # 23-table relational schema & migrations
│   └── seed_data.py             # 52 authentic catalog items & 6 city hubs
├── static/
│   ├── css/
│   │   └── style.css            # Complete Rosier Foods design system & themes
│   └── js/
│       ├── app.js               # Search autocomplete, cart, wishlist, admin
│       └── live-events.js       # Live Kafka SSE event inspector UI
├── templates/                   # 17 Jinja2 HTML5 responsive templates
│   ├── base.html                # Master layout, header, footer, modals
│   ├── index.html               # 18-section homepage
│   ├── products.html            # Catalog with multi-faceted filters
│   ├── product_detail.html      # Product specs & review submissions
│   ├── cart.html                # Dedicated shopping cart page
│   ├── wishlist.html            # Saved items grid
│   ├── checkout.html            # Multi-step checkout
│   ├── orders.html              # Customer order history
│   ├── order_detail.html        # BlueDart timeline & invoice
│   ├── auth_login.html          # Sign-in with 1-click demo switcher
│   ├── auth_register.html       # Customer registration
│   ├── profile.html             # Profile & address manager
│   ├── admin_dashboard.html     # Admin KPIs & revenue analytics
│   ├── admin_products.html      # Product catalog management
│   ├── admin_inventory.html     # Real-time stock adjustment
│   ├── admin_orders.html        # Order status transitions
│   └── architecture.html        # Aiven pitch deck & live testers
└── tests/                       # Comprehensive verification test suites
    ├── test_all_redesigned_pages.py
    ├── test_api_endpoints.py
    ├── test_concurrency.py
    ├── test_database_schema_and_integrity.py
    ├── test_kafka.py
    ├── test_opensearch.py
    ├── test_payment_security_and_webhooks.py
    └── test_sprint1_security_reliability.py
```

---

## 🚀 Getting Started

### Prerequisites
- **Python 3.10+** installed
- **Git** installed
- Modern web browser (Chrome, Edge, Firefox, Safari)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/ayush35099-cloud/BharatStore.git
   cd BharatStore
   ```

2. **Create and activate a virtual environment:**
   - **On Windows (PowerShell):**
     ```powershell
     python -m venv .venv
     .venv\Scripts\Activate.ps1
     ```
   - **On macOS / Linux:**
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

### Environment Variables Setup

1. Copy the example configuration:
   ```bash
   cp .env.example .env
   ```

2. Generate a secure random 256-bit `SECRET_KEY` and `ADMIN_API_KEY`:
   ```bash
   python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32)); print('ADMIN_API_KEY=' + secrets.token_hex(32))"
   ```

3. Open `.env` and paste your generated keys:
   ```ini
   PORT=5000
   SECRET_KEY=your_generated_secret_key_here
   ADMIN_API_KEY=your_generated_admin_key_here
   ALLOW_INSECURE_TEST_ENDPOINTS=false
   MAX_QUANTITY_PER_ITEM=50
   ```

> **Zero-Config Local Fallback:** If Aiven Cloud or Razorpay variables are left blank, BharatStore automatically activates high-fidelity local emulation (SQLite database, local fuzzy search engine, in-process Kafka broker) so developers can run the entire platform immediately without external cloud accounts!

### Database Setup & Migrations

Database tables and initial product seeds are initialized **automatically and idempotently** when the server starts:
- SQLite (`bharatkart_local.db` - automatically created in project root)
- PostgreSQL (when `AIVEN_PG_URL` is configured in `.env`)

To manually verify the 23-table schema and constraints:
```bash
python tests/test_database_schema_and_integrity.py
```

### Running the Application

Start the Flask server:
```bash
python run.py
```

Open your browser and navigate to:
- **Storefront:** [http://localhost:5000](http://localhost:5000)
- **Product Catalog:** [http://localhost:5000/products](http://localhost:5000/products)
- **Pure Organic Foods:** [http://localhost:5000/category/groceries](http://localhost:5000/category/groceries)
- **Admin Portal:** [http://localhost:5000/admin](http://localhost:5000/admin) *(Enter your configured `ADMIN_API_KEY`)*
- **Architecture & Live Testers:** [http://localhost:5000/architecture](http://localhost:5000/architecture)

---

## 🧪 Running Test Suites

Verify all platform features, concurrency locks, security decorators, and routes:

```bash
# 1. Verify all 17 redesigned pages and frontend APIs
python tests/test_all_redesigned_pages.py

# 2. Verify Sprint 1 security, HMAC timing defense, and race conditions
python tests/test_sprint1_security_reliability.py

# 3. Verify 23 relational database tables, B-tree indexes & migrations
python tests/test_database_schema_and_integrity.py

# 4. Verify payment security & Razorpay webhook signature validation
python tests/test_payment_security_and_webhooks.py

# 5. Verify 10-buyer simultaneous checkout race condition
python tests/test_concurrency.py

# 6. Verify Apache Kafka produce-consume event cycle
python tests/test_kafka.py

# 7. Verify OpenSearch typo tolerance & fuzzy search
python tests/test_opensearch.py
```

---

## 🤝 Git Branching & Team Collaboration Guide

BharatStore is configured for multi-developer collaboration using GitHub:
**Repository:** [https://github.com/ayush35099-cloud/BharatStore](https://github.com/ayush35099-cloud/BharatStore)

### Branching Model

```text
main (Production / Stable Release)
 │
 ├── frontend (Frontend UI/UX, CSS, Templates, Client JS)
 │    └── feature/theme-customizer
 │    └── feature/checkout-improvements
 │
 └── backend (API Endpoints, Database Migrations, Services)
      └── feature/order-event-consumer
      └── feature/payment-gateway-live
```

- **`main`**: Always clean, stable, and production-ready. Direct commits to `main` are restricted.
- **`frontend`**: Branch for frontend layout, UI components, stylesheets, and client interactivity.
- **`backend`**: Branch for database models, REST APIs, Kafka streaming, and OpenSearch integrations.
- **`feature/*`**: Short-lived branches created from either `frontend` or `backend` for specific features or bug fixes.

### Collaboration Workflow

1. **Pull the latest changes before starting work:**
   ```bash
   git checkout <branch-name>
   git pull origin <branch-name>
   ```

2. **Create a feature branch:**
   ```bash
   git checkout -b feature/your-feature-name
   ```

3. **Make clean, incremental commits:**
   ```bash
   git add .
   git commit -m "feat(cart): add free delivery progress calculation"
   ```

4. **Run tests to verify zero regressions:**
   ```bash
   python tests/test_all_redesigned_pages.py
   python tests/test_api_endpoints.py
   ```

5. **Push feature branch to GitHub:**
   ```bash
   git push -u origin feature/your-feature-name
   ```

### Pull Request & Merge Protocol

1. Open a **Pull Request (PR)** on GitHub targeting either `frontend`, `backend`, or `main`.
2. Provide a clear PR description detailing:
   - What changed
   - Testing steps completed
   - Screenshots (for UI changes)
3. Request code review from your team collaborator.
4. Resolve all review discussions.
5. Merge the PR and delete the feature branch.

---

## 🔒 Security Guidelines

1. **Never commit `.env` files**: All private secrets, database connection strings, passwords, and tokens must remain in your local `.env`.
2. **Never expose `ADMIN_API_KEY` in frontend code**: Administrative API routes require timing-safe HMAC authentication via `X-Admin-Token` or `Authorization: Bearer`.
3. **Cryptographic Validation**: Payment webhooks and status transitions strictly verify cryptographic SHA-256 signatures before updating database records.
4. **Input Sanitization**: Checkout payloads enforce strict limits (`MAX_QUANTITY_PER_ITEM=50`), positive integer product IDs, and validated customer details.

---

## 👥 Contributors

- **Ayush** ([@ayush35099-cloud](https://github.com/ayush35099-cloud)) — *Full-Stack Architecture, Database & Cloud Infrastructure*
- **Collaborator** — *Frontend UI/UX & E-Commerce Engineering*

---

*BharatStore (`bharatstore.`) — Physical Stores Across India, Now Online.*
