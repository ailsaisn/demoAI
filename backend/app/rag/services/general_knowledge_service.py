"""
Dedicated CRUD Service for General Knowledge Assistant (Arya Noble).

This service executes deterministic, validated database operations (READ metadata, EDIT, DELETE)
on approved Knowledge Base documents across:
- Local JSON storage (data/output/)
- PostgreSQL (Knowledge table)
- PGVector (arya_noble_kb table)
- MinIO Object Storage (approved & canonical buckets)
- BM25 Index (bm25_index.pkl)

Architectural Principle:
The LLM is NOT the primary decider of CRUD operations.
The AI Orchestrator validates requests against this service, displays a two-step preview,
and upon explicit Admin confirmation, delegates mutation to this Dedicated Service.
"""

import os
import re
import json
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timezone
from loguru import logger

from app.rag.config import settings
from app.rag.services.rag_retriever import parse_date_safely


def resolve_approved_file(knowledge_id: str, output_dir: str = "data/output") -> Optional[str]:
    """Resolves the physical JSON file path for an approved document, hydrating from MinIO/DB if needed."""
    if not knowledge_id:
        return None
    k_id = str(knowledge_id).strip()

    # Try exact paths first
    direct_paths = [
        os.path.join(output_dir, f"{k_id}.json"),
        os.path.join(output_dir, f"{k_id}_parsed.json"),
        os.path.join("backend", output_dir, f"{k_id}.json"),
        os.path.join("backend", output_dir, f"{k_id}_parsed.json"),
    ]
    for p in direct_paths:
        if os.path.exists(p):
            return p

    # Search in directory
    for folder in [output_dir, os.path.join("backend", output_dir)]:
        if os.path.exists(folder):
            for f in os.listdir(folder):
                if f.endswith(".json") and f != "bm25_index.pkl":
                    f_path = os.path.join(folder, f)
                    try:
                        with open(f_path, "r", encoding="utf-8") as fp:
                            doc = json.load(fp)
                        if isinstance(doc, dict):
                            doc_id = str(doc.get("knowledge_id", ""))
                            doc_title = str(doc.get("title", ""))
                            file_name = str(doc.get("file_name", ""))
                            f_no_ext = f.replace(".json", "").replace("_parsed", "")
                            if k_id.lower() in (doc_id.lower(), doc_title.lower(), file_name.lower(), f_no_ext.lower(), f.lower()):
                                return f_path
                    except Exception as err:
                        logger.debug(f"[DedicatedService] Error scanning file {f}: {err}")

    # MinIO Source of Truth Hydration fallback
    clean_p = os.path.join(output_dir, f"{k_id}.json")
    try:
        from app.services.storage import get_approved_json
        approved_data = get_approved_json(k_id)
        if approved_data:
            os.makedirs(output_dir, exist_ok=True)
            with open(clean_p, "w", encoding="utf-8") as fp:
                json.dump(approved_data, fp, indent=4, ensure_ascii=False)
            return clean_p
    except Exception as e:
        logger.debug(f"[DedicatedService] MinIO approved hydration note: {e}")

    # PostgreSQL Database Hydration fallback
    try:
        from app.core.database import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, title, file_name, ai_summary, metadata FROM knowledge WHERE id::text = :k_id AND status = 'APPROVED' AND deleted_at IS NULL LIMIT 1"),
                {"k_id": k_id}
            ).fetchone()
            if not row:
                row = conn.execute(
                    text("SELECT id, title, file_name, ai_summary, metadata FROM knowledge WHERE (LOWER(title) = LOWER(:k_id) OR LOWER(file_name) = LOWER(:k_id)) AND status = 'APPROVED' AND deleted_at IS NULL LIMIT 1"),
                    {"k_id": k_id}
                ).fetchone()

            if row:
                row_id, title, fname, summary, meta_val = row[0], row[1], row[2], row[3], row[4]
                m_dict = meta_val if isinstance(meta_val, dict) else (json.loads(meta_val) if isinstance(meta_val, str) else {})
                doc = {
                    "knowledge_id": str(row_id),
                    "batch_id": m_dict.get("batch_id"),
                    "file_name": fname or str(row_id),
                    "title": title or fname or str(row_id),
                    "status": "Approved",
                    "summary": summary or "",
                    "chunks": m_dict.get("chunks", []),
                    "images": m_dict.get("images", []),
                    "image_urls": m_dict.get("image_urls", []),
                    "categories": m_dict.get("categories", []),
                    "visibility_settings": m_dict.get("visibility_settings", {})
                }
                os.makedirs(output_dir, exist_ok=True)
                with open(clean_p, "w", encoding="utf-8") as fp:
                    json.dump(doc, fp, indent=4, ensure_ascii=False)
                return clean_p
    except Exception as db_e:
        logger.debug(f"[DedicatedService] DB hydration fallback note: {db_e}")

    return None


class GeneralKnowledgeService:
    """Dedicated service for performing safe, item-level CRUD operations on approved KB data."""

    @staticmethod
    async def find_all_target_documents_and_item(
        query: str, output_dir: str = "data/output", db: Optional[Any] = None
    ) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
        """
        Scans approved documents to identify the matching target entity/item name and
        ALL documents in the Knowledge Base that contain, define, or are affected by it.
        Returns (target_item_name, list_of_matched_docs) sorted by priority:
        1. Explicit UUID matches
        2. Dedicated documents (where doc_title or file_name matches target entity)
        3. Catalog documents (where target entity is a section heading)
        4. Content mentions
        """
        q_lower = query.lower()

        # Check if an explicit UUID is present in query
        uuid_matches = re.findall(
            r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',
            query
        )
        explicit_uuid = uuid_matches[0].lower() if uuid_matches else None

        # 1. Check for ingredient-based delete query:
        # e.g.: "hapus seluruh produk dengan yang mengandung Hyaluronic Acid"
        ingredient_delete_match = re.search(
            r'\b(?:hapus|delete|hilangkan|remove|buang|bersihkan|tiadakan|drop|clear|wipe|erase)\s+(?:seluruh|semua|setiap)?\s*(?:produk|item|barang|treatment)?\s*(?:dengan\s+)?(?:yang\s+)?(?:mengandung|ada\s+kandungan|kandungan|bahan|komposisi|berisi)\s+["\'“]?([^"\'”\n\?\.\(]+)',
            query,
            re.IGNORECASE
        )
        ingredient_filter = None
        if ingredient_delete_match:
            raw_ing = ingredient_delete_match.group(1).strip().strip('"\'“”`')
            raw_ing = re.sub(r'\s+(?:dari|pada|di|dalam|ke)\s+.*$', '', raw_ing, flags=re.IGNORECASE).strip()
            raw_ing = re.sub(r'[\s,\.]+(?:ya|dong|tolong|mohon|terima\s*kasih|thanks)$', '', raw_ing, flags=re.IGNORECASE).strip()
            if len(raw_ing) > 1:
                ingredient_filter = raw_ing

        # 2. Check for edit with transition word:
        # e.g.: "Ubah informasi kandungan Hyaluronic Acid menjadi Polyglutamic Acid (PGA) pada semua produk"
        edit_trans_match = re.search(
            r'\b(?:ubah|ganti|edit|tukar|salin|update|perbarui|revisi)\s+(?:informasi|data|bagian|detail)?\s*(kandungan|komposisi|ingredients|bahan|ukuran|harga|sku|nama|kategori|deskripsi)?\s*["\'“]?([^"\'”\n]+?)["\'”?]?\s+(?:menjadi|jadi|ke|sebagai|=)\s*["\'“]?([^"\'”\n]+?)["\'”?]?\s*(?:pada|di|dalam|untuk)?\s*(?:semua|seluruh|setiap)?\s*(?:produk|item|dokumen|kb|knowledge|data)?$',
            query,
            re.IGNORECASE
        )
        edit_target_candidate = None
        if edit_trans_match:
            edit_target_candidate = edit_trans_match.group(2).strip()
            # Clean leading field or preposition words if captured
            edit_target_candidate = re.sub(r'^(?:informasi|data|bagian|detail|kandungan|komposisi|ingredients|bahan|ukuran|harga|sku|nama|kategori|deskripsi)\s+', '', edit_target_candidate, flags=re.IGNORECASE).strip()

        # 3. Standard command extraction
        container_candidate = None
        explicit_item_candidate = ingredient_filter or edit_target_candidate
        action_verbs_regex = r'\b(?:hapus|delete|hilangkan|remove|buang|bersihkan|tiadakan|drop|clear|wipe|erase|ubah|ganti|edit|tukar|salin|revisi|pembaruan|perbarui|modifikasi|perbaiki|gantikan|gantiin|update|pasang|set|sesuaikan)\b'
        
        if not explicit_item_candidate:
            cmd_match = re.search(
                rf'{action_verbs_regex}\s+(?:bagian|item|produk|tahapan|parameter|indikator|baris|kolom|tabel)?\s*["\'“]?([^"\'”\n]+?)["\'”?]?\s+(?:dari|pada|di|dalam)\s+["\'“]?([^"\'”\n]+)["\'”]?',
                query,
                re.IGNORECASE
            )
            if cmd_match:
                explicit_item_candidate = cmd_match.group(1).strip()
                container_candidate = cmd_match.group(2).strip()
            else:
                quote_match = re.search(r'["\'“]([^"\'”]+)["\'”]', query)
                if quote_match:
                    explicit_item_candidate = quote_match.group(1).strip()
                else:
                    keyword_match = re.search(
                        r'\b(?:bagian|item|produk|tahapan|parameter|indikator|baris|kolom|tabel)\s+([a-zA-Z0-9\s&+\-_/]+?)(?:\s+(?:pada|di|dari|dalam|menjadi|ke|sebagai)\b|$)',
                        query,
                        re.IGNORECASE
                    )
                    if keyword_match:
                        candidate = keyword_match.group(1).strip()
                        if len(candidate) > 2 and candidate.lower() not in ("dokumen", "doc", "kb", "knowledge", "tersebut", "ini", "itu"):
                            explicit_item_candidate = candidate

        # Clean core entity extraction for edit/update patterns:
        if not explicit_item_candidate:
            core = re.sub(
                rf'^\s*(?:tolong\s+|mohon\s+|coba\s+)?{action_verbs_regex}\s+',
                '',
                query,
                flags=re.IGNORECASE
            )
            # Strip trailing target value (ke 40 g / jadi 40 g / dengan 50000 / menjadi 50000)
            val_m = re.search(r'\b(?:menjadi|jadi|ke|sebagai|dengan|sebesar|berupa|=)\s+[`"\'“]?([^\n\r`"\'”]+)[\'"”`]?$', core, re.IGNORECASE)
            if val_m:
                core = core[:val_m.start()].strip()
            else:
                # Also strip raw trailing value without transition word (e.g. "Facial Wash 40 g" -> "Facial Wash")
                raw_val_m = re.search(r'\b(\d+(?:\.\d+)?\s*(?:g|gram|ml|l|kg|oz)\b|(?:Rp\.?\s*)?\d[\d\.\,]+)$', core, re.IGNORECASE)
                if raw_val_m:
                    core = core[:raw_val_m.start()].strip()

            # Strip leading field words
            field_words = [
                'ukuran', 'size', 'berat', 'volume', 'netto',
                'harga', 'price', 'biaya', 'tarif',
                'sku', 'kode_sku', 'kode',
                'nama_produk', 'nama', 'judul',
                'kategori', 'category',
                'deskripsi', 'description', 'keterangan',
                'indikasi', 'cara_pakai', 'dosis',
                'kandungan', 'komposisi', 'ingredients', 'key ingredients', 'bahan'
            ]
            for fw in field_words:
                core = re.sub(rf'\b{fw}\b', '', core, flags=re.IGNORECASE).strip()

            core = re.sub(r'^\s*(?:pada|di|dari|dalam|untuk|bagian|item|produk|treatment|dokumen)\s+', '', core, flags=re.IGNORECASE).strip()
            core = re.sub(r'\s*(?:pada|di|dari|dalam|untuk|bagian|item|produk|treatment|dokumen)\s*$', '', core, flags=re.IGNORECASE).strip()
            if len(core) > 2 and not re.match(r'^[0-9a-fA-F\-]{10,}$', core):
                explicit_item_candidate = core

        # Filter out purely anaphoric terms from explicit_item_candidate
        if explicit_item_candidate:
            anaphoric_clean = explicit_item_candidate.lower().strip()
            if anaphoric_clean in ("tersebut", "produk tersebut", "item tersebut", "dokumen tersebut", "ini", "itu", "nya", "produk ini", "produk itu"):
                explicit_item_candidate = None

        search_folders = [output_dir, os.path.join("backend", output_dir)]
        seen_doc_ids = set()
        matched_docs = []
        resolved_entity_name = explicit_item_candidate

        for folder in search_folders:
            if not os.path.exists(folder):
                continue
            for f in os.listdir(folder):
                if not f.endswith(".json") or f == "bm25_index.pkl":
                    continue
                f_path = os.path.join(folder, f)
                try:
                    with open(f_path, "r", encoding="utf-8") as fp:
                        doc = json.load(fp)
                    if not isinstance(doc, dict):
                        continue

                    doc_id = str(doc.get("knowledge_id") or doc.get("id") or f.replace(".json", "").replace("_parsed", ""))
                    if doc_id in seen_doc_ids:
                        continue

                    doc_title = str(doc.get("title") or doc.get("file_name") or "")
                    file_name = str(doc.get("file_name") or "")
                    summary = str(doc.get("summary") or "")
                    batch_summary = str(doc.get("batch_summary") or "")

                    # Document's own content corpus (summary + chunks)
                    doc_own_corpus = summary
                    for chunk in doc.get("chunks", []):
                        if isinstance(chunk, dict):
                            doc_own_corpus += "\n" + str(chunk.get("text", ""))

                    # Full text corpus including batch and staging
                    full_text_corpus = doc_own_corpus + "\n" + batch_summary
                    if doc.get("staging_history") and isinstance(doc.get("staging_history"), list):
                        for t in doc.get("staging_history"):
                            if isinstance(t, dict) and t.get("role") == "assistant":
                                full_text_corpus += "\n" + str(t.get("content", ""))

                    # Collect candidate items/sections from this document
                    doc_candidates = []
                    for k in ["product_name", "title", "section", "heading", "treatment", "treatment_name", "category"]:
                        v = doc.get(k)
                        if v and isinstance(v, str) and len(v.strip()) > 2 and v.strip().lower() not in ("general", "unknown"):
                            doc_candidates.append(v.strip())

                    # Headings in summary
                    for h in re.findall(r'^#{1,4}\s+([^\n\r]+)', full_text_corpus, re.MULTILINE):
                        h_clean = re.sub(r'[\*\_]', '', h).strip()
                        if len(h_clean) > 2 and h_clean.lower() not in ("ringkasan dokumen", "penutup", "evaluasi hasil", "profil pasien", "detail perawatan"):
                            doc_candidates.append(h_clean)

                    # Chunks metadata
                    for chunk in doc.get("chunks", []):
                        if not isinstance(chunk, dict):
                            continue
                        meta = chunk.get("metadata", {})
                        for k in ["product_name", "title", "section", "heading", "treatment", "treatment_name"]:
                            v = meta.get(k)
                            if v and isinstance(v, str) and len(v.strip()) > 2 and v.strip().lower() not in ("general", "unknown"):
                                doc_candidates.append(v.strip())

                    # Clean candidates
                    unique_candidates = []
                    seen_c = set()
                    for c in doc_candidates:
                        if c.lower() not in seen_c:
                            seen_c.add(c.lower())
                            unique_candidates.append(c)
                    unique_candidates.sort(key=len, reverse=True)

                    # Calculate match score
                    score = 0
                    match_type = "mention"
                    matched_item_for_doc = None
                    target_sub_items = []

                    # 1. Explicit UUID in prompt matches this doc
                    if explicit_uuid and (explicit_uuid == doc_id.lower()):
                        score += 1000
                        match_type = "explicit_uuid"

                    # 2. Ingredient filter match (e.g. "Hyaluronic Acid", "Retinol", "BHA")
                    # Check document's own corpus so cross-document batch summaries don't cause false positives
                    if ingredient_filter:
                        ing_low = ingredient_filter.lower()
                        ing_regex = re.compile(rf'\b{re.escape(ing_low)}\b', re.IGNORECASE)
                        if ing_regex.search(doc_own_corpus):
                            score += 450
                            match_type = "ingredient_match"
                            # Identify specific product sections containing this ingredient
                            sections = re.split(r'(?=^#{1,3}\s+)', full_text_corpus, flags=re.MULTILINE)
                            for s in sections:
                                m_h = re.match(r'^#{1,3}\s+([^\n]+)', s)
                                if m_h:
                                    h_name = re.sub(r'[\*\_]', '', m_h.group(1)).strip()
                                    if ing_regex.search(s) and h_name.lower() not in ("ringkasan dokumen", "penutup", "evaluasi hasil", "profil pasien", "detail perawatan"):
                                        target_sub_items.append(h_name)

                            # Also check markdown table rows for product name
                            for line in full_text_corpus.splitlines():
                                if ing_regex.search(line) and "|" in line:
                                    cols = [c.strip() for c in line.split("|") if c.strip()]
                                    for col in cols:
                                        col_clean = re.sub(r'!\[.*?\]\(.*?\)', '', col).strip()
                                        if len(col_clean) > 3 and not col_clean.startswith("http") and not col_clean.startswith("/api/storage"):
                                            if any(kw in col_clean.lower() for kw in ["erha", "serum", "gel", "cream", "wash", "lotion", "moisturizer", "toner", "sabun"]):
                                                target_sub_items.append(col_clean)
                                                break

                            # Deduplicate preserving order
                            seen_items = set()
                            unique_sub_items = []
                            for it in target_sub_items:
                                if it.lower() not in seen_items:
                                    seen_items.add(it.lower())
                                    unique_sub_items.append(it)

                            if unique_sub_items:
                                matched_item_for_doc = ", ".join(unique_sub_items)
                            else:
                                matched_item_for_doc = f"Produk dengan kandungan {ingredient_filter}"

                            if not resolved_entity_name:
                                resolved_entity_name = matched_item_for_doc

                    # 3. Check explicit item candidate against document title / filename / candidates / summary
                    elif explicit_item_candidate:
                        cand_low = explicit_item_candidate.lower()
                        # Exact or strong title match -> Dedicated document!
                        if cand_low == doc_title.lower() or cand_low in doc_title.lower() or cand_low in file_name.lower().replace("_", " "):
                            score += 500 + len(doc_title)
                            match_type = "dedicated_document"
                            matched_item_for_doc = explicit_item_candidate
                            if not resolved_entity_name or len(doc_title) > len(resolved_entity_name):
                                resolved_entity_name = doc_title

                        # Section match in catalog document
                        for c in unique_candidates:
                            if cand_low == c.lower() or cand_low in c.lower() or c.lower() in cand_low:
                                if match_type != "dedicated_document":
                                    score += 200 + len(c)
                                    match_type = "section"
                                matched_item_for_doc = c
                                if not resolved_entity_name:
                                    resolved_entity_name = c
                                break

                        # Content / ingredient match in summary or batch_summary
                        if score == 0 and (cand_low in full_text_corpus.lower()):
                            score += 150 + len(explicit_item_candidate)
                            match_type = "content_mention"
                            matched_item_for_doc = explicit_item_candidate

                    # 4. Check query text against document title or unique candidates
                    if score == 0:
                        if doc_title and len(doc_title) > 3 and doc_title.lower() in q_lower:
                            score += 300 + len(doc_title)
                            match_type = "title_in_query"
                            matched_item_for_doc = doc_title
                            if not resolved_entity_name:
                                resolved_entity_name = doc_title
                        else:
                            for c in unique_candidates:
                                if len(c) > 3 and c.lower() in q_lower:
                                    score += 150 + len(c)
                                    match_type = "item_in_query"
                                    matched_item_for_doc = c
                                    if not resolved_entity_name or len(c) > len(resolved_entity_name):
                                        resolved_entity_name = c
                                    break

                    if score > 0:
                        seen_doc_ids.add(doc_id)
                        doc_copy = dict(doc)
                        doc_copy["_matched_context_label"] = matched_item_for_doc or resolved_entity_name or doc_title
                        matched_docs.append({
                            "knowledge_id": doc_id,
                            "title": doc_title,
                            "file_name": file_name,
                            "batch_id": doc.get("batch_id") or doc.get("metadata", {}).get("batch_id"),
                            "score": score,
                            "match_type": match_type,
                            "target_item": matched_item_for_doc or resolved_entity_name,
                            "doc_data": doc_copy
                        })

                except Exception as e:
                    logger.debug(f"[DedicatedService] scan error {f}: {e}")

        # DB Hydration fallback: scan active APPROVED PostgreSQL Knowledge records if disk scan yields no matches
        if not matched_docs:
            try:
                from app.models.knowledge import Knowledge, KnowledgeStatus
                from sqlalchemy import select, or_

                async def _scan_db(session):
                    stmt = select(Knowledge).where(
                        or_(Knowledge.status == KnowledgeStatus.APPROVED, Knowledge.status == 'APPROVED'),
                        Knowledge.deleted_at.is_(None)
                    )
                    res = await session.execute(stmt)
                    return res.scalars().all()

                if db:
                    k_rows = await _scan_db(db)
                else:
                    from app.core.database import AsyncSessionLocal
                    async with AsyncSessionLocal() as session:
                        k_rows = await _scan_db(session)

                for k_obj in k_rows:
                    doc_id = str(k_obj.id)
                    if doc_id in seen_doc_ids:
                        continue
                    doc_title = str(k_obj.title or k_obj.file_name or doc_id)
                    file_name = str(k_obj.file_name or "")
                    summary = str(k_obj.ai_summary or "")
                    m_dict = dict(k_obj.metadata_) if isinstance(k_obj.metadata_, dict) else {}
                    doc = {
                        "knowledge_id": doc_id,
                        "batch_id": m_dict.get("batch_id"),
                        "file_name": file_name,
                        "title": doc_title,
                        "summary": summary,
                        "chunks": m_dict.get("chunks", []),
                        "images": m_dict.get("images", []),
                        "image_urls": m_dict.get("image_urls", []),
                        "categories": m_dict.get("categories", []),
                        "visibility_settings": m_dict.get("visibility_settings", {})
                    }

                    doc_candidates = [doc_title]
                    for h in re.findall(r'^#{1,4}\s+([^\n\r]+)', summary, re.MULTILINE):
                        h_clean = re.sub(r'[\*\_]', '', h).strip()
                        if len(h_clean) > 2:
                            doc_candidates.append(h_clean)

                    score = 0
                    match_type = "mention"
                    matched_item_for_doc = None

                    if explicit_uuid and (explicit_uuid == doc_id.lower()):
                        score += 1000
                        match_type = "explicit_uuid"

                    if ingredient_filter:
                        ing_low = ingredient_filter.lower()
                        ing_regex = re.compile(rf'\b{re.escape(ing_low)}\b', re.IGNORECASE)
                        full_txt = summary + " " + doc_title
                        if ing_regex.search(full_txt):
                            score += 450
                            match_type = "ingredient_match"
                            matched_item_for_doc = f"Produk dengan kandungan {ingredient_filter}"
                            if not resolved_entity_name:
                                resolved_entity_name = matched_item_for_doc

                    if explicit_item_candidate:
                        cand_low = explicit_item_candidate.lower()
                        if cand_low == doc_title.lower() or cand_low in doc_title.lower() or cand_low in file_name.lower().replace("_", " "):
                            score += 500 + len(doc_title)
                            match_type = "dedicated_document"
                            matched_item_for_doc = explicit_item_candidate
                            if not resolved_entity_name:
                                resolved_entity_name = doc_title

                        for c in doc_candidates:
                            if cand_low == c.lower() or cand_low in c.lower() or c.lower() in cand_low:
                                if match_type != "dedicated_document":
                                    score += 200 + len(c)
                                    match_type = "section"
                                matched_item_for_doc = c
                                if not resolved_entity_name:
                                    resolved_entity_name = c
                                break

                    if score == 0:
                        if doc_title and len(doc_title) > 3 and doc_title.lower() in q_lower:
                            score += 300 + len(doc_title)
                            match_type = "title_in_query"
                            matched_item_for_doc = doc_title
                            if not resolved_entity_name:
                                resolved_entity_name = doc_title
                        else:
                            for c in doc_candidates:
                                if len(c) > 3 and c.lower() in q_lower:
                                    score += 150 + len(c)
                                    match_type = "item_in_query"
                                    matched_item_for_doc = c
                                    if not resolved_entity_name:
                                        resolved_entity_name = c
                                    break

                    if score > 0:
                        seen_doc_ids.add(doc_id)
                        doc_copy = dict(doc)
                        doc_copy["_matched_context_label"] = matched_item_for_doc or resolved_entity_name or doc_title
                        matched_docs.append({
                            "knowledge_id": doc_id,
                            "title": doc_title,
                            "file_name": file_name,
                            "batch_id": doc.get("batch_id"),
                            "score": score,
                            "match_type": match_type,
                            "target_item": matched_item_for_doc or resolved_entity_name,
                            "doc_data": doc_copy
                        })
            except Exception as db_scan_err:
                logger.debug(f"[GeneralKnowledgeService] DB scan fallback note: {db_scan_err}")

        if not matched_docs:
            return None

        # Sort: highest score first (dedicated document first, then catalog sections)
        matched_docs.sort(key=lambda x: x["score"], reverse=True)
        return (resolved_entity_name, matched_docs)

    @staticmethod
    async def find_target_document_and_item(
        query: str, output_dir: str = "data/output", db: Optional[Any] = None
    ) -> Optional[Tuple[str, Optional[str], Dict[str, Any]]]:
        """
        Scans approved documents to identify the matching document ID and target item/entity/section name.
        Returns the highest-priority matching document (knowledge_id, target_item_name, doc_data).
        """
        res = await GeneralKnowledgeService.find_all_target_documents_and_item(query, output_dir, db=db)
        if not res:
            return None
        target_item, matched_docs = res
        if not matched_docs:
            return None
        top_doc = matched_docs[0]
        return (top_doc["knowledge_id"], target_item, top_doc["doc_data"])

    @staticmethod
    def validate_target_entity(knowledge_id: str, target_item: Optional[str] = None) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Validates that the target document and (if specified) target item/entity exist in approved KB.
        Returns (is_valid, error_message, doc_data).
        """
        approved_file = resolve_approved_file(knowledge_id)
        if not approved_file:
            return False, f"Dokumen dengan ID/Nama '{knowledge_id}' tidak ditemukan dalam Basis Data Pengetahuan ERHA.", None

        try:
            with open(approved_file, "r", encoding="utf-8") as f:
                doc_data = json.load(f)

            if target_item and target_item.strip():
                item_lower = target_item.strip().lower()
                doc_summary = doc_data.get("summary", "").lower()
                chunks = doc_data.get("chunks", [])
                item_found = item_lower in doc_summary or any(
                    item_lower in str(ch.get("text", "")).lower()
                    or item_lower in str(ch.get("metadata", {}).get("product_name", "")).lower()
                    or item_lower in str(ch.get("metadata", {}).get("section", "")).lower()
                    or item_lower in str(ch.get("metadata", {}).get("heading", "")).lower()
                    or item_lower in str(ch.get("metadata", {}).get("title", "")).lower()
                    for ch in chunks if isinstance(ch, dict)
                )
                if not item_found:
                    return False, f"Item/bagian '{target_item}' tidak ditemukan di dalam dokumen '{knowledge_id}'.", doc_data

            return True, None, doc_data
        except Exception as e:
            return False, f"Gagal membaca data dokumen: {str(e)}", None

    @staticmethod
    async def sync_knowledge_db(
        knowledge_id: str,
        existing_doc: Optional[Dict[str, Any]] = None,
        deleted: bool = False,
        db: Optional[Any] = None
    ):
        """Synchronously updates the PostgreSQL Knowledge record and commits."""
        from app.models.knowledge import Knowledge
        from sqlalchemy import select
        import uuid as _uuid

        async def _do_sync(session):
            k_obj = None
            try:
                kid_uuid = _uuid.UUID(str(knowledge_id).strip())
                stmt = select(Knowledge).where(Knowledge.id == kid_uuid)
                res = await session.execute(stmt)
                k_obj = res.scalar_one_or_none()
            except Exception:
                pass

            if not k_obj:
                stmt2 = select(Knowledge).where(
                    Knowledge.deleted_at.is_(None),
                    Knowledge.metadata_.op("->>")("document_id") == str(knowledge_id)
                )
                res2 = await session.execute(stmt2)
                k_obj = res2.scalar_one_or_none()

            if not k_obj:
                stmt3 = select(Knowledge).where(
                    Knowledge.deleted_at.is_(None),
                    Knowledge.file_name == str(knowledge_id)
                )
                res3 = await session.execute(stmt3)
                k_obj = res3.scalar_one_or_none()

            if k_obj:
                if deleted:
                    k_obj.deleted_at = datetime.now(timezone.utc)
                    logger.info(f"[DedicatedService] Marked Knowledge '{k_obj.id}' as deleted_at={k_obj.deleted_at}")
                elif existing_doc:
                    k_obj.title = existing_doc.get("title", k_obj.title)
                    k_obj.ai_summary = existing_doc.get("summary", k_obj.ai_summary)
                    meta = dict(k_obj.metadata_) if isinstance(k_obj.metadata_, dict) else {}
                    meta.update(existing_doc.get("metadata", {}))
                    meta["chunks"] = existing_doc.get("chunks", [])
                    meta["summary"] = existing_doc.get("summary")
                    if existing_doc.get("batch_summary"):
                        meta["batch_summary"] = existing_doc.get("batch_summary")
                    if "staging_history" in existing_doc:
                        meta["staging_history"] = existing_doc["staging_history"]
                    if "edit_history" in existing_doc:
                        meta["edit_history"] = existing_doc["edit_history"]
                    k_obj.metadata_ = meta
                    logger.info(f"[DedicatedService] Updated Knowledge '{k_obj.id}' metadata & summary in DB")
                await session.commit()

        try:
            if db:
                await _do_sync(db)
            else:
                from app.core.database import AsyncSessionLocal
                async with AsyncSessionLocal() as session:
                    await _do_sync(session)
        except Exception as e:
            logger.error(f"[DedicatedService] Failed to sync Knowledge DB record '{knowledge_id}': {e}")

    @staticmethod
    async def apply_edit(
        knowledge_id: str,
        field: str,
        new_value: str,
        vector_store=None,
        bm25_index=None,
        pipeline=None,
        target_item: Optional[str] = None,
        db=None,
        auto_approve: bool = True
    ) -> Dict[str, Any]:
        """
        Applies a surgical, item-level edit to an approved KB document.
        Updates local JSON, PostgreSQL, PGVector, MinIO, and BM25 index.
        """
        approved_file = resolve_approved_file(knowledge_id)
        if not approved_file:
            return {"success": False, "error": f"Dokumen dengan ID/Nama '{knowledge_id}' tidak ditemukan di approved KB."}

        try:
            with open(approved_file, "r", encoding="utf-8") as f:
                existing_doc = json.load(f)

            doc_kid = str(existing_doc.get("knowledge_id") or knowledge_id)
            old_value = None
            clean_field = (field or "").strip().lower()
            formatted_val = str(new_value).strip()

            # Prevent chatbot conversational response from polluting summary
            conv_phrases = ["berhasil diubah", "berhasil diperbarui", "telah diubah", "telah diperbarui", "berhasil diterapkan", "berhasil dihapus"]
            if clean_field in ("summary", "deskripsi", "ringkasan") and any(p in formatted_val.lower() for p in conv_phrases):
                logger.warning(f"[DedicatedService] Rejected chatbot conversational response as summary value: {formatted_val}")
                return {"success": False, "error": "Value summary tidak boleh berupa kalimat konfirmasi percakapan chatbot."}

            # Update document root ONLY if no target_item is specified (item-level isolation)
            if not target_item:
                if clean_field in ("price", "harga", "biaya"):
                    old_value = existing_doc.get("price") or existing_doc.get("metadata", {}).get("price")
                    existing_doc["price"] = formatted_val
                    if "metadata" not in existing_doc or not isinstance(existing_doc["metadata"], dict):
                        existing_doc["metadata"] = {}
                    existing_doc["metadata"]["price"] = formatted_val
                elif clean_field in ("title", "nama", "nama_produk"):
                    old_value = existing_doc.get("title", existing_doc.get("file_name", ""))
                    existing_doc["title"] = formatted_val
                elif clean_field in ("valid_until", "expiry_date", "end_date", "periode", "masa_berlaku"):
                    old_value = existing_doc.get("valid_until")
                    existing_doc["valid_until"] = formatted_val
                elif clean_field in ("categories", "kategori"):
                    old_value = existing_doc.get("categories", [])
                    try:
                        parsed_cats = json.loads(new_value) if isinstance(new_value, str) else new_value
                        existing_doc["categories"] = parsed_cats if isinstance(parsed_cats, list) else [str(parsed_cats)]
                    except Exception:
                        existing_doc["categories"] = [formatted_val]
                else:
                    old_value = existing_doc.get(clean_field) or existing_doc.get("metadata", {}).get(clean_field)
                    existing_doc[clean_field] = formatted_val
                    if "metadata" not in existing_doc or not isinstance(existing_doc["metadata"], dict):
                        existing_doc["metadata"] = {}
                    existing_doc["metadata"][clean_field] = formatted_val

            # Surgically update summary and chunks
            chunks = existing_doc.get("chunks", [])
            clean_item_name = re.sub(r'^\*+|\*+$|^_+|_+$|^#+\s*', '', target_item.strip()).strip() if target_item else ""
            target_item_lower = clean_item_name.lower() if clean_item_name else None

            # 1. Update summary for target item
            curr_summary = existing_doc.get("summary", "")
            if curr_summary:
                doc_title = str(existing_doc.get("title") or existing_doc.get("file_name") or "")
                is_dedicated = bool(target_item and (target_item_lower in doc_title.lower() or doc_title.lower() in target_item_lower))

                # Field synonym regex helper
                field_synonyms = [re.escape(clean_field)]
                if clean_field in ("ukuran", "size", "netto", "berat", "weight", "volume"):
                    field_synonyms = ["ukuran", "size", "netto", "berat", "weight", "volume"]
                elif clean_field in ("harga", "price", "biaya", "tarif"):
                    field_synonyms = ["harga", "price", "biaya", "tarif"]
                elif clean_field in ("sku", "kode", "kode_sku"):
                    field_synonyms = ["sku", "kode", "kode_sku"]
                elif clean_field in ("kategori", "category"):
                    field_synonyms = ["kategori", "category"]
                elif clean_field in ("deskripsi", "description", "keterangan"):
                    field_synonyms = ["deskripsi", "description", "keterangan"]
                elif clean_field in ("indikasi", "indication"):
                    field_synonyms = ["indikasi", "indication", "indications"]
                elif clean_field in ("cara_pakai", "aturan_pakai", "instruksi", "penggunaan", "dosis"):
                    field_synonyms = ["cara_pakai", "aturan_pakai", "instruksi", "penggunaan", "dosis", "cara pakai", "aturan pakai"]
                elif clean_field in ("kandungan", "komposisi", "ingredients", "key_ingredients", "key ingredients", "ingridients", "bahan"):
                    field_synonyms = ["kandungan", "komposisi", "ingredients", "key ingredients", "key_ingredients", "ingridients", "bahan"]

                syn_regex = "|".join(field_synonyms)
                bullet_attr_pattern = re.compile(
                    r'(^[|\-\*]\s*\*+(?:' + syn_regex + r')[:\*\s]+|^[|\-\*]\s*(?:' + syn_regex + r')[:\s]+)[^\n\r]+',
                    re.MULTILINE | re.IGNORECASE
                )

                if is_dedicated:
                    # In a dedicated document, the entire document is about target_item
                    if bullet_attr_pattern.search(curr_summary):
                        curr_summary = bullet_attr_pattern.sub(rf'\g<1>{formatted_val}', curr_summary)
                    else:
                        if "## Informasi Produk" in curr_summary:
                            curr_summary = re.sub(
                                r'(## Informasi Produk[^\n]*\n(?:[^\n]*\n)*?)(?=\n##|\Z)',
                                rf'\g<1>- **{field.capitalize()}:** {formatted_val}\n',
                                curr_summary
                            )
                        else:
                            curr_summary = curr_summary.rstrip() + f"\n- **{field.capitalize()}:** {formatted_val}\n"
                    existing_doc["summary"] = curr_summary

                elif target_item and target_item_lower:
                    escaped_item = re.escape(target_item.strip())
                    # Heading section match: ## target_item ... until next same-level or higher heading
                    item_section_pattern = re.compile(
                        r'(#{1,4}\s*[^\n]*' + escaped_item + r'[^\n]*\n(?:(?!^#{1,2}\s)[^\n]*\n?)*)',
                        re.MULTILINE | re.IGNORECASE
                    )
                    match = item_section_pattern.search(curr_summary)
                    if match:
                        section_text = match.group(1)
                        if clean_field in ("price", "harga", "biaya"):
                            clean_num = re.sub(r'^(?:rp\.?\s*)', '', formatted_val, flags=re.IGNORECASE).strip()
                            price_pat = re.compile(
                                r'(^[|\-\*]\s*\*+(?:harga|price|biaya|tarif)[:\*\s]+|^[|\-\*]\s*(?:harga|price|biaya|tarif)[:\s]+)(?:Rp\.?\s*)?[^\n\r]+',
                                re.MULTILINE | re.IGNORECASE
                            )
                            if price_pat.search(section_text):
                                section_text = price_pat.sub(rf'\g<1>Rp {clean_num}', section_text)
                            else:
                                section_text = section_text.rstrip() + f"\n- **Harga**: Rp {clean_num}\n\n"
                        elif clean_field in ("sku", "kode", "kode_sku"):
                            sku_pat = re.compile(
                                r'(^[|\-\*]\s*\*+(?:sku|kode)[:\*\s]+|^[|\-\*]\s*(?:sku|kode)[:\s]+)[^\n\r]+',
                                re.MULTILINE | re.IGNORECASE
                            )
                            if sku_pat.search(section_text):
                                section_text = sku_pat.sub(rf'\g<1>{formatted_val}', section_text)
                            else:
                                section_text = section_text.rstrip() + f"\n- **SKU**: {formatted_val}\n\n"
                        else:
                            if bullet_attr_pattern.search(section_text):
                                section_text = bullet_attr_pattern.sub(rf'\g<1>{formatted_val}', section_text)
                            else:
                                section_text = section_text.rstrip() + f"\n- **{field.capitalize()}**: {formatted_val}\n\n"

                        curr_summary = curr_summary[:match.start()] + section_text + curr_summary[match.end():]
                        existing_doc["summary"] = curr_summary

                    # 1B. Table row match: | target_item | ... |
                    table_row_pattern = re.compile(rf'(^\s*\|\s*[^\n|]*{escaped_item}[^\n|]*\|)([^\n]+)$', re.MULTILINE | re.IGNORECASE)
                    if table_row_pattern.search(curr_summary):
                        curr_summary = table_row_pattern.sub(rf'\g<1> {formatted_val} |', curr_summary)
                        existing_doc["summary"] = curr_summary

                    # 1C. Bullet key match: - **target_item**: ...
                    bullet_key_pattern = re.compile(rf'(^[|\-\*]\s*\*\*[^\*\n:]*{escaped_item}[^\*\n:]*\*\*\s*:\s*)[^\n]+', re.MULTILINE | re.IGNORECASE)
                    if bullet_key_pattern.search(curr_summary):
                        curr_summary = bullet_key_pattern.sub(rf'\g<1>{formatted_val}', curr_summary)
                        existing_doc["summary"] = curr_summary

                    # 1D. Ingredient / keyword replacement across summary:
                    if clean_item_name and clean_item_name.lower() in curr_summary.lower():
                        curr_summary = re.sub(rf'\b{re.escape(clean_item_name)}\b', formatted_val, curr_summary, flags=re.IGNORECASE)
                        existing_doc["summary"] = curr_summary

            # 2. Update matching chunks
            for chunk in chunks:
                if not isinstance(chunk, dict):
                    continue
                if "metadata" not in chunk:
                    chunk["metadata"] = {}
                chunk["metadata"]["knowledge_id"] = doc_kid

                chunk_text = chunk.get("text", "")
                chunk_text_lower = chunk_text.lower()

                # Replace direct ingredient / keyword in chunk text if present
                if clean_item_name and clean_item_name.lower() in chunk_text_lower:
                    chunk["text"] = re.sub(rf'\b{re.escape(clean_item_name)}\b', formatted_val, chunk_text, flags=re.IGNORECASE)
                    chunk_text = chunk["text"]
                    chunk_text_lower = chunk_text.lower()

                # If target_item is specified, skip chunks that do not belong to this item
                if target_item_lower and target_item_lower not in chunk_text_lower:
                    continue

                # Apply field metadata to matching chunk
                chunk["metadata"][clean_field] = formatted_val

                # Update chunk text
                escaped_item = re.escape(target_item.strip()) if target_item else ""
                if clean_field in ("price", "harga", "biaya"):
                    clean_num = re.sub(r'^(?:rp\.?\s*)', '', formatted_val, flags=re.IGNORECASE).strip()
                    price_pattern = re.compile(r'(^[|\-\*]\s*\*+(?:harga|price|biaya|tarif)[:\*\s]+|^[|\-\*]\s*(?:harga|price|biaya|tarif)[:\s]+)(?:Rp\.?\s*)?[^\n\r]+', re.MULTILINE | re.IGNORECASE)
                    if price_pattern.search(chunk_text):
                        chunk["text"] = price_pattern.sub(rf'\g<1>Rp {clean_num}', chunk_text)
                    elif not re.match(r'^#{1,3}\s+[^\n]+$', chunk_text.strip()):
                        chunk["text"] = chunk_text.strip() + f"\n- **Harga**: Rp {clean_num}"
                elif clean_field in ("sku", "kode_sku", "kode"):
                    sku_pattern = re.compile(r'(^[|\-\*]\s*\*+(?:sku|kode)[:\*\s]+|^[|\-\*]\s*(?:sku|kode)[:\s]+)[^\n\r]+', re.MULTILINE | re.IGNORECASE)
                    if sku_pattern.search(chunk_text):
                        chunk["text"] = sku_pattern.sub(rf'\g<1>{formatted_val}', chunk_text)
                    elif not re.match(r'^#{1,3}\s+[^\n]+$', chunk_text.strip()):
                        chunk["text"] = chunk_text.strip() + f"\n- **SKU**: {formatted_val}"
                elif escaped_item:
                    # Check table row in chunk
                    t_pattern = re.compile(rf'(^\s*\|\s*[^\n|]*{escaped_item}[^\n|]*\|)([^\n]+)$', re.MULTILINE | re.IGNORECASE)
                    if t_pattern.search(chunk_text):
                        chunk["text"] = t_pattern.sub(rf'\g<1> {formatted_val} |', chunk_text)
                    else:
                        b_pattern = re.compile(rf'(^[|\-\*]\s*\*\*[^\*\n:]*{escaped_item}[^\*\n:]*\*\*\s*:\s*)[^\n]+', re.MULTILINE | re.IGNORECASE)
                        if b_pattern.search(chunk_text):
                            chunk["text"] = b_pattern.sub(rf'\g<1>{formatted_val}', chunk_text)
                        elif bullet_attr_pattern.search(chunk_text):
                            chunk["text"] = bullet_attr_pattern.sub(rf'\g<1>{formatted_val}', chunk_text)
                        elif not re.match(r'^#{1,3}\s+[^\n]+$', chunk_text.strip()):
                            chunk["text"] = chunk_text.strip() + f"\n- **{field.capitalize()}**: {formatted_val}"
                else:
                    if bullet_attr_pattern.search(chunk_text):
                        chunk["text"] = bullet_attr_pattern.sub(rf'\g<1>{formatted_val}', chunk_text)
                    elif not re.match(r'^#{1,3}\s+[^\n]+$', chunk_text.strip()):
                        chunk["text"] = chunk_text.strip() + f"\n- **{field.capitalize()}**: {formatted_val}"

            # Synchronize last assistant turn in staging_history/history if present
            curr_summary = existing_doc.get("summary", "")
            if curr_summary:
                for hist_key in ("staging_history", "history"):
                    if hist_key in existing_doc and isinstance(existing_doc[hist_key], list) and existing_doc[hist_key]:
                        for turn in reversed(existing_doc[hist_key]):
                            if isinstance(turn, dict) and turn.get("role") == "assistant":
                                turn["content"] = curr_summary
                                break

            # Append to edit_history
            edit_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": "edit",
                "field": clean_field,
                "target_item": target_item,
                "old_value": str(old_value)[:200] if old_value else None,
                "new_value": formatted_val,
                "source": "general_prompt"
            }
            if "edit_history" not in existing_doc or not isinstance(existing_doc["edit_history"], list):
                existing_doc["edit_history"] = []
            existing_doc["edit_history"].append(edit_entry)

            # Update batch_summary if this document belongs to a batch
            batch_id = existing_doc.get("batch_id")
            cur_bs = existing_doc.get("batch_summary") or existing_doc.get("metadata", {}).get("batch_summary")
            if cur_bs and target_item:
                if bullet_attr_pattern.search(cur_bs):
                    cur_bs = bullet_attr_pattern.sub(rf'\g<1>{formatted_val}', cur_bs)
                existing_doc["batch_summary"] = cur_bs
                if "metadata" in existing_doc and isinstance(existing_doc["metadata"], dict):
                    existing_doc["metadata"]["batch_summary"] = cur_bs

                # Propagate updated batch_summary to other output/pending files in this batch
                out_dir = settings.output_dir if hasattr(settings, "output_dir") else "data/output"
                if os.path.exists(out_dir):
                    for fn in os.listdir(out_dir):
                        if fn.endswith(".json") and fn != os.path.basename(approved_file):
                            f_path = os.path.join(out_dir, fn)
                            try:
                                with open(f_path, "r", encoding="utf-8") as bf:
                                    b_data = json.load(bf)
                                if b_data.get("batch_id") == batch_id:
                                    b_data["batch_summary"] = cur_bs
                                    if "metadata" in b_data and isinstance(b_data["metadata"], dict):
                                        b_data["metadata"]["batch_summary"] = cur_bs
                                    with open(f_path, "w", encoding="utf-8") as bf:
                                        json.dump(b_data, bf, indent=4, ensure_ascii=False)
                            except Exception:
                                pass

            if auto_approve:
                # AUTO-APPROVE: General Prompt confirm → overwrite approved file, re-ingest immediately
                existing_doc["status"] = "Approved"
                existing_doc.pop("is_revision", None)

                # 1. Overwrite data/output/{doc_kid}.json
                os.makedirs("data/output", exist_ok=True)
                with open(approved_file, "w", encoding="utf-8") as f:
                    json.dump(existing_doc, f, indent=4, ensure_ascii=False)

                # 2. Re-chunk from updated summary for vector + BM25 indexing
                doc_chunks = existing_doc.get("chunks", [])
                updated_summary = existing_doc.get("summary", "")
                if updated_summary and updated_summary.strip():
                    try:
                        from app.rag.utils.summary_chunker import chunk_summary_markdown
                        doc_img_url = existing_doc.get("image_url") or (
                            existing_doc.get("image_urls", [None])[0]
                            if existing_doc.get("image_urls") else None
                        )
                        raw_cats = existing_doc.get("categories") or existing_doc.get("suggested_categories") or []
                        parsed_cats = []
                        if isinstance(raw_cats, list):
                            for c in raw_cats:
                                if isinstance(c, dict) and "name" in c:
                                    parsed_cats.append(c["name"])
                                elif isinstance(c, str):
                                    parsed_cats.append(c)
                        vis_settings = existing_doc.get("visibility_settings") or {
                            "clinics": ["all"], "doctor_types": ["all"], "doctors": ["all"]
                        }
                        doc_chunks = chunk_summary_markdown(
                            summary=updated_summary,
                            source_file=existing_doc.get("file_name", doc_kid),
                            knowledge_id=doc_kid,
                            batch_id=existing_doc.get("batch_id"),
                            file_hash=existing_doc.get("file_hash", ""),
                            title=existing_doc.get("title", doc_kid),
                            doc_type=existing_doc.get("document_type", "GENERAL"),
                            categories=parsed_cats,
                            valid_from=str(existing_doc.get("valid_from", "")).strip() or None,
                            valid_until=str(existing_doc.get("valid_until", "")).strip() or None,
                            visibility_settings=vis_settings,
                            default_image_url=doc_img_url,
                        )
                        existing_doc["chunks"] = doc_chunks
                        # Re-save with updated chunks
                        with open(approved_file, "w", encoding="utf-8") as f:
                            json.dump(existing_doc, f, indent=4, ensure_ascii=False)
                        logger.info(f"[DedicatedService] Re-chunked summary into {len(doc_chunks)} chunks for '{doc_kid}'")
                    except Exception as rechunk_err:
                        logger.warning(f"[DedicatedService] Re-chunking failed, using existing chunks: {rechunk_err}")

                # 3. Re-ingest into Vector Store (delete old → insert new)
                v_store = vector_store
                if not v_store and pipeline:
                    v_store = pipeline.vector_store
                if not v_store:
                    try:
                        from app.rag.services.vector_store import PGVectorAdapter
                        v_store = PGVectorAdapter()
                    except Exception:
                        pass
                if v_store:
                    try:
                        v_store.delete_document(doc_kid)
                        file_name = existing_doc.get("file_name", "")
                        if file_name and file_name != doc_kid:
                            v_store.delete_document(file_name)
                    except Exception as del_err:
                        logger.debug(f"[DedicatedService] Vector pre-delete note: {del_err}")
                    if doc_chunks:
                        try:
                            v_store.insert_chunks(doc_chunks)
                            logger.info(f"[DedicatedService] Re-indexed {len(doc_chunks)} chunks in vector store for '{doc_kid}'")
                        except Exception as ins_err:
                            logger.error(f"[DedicatedService] Vector insert failed: {ins_err}")

                # 4. Re-ingest into BM25 Index
                bm25_inst = bm25_index
                if not bm25_inst:
                    try:
                        from app.rag.services.rag_retriever import BM25Index
                        bm25_inst = BM25Index()
                        if os.path.exists(settings.bm25_index_path):
                            bm25_inst.load(settings.bm25_index_path)
                    except Exception:
                        pass
                if bm25_inst:
                    try:
                        bm25_inst.remove_file_chunks(doc_kid)
                        file_name = existing_doc.get("file_name", "")
                        if file_name and file_name != doc_kid:
                            bm25_inst.remove_file_chunks(file_name)
                    except Exception as bm25_del_err:
                        logger.debug(f"[DedicatedService] BM25 pre-delete note: {bm25_del_err}")
                    if doc_chunks:
                        try:
                            bm25_inst.add_chunks(doc_chunks)
                            os.makedirs(os.path.dirname(settings.bm25_index_path), exist_ok=True)
                            bm25_inst.save(settings.bm25_index_path)
                            logger.info(f"[DedicatedService] Re-indexed {len(doc_chunks)} chunks in BM25 for '{doc_kid}'")
                        except Exception as bm25_ins_err:
                            logger.error(f"[DedicatedService] BM25 insert failed: {bm25_ins_err}")

                # 5. Sync PostgreSQL Knowledge record
                try:
                    await GeneralKnowledgeService.sync_knowledge_db(doc_kid, existing_doc=existing_doc, db=db)
                except Exception as db_err:
                    logger.debug(f"[DedicatedService] DB sync note: {db_err}")

                # 6. Upload approved JSON to MinIO approved bucket
                try:
                    from app.services.storage import promote_staging_to_approved
                    promote_staging_to_approved(doc_kid, existing_doc)
                except Exception as s3_err:
                    logger.debug(f"[DedicatedService] MinIO approved sync note: {s3_err}")

                # 7. Clean up any stale pending file
                pending_cleanup = os.path.join("data/pending", f"{doc_kid}.json")
                if os.path.exists(pending_cleanup):
                    try:
                        os.remove(pending_cleanup)
                    except Exception:
                        pass

                logger.info(f"[DedicatedService] Auto-approved edit for '{doc_kid}'. Data immediately retrievable by RAG.")
                return {
                    "success": True,
                    "knowledge_id": doc_kid,
                    "field": field,
                    "target_item": target_item,
                    "old_value": str(old_value)[:200] if old_value else None,
                    "new_value": str(new_value)[:200],
                    "message": f"Perubahan pada '{target_item or doc_kid}' berhasil diterapkan dan langsung aktif di RAG."
                }
            else:
                # PENDING DRAFT: Dashboard Admin edit → Priority 4 versioning rule
                existing_doc["status"] = "On review"
                existing_doc["is_revision"] = True
                os.makedirs("data/pending", exist_ok=True)
                pending_file = os.path.join("data/pending", f"{doc_kid}.json")
                with open(pending_file, "w", encoding="utf-8") as f:
                    json.dump(existing_doc, f, indent=4, ensure_ascii=False)

                try:
                    from app.services.storage import upload_staging_json
                    upload_staging_json(doc_kid, existing_doc)
                except Exception as s3_err:
                    logger.debug(f"[DedicatedService] MinIO staging sync note: {s3_err}")

                logger.info(f"[DedicatedService] Staged edit revision for '{doc_kid}' to pending queue (status: 'On review'). Active approved document remains searchable until approved.")
                return {
                    "success": True,
                    "knowledge_id": doc_kid,
                    "field": field,
                    "target_item": target_item,
                    "old_value": str(old_value)[:200] if old_value else None,
                    "new_value": str(new_value)[:200],
                    "message": f"Perubahan pada '{target_item or doc_kid}' berhasil disimpan sebagai draft peninjauan (PENDING). Dokumen aktif tetap diretrieve RAG sampai diapprove."
                }


        except Exception as e:
            logger.error(f"[DedicatedService] Failed to apply edit for '{knowledge_id}': {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def apply_delete(
        knowledge_id: str,
        vector_store=None,
        bm25_index=None,
        target_item: Optional[str] = None,
        db=None
    ) -> Dict[str, Any]:
        """
        Deletes a KB document or surgically deletes a specific item within a multi-item document.
        Synchronizes local JSON, PostgreSQL, PGVector, MinIO, and BM25 index.
        """
        clean_target = (knowledge_id or "").strip().lower()

        # 1. Item-Level Surgical Deletion
        if target_item and target_item.strip():
            raw_item_clean = re.sub(r'^\*+|\*+$|^_+|_+$|^#+\s*', '', target_item.strip()).strip()
            target_item_clean = raw_item_clean
            target_item_lower = target_item_clean.lower()
            approved_file = resolve_approved_file(knowledge_id)
            if not approved_file:
                return {"success": False, "error": f"Dokumen dengan ID '{knowledge_id}' tidak ditemukan di approved KB."}

            try:
                with open(approved_file, "r", encoding="utf-8") as f:
                    existing_doc = json.load(f)

                doc_kid = str(existing_doc.get("knowledge_id") or knowledge_id)
                summary = existing_doc.get("summary", "")

                # Build list of specific items to delete (supports comma-separated or ingredient queries)
                delete_targets = []
                if "," in target_item:
                    for s in target_item.split(","):
                        s_clean = s.strip()
                        if s_clean and not s_clean.lower().startswith("produk dengan kandungan"):
                            delete_targets.append(s_clean)

                ing_m = re.search(r'(?:produk\s+(?:dengan\s+)?(?:yang\s+)?(?:mengandung|kandungan|bahan)\s+|kandungan\s+)(.+)', target_item, re.IGNORECASE)
                ing_keyword = ing_m.group(1).strip().lower() if ing_m else None
                if not ing_keyword and len(target_item_clean.split()) <= 4 and target_item_clean.lower() not in (str(existing_doc.get("title", "")).lower(), str(existing_doc.get("file_name", "")).lower()):
                    ing_keyword = target_item_clean.lower()

                # If ingredient keyword is present, collect all specific product names containing it
                if ing_keyword:
                    corpus = summary + " " + str(existing_doc.get("batch_summary", ""))
                    if existing_doc.get("staging_history") and isinstance(existing_doc.get("staging_history"), list):
                        for t in existing_doc.get("staging_history"):
                            if isinstance(t, dict) and t.get("role") == "assistant":
                                corpus += "\n" + str(t.get("content", ""))
                    ing_re = re.compile(rf'\b{re.escape(ing_keyword)}\b', re.IGNORECASE)
                    for line in corpus.splitlines():
                        if ing_re.search(line):
                            # Check for heading
                            m_h = re.match(r'^#{1,3}\s+([^\n]+)', line)
                            if m_h:
                                h_name = re.sub(r'[\*\_]', '', m_h.group(1)).strip()
                                if len(h_name) > 2 and h_name.lower() not in ("ringkasan dokumen", "penutup", "evaluasi hasil", "profil pasien", "detail perawatan"):
                                    delete_targets.append(h_name)
                            # Check for bullet or table row product name
                            m_b = re.match(r'^[|\-\*]\s*([^\n|→]+?)(?:\s*→|\s*\||\s*:\s*Sabun|\s*:\s*Pelembap|\s*:\s*Perawatan)', line)
                            if m_b:
                                b_name = re.sub(r'[\*\_#]', '', m_b.group(1)).strip()
                                if len(b_name) > 3 and not b_name.lower().startswith("http") and not b_name.lower().startswith("/api/storage"):
                                    delete_targets.append(b_name)

                if not delete_targets:
                    delete_targets = [target_item_clean]

                # Deduplicate delete_targets
                unique_delete_targets = []
                seen_dt = set()
                for dt in delete_targets:
                    if dt.lower() not in seen_dt:
                        seen_dt.add(dt.lower())
                        unique_delete_targets.append(dt)
                delete_targets = unique_delete_targets

                original_chunks = existing_doc.get("chunks", [])
                filtered_chunks = []
                removed_count = 0
                ing_re = re.compile(rf'\b{re.escape(ing_keyword)}\b', re.IGNORECASE) if ing_keyword else None

                for chunk in original_chunks:
                    chunk_text = chunk.get("text", "") if isinstance(chunk, dict) else ""
                    chunk_lower = chunk_text.lower()
                    meta = chunk.get("metadata", {}) if isinstance(chunk, dict) else {}

                    # Check if chunk matches any delete target or ingredient
                    should_remove = False
                    for dt in delete_targets:
                        dt_low = dt.lower()
                        if dt_low in chunk_lower or re.sub(r'[\*\_#]', '', chunk_lower).find(dt_low) != -1:
                            should_remove = True
                            break
                        if dt_low in (str(meta.get("product_name", "")).lower(), str(meta.get("title", "")).lower(), str(meta.get("section", "")).lower(), str(meta.get("heading", "")).lower()):
                            should_remove = True
                            break

                    if not should_remove and ing_re and ing_re.search(chunk_lower):
                        should_remove = True

                    if should_remove:
                        removed_count += 1
                    else:
                        filtered_chunks.append(chunk)

                # Helper to clean markdown sections, bullets, and table rows
                def _clean_md(text: str, targets: list[str], ing_kw: Optional[str]) -> str:
                    if not text:
                        return ""
                    res = text
                    for t in targets:
                        if not t or len(t.strip()) < 2:
                            continue
                        esc = re.escape(t.strip())
                        res = re.sub(
                            r'(?:^|\n)(#{1,4}\s*[^\n]*' + esc + r'[^\n]*\n(?:(?!^#{1,4}\s)[^\n]*\n?)*)',
                            '\n',
                            res,
                            flags=re.MULTILINE | re.IGNORECASE
                        )
                        res = re.sub(
                            rf'^[|\-\*\d\.]+\s*[^\n]*{esc}[^\n]*$\n?',
                            '',
                            res,
                            flags=re.MULTILINE | re.IGNORECASE
                        )
                    if ing_kw and len(ing_kw.strip()) > 1:
                        esc_ing = re.escape(ing_kw.strip())
                        res = re.sub(
                            rf'^[|\-\*\d\.]+\s*[^\n]*\b{esc_ing}\b[^\n]*$\n?',
                            '',
                            res,
                            flags=re.MULTILINE | re.IGNORECASE
                        )
                    return re.sub(r'\n{3,}', '\n\n', res).strip()

                # Clean summary
                if summary:
                    existing_doc["summary"] = _clean_md(summary, delete_targets, ing_keyword)

                # Clean batch_summary
                if existing_doc.get("batch_summary"):
                    existing_doc["batch_summary"] = _clean_md(existing_doc["batch_summary"], delete_targets, ing_keyword)
                    if "metadata" in existing_doc and isinstance(existing_doc["metadata"], dict):
                        existing_doc["metadata"]["batch_summary"] = existing_doc["batch_summary"]

                # Clean staging_history
                for hist_key in ("staging_history", "history"):
                    if hist_key in existing_doc and isinstance(existing_doc[hist_key], list):
                        for turn in existing_doc[hist_key]:
                            if isinstance(turn, dict) and turn.get("role") == "assistant":
                                orig_c = turn.get("content", "")
                                if orig_c:
                                    turn["content"] = _clean_md(orig_c, delete_targets, ing_keyword)

                existing_doc["chunks"] = filtered_chunks

                if not filtered_chunks:
                    # All chunks were removed -> Full document deletion
                    if approved_file and os.path.exists(approved_file):
                        try:
                            os.remove(approved_file)
                        except Exception:
                            pass
                    if vector_store:
                        vector_store.delete_document(doc_kid)
                    if bm25_index:
                        bm25_index.remove_file_chunks(doc_kid)
                        bm25_index.save(settings.bm25_index_path)
                    try:
                        from app.services.storage import delete_knowledge_images_and_assets
                        delete_knowledge_images_and_assets(doc_kid, doc_data=existing_doc)
                    except Exception as s3_err:
                        logger.debug(f"[DedicatedService] MinIO delete note: {s3_err}")
                    await GeneralKnowledgeService.sync_knowledge_db(doc_kid, deleted=True, db=db)
                    return {
                        "success": True,
                        "knowledge_id": doc_kid,
                        "target_item": target_item_clean,
                        "title": f"Seluruh item ({', '.join(delete_targets)}) dan dokumen '{doc_kid}' berhasil dihapus dari basis pengetahuan."
                    }

                with open(approved_file, "w", encoding="utf-8") as f:
                    json.dump(existing_doc, f, indent=4, ensure_ascii=False)

                if vector_store:
                    vector_store.delete_document(doc_kid)
                    if filtered_chunks:
                        vector_store.insert_chunks(filtered_chunks)

                if bm25_index:
                    bm25_index.remove_file_chunks(doc_kid)
                    if filtered_chunks:
                        bm25_index.add_chunks(filtered_chunks)
                    bm25_index.save(settings.bm25_index_path)

                try:
                    from app.services.storage import upload_approved_json
                    upload_approved_json(doc_kid, existing_doc)
                except Exception as s3_err:
                    logger.debug(f"[DedicatedService] MinIO update note: {s3_err}")

                # Sync PostgreSQL Knowledge DB record directly and commit
                await GeneralKnowledgeService.sync_knowledge_db(doc_kid, existing_doc=existing_doc, db=db)

                logger.info(f"[DedicatedService] Surgically deleted item '{target_item_clean}' from doc '{doc_kid}' ({removed_count} chunks removed)")
                return {
                    "success": True,
                    "knowledge_id": doc_kid,
                    "target_item": target_item_clean,
                    "title": f"Item '{target_item_clean}' berhasil dihapus dari basis pengetahuan."
                }
            except Exception as e:
                logger.error(f"[DedicatedService] Item-level delete failed: {e}")
                return {"success": False, "error": str(e)}

        # 2. Batch Delete Expired Promos
        if clean_target in ("expired", "expired_promos", "promo_expired", "promo expired", "promo bulan lalu", "semua promo expired", "promo yang sudah expired"):
            today = datetime.now(timezone.utc).date()
            deleted_items = []
            pending_dir = "data/pending"
            approved_dir = "data/output"

            for folder in [pending_dir, approved_dir, os.path.join("backend", pending_dir), os.path.join("backend", approved_dir)]:
                if os.path.exists(folder):
                    for f in os.listdir(folder):
                        if f.endswith(".json") and f != "bm25_index.pkl":
                            f_path = os.path.join(folder, f)
                            try:
                                with open(f_path, "r", encoding="utf-8") as fp:
                                    f_data = json.load(fp)
                                is_expired = False
                                vu = f_data.get("valid_until") or f_data.get("expiry_date")
                                if vu:
                                    parsed_vu = parse_date_safely(vu)
                                    if parsed_vu and parsed_vu < today:
                                        is_expired = True

                                if is_expired:
                                    doc_id = str(f_data.get("knowledge_id", f.replace(".json", "")))
                                    doc_title = str(f_data.get("title", f_data.get("file_name", doc_id)))
                                    os.remove(f_path)
                                    if vector_store:
                                        vector_store.delete_document(doc_id)
                                    if bm25_index:
                                        bm25_index.remove_file_chunks(doc_id)
                                    deleted_items.append(f"{doc_title} (expired: {vu})")
                            except Exception as err:
                                logger.debug(f"[DedicatedService] Error checking expired file {f}: {err}")

            if bm25_index and deleted_items:
                bm25_index.save(settings.bm25_index_path)

            return {
                "success": True,
                "knowledge_id": "expired",
                "title": f"Berhasil menghapus {len(deleted_items)} promo kadaluarsa:\n" + "\n".join(f"- {d}" for d in deleted_items[:10])
            }

        # 3. Full Document Deletion
        approved_file = resolve_approved_file(knowledge_id)
        if not approved_file:
            return {"success": False, "error": f"Dokumen dengan ID/Nama '{knowledge_id}' tidak ditemukan di database."}

        try:
            with open(approved_file, "r", encoding="utf-8") as fp:
                f_data = json.load(fp)
            target_kid = str(f_data.get("knowledge_id") or knowledge_id)
            deleted_title = str(f_data.get("title", f_data.get("file_name", target_kid)))

            # Delete local file
            os.remove(approved_file)

            # Clear Vector Store
            if vector_store:
                vector_store.delete_document(target_kid)

            # Clear BM25
            if bm25_index:
                bm25_index.remove_file_chunks(target_kid)
                bm25_index.save(settings.bm25_index_path)

            # Delete from MinIO (including all embedded images and documents)
            try:
                from app.services.storage import delete_knowledge_images_and_assets
                delete_knowledge_images_and_assets(target_kid, doc_data=f_data)
            except Exception as s3_err:
                logger.debug(f"[DedicatedService] MinIO delete note: {s3_err}")

            # Soft-delete in PostgreSQL Knowledge DB record directly and commit
            await GeneralKnowledgeService.sync_knowledge_db(target_kid, deleted=True, db=db)

            return {
                "success": True,
                "knowledge_id": target_kid,
                "title": deleted_title
            }

        except Exception as e:
            logger.error(f"[DedicatedService] Failed to delete document '{knowledge_id}': {e}")
            return {"success": False, "error": str(e)}
