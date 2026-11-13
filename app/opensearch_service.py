"""
BharatKart OpenSearch Service
Implements full-text fuzzy typo-tolerant search and faceted filtering
for Aiven OpenSearch, with a matching local fallback engine.
"""

import logging
import json
from typing import Dict, Any, List, Optional
from app.config import Config

logger = logging.getLogger("BharatKart.OpenSearch")

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
    # Search with Fuzzy Typo Tolerance & Faceted Filters
    # -------------------------------------------------------------------------
    def search(
        self,
        query_text: Optional[str] = None,
        category: Optional[str] = None,
        city: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Executes an OpenSearch query:
        - Fuzzy queries on title, brand, description (e.g. 'lapop' -> 'laptop', 'bluetoth' -> 'bluetooth')
        - Filters on category, fulfillment_city, and price range
        """
        query_text = (query_text or "").strip()

        # Build official OpenSearch DSL Query JSON
        must_clauses = []
        filter_clauses = []

        if query_text:
            must_clauses.append({
                "multi_match": {
                    "query": query_text,
                    "fields": ["title^3", "brand^2", "category", "description"],
                    "fuzziness": "AUTO",
                    "prefix_length": 1,
                    "operator": "or"
                }
            })
        else:
            must_clauses.append({"match_all": {}})

        if category and category.lower() != "all":
            filter_clauses.append({"term": {"category": category}})

        if city and city.lower() != "all":
            filter_clauses.append({"term": {"cities": city}})

        price_range = {}
        if min_price is not None:
            price_range["gte"] = min_price
        if max_price is not None:
            price_range["lte"] = max_price
        if price_range:
            filter_clauses.append({"range": {"price": price_range}})

        dsl_query = {
            "query": {
                "bool": {
                    "must": must_clauses,
                    "filter": filter_clauses
                }
            }
        }

        # If connected to live OpenSearch:
        if self.is_live_opensearch and self.client:
            try:
                res = self.client.search(index=self.index_name, body=dsl_query)
                hits = res["hits"]["hits"]
                results = []
                for h in hits:
                    source = h["_source"]
                    source["_score"] = h["_score"]
                    results.append(source)

                return {
                    "total": len(results),
                    "results": results,
                    "engine": "Aiven OpenSearch (Live Cluster)",
                    "dsl_query": dsl_query,
                    "fuzzy_applied": bool(query_text)
                }
            except Exception as e:
                logger.error(f"Aiven OpenSearch query error: {e}. Falling back to local engine.")

        # Local Fuzzy Simulation Engine
        results = self._local_fuzzy_search(query_text, category, city, min_price, max_price)
        return {
            "total": len(results),
            "results": results,
            "engine": "OpenSearch Engine (Local Typo-Tolerant Matcher)",
            "dsl_query": dsl_query,
            "fuzzy_applied": bool(query_text)
        }

    def _local_fuzzy_search(
        self,
        query: str,
        category: Optional[str],
        city: Optional[str],
        min_price: Optional[float],
        max_price: Optional[float]
    ) -> List[Dict[str, Any]]:
        query = query.lower().strip()
        tokens = query.split() if query else []
        matched = []

        for p in self._local_index.values():
            # Filters
            if category and category.lower() != "all" and p["category"].lower() != category.lower():
                continue
            if city and city.lower() != "all" and city not in p.get("cities", []):
                continue
            if min_price is not None and p["price"] < min_price:
                continue
            if max_price is not None and p["price"] > max_price:
                continue

            # If no query string, it matches all filters
            if not tokens:
                matched.append(dict(p, _score=1.0))
                continue

            score = 0.0
            p_text = f"{p['title']} {p['brand']} {p['category']} {p['description']}".lower()
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
                                # Closer match gets higher score
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

    def get_suggestions(self, prefix_or_typo: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Fast autocomplete and 'Did you mean' suggestions for live search bar
        """
        prefix_or_typo = (prefix_or_typo or "").strip().lower()
        if not prefix_or_typo or len(prefix_or_typo) < 2:
            return []

        search_res = self.search(query_text=prefix_or_typo)
        hits = search_res.get("results", [])[:limit]
        suggestions = []
        for h in hits:
            suggestions.append({
                "id": h["id"],
                "title": h["title"],
                "brand": h["brand"],
                "category": h["category"],
                "price": h["price"],
                "image_url": h["image_url"],
                "stock": h.get("stock", 0)
            })
        return suggestions
