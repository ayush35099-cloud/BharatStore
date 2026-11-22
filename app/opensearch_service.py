"""
BharatKart OpenSearch Service
Implements full-text fuzzy typo-tolerant search and faceted filtering
for Aiven OpenSearch, with a matching local fallback engine.
Enhanced for Phase 9: Mode-Aware OpenSearch with physical store inventory integration.
"""

import logging
import json
import math
from collections import Counter
from typing import Dict, Any, List, Optional
from app.config import Config

logger = logging.getLogger("BharatKart.OpenSearch")

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

def is_grocery_product_item(item: Dict[str, Any]) -> bool:
    """Helper to verify if a product record is strictly grocery."""
    if not item or not isinstance(item, dict):
        return False
    cat = (item.get("category") or "").strip()
    sub = (item.get("sub_category") or "").strip()
    if cat in NON_GROCERY_CATEGORIES or sub in NON_GROCERY_CATEGORIES:
        return False
    if cat == "Daily Essentials & Groceries" or cat in ALLOWED_RETAIL_CATEGORIES:
        return True
    if sub in ALLOWED_RETAIL_CATEGORIES:
        return True
    return False

def _levenshtein_distance(s1: str, s2: str) -> int:
    """Calculates Levenshtein edit distance for typo tolerance"""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

class OpenSearchService:
    def __init__(self):
        self.is_live_opensearch = False
        self.index_name = Config.AIVEN_OPENSEARCH_INDEX
        self.client = None
        self._local_index: Dict[int, Dict[str, Any]] = {}
        self._store_inventories: Dict[int, Dict[int, Dict[str, Any]]] = {}
        self._init_opensearch()

    def _init_opensearch(self):
        if Config.is_opensearch_configured():
            try:
                from opensearchpy import OpenSearch
                auth = None
                if Config.AIVEN_OPENSEARCH_USER and Config.AIVEN_OPENSEARCH_PASSWORD:
                    auth = (Config.AIVEN_OPENSEARCH_USER, Config.AIVEN_OPENSEARCH_PASSWORD)
                
                self.client = OpenSearch(
                    hosts=[Config.AIVEN_OPENSEARCH_URL],
                    http_auth=auth,
                    use_ssl=True,
                    verify_certs=True,
                    ssl_assert_hostname=False,
                    ssl_show_warn=False,
                    timeout=10
                )
                
                # Ping
                info = self.client.info()
                self.is_live_opensearch = True
                logger.info(f"Connected to Aiven OpenSearch (Cluster: {info.get('cluster_name')})")
                self._ensure_index_and_mappings()
                return
            except Exception as e:
                logger.warning(f"Could not connect to Aiven OpenSearch: {e}. Using local OpenSearch simulation.")

        self.is_live_opensearch = False
        logger.info("Local OpenSearch search engine active.")

    def _ensure_index_and_mappings(self):
        if not self.is_live_opensearch or not self.client:
            return
        
        index_body = {
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
                "analysis": {
                    "analyzer": {
                        "product_analyzer": {
                            "type": "custom",
                            "tokenizer": "standard",
                            "filter": ["lowercase", "trim"]
                        }
                    }
                }
            },
            "mappings": {
                "properties": {
                    "id": {"type": "integer"},
                    "sku": {"type": "keyword"},
                    "title": {"type": "text", "analyzer": "product_analyzer"},
                    "brand": {"type": "keyword"},
                    "category": {"type": "keyword"},
                    "sub_category": {"type": "keyword"},
                    "price": {"type": "float"},
                    "original_price": {"type": "float"},
                    "stock": {"type": "integer"},
                    "rating": {"type": "float"},
                    "rating_count": {"type": "integer"},
                    "image_url": {"type": "keyword", "index": False},
                    "description": {"type": "text"},
                    "cities": {"type": "keyword"}
                }
            }
        }

        try:
            if not self.client.indices.exists(index=self.index_name):
                self.client.indices.create(index=self.index_name, body=index_body)
                logger.info(f"Created OpenSearch index '{self.index_name}' with fuzzy schema.")
        except Exception as e:
            logger.error(f"Error checking/creating index: {e}")

    def index_all_products(self, products: List[Dict[str, Any]]):
        """Ingests full catalog into OpenSearch and local search cache"""
        for p in products:
            self._local_index[p["id"]] = dict(p)

        if self.is_live_opensearch and self.client:
            try:
                for p in products:
                    self.client.index(
                        index=self.index_name,
                        id=p["id"],
                        body=p,
                        refresh=True
                    )
                logger.info(f"Successfully indexed {len(products)} products into Aiven OpenSearch '{self.index_name}'")
            except Exception as e:
                logger.error(f"Failed to bulk index to Aiven OpenSearch: {e}")

    # -------------------------------------------------------------------------
    # Store-Specific Inventory Indexing (Phase 9)
    # -------------------------------------------------------------------------
    def index_store_inventory(self, store_id: int, items: List[Dict[str, Any]]):
        """Indexes inventory records for a specific physical store."""
        if store_id not in self._store_inventories:
            self._store_inventories[store_id] = {}
        for it in items:
            pid = it.get("product_id")
            if not pid:
                continue
            sq = int(it.get("stock_quantity", 0))
            ia = bool(it.get("is_available", True) and sq > 0)
            self._store_inventories[store_id][pid] = {
                "id": it.get("id"),
                "store_id": store_id,
                "product_id": pid,
                "selling_price": float(it.get("selling_price", 0.0)),
                "original_price": float(it.get("original_price")) if it.get("original_price") is not None else float(it.get("selling_price", 0.0)),
                "stock_quantity": sq,
                "is_available": ia,
                "low_stock_threshold": int(it.get("low_stock_threshold", 5)),
                "updated_at": it.get("updated_at")
            }

    def index_all_store_inventories(self, store_inventories: Dict[int, List[Dict[str, Any]]]):
        """Indexes inventory records across multiple physical stores."""
        for s_id, items in store_inventories.items():
            self.index_store_inventory(s_id, items)

    def update_store_inventory_item(
        self,
        store_id: int,
        product_id: int,
        selling_price: Optional[float] = None,
        stock_quantity: Optional[int] = None,
        is_available: Optional[bool] = None,
        original_price: Optional[float] = None
    ):
        """Keeps store inventory cache in exact synchronization with database updates."""
        if store_id not in self._store_inventories:
            self._store_inventories[store_id] = {}

        curr = self._store_inventories[store_id].get(product_id, {})
        sp = float(selling_price) if selling_price is not None else curr.get("selling_price", 0.0)
        op = float(original_price) if original_price is not None else curr.get("original_price", sp)
        sq = int(stock_quantity) if stock_quantity is not None else curr.get("stock_quantity", 0)
        ia = bool(is_available if is_available is not None else (curr.get("is_available", True) and sq > 0))
        if sq <= 0:
            ia = False

        self._store_inventories[store_id][product_id] = {
            "store_id": store_id,
            "product_id": product_id,
            "selling_price": sp,
            "original_price": op,
            "stock_quantity": sq,
            "is_available": ia
        }

    def remove_store_inventory_item(self, store_id: int, product_id: int):
        """Removes a store inventory mapping when deleted."""
        if store_id in self._store_inventories:
            self._store_inventories[store_id].pop(product_id, None)

    def get_store_inventory_data(self, store_id: int) -> Dict[int, Dict[str, Any]]:
        """Returns indexed inventory for store, lazy-loading from database if necessary."""
        if store_id not in self._store_inventories or not self._store_inventories[store_id]:
            try:
                from app.database import db_service
                items = db_service.get_store_inventory(store_id)
                self.index_store_inventory(store_id, items)
            except Exception as e:
                logger.debug(f"Could not load inventory for store #{store_id}: {e}")
                self._store_inventories[store_id] = {}
        return self._store_inventories.get(store_id, {})

    def update_product_stock(self, product_id: int, new_stock: int):
        """
        Called when Kafka consumer reacts to an order event:
        keeps OpenSearch in exact synchronization with PostgreSQL inventory!
        """
        if product_id in self._local_index:
            self._local_index[product_id]["stock"] = new_stock

        if self.is_live_opensearch and self.client:
            try:
                self.client.update(
                    index=self.index_name,
                    id=product_id,
                    body={"doc": {"stock": new_stock}},
                    refresh=True
                )
                logger.info(f"[OpenSearch Sync] Synced stock for product #{product_id} -> {new_stock} units.")
            except Exception as e:
                logger.error(f"Failed to update stock in OpenSearch: {e}")

    # -------------------------------------------------------------------------
    # Mode-Aware Search with Fuzzy Typo Tolerance, Facets, and Store Pricing
    # -------------------------------------------------------------------------
    def search(
        self,
        query_text: Optional[str] = None,
        category: Optional[str] = None,
        brand: Optional[str] = None,
        city: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        shopping_mode: str = "ONLINE",
        store_id: Optional[int] = None,
        sort_by: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
        in_stock_only: bool = False
    ) -> Dict[str, Any]:
        """
        Executes a Mode-Aware OpenSearch query:
        - ONLINE Mode: Full marketplace catalog, categories, brands, price filters, sorting, pagination.
        - RETAIL_NEAR_ME Mode: Strictly grocery products only, store-specific availability,
          store-specific pricing, store stock levels, zero non-grocery items.
        """
        query_text = (query_text or "").strip()
        shopping_mode = shopping_mode.upper() if shopping_mode else "ONLINE"
        if shopping_mode not in ("ONLINE", "RETAIL_NEAR_ME"):
            shopping_mode = "RETAIL_NEAR_ME" if "RETAIL" in shopping_mode else "ONLINE"

        is_retail = (shopping_mode == "RETAIL_NEAR_ME")

        # In Retail mode, if a non-grocery category is explicitly requested, immediately return empty results
        if is_retail and category:
            cat_clean = category.strip()
            if cat_clean in NON_GROCERY_CATEGORIES:
                return {
                    "total": 0,
                    "page": page,
                    "per_page": per_page,
                    "total_pages": 1,
                    "hits": [],
                    "results": [],
                    "facets": {"categories": [], "brands": []},
                    "shopping_mode": shopping_mode,
                    "store_id": store_id,
                    "engine": "OpenSearch Mode Filter (Grocery Isolation)",
                    "dsl_query": None,
                    "fuzzy_applied": False
                }

        # Build official OpenSearch DSL Query JSON
        must_clauses = []
        filter_clauses = []
        must_not_clauses = []

        if query_text:
            must_clauses.append({
                "multi_match": {
                    "query": query_text,
                    "fields": ["title^3", "brand^2", "category", "sub_category", "description"],
                    "fuzziness": "AUTO",
                    "prefix_length": 1,
                    "operator": "or"
                }
            })
        else:
            must_clauses.append({"match_all": {}})

        if category and category.lower() != "all":
            filter_clauses.append({"term": {"category": category}})

        if brand and brand.lower() != "all":
            filter_clauses.append({"term": {"brand": brand}})

        if city and city.lower() != "all":
            filter_clauses.append({"term": {"cities": city}})

        if is_retail:
            must_not_clauses.append({"terms": {"category": list(NON_GROCERY_CATEGORIES)}})

        price_range = {}
        if min_price is not None:
            price_range["gte"] = min_price
        if max_price is not None:
            price_range["lte"] = max_price
        if price_range:
            filter_clauses.append({"range": {"price": price_range}})

        bool_body: Dict[str, Any] = {"must": must_clauses}
        if filter_clauses:
            bool_body["filter"] = filter_clauses
        if must_not_clauses:
            bool_body["must_not"] = must_not_clauses

        dsl_query = {"query": {"bool": bool_body}}

        # If connected to live OpenSearch:
        if self.is_live_opensearch and self.client:
            try:
                res = self.client.search(index=self.index_name, body=dsl_query)
                raw_hits = [h["_source"] for h in res["hits"]["hits"]]
                for idx, h in enumerate(res["hits"]["hits"]):
                    raw_hits[idx]["_score"] = h["_score"]
                return self._process_search_results(
                    raw_hits=raw_hits,
                    query_text=query_text,
                    category=category,
                    brand=brand,
                    city=city,
                    min_price=min_price,
                    max_price=max_price,
                    shopping_mode=shopping_mode,
                    store_id=store_id,
                    sort_by=sort_by,
                    page=page,
                    per_page=per_page,
                    in_stock_only=in_stock_only,
                    engine="Aiven OpenSearch (Live Cluster)",
                    dsl_query=dsl_query
                )
            except Exception as e:
                logger.error(f"Aiven OpenSearch query error: {e}. Falling back to local engine.")

        # Local Typo-Tolerant Engine Fallback
        matched = self._local_fuzzy_search(
            query=query_text,
            category=category,
            brand=brand,
            city=city,
            min_price=min_price,
            max_price=max_price,
            shopping_mode=shopping_mode,
            store_id=store_id,
            in_stock_only=in_stock_only
        )

        return self._process_search_results(
            raw_hits=matched,
            query_text=query_text,
            category=category,
            brand=brand,
            city=city,
            min_price=min_price,
            max_price=max_price,
            shopping_mode=shopping_mode,
            store_id=store_id,
            sort_by=sort_by,
            page=page,
            per_page=per_page,
            in_stock_only=in_stock_only,
            engine="OpenSearch Engine (Local Typo-Tolerant Matcher)",
            dsl_query=dsl_query
        )

    def _process_search_results(
        self,
        raw_hits: List[Dict[str, Any]],
        query_text: str,
        category: Optional[str],
        brand: Optional[str],
        city: Optional[str],
        min_price: Optional[float],
        max_price: Optional[float],
        shopping_mode: str,
        store_id: Optional[int],
        sort_by: Optional[str],
        page: int,
        per_page: int,
        in_stock_only: bool,
        engine: str,
        dsl_query: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Applies mode-aware enrichment, sorting, faceted aggregation, and pagination."""
        is_retail = (shopping_mode == "RETAIL_NEAR_ME")
        store_inv = self.get_store_inventory_data(store_id) if (is_retail and store_id) else None

        filtered: List[Dict[str, Any]] = []

        for item in raw_hits:
            hit = dict(item)

            # Strict grocery check in Retail Near Me
            if is_retail and not is_grocery_product_item(hit):
                continue

            # In Retail mode with selected store, enrich with store pricing & inventory
            if is_retail and store_id:
                inv_record = store_inv.get(hit["id"]) if store_inv else None
                if inv_record:
                    hit["price"] = inv_record["selling_price"]
                    hit["selling_price"] = inv_record["selling_price"]
                    hit["original_price"] = inv_record["original_price"]
                    hit["stock"] = inv_record["stock_quantity"]
                    hit["stock_quantity"] = inv_record["stock_quantity"]
                    hit["is_available"] = inv_record["is_available"]
                    hit["store_id"] = store_id
                else:
                    hit["stock"] = 0
                    hit["stock_quantity"] = 0
                    hit["is_available"] = False
                    hit["store_id"] = store_id

                hit["status_text"] = "In Stock" if hit["is_available"] else "Out of Stock"
                if hit["is_available"] and hit["stock"] <= 5:
                    hit["status_text"] = f"Only {hit['stock']} left!"

                if in_stock_only and not hit["is_available"]:
                    continue
            else:
                hit["selling_price"] = float(hit.get("price", 0.0))
                hit["stock_quantity"] = int(hit.get("stock", 0))
                hit["is_available"] = bool(hit["stock_quantity"] > 0)
                hit["status_text"] = "In Stock" if hit["is_available"] else "Out of Stock"
                if in_stock_only and hit["stock_quantity"] <= 0:
                    continue

            # Min/Max Price filter against effective selling price
            eff_price = float(hit.get("price", 0.0))
            if min_price is not None and eff_price < min_price:
                continue
            if max_price is not None and eff_price > max_price:
                continue

            filtered.append(hit)

        # Sorting
        if sort_by == "price_asc":
            filtered.sort(key=lambda x: (float(x.get("price", 0.0)), -float(x.get("_score", 0.0))))
        elif sort_by == "price_desc":
            filtered.sort(key=lambda x: (-float(x.get("price", 0.0)), -float(x.get("_score", 0.0))))
        elif sort_by == "rating_desc":
            filtered.sort(key=lambda x: (-float(x.get("rating", 0.0)), -float(x.get("_score", 0.0))))
        elif sort_by == "newest":
            filtered.sort(key=lambda x: (-int(x.get("id", 0)), -float(x.get("_score", 0.0))))
        else:
            # Default: relevance score descending
            filtered.sort(key=lambda x: float(x.get("_score", 0.0)), reverse=True)

        # Facets computation
        cat_counter = Counter(h.get("category") for h in filtered if h.get("category"))
        brand_counter = Counter(h.get("brand") for h in filtered if h.get("brand"))

        # Pagination
        total = len(filtered)
        page = max(1, page)
        per_page = max(1, min(per_page, 100))
        total_pages = max(1, math.ceil(total / per_page))
        start_idx = (page - 1) * per_page
        paginated_results = filtered[start_idx : start_idx + per_page]

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "hits": paginated_results,
            "results": paginated_results,
            "facets": {
                "categories": [{"name": k, "count": v} for k, v in cat_counter.most_common()],
                "brands": [{"name": k, "count": v} for k, v in brand_counter.most_common()]
            },
            "shopping_mode": shopping_mode,
            "store_id": store_id,
            "engine": engine,
            "dsl_query": dsl_query,
            "fuzzy_applied": bool(query_text)
        }

    def _local_fuzzy_search(
        self,
        query: str,
        category: Optional[str],
        brand: Optional[str],
        city: Optional[str],
        min_price: Optional[float],
        max_price: Optional[float],
        shopping_mode: str,
        store_id: Optional[int],
        in_stock_only: bool
    ) -> List[Dict[str, Any]]:
        query = query.lower().strip()
        tokens = query.split() if query else []
        is_retail = (shopping_mode == "RETAIL_NEAR_ME")
        store_inv = self.get_store_inventory_data(store_id) if (is_retail and store_id) else None

        if not self._local_index and not self.is_live_opensearch:
            try:
                from app.database import db_service
                prods = db_service.get_all_products()
                self.index_all_products(prods)
            except Exception as e:
                logger.debug(f"Lazy OpenSearch catalog index notice: {e}")

        matched = []

        for p in self._local_index.values():
            # Mode grocery isolation
            if is_retail and not is_grocery_product_item(p):
                continue

            # Store inventory enrichment & availability
            eff_price = float(p.get("price", 0.0))
            eff_stock = int(p.get("stock", 0))
            is_avail = bool(eff_stock > 0)

            if is_retail and store_id:
                inv_rec = store_inv.get(p["id"]) if store_inv else None
                if inv_rec:
                    eff_price = inv_rec["selling_price"]
                    eff_stock = inv_rec["stock_quantity"]
                    is_avail = inv_rec["is_available"]
                else:
                    eff_stock = 0
                    is_avail = False

                if in_stock_only and not is_avail:
                    continue
            else:
                if in_stock_only and eff_stock <= 0:
                    continue

            # Category filter
            if category and category.lower() != "all":
                p_cat = (p.get("category") or "").lower()
                p_sub = (p.get("sub_category") or "").lower()
                req_cat = category.lower()
                if req_cat != p_cat and req_cat != p_sub:
                    continue

            # Brand filter
            if brand and brand.lower() != "all":
                if (p.get("brand") or "").lower() != brand.lower():
                    continue

            # City filter
            if city and city.lower() != "all" and city not in p.get("cities", []):
                continue

            # Price filters
            if min_price is not None and eff_price < min_price:
                continue
            if max_price is not None and eff_price > max_price:
                continue

            # If no query string, matches all filters
            if not tokens:
                matched.append(dict(p, _score=1.0))
                continue

            score = 0.0
            p_text = f"{p['title']} {p.get('brand', '')} {p.get('category', '')} {p.get('sub_category', '')} {p.get('description', '')}".lower()
            p_words = [w.strip("(),.-'\"") for w in p_text.split()]

            matched_all_tokens = True
            for q_tok in tokens:
                token_matched = False
                best_token_score = 0.0

                # 1. Exact substring match
                if q_tok in p_text:
                    token_matched = True
                    best_token_score = 3.0 if q_tok in p['title'].lower() else 1.5
                else:
                    # 2. Fuzzy match against words with Levenshtein distance
                    # Fuzziness AUTO rule: length <= 2: 0, length 3..5: 1, length > 5: 2
                    allowed_dist = 0 if len(q_tok) <= 2 else (1 if len(q_tok) <= 5 else 2)
                    
                    for w in p_words:
                        if abs(len(w) - len(q_tok)) <= allowed_dist:
                            dist = _levenshtein_distance(q_tok, w)
                            if dist <= allowed_dist:
                                token_matched = True
                                best_token_score = max(best_token_score, 2.0 - (dist * 0.5))

                if token_matched:
                    score += best_token_score
                else:
                    matched_all_tokens = False
                    break

            if matched_all_tokens:
                matched.append(dict(p, _score=round(score, 2)))

        matched.sort(key=lambda x: x.get("_score", 0), reverse=True)
        return matched

    def get_suggestions(
        self,
        prefix_or_typo: str,
        limit: int = 5,
        shopping_mode: str = "ONLINE",
        store_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fast mode-aware autocomplete and suggestions for live search bar.
        In Retail Near Me mode, returns strictly grocery products.
        In Online Shopping mode, returns catalog-wide results.
        """
        prefix_or_typo = (prefix_or_typo or "").strip()
        if not prefix_or_typo or len(prefix_or_typo) < 2:
            return []

        search_res = self.search(
            query_text=prefix_or_typo,
            shopping_mode=shopping_mode,
            store_id=store_id,
            page=1,
            per_page=limit
        )
        hits = search_res.get("results", [])[:limit]
        suggestions = []
        for h in hits:
            suggestions.append({
                "id": h["id"],
                "title": h["title"],
                "brand": h.get("brand", ""),
                "category": h.get("category", ""),
                "price": h.get("price", 0.0),
                "selling_price": h.get("selling_price", h.get("price", 0.0)),
                "image_url": h.get("image_url", ""),
                "stock": h.get("stock", 0),
                "is_available": h.get("is_available", True),
                "store_id": h.get("store_id")
            })
        return suggestions

