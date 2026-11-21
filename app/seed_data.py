"""
BharatKart Seed Catalog & Store Data
Reflecting the physical retail chain's expansion across India.
"""

FULFILLMENT_HUBS = [
    {"code": "MUM", "city": "Mumbai", "name": "BharatKart Mumbai MegaHub - Andheri West", "state": "Maharashtra"},
    {"code": "BLR", "city": "Bengaluru", "name": "BharatKart Bengaluru Central - Indiranagar", "state": "Karnataka"},
    {"code": "DEL", "city": "Delhi", "name": "BharatKart Delhi NCR - Connaught Place", "state": "Delhi"},
    {"code": "HYD", "city": "Hyderabad", "name": "BharatKart Hyderabad Hub - HITEC City", "state": "Telangana"},
    {"code": "MAA", "city": "Chennai", "name": "BharatKart Chennai Hub - Anna Nagar", "state": "Tamil Nadu"},
    {"code": "PNQ", "city": "Pune", "name": "BharatKart Pune Central - Shivaji Nagar", "state": "Maharashtra"},
    {"code": "CCU", "city": "Kolkata", "name": "BharatKart Kolkata Hub - Park Street", "state": "West Bengal"}
]

SAMPLE_PRODUCTS = [
    {
        "id": 1,
        "sku": "BK-MOB-001",
        "title": "Apple iPhone 15 (128 GB) - Black",
        "brand": "Apple",
        "category": "Mobiles & Tablets",
        "price": 71999,
        "original_price": 79900,
        "stock": 14,
        "rating": 4.6,
        "rating_count": 3420,
        "image_url": "https://images.unsplash.com/photo-1695048133142-1a20484d2569?w=500&auto=format&fit=crop&q=80",
        "description": "Dynamic Island, 48MP main camera with 2x Telephoto, durable color-infused glass and aluminum design with USB-C connector.",
        "cities": ["Mumbai", "Bengaluru", "Delhi", "Hyderabad", "Chennai"]
    },
    {
        "id": 2,
        "sku": "BK-MOB-002",
        "title": "Samsung Galaxy S24 5G (Onyx Black, 256GB)",
        "brand": "Samsung",
        "category": "Mobiles & Tablets",
        "price": 74999,
        "original_price": 82999,
        "stock": 9,
        "rating": 4.5,
        "rating_count": 2180,
        "image_url": "https://images.unsplash.com/photo-1610945265064-0e34e5519bbf?w=500&auto=format&fit=crop&q=80",
        "description": "Galaxy AI powered smartphone featuring Circle to Search, Live Translate, Note Assist and a pro-grade 50MP camera.",
        "cities": ["Mumbai", "Delhi", "Bengaluru", "Kolkata"]
    },
    {
        "id": 3,
        "sku": "BK-MOB-003",
        "title": "OnePlus 12R (Cool Blue, 16GB RAM, 256GB Storage)",
        "brand": "OnePlus",
        "category": "Mobiles & Tablets",
        "price": 45999,
        "original_price": 49999,
        "stock": 20,
        "rating": 4.4,
        "rating_count": 1890,
        "image_url": "https://images.unsplash.com/photo-1598327105666-5b89351aff97?w=500&auto=format&fit=crop&q=80",
        "description": "Snapdragon 8 Gen 2 processor, 1.5K 4th Gen LTPO ProXDR 120Hz display, and 100W SUPERVOOC fast charging.",
        "cities": ["Mumbai", "Bengaluru", "Hyderabad", "Delhi", "Chennai", "Kolkata"]
    },
    {
        "id": 4,
        "sku": "BK-LAP-001",
        "title": "Apple MacBook Air M2 (13.6-inch, 8GB Unified Memory, 256GB SSD) - Midnight",
        "brand": "Apple",
        "category": "Laptops & Computers",
        "price": 94990,
        "original_price": 109900,
        "stock": 6,
        "rating": 4.8,
        "rating_count": 1420,
        "image_url": "https://images.unsplash.com/photo-1517336714731-489689fd1ca8?w=500&auto=format&fit=crop&q=80",
        "description": "Strikingly thin design with M2 chip, 1080p FaceTime HD camera, MagSafe 3 charging, and up to 18 hours of battery life.",
        "cities": ["Mumbai", "Bengaluru", "Delhi"]
    },
    {
        "id": 5,
        "sku": "BK-LAP-002",
        "title": "Dell XPS 13 Laptop (Intel Core i7 13th Gen, 16GB RAM, 512GB SSD)",
        "brand": "Dell",
        "category": "Laptops & Computers",
        "price": 112990,
        "original_price": 128990,
        "stock": 4,
        "rating": 4.7,
        "rating_count": 870,
        "image_url": "https://images.unsplash.com/photo-1593642632823-8f785ba67e45?w=500&auto=format&fit=crop&q=80",
        "description": "InfinityEdge 500 nits FHD+ display, premium CNC machined aluminum chassis, Intel Iris Xe Graphics with Windows 11 Home.",
        "cities": ["Bengaluru", "Delhi", "Hyderabad"]
    },
    {
        "id": 6,
        "sku": "BK-LAP-003",
        "title": "Lenovo ThinkPad E14 Gen 5 (AMD Ryzen 5 7530U, 16GB RAM, 512GB SSD)",
        "brand": "Lenovo",
        "category": "Laptops & Computers",
        "price": 54990,
        "original_price": 68900,
        "stock": 11,
        "rating": 4.5,
        "rating_count": 640,
        "image_url": "https://images.unsplash.com/photo-1588872657578-7efd1f1555ed?w=500&auto=format&fit=crop&q=80",
        "description": "Military-grade durability, legendary ergonomic ThinkPad keyboard, hardware TPM 2.0 security chip, and anti-glare display.",
        "cities": ["Mumbai", "Bengaluru", "Delhi", "Kolkata", "Chennai"]
    },
    {
        "id": 7,
        "sku": "BK-AUD-001",
        "title": "Sony WH-1000XM5 Wireless Industry Leading Bluetooth Noise Cancelling Headphones",
        "brand": "Sony",
        "category": "Audio & Wearables",
        "price": 28990,
        "original_price": 34990,
        "stock": 8,
        "rating": 4.7,
        "rating_count": 4120,
        "image_url": "https://images.unsplash.com/photo-1546435770-a3e426bf472b?w=500&auto=format&fit=crop&q=80",
        "description": "Two processors control 8 microphones for unprecedented noise cancellation. Auto NC Optimizer, 30-hour battery life with quick charge.",
        "cities": ["Mumbai", "Bengaluru", "Delhi", "Hyderabad", "Chennai"]
    },
    {
        "id": 8,
        "sku": "BK-AUD-002",
        "title": "boAt Rockerz 450 Bluetooth On-Ear Headphones with 15H Playtime",
        "brand": "boAt",
        "category": "Audio & Wearables",
        "price": 1499,
        "original_price": 3990,
        "stock": 35,
        "rating": 4.2,
        "rating_count": 12890,
        "image_url": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=500&auto=format&fit=crop&q=80",
        "description": "40mm dynamic drivers for immersive HD audio, adaptive padded earcups, voice assistant integration, dual mode Bluetooth & AUX.",
        "cities": ["Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Kolkata"]
    },
    {
        "id": 9,
        "sku": "BK-AUD-003",
        "title": "Noise ColorFit Pulse 3 Smart Watch with 1.96-inch TFT Display & Bluetooth Calling",
        "brand": "Noise",
        "category": "Audio & Wearables",
        "price": 1799,
        "original_price": 4999,
        "stock": 25,
        "rating": 4.1,
        "rating_count": 9400,
        "image_url": "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=500&auto=format&fit=crop&q=80",
        "description": "Advanced TruSync BT calling, 550 nits brightness, 24x7 Heart Rate & SpO2 monitor, and 100+ sports modes.",
        "cities": ["Mumbai", "Delhi", "Bengaluru", "Kolkata"]
    },
    {
        "id": 10,
        "sku": "BK-FAS-001",
        "title": "Fabindia Men's Pure Cotton Long Kurta - Indigo Blue",
        "brand": "Fabindia",
        "category": "Fashion & Apparel",
        "price": 1890,
        "original_price": 2490,
        "stock": 18,
        "rating": 4.5,
        "rating_count": 1530,
        "image_url": "https://images.unsplash.com/photo-1602810318383-e386cc2a3ccf?w=500&auto=format&fit=crop&q=80",
        "description": "Hand-spun breathable artisan cotton with traditional Mandarin collar and mother-of-pearl buttons. Crafted in Rajasthan.",
        "cities": ["Mumbai", "Delhi", "Bengaluru", "Chennai", "Kolkata", "Hyderabad"]
    },
    {
        "id": 11,
        "sku": "BK-FAS-002",
        "title": "Puma Men's Softride Enzo NXT Running Shoes - Puma Black",
        "brand": "Puma",
        "category": "Fashion & Apparel",
        "price": 3299,
        "original_price": 5499,
        "stock": 15,
        "rating": 4.3,
        "rating_count": 2740,
        "image_url": "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=500&auto=format&fit=crop&q=80",
        "description": "SOFTRIDE foam technology for extreme cushioning and all-day comfort. Bold clamshell construction with TPU eyestay.",
        "cities": ["Mumbai", "Bengaluru", "Delhi", "Hyderabad"]
    },
    {
        "id": 12,
        "sku": "BK-FAS-003",
        "title": "Biba Women Printed Cotton Straight Kurta with Palazzo & Dupatta",
        "brand": "Biba",
        "category": "Fashion & Apparel",
        "price": 2699,
        "original_price": 4599,
        "stock": 12,
        "rating": 4.4,
        "rating_count": 1890,
        "image_url": "https://images.unsplash.com/photo-1583391733956-3750e0ff4e8b?w=500&auto=format&fit=crop&q=80",
        "description": "Elegant festive 3-piece ethnic set crafted from lightweight combed cotton with intricate zari embroidery on yoke.",
        "cities": ["Delhi", "Mumbai", "Kolkata", "Bengaluru"]
    },
    {
        "id": 13,
        "sku": "BK-KIT-001",
        "title": "Prestige Deluxe Alpha Stainless Steel Pressure Cooker 3 Litre",
        "brand": "Prestige",
        "category": "Home & Kitchen",
        "price": 2350,
        "original_price": 2990,
        "stock": 22,
        "rating": 4.6,
        "rating_count": 6800,
        "image_url": "https://images.unsplash.com/photo-1584990347449-39b5eeac27b1?w=500&auto=format&fit=crop&q=80",
        "description": "Alpha base induction and gas compatible pressure cooker with unique pressure indicator and controlled gasket release system.",
        "cities": ["Mumbai", "Bengaluru", "Delhi", "Hyderabad", "Chennai", "Kolkata"]
    },
    {
        "id": 14,
        "sku": "BK-KIT-002",
        "title": "Wonderchef Nutri-Blend Mixer Grinder & Blender (400W, 2 Jars)",
        "brand": "Wonderchef",
        "category": "Home & Kitchen",
        "price": 2799,
        "original_price": 5000,
        "stock": 16,
        "rating": 4.4,
        "rating_count": 5120,
        "image_url": "https://images.unsplash.com/photo-1570222094114-d054a817e56b?w=500&auto=format&fit=crop&q=80",
        "description": "High-speed 22,000 RPM super-fast extraction motor designed with Chef Sanjeev Kapoor. Perfect for chutneys, smoothies & masala.",
        "cities": ["Mumbai", "Delhi", "Bengaluru", "Chennai"]
    },
    {
        "id": 15,
        "sku": "BK-KIT-003",
        "title": "Havells Glaze 1200mm Ceiling Fan (Espresso Brown)",
        "brand": "Havells",
        "category": "Home & Kitchen",
        "price": 2899,
        "original_price": 3850,
        "stock": 19,
        "rating": 4.3,
        "rating_count": 3100,
        "image_url": "https://images.unsplash.com/photo-1615873968403-89e068629265?w=500&auto=format&fit=crop&q=80",
        "description": "High air delivery rate of 230 cmm, metallic paint finish with decorative trims, and 100% pure copper wire motor.",
        "cities": ["Delhi", "Kolkata", "Mumbai", "Hyderabad"]
    },
    {
        "id": 16,
        "sku": "BK-GRO-001",
        "title": "Tata Tea Gold Leaf Black Tea 1kg Poly Pack",
        "brand": "Tata Tea",
        "category": "Daily Essentials & Groceries",
        "price": 540,
        "original_price": 625,
        "stock": 50,
        "rating": 4.7,
        "rating_count": 18200,
        "image_url": "https://images.unsplash.com/photo-1576092768241-dec231879fc3?w=500&auto=format&fit=crop&q=80",
        "description": "Exquisite blend of fine Assam CTC teas with gently rolled 15% long leaves for rich aroma and golden liquor taste.",
        "cities": ["Mumbai", "Bengaluru", "Delhi", "Hyderabad", "Chennai", "Kolkata"]
    },
    {
        "id": 17,
        "sku": "BK-GRO-002",
        "title": "Fortune Sunlite Refined Sunflower Oil Jar, 5 Litre",
        "brand": "Fortune",
        "category": "Daily Essentials & Groceries",
        "price": 749,
        "original_price": 950,
        "stock": 30,
        "rating": 4.5,
        "rating_count": 8940,
        "image_url": "https://images.unsplash.com/photo-1474979266404-7eaacbcd87c5?w=500&auto=format&fit=crop&q=80",
        "description": "Light and healthy cooking oil enriched with Vitamins A & D. Low absorption technology keeps fried foods crisp and light.",
        "cities": ["Mumbai", "Bengaluru", "Delhi", "Chennai", "Hyderabad"]
    },
    {
        "id": 18,
        "sku": "BK-GRO-003",
        "title": "Aashirvaad Select 100% MP Sharbati Whole Wheat Atta 5kg",
        "brand": "Aashirvaad",
        "category": "Daily Essentials & Groceries",
        "price": 315,
        "original_price": 360,
        "stock": 42,
        "rating": 4.8,
        "rating_count": 14750,
        "image_url": "https://images.unsplash.com/photo-1509440159596-0249088772ff?w=500&auto=format&fit=crop&q=80",
        "description": "Made from king of wheat - golden Sharbati grains from Sehore Madhya Pradesh, producing extra soft rotis that stay tender longer.",
        "cities": ["Mumbai", "Delhi", "Bengaluru", "Kolkata"]
    },
    {
        "id": 19,
        "sku": "BK-FOOD-001",
        "title": "Rosier Pure Vedic A2 Gir Cow Bilona Ghee (500ml Glass Jar)",
        "brand": "Rosier Foods",
        "category": "Daily Essentials & Groceries",
        "price": 1499,
        "original_price": 1799,
        "stock": 35,
        "rating": 4.9,
        "rating_count": 4820,
        "image_url": "https://images.unsplash.com/photo-1573812461383-e5f8b759d12e?w=500&auto=format&fit=crop&q=80",
        "description": "Hand-churned bilona ghee crafted from the curd of grass-fed indigenous Gir cows. Rich in CLA, butyric acid, and essential fat-soluble vitamins.",
        "cities": ["Mumbai", "Bengaluru", "Delhi", "Hyderabad", "Chennai", "Kolkata"]
    },
    {
        "id": 20,
        "sku": "BK-FOOD-002",
        "title": "Rosier Raw Wild Forest Honey - Unfiltered & Unheated (500g)",
        "brand": "Rosier Foods",
        "category": "Daily Essentials & Groceries",
        "price": 799,
        "original_price": 999,
        "stock": 28,
        "rating": 4.8,
        "rating_count": 3120,
        "image_url": "https://images.unsplash.com/photo-1587049352846-4a222e784d38?w=500&auto=format&fit=crop&q=80",
        "description": "Ethically harvested from wild beehives in pristine forest reserves. Rich in natural bee pollen, live digestive enzymes, and antioxidants.",
        "cities": ["Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai"]
    },
    {
        "id": 21,
        "sku": "BK-FOOD-003",
        "title": "Wood Pressed Kachi Ghani Mustard Oil (Cold-Pressed 1L Bottle)",
        "brand": "Rosier Foods",
        "category": "Daily Essentials & Groceries",
        "price": 389,
        "original_price": 490,
        "stock": 40,
        "rating": 4.7,
        "rating_count": 2740,
        "image_url": "https://images.unsplash.com/photo-1474979266404-7eaacbcd87c5?w=500&auto=format&fit=crop&q=80",
        "description": "Traditional wooden chekku cold-pressed yellow mustard oil preserving natural pungent aroma, rich omega-3 fatty acids, and natural tocopherols.",
        "cities": ["Mumbai", "Delhi", "Kolkata", "Bengaluru"]
    },
    {
        "id": 22,
        "sku": "BK-FOOD-004",
        "title": "Organic Emmer Khapli Ancient Wheat Atta (Stone-Ground 5kg)",
        "brand": "Rosier Foods",
        "category": "Daily Essentials & Groceries",
        "price": 549,
        "original_price": 650,
        "stock": 25,
        "rating": 4.9,
        "rating_count": 1980,
        "image_url": "https://images.unsplash.com/photo-1574323347407-f5e1ad6d020b?w=500&auto=format&fit=crop&q=80",
        "description": "Heritage low-gluten ancient grain khapli wheat, slow stone-milled to retain dietary fiber, magnesium, and natural complex vitamins for better digestion.",
        "cities": ["Mumbai", "Bengaluru", "Delhi", "Hyderabad"]
    },
    {
        "id": 23,
        "sku": "BK-FOOD-005",
        "title": "Grade-A Certified Kashmiri Mongra Saffron (1 Gram Tin)",
        "brand": "Pampore Heritage",
        "category": "Daily Essentials & Groceries",
        "price": 499,
        "original_price": 650,
        "stock": 50,
        "rating": 5.0,
        "rating_count": 920,
        "image_url": "https://images.unsplash.com/photo-1615485290382-441e4d049cb5?w=500&auto=format&fit=crop&q=80",
        "description": "100% pure all-red Kashmiri Mongra saffron stigmas. Exceptional natural crocin coloring potency, sweet aroma, and antioxidant richness.",
        "cities": ["Mumbai", "Bengaluru", "Delhi", "Hyderabad", "Chennai", "Kolkata"]
    },
    {
        "id": 24,
        "sku": "BK-FOOD-006",
        "title": "Organic Lakadong High-Curcumin Turmeric Powder (250g Jar)",
        "brand": "Rosier Foods",
        "category": "Daily Essentials & Groceries",
        "price": 299,
        "original_price": 380,
        "stock": 45,
        "rating": 4.8,
        "rating_count": 1640,
        "image_url": "https://images.unsplash.com/photo-1615485500704-8e990f9900f7?w=500&auto=format&fit=crop&q=80",
        "description": "Originating from Meghalaya's Jaintia Hills with 7.5%+ natural curcumin content. Powerful natural anti-inflammatory and restorative immunity booster.",
        "cities": ["Mumbai", "Delhi", "Bengaluru", "Chennai"]
    },
    {
        "id": 25,
        "sku": "BK-FOOD-007",
        "title": "Single-Origin Coorg Arabica Coffee Beans Medium-Dark Roast (250g)",
        "brand": "Coorg Roastmasters",
        "category": "Daily Essentials & Groceries",
        "price": 449,
        "original_price": 550,
        "stock": 32,
        "rating": 4.7,
        "rating_count": 2150,
        "image_url": "https://images.unsplash.com/photo-1559056199-641a0ac8b55e?w=500&auto=format&fit=crop&q=80",
        "description": "Shade-grown, handpicked Arabica beans roasted in small batches. Tasting notes of dark chocolate, roasted almond, and sweet wild citrus.",
        "cities": ["Bengaluru", "Mumbai", "Hyderabad", "Chennai", "Delhi"]
    },
    {
        "id": 26,
        "sku": "BK-MOB-004",
        "title": "Google Pixel 8 (Hazel, 128GB Storage, 8GB RAM)",
        "brand": "Google",
        "category": "Mobiles & Tablets",
        "price": 63999,
        "original_price": 75999,
        "stock": 8,
        "rating": 4.6,
        "rating_count": 1820,
        "image_url": "https://images.unsplash.com/photo-1598327105666-5b89351aff97?w=500&auto=format&fit=crop&q=80",
        "description": "Google Tensor G3 chip, best-in-class computational photography with Best Take and Magic Editor, with 7 years of promised OS updates.",
        "cities": ["Mumbai", "Bengaluru", "Delhi", "Hyderabad"]
    },
    {
        "id": 27,
        "sku": "BK-MOB-005",
        "title": "Apple iPad Air M2 (11-inch Liquid Retina, Wi-Fi 128GB) - Space Grey",
        "brand": "Apple",
        "category": "Mobiles & Tablets",
        "price": 59900,
        "original_price": 64900,
        "stock": 12,
        "rating": 4.8,
        "rating_count": 1290,
        "image_url": "https://images.unsplash.com/photo-1544244015-0df4b3ffc6b0?w=500&auto=format&fit=crop&q=80",
        "description": "Supercharged by Apple M2 chip. 11-inch Liquid Retina display with P3 wide color, landscape 12MP front camera with Center Stage.",
        "cities": ["Mumbai", "Bengaluru", "Delhi", "Chennai"]
    },
    {
        "id": 28,
        "sku": "BK-MOB-006",
        "title": "OnePlus Pad Go (11.35-inch 2.4K Display, 8GB RAM, 128GB LTE)",
        "brand": "OnePlus",
        "category": "Mobiles & Tablets",
        "price": 21999,
        "original_price": 24999,
        "stock": 18,
        "rating": 4.4,
        "rating_count": 3410,
        "image_url": "https://images.unsplash.com/photo-1561154464-82e9adf32764?w=500&auto=format&fit=crop&q=80",
        "description": "Ultra-vivid 2.4K eye-care display with 7:5 ReadFit screen ratio, quad speakers with Dolby Atmos, and 8000mAh long-lasting battery.",
        "cities": ["Mumbai", "Bengaluru", "Delhi", "Hyderabad", "Kolkata"]
    },
    {
        "id": 29,
        "sku": "BK-LAP-004",
        "title": "ASUS ROG Zephyrus G14 OLED Gaming Laptop (Ryzen 9, RTX 4060, 16GB, 1TB)",
        "brand": "ASUS",
        "category": "Laptops & Computers",
        "price": 149990,
        "original_price": 174990,
        "stock": 5,
        "rating": 4.9,
        "rating_count": 640,
        "image_url": "https://images.unsplash.com/photo-1603302576837-37561b2e2302?w=500&auto=format&fit=crop&q=80",
        "description": "Ultra-portable 1.5kg gaming notebook with 3K 120Hz ROG Nebula OLED display, CNC aluminum chassis, and dual Arc Flow fans cooling.",
        "cities": ["Bengaluru", "Mumbai", "Delhi"]
    },
    {
        "id": 30,
        "sku": "BK-LAP-005",
        "title": "HP Envy x360 2-in-1 Laptop (Intel Core i5 13th Gen, 16GB RAM, 512GB SSD)",
        "brand": "HP",
        "category": "Laptops & Computers",
        "price": 78990,
        "original_price": 92500,
        "stock": 9,
        "rating": 4.5,
        "rating_count": 1120,
        "image_url": "https://images.unsplash.com/photo-1588872657578-7efd1f1555ed?w=500&auto=format&fit=crop&q=80",
        "description": "360-degree convertible touchscreen laptop with rechargeable pen, 5MP IR webcam with auto-framing, and Audio by Bang & Olufsen.",
        "cities": ["Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai"]
    },
    {
        "id": 31,
        "sku": "BK-ACC-001",
        "title": "Logitech MX Master 3S Ergonomic Wireless Performance Mouse",
        "brand": "Logitech",
        "category": "Laptops & Computers",
        "price": 8995,
        "original_price": 10995,
        "stock": 22,
        "rating": 4.9,
        "rating_count": 5120,
        "image_url": "https://images.unsplash.com/photo-1615663245857-ac93bb7c39e7?w=500&auto=format&fit=crop&q=80",
        "description": "Quiet Clicks technology with 8K DPI any-surface glass tracking sensor and MagSpeed electromagnetic scroll wheel.",
        "cities": ["Mumbai", "Bengaluru", "Delhi", "Chennai", "Hyderabad", "Kolkata"]
    },
    {
        "id": 32,
        "sku": "BK-ACC-002",
        "title": "Keychron K2 V2 Wireless Bluetooth Mechanical Keyboard (RGB Backlit)",
        "brand": "Keychron",
        "category": "Laptops & Computers",
        "price": 7499,
        "original_price": 8999,
        "stock": 14,
        "rating": 4.7,
        "rating_count": 1840,
        "image_url": "https://images.unsplash.com/photo-1587829741301-dc798b83add3?w=500&auto=format&fit=crop&q=80",
        "description": "Compact 75% layout wireless mechanical keyboard with Gateron G Pro Brown switches, dual Mac/Windows compatibility and 4000mAh battery.",
        "cities": ["Bengaluru", "Mumbai", "Delhi", "Hyderabad"]
    },
    {
        "id": 33,
        "sku": "BK-AUD-004",
        "title": "Sony WH-1000XM5 Wireless Noise Cancelling Headphones (Silver)",
        "brand": "Sony",
        "category": "Audio & Wearables",
        "price": 28990,
        "original_price": 34990,
        "stock": 7,
        "rating": 4.8,
        "rating_count": 4210,
        "image_url": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=500&auto=format&fit=crop&q=80",
        "description": "Dual processor Auto NC Optimizer, 8 precision microphones, carbon fiber 30mm driver units and 30-hour battery life with quick charge.",
        "cities": ["Mumbai", "Bengaluru", "Delhi", "Hyderabad", "Chennai"]
    },
    {
        "id": 34,
        "sku": "BK-AUD-005",
        "title": "Apple AirPods Pro (2nd Gen) with MagSafe Case (USB-C)",
        "brand": "Apple",
        "category": "Audio & Wearables",
        "price": 22990,
        "original_price": 24900,
        "stock": 15,
        "rating": 4.8,
        "rating_count": 8930,
        "image_url": "https://images.unsplash.com/photo-1600294037681-c80b4cb5b434?w=500&auto=format&fit=crop&q=80",
        "description": "Apple H2 chip, up to 2x more Active Noise Cancellation, Adaptive Audio, Personalized Spatial Audio with dynamic head tracking.",
        "cities": ["Mumbai", "Bengaluru", "Delhi", "Hyderabad", "Chennai", "Kolkata"]
    },
    {
        "id": 35,
        "sku": "BK-AUD-006",
        "title": "boAt Nirvana Ion ANC True Wireless Earbuds with 120H Playtime",
        "brand": "boAt",
        "category": "Audio & Wearables",
        "price": 2499,
        "original_price": 7990,
        "stock": 45,
        "rating": 4.3,
        "rating_count": 12840,
        "image_url": "https://images.unsplash.com/photo-1590658268037-6bf12165a8df?w=500&auto=format&fit=crop&q=80",
        "description": "32dB Active Noise Cancellation, crystal bionic sound with dual EQ modes, in-ear detection and massive 120 hours total playback.",
        "cities": ["Mumbai", "Delhi", "Bengaluru", "Kolkata", "Hyderabad", "Chennai"]
    },
    {
        "id": 36,
        "sku": "BK-AUD-007",
        "title": "Marshall Kilburn II Portable Bluetooth Speaker (Black and Brass)",
        "brand": "Marshall",
        "category": "Audio & Wearables",
        "price": 27999,
        "original_price": 31999,
        "stock": 6,
        "rating": 4.9,
        "rating_count": 1560,
        "image_url": "https://images.unsplash.com/photo-1545454675-3531b543be5d?w=500&auto=format&fit=crop&q=80",
        "description": "Multi-directional stereophonic sound, rugged IPX2 water-resistant exterior, analog control knobs and 20+ hours of portable playtime.",
        "cities": ["Mumbai", "Bengaluru", "Delhi"]
    },
    {
        "id": 37,
        "sku": "BK-HOM-004",
        "title": "Philips Digital Air Fryer HD9252 with Rapid Air Technology (4.1L)",
        "brand": "Philips",
        "category": "Home & Kitchen",
        "price": 6999,
        "original_price": 10995,
        "stock": 19,
        "rating": 4.6,
        "rating_count": 6780,
        "image_url": "https://images.unsplash.com/photo-1585515320310-259814833e62?w=500&auto=format&fit=crop&q=80",
        "description": "Cook delicious meals with up to 90% less oil. 7 preset touchscreen cooking options and NutriU recipe app integration.",
        "cities": ["Mumbai", "Bengaluru", "Delhi", "Hyderabad", "Chennai", "Kolkata"]
    },
    {
        "id": 38,
        "sku": "BK-HOM-005",
        "title": "Prestige Deluxe Alpha Stainless Steel Pressure Cooker (5 Litre)",
        "brand": "Prestige",
        "category": "Home & Kitchen",
        "price": 2895,
        "original_price": 3550,
        "stock": 26,
        "rating": 4.7,
        "rating_count": 9430,
        "image_url": "https://images.unsplash.com/photo-1584269600464-37b1b58a9fe7?w=500&auto=format&fit=crop&q=80",
        "description": "Heavy-gauge 304 food-grade stainless steel with induction and gas compatible Alpha bottom and controlled gasket release safety system.",
        "cities": ["Mumbai", "Delhi", "Bengaluru", "Chennai", "Hyderabad", "Kolkata"]
    },
    {
        "id": 39,
        "sku": "BK-HOM-006",
        "title": "Dyson V12 Detect Slim Total Clean Cordless Vacuum Cleaner",
        "brand": "Dyson",
        "category": "Home & Kitchen",
        "price": 49900,
        "original_price": 55900,
        "stock": 4,
        "rating": 4.8,
        "rating_count": 890,
        "image_url": "https://images.unsplash.com/photo-1558317374-067fb5f30001?w=500&auto=format&fit=crop&q=80",
        "description": "Illuminating cleaner head reveals microscopic dust, Piezo acoustic sensor measures dust particles, and lightweight ergonomic 2.2kg body.",
        "cities": ["Mumbai", "Bengaluru", "Delhi"]
    },
    {
        "id": 40,
        "sku": "BK-HOM-007",
        "title": "Wonderchef Nutri-Blend Compact Mixer Grinder & Blender (400W)",
        "brand": "Wonderchef",
        "category": "Home & Kitchen",
        "price": 2799,
        "original_price": 4500,
        "stock": 30,
        "rating": 4.5,
        "rating_count": 8210,
        "image_url": "https://images.unsplash.com/photo-1570222094114-d054a817e56b?w=500&auto=format&fit=crop&q=80",
        "description": "High-speed 22,000 RPM precision surgical stainless steel blades, break-resistant transparent polycarbonate jars with on-the-go sipper lids.",
        "cities": ["Mumbai", "Bengaluru", "Delhi", "Hyderabad", "Chennai"]
    },
    {
        "id": 41,
        "sku": "BK-HOM-008",
        "title": "Kent Grand Plus RO+UV+UF+TDS Mineral Water Purifier (9L)",
        "brand": "Kent",
        "category": "Home & Kitchen",
        "price": 14999,
        "original_price": 20000,
        "stock": 14,
        "rating": 4.6,
        "rating_count": 7320,
        "image_url": "https://images.unsplash.com/photo-1585698150772-5a9d6e4cb73f?w=500&auto=format&fit=crop&q=80",
        "description": "Multiple purification with in-tank UV disinfection, Mineral RO technology retains essential natural minerals in drinking water.",
        "cities": ["Delhi", "Mumbai", "Bengaluru", "Hyderabad", "Kolkata"]
    },
    {
        "id": 42,
        "sku": "BK-FAS-010",
        "title": "Fabindia Men Handloom Fine Khadi Cotton Short Kurta (Beige)",
        "brand": "Fabindia",
        "category": "Fashion & Apparel",
        "price": 1890,
        "original_price": 2290,
        "stock": 24,
        "rating": 4.6,
        "rating_count": 3120,
        "image_url": "https://images.unsplash.com/photo-1596755094514-f87e34085b2c?w=500&auto=format&fit=crop&q=80",
        "description": "Artisan spun pure khadi cotton kurta with Chinese mandarin collar, full sleeves, side slits, and shell buttons for natural summer comfort.",
        "cities": ["Delhi", "Mumbai", "Bengaluru", "Kolkata", "Hyderabad", "Chennai"]
    },
    {
        "id": 43,
        "sku": "BK-FAS-005",
        "title": "Manyavar Royal Jacquard Silk Festive Kurta & Churidar Set",
        "brand": "Manyavar",
        "category": "Fashion & Apparel",
        "price": 4999,
        "original_price": 6999,
        "stock": 16,
        "rating": 4.8,
        "rating_count": 2450,
        "image_url": "https://images.unsplash.com/photo-1617137984095-74e4e5e3613f?w=500&auto=format&fit=crop&q=80",
        "description": "Intricate self-woven floral jacquard silk kurta in royal cream with matching dupion silk churidar pyjama, perfect for festive celebrations.",
        "cities": ["Mumbai", "Delhi", "Bengaluru", "Kolkata"]
    },
    {
        "id": 44,
        "sku": "BK-FAS-006",
        "title": "Ray-Ban Classic Polarized Aviator Sunglasses (Gold Frame, G-15 Green)",
        "brand": "Ray-Ban",
        "category": "Fashion & Apparel",
        "price": 9890,
        "original_price": 11590,
        "stock": 11,
        "rating": 4.9,
        "rating_count": 4780,
        "image_url": "https://images.unsplash.com/photo-1511499767150-a48a237f0083?w=500&auto=format&fit=crop&q=80",
        "description": "The timeless icon originally created in 1937 for aviators. 100% UV400 polarized crystal lenses block reflective glare and eye fatigue.",
        "cities": ["Mumbai", "Bengaluru", "Delhi", "Hyderabad"]
    },
    {
        "id": 45,
        "sku": "BK-FAS-007",
        "title": "Woodland Men Rugged Camel Leather Ankle Trekking Boots",
        "brand": "Woodland",
        "category": "Fashion & Apparel",
        "price": 4495,
        "original_price": 5495,
        "stock": 20,
        "rating": 4.6,
        "rating_count": 6890,
        "image_url": "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=500&auto=format&fit=crop&q=80",
        "description": "Durable genuine nubuck leather upper with grooved high-traction rubber outsole designed for all-terrain trekking and urban wear.",
        "cities": ["Delhi", "Mumbai", "Bengaluru", "Kolkata", "Hyderabad"]
    },
    {
        "id": 46,
        "sku": "BK-FAS-008",
        "title": "Titan Edge Men Ultra-Slim Ceramic Analog Watch (Sapphire Glass)",
        "brand": "Titan",
        "category": "Fashion & Apparel",
        "price": 12995,
        "original_price": 14995,
        "stock": 10,
        "rating": 4.9,
        "rating_count": 1830,
        "image_url": "https://images.unsplash.com/photo-1524805444758-089113d48a6d?w=500&auto=format&fit=crop&q=80",
        "description": "One of the world's slimmest quartz watches at just 4.4mm thickness. High-grade scratch-resistant ceramic case with sapphire crystal.",
        "cities": ["Bengaluru", "Mumbai", "Delhi", "Chennai"]
    },
    {
        "id": 47,
        "sku": "BK-BEA-001",
        "title": "Forest Essentials Soundarya Radiance 24K Gold Face Cream (50g)",
        "brand": "Forest Essentials",
        "category": "Beauty & Personal Care",
        "price": 5600,
        "original_price": 6200,
        "stock": 15,
        "rating": 4.9,
        "rating_count": 2180,
        "image_url": "https://images.unsplash.com/photo-1556228720-195a672e8a03?w=500&auto=format&fit=crop&q=80",
        "description": "Traditional Ayurvedic formulation infused with 24 Karat gold bhasma, saffron, cow's ghee and sweet almond cold-pressed oil for luminous glow.",
        "cities": ["Delhi", "Mumbai", "Bengaluru", "Hyderabad"]
    },
    {
        "id": 48,
        "sku": "BK-BEA-002",
        "title": "Kama Ayurveda Pure Kumkumadi Miraculous Ayurvedic Beauty Fluid (12ml)",
        "brand": "Kama Ayurveda",
        "category": "Beauty & Personal Care",
        "price": 3195,
        "original_price": 3595,
        "stock": 20,
        "rating": 4.8,
        "rating_count": 3490,
        "image_url": "https://images.unsplash.com/photo-1608248597359-399042b58efb?w=500&auto=format&fit=crop&q=80",
        "description": "Prescribed in the Ashtanga Hrudaya, 100% natural night serum made with rare Kashmiri saffron and lotus extracts to brighten and smooth pigmentation.",
        "cities": ["Mumbai", "Bengaluru", "Delhi", "Chennai"]
    },
    {
        "id": 49,
        "sku": "BK-BEA-003",
        "title": "Mamaearth Onion Hair Oil with Redensyl for Hair Fall Control (250ml)",
        "brand": "Mamaearth",
        "category": "Beauty & Personal Care",
        "price": 539,
        "original_price": 599,
        "stock": 55,
        "rating": 4.5,
        "rating_count": 14920,
        "image_url": "https://images.unsplash.com/photo-1526947425960-945c6e72858f?w=500&auto=format&fit=crop&q=80",
        "description": "Rich in sulfur, potassium and antioxidants, blended with almond oil and bhringraj to strengthen roots and nourish hair scalp naturally.",
        "cities": ["Mumbai", "Delhi", "Bengaluru", "Kolkata", "Hyderabad", "Chennai"]
    },
    {
        "id": 50,
        "sku": "BK-HOM-009",
        "title": "Sujata Powermatic Plus 900W Juicer Mixer Grinder with Jar",
        "brand": "Sujata",
        "category": "Home & Kitchen",
        "price": 5899,
        "original_price": 7250,
        "stock": 17,
        "rating": 4.8,
        "rating_count": 11340,
        "image_url": "https://images.unsplash.com/photo-1570222094114-d054a817e56b?w=500&auto=format&fit=crop&q=80",
        "description": "Heavy-duty 900 watt motor with double ball bearings, continuous 90 minutes run-time and honeycomb mesh juicer for maximum juice extraction.",
        "cities": ["Delhi", "Mumbai", "Bengaluru", "Kolkata"]
    },
    {
        "id": 51,
        "sku": "BK-FOOD-008",
        "title": "Rosier Stone-Pressed Cold Virgin Coconut Oil (500ml Glass Jar)",
        "brand": "Rosier Foods",
        "category": "Daily Essentials & Groceries",
        "price": 429,
        "original_price": 520,
        "stock": 38,
        "rating": 4.9,
        "rating_count": 1870,
        "image_url": "https://images.unsplash.com/photo-1474979266404-7eaacbcd87c5?w=500&auto=format&fit=crop&q=80",
        "description": "Extracted from freshly grated mature coconuts without heating. Unbleached, unrefined with pure natural aroma and healthy medium chain triglycerides.",
        "cities": ["Chennai", "Bengaluru", "Mumbai", "Hyderabad", "Delhi"]
    },
    {
        "id": 52,
        "sku": "BK-FOOD-009",
        "title": "Himalayan Mineral Pink Rock Salt Granules (1kg Eco-Pouch)",
        "brand": "Rosier Foods",
        "category": "Daily Essentials & Groceries",
        "price": 149,
        "original_price": 199,
        "stock": 60,
        "rating": 4.8,
        "rating_count": 4290,
        "image_url": "https://images.unsplash.com/photo-1518843875459-f738682238a6?w=500&auto=format&fit=crop&q=80",
        "description": "100% unrefined natural pink crystalline rock salt containing 84+ essential trace minerals including iron, calcium, magnesium, and potassium.",
        "cities": ["Mumbai", "Bengaluru", "Delhi", "Hyderabad", "Chennai", "Kolkata"]
    }
]

SAMPLE_CUSTOMERS = [
    {
        "id": 1,
        "name": "Priya Sharma",
        "email": "priya.sharma@example.in",
        "phone": "+91 98201 12345",
        "city": "Mumbai",
        "address": "Flat 402, Sea Green Apts, Worli Sea Face, Mumbai 400030"
    },
    {
        "id": 2,
        "name": "Arjun Patel",
        "email": "arjun.patel@example.in",
        "phone": "+91 98450 67890",
        "city": "Bengaluru",
        "address": "Villa 18, Prestige Oasis, Doddaballapur Road, Bengaluru 560064"
    },
    {
        "id": 3,
        "name": "Simran Kaur",
        "email": "simran.k@example.in",
        "phone": "+91 98110 54321",
        "city": "Delhi",
        "address": "C-4/12, Safdarjung Development Area, New Delhi 110016"
    }
]

# -----------------------------------------------------------------------------
# Phase 2: Authentic Product Gallery Images by Category
# -----------------------------------------------------------------------------
CATEGORY_GALLERY_IMAGES = {
    "Daily Essentials & Groceries": [
        "https://images.unsplash.com/photo-1615485290382-441e4d049cb5?w=700&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1542838132-92c53300491e?w=700&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1506484381205-f7945653044d?w=700&auto=format&fit=crop&q=80"
    ],
    "Mobiles & Tablets": [
        "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=700&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1565849904461-04a58ad377e0?w=700&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1592750475338-74b7b21085ab?w=700&auto=format&fit=crop&q=80"
    ],
    "Laptops & Computers": [
        "https://images.unsplash.com/photo-1588872657578-7efd1f1555ed?w=700&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1541807084-5c52b6b3adef?w=700&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1496181133206-80ce9b88a853?w=700&auto=format&fit=crop&q=80"
    ],
    "Audio & Wearables": [
        "https://images.unsplash.com/photo-1546435770-a3e426bf472b?w=700&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1484704849700-f032a568e944?w=700&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=700&auto=format&fit=crop&q=80"
    ],
    "Home & Kitchen": [
        "https://images.unsplash.com/photo-1584269600464-37b1b58a9fe7?w=700&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1556911220-e15b29be8c8f?w=700&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1585515320310-259814833e62?w=700&auto=format&fit=crop&q=80"
    ],
    "Fashion & Apparel": [
        "https://images.unsplash.com/photo-1523381210434-271e8be1f52b?w=700&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1489987707025-afc232f7ea0f?w=700&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1445205170230-053b83016050?w=700&auto=format&fit=crop&q=80"
    ],
    "Beauty & Personal Care": [
        "https://images.unsplash.com/photo-1571781926291-c477ebfd024b?w=700&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1608248597359-2e7837b0d4f3?w=700&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1556228720-195a672e8a03?w=700&auto=format&fit=crop&q=80"
    ],
    "Electronics": [
        "https://images.unsplash.com/photo-1546435770-a3e426bf472b?w=700&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=700&auto=format&fit=crop&q=80",
        "https://images.unsplash.com/photo-1496181133206-80ce9b88a853?w=700&auto=format&fit=crop&q=80"
    ]
}

def get_product_gallery_seed_data(product: dict) -> list:
    """Returns 4 ordered images: 1 primary + 3 category angle shots"""
    primary_img = product.get("image_url") or "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=700"
    cat = product.get("category", "")
    angles = CATEGORY_GALLERY_IMAGES.get(cat, CATEGORY_GALLERY_IMAGES["Electronics"])
    return [
        {"image_url": primary_img, "is_primary": True, "display_order": 1},
        {"image_url": angles[0], "is_primary": False, "display_order": 2},
        {"image_url": angles[1], "is_primary": False, "display_order": 3},
        {"image_url": angles[2], "is_primary": False, "display_order": 4}
    ]

def get_product_specifications_seed_data(product: dict) -> list:
    """Generates structured specifications grouped into General, Technical/Purity, and Fulfillment"""
    cat = product.get("category", "")
    cities = product.get("cities", ["Mumbai", "Bengaluru", "Delhi"])
    hubs_str = ", ".join(cities) if isinstance(cities, list) else str(cities)

    specs = [
        {"spec_group": "General", "spec_key": "Brand", "spec_value": product.get("brand", "BharatStore")},
        {"spec_group": "General", "spec_key": "Category", "spec_value": cat},
        {"spec_group": "General", "spec_key": "Model Title", "spec_value": product.get("title", "")},
        {"spec_group": "General", "spec_key": "SKU Identifier", "spec_value": product.get("sku", "")}
    ]

    if cat == "Daily Essentials & Groceries":
        specs.extend([
            {"spec_group": "Purity & Quality", "spec_key": "Organic Certification", "spec_value": "100% NPOP & FSSAI Certified"},
            {"spec_group": "Purity & Quality", "spec_key": "Preservatives", "spec_value": "Zero Chemical Preservatives or Additives"},
            {"spec_group": "Purity & Quality", "spec_key": "Shelf Life", "spec_value": "12 Months from Manufacturing"},
            {"spec_group": "Purity & Quality", "spec_key": "Storage Advice", "spec_value": "Store in a cool, dry place away from moisture"}
        ])
    elif cat in ("Mobiles & Tablets", "Electronics"):
        specs.extend([
            {"spec_group": "Hardware & Performance", "spec_key": "Network Connectivity", "spec_value": "5G Dual SIM VoLTE Supported"},
            {"spec_group": "Hardware & Performance", "spec_key": "Display Tech", "spec_value": "High Refresh Rate OLED / Super Retina HDR"},
            {"spec_group": "Hardware & Performance", "spec_key": "Charging & Port", "spec_value": "Fast Charging Supported (USB-C)"},
            {"spec_group": "Hardware & Performance", "spec_key": "Security", "spec_value": "Biometric Authentication (Fingerprint / Face ID)"}
        ])
    elif cat == "Laptops & Computers":
        specs.extend([
            {"spec_group": "Hardware & Performance", "spec_key": "System Architecture", "spec_value": "Multi-Core High Efficiency Processor"},
            {"spec_group": "Hardware & Performance", "spec_key": "Storage Drive", "spec_value": "Ultra-Fast NVMe Solid State Drive (SSD)"},
            {"spec_group": "Hardware & Performance", "spec_key": "Display Screen", "spec_value": "Anti-Glare IPS Display, 100% sRGB Color Space"},
            {"spec_group": "Hardware & Performance", "spec_key": "Wireless Connectivity", "spec_value": "Wi-Fi 6 (802.11ax) + Bluetooth 5.2"}
        ])
    elif cat == "Audio & Wearables":
        specs.extend([
            {"spec_group": "Acoustics & Battery", "spec_key": "Driver Architecture", "spec_value": "High Fidelity Dynamic Neodymium Drivers"},
            {"spec_group": "Acoustics & Battery", "spec_key": "Noise Cancellation", "spec_value": "Active Noise Cancellation (ANC) with Ambient Mode"},
            {"spec_group": "Acoustics & Battery", "spec_key": "Total Playtime", "spec_value": "Up to 30+ Hours Battery Life with Fast Charge"},
            {"spec_group": "Acoustics & Battery", "spec_key": "Ingress Protection", "spec_value": "IPX4 Sweat & Splash Resistant"}
        ])
    elif cat == "Home & Kitchen":
        specs.extend([
            {"spec_group": "Material & Build", "spec_key": "Construction Material", "spec_value": "Food-Grade Stainless Steel / Heavy Anodized Aluminum"},
            {"spec_group": "Material & Build", "spec_key": "Dishwasher Safe", "spec_value": "Yes, Dishwasher & Oven Safe"},
            {"spec_group": "Material & Build", "spec_key": "Safety Standards", "spec_value": "ISI Certified Thermal Safety Valve"}
        ])
    elif cat == "Fashion & Apparel":
        specs.extend([
            {"spec_group": "Fabric & Fit", "spec_key": "Material Composition", "spec_value": "100% Breathable Combed Cotton Bio-Washed"},
            {"spec_group": "Fabric & Fit", "spec_key": "Silhouette", "spec_value": "Contemporary Tailored Comfort Fit"},
            {"spec_group": "Fabric & Fit", "spec_key": "Wash Care", "spec_value": "Machine Wash Cold, Gentle Cycle, Warm Iron"}
        ])
    elif cat == "Beauty & Personal Care":
        specs.extend([
            {"spec_group": "Formulation", "spec_key": "Skin Compatibility", "spec_value": "Dermatologically Tested for All Skin Types"},
            {"spec_group": "Formulation", "spec_key": "Key Actives", "spec_value": "100% Vegan, Cruelty-Free, Paraben-Free"},
            {"spec_group": "Formulation", "spec_key": "Application", "spec_value": "Apply daily on cleansed skin for maximum radiance"}
        ])

    specs.extend([
        {"spec_group": "Fulfillment & Guarantee", "spec_key": "Physical Store Hubs", "spec_value": hubs_str},
        {"spec_group": "Fulfillment & Guarantee", "spec_key": "Delivery Commitment", "spec_value": "Instant 2-Hour Express Delivery or Same-Day Pickup"},
        {"spec_group": "Fulfillment & Guarantee", "spec_key": "Return Policy", "spec_value": "7-Day No-Questions-Asked Hub Replacement Guarantee"}
    ])

    return specs

SEED_CUSTOMER_REVIEWS = [
    {
        "product_id": 1,
        "customer_id": 1,
        "rating": 5,
        "title": "Superb Build Quality and Battery Life!",
        "comment": "Upgraded from my older phone. The dynamic island and battery life are phenomenal. Received via Bengaluru hub in under 90 minutes with sealed packaging!"
    },
    {
        "product_id": 1,
        "customer_id": 2,
        "rating": 5,
        "title": "Flawless Performance & Camera",
        "comment": "The portrait mode and low-light photography are unmatched. Picked up from the physical store counter without waiting in line."
    },
    {
        "product_id": 1,
        "customer_id": 3,
        "rating": 4,
        "title": "Great device, premium feel in hand",
        "comment": "Lightweight titanium-feel edges and vibrant display. Charging speed is good, and customer support was very helpful."
    },
    {
        "product_id": 2,
        "customer_id": 2,
        "rating": 5,
        "title": "Galaxy AI features are very practical",
        "comment": "Live translate and circle to search work seamlessly. Gorgeous 120Hz display with incredible outdoor brightness."
    },
    {
        "product_id": 2,
        "customer_id": 1,
        "rating": 4,
        "title": "Excellent Android flagship",
        "comment": "Camera quality is top-tier. Battery easily lasts 1.5 days under heavy usage. Fast dispatch from Mumbai MegaHub."
    },
    {
        "product_id": 4,
        "customer_id": 1,
        "rating": 5,
        "title": "Silent, Fast, and Unbeatable Battery",
        "comment": "The M2 processor is a dream. Fanless design means complete silence during compiling and rendering. Battery lasts two full days!"
    },
    {
        "product_id": 4,
        "customer_id": 2,
        "rating": 5,
        "title": "Best Laptop for Software Development",
        "comment": "Handles Docker, VS Code, and dozens of tabs without breaking a sweat. Liquid Retina screen is easy on the eyes."
    },
    {
        "product_id": 5,
        "customer_id": 3,
        "rating": 5,
        "title": "Compact Powerhouse for Windows",
        "comment": "Dell XPS keyboard is the best in class. Super slim bezels and bright 4K-like display. Very pleased with this purchase."
    },
    {
        "product_id": 9,
        "customer_id": 2,
        "rating": 5,
        "title": "Industry Leading Noise Cancellation",
        "comment": "Cuts out train and office noise completely. Sound stage is wide and microphone is crystal clear on Zoom calls."
    },
    {
        "product_id": 9,
        "customer_id": 1,
        "rating": 4,
        "title": "Comfortable for all-day wearing",
        "comment": "Extremely soft cushions that don't press on glasses. Companion app offers deep EQ customization."
    },
    {
        "product_id": 14,
        "customer_id": 3,
        "rating": 5,
        "title": "Authentic Bilona Aroma and Pure Taste",
        "comment": "Reminds me of traditional homemade ghee from our village. Danedar texture and heavenly aroma. Will be reordering regularly!"
    },
    {
        "product_id": 14,
        "customer_id": 1,
        "rating": 5,
        "title": "Gold standard of pure organic ghee",
        "comment": "Certified organic with verifiable batch laboratory reports. Delivered in heavy glass jar safe from damage."
    },
    {
        "product_id": 15,
        "customer_id": 2,
        "rating": 5,
        "title": "Rich Wild Forest Honey",
        "comment": "Raw, unpasteurized, and full of natural pollen. You can taste the purity compared to supermarket processed honey."
    },
    {
        "product_id": 20,
        "customer_id": 1,
        "rating": 5,
        "title": "Induction base and heavy build",
        "comment": "Prestige cooker cooks evenly on both gas and induction. Pressure indicator gives complete peace of mind."
    },
    {
        "product_id": 25,
        "customer_id": 3,
        "rating": 5,
        "title": "100% Breathable Cotton Fabric",
        "comment": "Perfect fit, does not shrink after washing. Stitching is solid and color stays vibrant."
    }
]

