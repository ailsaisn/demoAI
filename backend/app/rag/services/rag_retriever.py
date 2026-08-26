import os
import re
import pickle
from datetime import datetime, date, timezone
from typing import List, Dict, Any, Optional
from loguru import logger
# pyrefly: ignore [missing-import]
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from app.rag.services.interfaces import BaseVectorStoreAdapter
from app.rag.config import settings


# --- Temporal Filtering Helpers ---

def parse_date_safely(date_val: Any) -> Optional[date]:
    """Parses various date string formats safely into a date object."""
    if not date_val:
        return None
    if isinstance(date_val, date) and not isinstance(date_val, datetime):
        return date_val
    if isinstance(date_val, datetime):
        return date_val.date()
    
    date_str = str(date_val).strip()
    if not date_str or date_str.lower() in ("null", "none", "undefined", ""):
        return None

    # Strip time part if present (e.g. 2026-08-31T00:00:00Z)
    if "t" in date_str.lower():
        date_str = date_str.split("T")[0].split("t")[0]
    if " " in date_str:
        date_str = date_str.split(" ")[0]

    date_formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y.%m.%d",
        "%d.%m.%Y"
    ]
    for fmt in date_formats:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def is_chunk_valid_temporal(
    metadata: Dict[str, Any], 
    current_date: Optional[date] = None, 
    include_expired: bool = False
) -> bool:
    """
    Checks if a chunk is currently active and not expired.
    - If include_expired is True: always returns True.
    - If valid_until is present and valid_until < current_date: returns False (expired).
    - If valid_from is present and current_date < valid_from: returns False (future/not yet active).
    """
    if include_expired:
        return True

    if not metadata:
        return True

    today = current_date or datetime.now(timezone.utc).date()

    valid_until_str = metadata.get("valid_until") or metadata.get("expiry_date") or metadata.get("end_date")
    if valid_until_str:
        until_date = parse_date_safely(valid_until_str)
        if until_date and until_date < today:
            return False

    valid_from_str = metadata.get("valid_from") or metadata.get("start_date")
    if valid_from_str:
        from_date = parse_date_safely(valid_from_str)
        if from_date and today < from_date:
            return False

    return True


# --- Local BM25 Index ---
class BM25Index:
    def __init__(self):
        self.chunks: List[Dict[str, Any]] = []       # Original chunks with text and metadata
        self.corpus: List[List[str]] = []            # Tokenized corpus for BM25
        self.bm25: Optional[BM25Okapi] = None         # rank-bm25 object

    def tokenize(self, text: str) -> List[str]:
        """Simple lowercase alphanumeric word tokenization."""
        if not text:
            return []
        return re.findall(r'\w+', text.lower())

    def add_chunks(self, new_chunks: List[Dict[str, Any]]):
        """Adds new chunks to the BM25 index, removing old chunks of the same source file first."""
        if not new_chunks:
            return

        # Try to extract the source_file name to clear older entries
        source_file = new_chunks[0].get("metadata", {}).get("source_file")
        if source_file:
            logger.debug(f"Clearing old BM25 chunks for source file: {source_file}")
            self.remove_file_chunks(source_file)

        for chunk in new_chunks:
            text = chunk.get("text", "")
            metadata = chunk.get("metadata", {})
            self.chunks.append({
                "text": text,
                "metadata": metadata
            })
            self.corpus.append(self.tokenize(text))

        # Re-initialize the BM25 model with the updated corpus
        if self.corpus:
            self.bm25 = BM25Okapi(self.corpus)
            logger.info(f"Re-initialized BM25 index. Total chunks in index: {len(self.chunks)}")
        else:
            self.bm25 = None

    def remove_file_chunks(self, source_file: str):
        """Removes all chunks associated with a given source file name."""
        indices_to_keep = [
            i for i, chunk in enumerate(self.chunks) 
            if chunk.get("metadata", {}).get("source_file") != source_file
        ]
        self.chunks = [self.chunks[i] for i in indices_to_keep]
        self.corpus = [self.corpus[i] for i in indices_to_keep]
        
        if self.corpus:
            self.bm25 = BM25Okapi(self.corpus)
        else:
            self.bm25 = None

    def clear(self):
        """Clears all chunks and corpus, resetting the BM25 index state."""
        self.chunks = []
        self.corpus = []
        self.bm25 = None


    def search(
        self, 
        query: str, 
        top_k: int = 5, 
        filter_metadata: Optional[Dict[str, Any]] = None,
        include_expired: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Searches the corpus using BM25.
        Applies metadata filtering and temporal validity before scoring if filter_metadata is provided.
        """
        if not self.chunks:
            return []

        today = datetime.now(timezone.utc).date()

        # Step 1: Filter chunk candidates by metadata and temporal validity
        filtered_indices = []
        for idx, chunk in enumerate(self.chunks):
            meta = chunk.get("metadata", {})
            
            # Check temporal validity for promo/dated documents
            if not is_chunk_valid_temporal(meta, current_date=today, include_expired=include_expired):
                continue

            match = True
            if filter_metadata:
                for k, v in filter_metadata.items():
                    if k == "excluded_categories" and isinstance(v, list):
                        chunk_cats = meta.get("categories", [])
                        if not isinstance(chunk_cats, list):
                            chunk_cats = [chunk_cats] if chunk_cats else []
                        if any(item in chunk_cats for item in v if item):
                            match = False
                            break
                    elif isinstance(v, list):
                        chunk_val = meta.get(k, [])
                        if not isinstance(chunk_val, list):
                            chunk_val = [chunk_val] if chunk_val else []
                        if not any(item in chunk_val for item in v if item):
                            match = False
                            break
                    elif meta.get(k) != v:
                        match = False
                        break
            if match:
                filtered_indices.append(idx)

        if not filtered_indices:
            logger.debug(f"No chunks matched metadata filter {filter_metadata} in BM25 index.")
            return []

        tokenized_query = self.tokenize(query)

        # Step 2: Calculate BM25 scores
        # If we have a filter, build a temporary BM25 okapi index of just the filtered candidates
        if (filter_metadata or not include_expired) and len(filtered_indices) < len(self.chunks):
            filtered_corpus = [self.corpus[i] for i in filtered_indices]
            temp_bm25 = BM25Okapi(filtered_corpus)
            scores = temp_bm25.get_scores(tokenized_query)
            
            top_temp_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
            results = []
            for idx in top_temp_indices:
                score = scores[idx]
                if score == 0.0:  # Skip chunks with absolutely zero term matches
                    continue
                orig_idx = filtered_indices[idx]
                results.append({
                    "text": self.chunks[orig_idx]["text"],
                    "score": float(score),
                    "metadata": self.chunks[orig_idx]["metadata"]
                })
            return results
        else:
            # Score against global BM25 model
            if not self.bm25:
                return []
            scores = self.bm25.get_scores(tokenized_query)
            top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
            results = []
            for idx in top_indices:
                score = scores[idx]
                if score == 0.0:  # Skip chunks with absolutely zero term matches
                    continue
                results.append({
                    "text": self.chunks[idx]["text"],
                    "score": float(score),
                    "metadata": self.chunks[idx]["metadata"]
                })
            return results

    def save(self, file_path: str):
        """Serializes and saves the index to disk using pickle."""
        try:
            parent_dir = os.path.dirname(file_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            with open(file_path, "wb") as f:
                pickle.dump({
                    "chunks": self.chunks,
                    "corpus": self.corpus
                }, f)
            logger.info(f"Successfully saved BM25 index to {file_path}")
        except Exception as e:
            logger.error(f"Failed to save BM25 index: {e}")

    def load(self, file_path: str):
        """Loads and deserializes the index from disk."""
        if not os.path.exists(file_path):
            logger.info(f"No existing BM25 index file found at {file_path}. Creating new.")
            return
            
        try:
            with open(file_path, "rb") as f:
                data = pickle.load(f)
                self.chunks = data.get("chunks", [])
                self.corpus = data.get("corpus", [])
            
            if self.corpus:
                self.bm25 = BM25Okapi(self.corpus)
                logger.info(f"Successfully loaded BM25 index from {file_path}. Loaded {len(self.chunks)} chunks.")
            else:
                self.bm25 = None
        except Exception as e:
            logger.error(f"Failed to load BM25 index: {e}")


# --- Cross-Encoder Reranker ---
class Reranker:
    def __init__(self, model_name: str = "BAAI/bge-reranker-base"):
        self.model_name = model_name
        self.model = None
        self._initialized = False

    def _ensure_loaded(self):
        if not self._initialized:
            self._initialized = True
            logger.info(f"Loading Cross-Encoder Reranker model: {self.model_name}...")
            try:
                self.model = CrossEncoder(self.model_name)
                logger.info("Cross-Encoder Reranker model loaded successfully.")
            except Exception as e:
                logger.error(f"Failed to load CrossEncoder model: {e}")
                self.model = None

    def rerank(self, query: str, hits: List[Dict[str, Any]], top_n: int = 3) -> List[Dict[str, Any]]:
        """
        Reranks retrieve search candidates using the Cross-Encoder.
        Optimized for fast CPU inference (< 200ms) by clipping candidate set to top 5
        and truncating text snippets to 350 chars.
        """
        if not hits:
            return []
            
        self._ensure_loaded()
        if not self.model:
            logger.warning("Reranker model is not loaded. Returning original hits limited to top_n.")
            return hits[:top_n]

        try:
            # Clip candidates to top 5 and truncate text to 350 chars for fast CPU inference (< 200ms)
            target_hits = hits[:5]
            pairs = []
            for hit in target_hits:
                meta = hit.get("metadata", {})
                product_name = meta.get("product_name")
                if not product_name:
                    source_file = meta.get("source_file", "unknown")
                    product_name = source_file
                    for ext in [".pdf", ".docx", ".txt", "_parsed.json"]:
                        product_name = product_name.replace(ext, "")
                    pn_lower = product_name.lower()
                    for prefix in ["dummy_", "dumy_", "dummy-", "dumy-", "dummy ", "dumy "]:
                        if pn_lower.startswith(prefix):
                            product_name = product_name[len(prefix):]
                            pn_lower = pn_lower[len(prefix):]
                    if pn_lower.startswith("dummy") or pn_lower.startswith("dumy"):
                        product_name = product_name[5:]
                    product_name = product_name.replace("-", " ").replace("_", " ")
                    product_name = product_name.strip()
                
                section = meta.get("section", "General")
                text = hit.get("text", "")[:350]
                
                enriched_text = f"Product: {product_name} | Section: {section} | Content: {text}"
                pairs.append([query, enriched_text])
            
            import torch
            with torch.no_grad():
                scores = self.model.predict(pairs, batch_size=8, show_progress_bar=False)
            
            import math
            reranked_hits = []
            for hit, raw_score in zip(target_hits, scores):
                updated_hit = hit.copy()
                val = float(raw_score)
                norm_score = 1.0 / (1.0 + math.exp(-val)) if -700 <= val <= 700 else (1.0 if val > 700 else 0.0)
                updated_hit["rerank_score"] = norm_score
                reranked_hits.append(updated_hit)
                
            sorted_hits = sorted(reranked_hits, key=lambda h: h["rerank_score"], reverse=True)
            
            logger.info(f"Successfully reranked {len(target_hits)} candidates. Top score: {sorted_hits[0]['rerank_score']:.4f}")
            return sorted_hits[:top_n]
        except Exception as e:
            logger.error(f"Reranking failed: {e}. Falling back to original rankings.")
            return hits[:top_n]


# --- Prompt Context Builder ---
class PromptContextBuilder:
    @staticmethod
    def build_context(hits: List[Dict[str, Any]]) -> str:
        """
        Builds a structured, numbered context string with source file, page, 
        section headers, and promotional period (if any) to pass into the LLM prompt.
        """
        if not hits:
            return "No relevant context found."

        context_parts = []
        for idx, hit in enumerate(hits, start=1):
            metadata = hit.get("metadata", {})
            source_file = metadata.get("source_file", "unknown")
            product_name = metadata.get("product_name")
            if not product_name:
                product_name = source_file
                for ext in [".pdf", ".docx", ".txt", "_parsed.json"]:
                    product_name = product_name.replace(ext, "")
                pn_lower = product_name.lower()
                for prefix in ["dummy_", "dumy_", "dummy-", "dumy-", "dummy ", "dumy "]:
                    if pn_lower.startswith(prefix):
                        product_name = product_name[len(prefix):]
                        pn_lower = pn_lower[len(prefix):]
                if pn_lower.startswith("dummy") or pn_lower.startswith("dumy"):
                    product_name = product_name[5:]
                product_name = product_name.replace("-", " ").replace("_", " ")
                product_name = product_name.strip()
                
            section = metadata.get("section", "General")
            page = metadata.get("page", 1)
            image_url = metadata.get("image_url") or metadata.get("image")
            text = hit.get("text", "")

            valid_from = metadata.get("valid_from")
            valid_until = metadata.get("valid_until")
            promo_header = ""
            if valid_until or valid_from:
                if valid_from and valid_until:
                    promo_header = f" | Periode Promo: {valid_from} s/d {valid_until}"
            kid = metadata.get("knowledge_id") or source_file
            img_header = f" | Image: {image_url}" if image_url else ""
            part = (
                f"[{idx}] ID: {kid} | Source: {source_file} | Title: {product_name}{promo_header}{img_header} | Section: {section} | Page: {page}\n"
                f"Content:\n{text.strip()}"
            )
            context_parts.append(part)

        return "\n\n".join(context_parts)


# --- Helper Rank Functions ---
def get_chunk_key(hit: Dict[str, Any]) -> str:
    meta = hit.get("metadata", {})
    source_file = meta.get("source_file")
    chunk_index = meta.get("chunk_index")
    if source_file is not None and chunk_index is not None:
        return f"{source_file}_{chunk_index}"
    return str(hash(hit.get("text", "")))

def reciprocal_rank_fusion(
    dense_hits: List[Dict[str, Any]], 
    sparse_hits: List[Dict[str, Any]], 
    rrf_k: int = 60
) -> List[Dict[str, Any]]:
    rrf_scores = {}

    for rank, hit in enumerate(dense_hits, start=1):
        key = get_chunk_key(hit)
        if key not in rrf_scores:
            rrf_scores[key] = {"hit": hit, "score": 0.0}
        rrf_scores[key]["score"] += 1.0 / (rrf_k + rank)

    for rank, hit in enumerate(sparse_hits, start=1):
        key = get_chunk_key(hit)
        if key not in rrf_scores:
            rrf_scores[key] = {"hit": hit, "score": 0.0}
        rrf_scores[key]["score"] += 1.0 / (rrf_k + rank)

    sorted_keys = sorted(rrf_scores.keys(), key=lambda k: rrf_scores[k]["score"], reverse=True)

    fused_hits = []
    for key in sorted_keys:
        merged_hit = rrf_scores[key]["hit"].copy()
        merged_hit["rrf_score"] = rrf_scores[key]["score"]
        merged_hit["score"] = rrf_scores[key]["score"]
        fused_hits.append(merged_hit)

    return fused_hits


# --- Hybrid Retriever ---
class HybridRetriever:
    def __init__(
        self, 
        vector_store: BaseVectorStoreAdapter, 
        bm25_index: BM25Index,
        reranker: Optional[Reranker] = None
    ):
        self.vector_store = vector_store
        self.bm25_index = bm25_index
        self.reranker = reranker

    def retrieve(
        self, 
        query: str, 
        top_k: int = 5, 
        filter_metadata: Optional[Dict[str, Any]] = None,
        rerank: bool = True,
        rerank_top_n: int = 3,
        confidence_threshold: Optional[float] = None,
        include_expired: bool = False
    ) -> Dict[str, Any]:
        """
        Executes Advanced Retrieval Pipeline:
        1. Dense Retrieval (PGVector)
        2. Sparse Retrieval (BM25)
        3. Reciprocal Rank Fusion (RRF)
        4. Temporal Validity Filtering (exclude expired promos if include_expired=False)
        5. Cross-Encoder Reranking (optional)
        6. Prompt Context Generation
        """
        logger.debug(f"Retrieving for query: '{query}' with top_k={top_k}, metadata_filter={filter_metadata}, include_expired={include_expired}")

        candidate_k = top_k * 2

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future_dense = executor.submit(self.vector_store.search, query, candidate_k, filter_metadata) if self.vector_store else None
            future_sparse = executor.submit(self.bm25_index.search, query, candidate_k, filter_metadata, include_expired) if self.bm25_index else None
            
            dense_hits = future_dense.result() if future_dense else []
            sparse_hits = future_sparse.result() if future_sparse else []

        if self.vector_store:
            logger.debug(f"Dense retrieval returned {len(dense_hits)} candidates.")
        if self.bm25_index:
            logger.debug(f"Sparse retrieval returned {len(sparse_hits)} candidates.")
        
        fused_hits = reciprocal_rank_fusion(dense_hits, sparse_hits)
        logger.debug(f"RRF Fusion completed. Fused {len(fused_hits)} candidates.")

        # Deduplicate
        seen_texts = set()
        deduplicated_hits = []
        for hit in fused_hits:
            text = hit.get("text", "").strip()
            norm_text = " ".join(text.split()).lower()
            if norm_text not in seen_texts:
                seen_texts.add(norm_text)
                deduplicated_hits.append(hit)
        logger.debug(f"Deduplicated fused hits from {len(fused_hits)} to {len(deduplicated_hits)} unique candidates.")

        # Temporal filtering: exclude expired promotional chunks when include_expired=False
        today = datetime.now(timezone.utc).date()
        active_hits = []
        for hit in deduplicated_hits:
            meta = hit.get("metadata", {})
            if is_chunk_valid_temporal(meta, current_date=today, include_expired=include_expired):
                active_hits.append(hit)
            else:
                p_name = meta.get("product_name") or meta.get("source_file", "unknown")
                vu = meta.get("valid_until") or meta.get("expiry_date")
                logger.info(f"Filtered out expired promotional chunk: '{p_name}' (valid_until: {vu})")

        final_hits = active_hits
        if rerank and self.reranker and active_hits:
            all_reranked = self.reranker.rerank(query, active_hits, top_n=len(active_hits))
            
            query_lower = query.lower()
            usage_keywords = ["how to use", "directions", "cara pakai", "cara penggunaan", "aturan pakai", "dosis", "instruksi"]
            ingredients_keywords = ["kandungan", "ingredients", "bahan aktif", "komposisi", "active ingredients"]
            treatment_keywords = ["treatment", "tindakan", "prosedur", "perawatan", "peeling", "ekstraksi", "facial", "terapi", "laser"]
            product_keywords = ["produk", "skincare", "serum", "krim", "cream", "facial wash", "cleanser", "sunscreen", "moisturizer", "sku"]

            is_usage_intent = any(k in query_lower for k in usage_keywords)
            is_ingredients_intent = any(k in query_lower for k in ingredients_keywords)
            is_treatment_intent = any(k in query_lower for k in treatment_keywords)
            is_product_intent = any(k in query_lower for k in product_keywords)

            boosted_hits = []
            for hit in all_reranked:
                updated_hit = hit.copy()
                meta = updated_hit.get("metadata", {})
                section_upper = meta.get("section", "").upper()
                doc_type_upper = str(meta.get("document_type", "")).upper()
                boost = 0.0
                
                if is_usage_intent and any(s in section_upper for s in ["HOW TO USE", "DIRECTIONS"]):
                    boost += 0.05
                elif is_ingredients_intent and any(s in section_upper for s in ["INGREDIENT", "KANDUNGAN", "KOMPOSISI"]):
                    boost += 0.05
                    
                if is_treatment_intent and (doc_type_upper == "TREATMENT" or any(s in section_upper for s in ["TREATMENT", "PERAWATAN", "TINDAKAN", "PROSEDUR", "PROTOKOL"])):
                    boost += 0.10
                elif is_product_intent and (doc_type_upper == "PRODUCT" or any(s in section_upper for s in ["PRODUCT", "PRODUK", "KATALOG", "SKINCARE"])):
                    boost += 0.05

                if boost > 0:
                    updated_hit["rerank_score"] = updated_hit.get("rerank_score", 0.0) + boost
                    logger.debug(f"Applied intent boost of +{boost} to section '{section_upper}' / doc_type '{doc_type_upper}' (new score: {updated_hit['rerank_score']:.4f})")
                boosted_hits.append(updated_hit)

            final_hits = sorted(boosted_hits, key=lambda h: h.get("rerank_score", 0.0), reverse=True)[:rerank_top_n]
            logger.debug(f"Reranking and intent boosting completed. Returned top {len(final_hits)} chunks.")
        else:
            final_hits = active_hits[:top_k]

        threshold = confidence_threshold if confidence_threshold is not None else settings.rerank_confidence_threshold
        if rerank and self.reranker and final_hits:
            max_score = final_hits[0].get("rerank_score", 0.0)
            if max_score < threshold:
                logger.warning(f"Retrieval confidence score {max_score:.4f} is below threshold {threshold:.4f}. Rejecting retrieved context.")
                return {
                    "query": query,
                    "results": [],
                    "context": "Maaf, saya tidak menemukan informasi."
                }

        context_string = PromptContextBuilder.build_context(final_hits)

        return {
            "query": query,
            "results": final_hits,
            "context": context_string
        }
