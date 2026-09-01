import os
import json
import asyncio
from typing import List, Optional, Dict, Any, Union
from loguru import logger
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, BackgroundTasks, Path, Body, Request
from pydantic import BaseModel, Field, model_validator

import uuid

from app.rag.schemas import (
    ChatRequest, 
    ChatResponse, 
    UserContext,
    EvaluationItem,
    TextIngestRequest,
    DocumentListItem,
    PendingDocumentResponse,
    RefineRequest,
    EditApprovedDocumentRequest,
    ApprovedDocumentResponse,
    RAGEvaluationItem,
    RAGEvaluationRequest,
    RAGEvaluationQueryResult,
    RAGEvaluationResponse
)
from app.rag.services.rag_pipeline import IngestionPipeline
from app.rag.services.rag_retriever import HybridRetriever, BM25Index
from app.rag.services.rag_generator import GenerationPipeline
from app.rag.services.evaluation import RetrievalEvaluator, RAGEvaluator
from app.rag.services.guardrails import GuardrailsPipeline
from app.rag.config import settings
from app.rag.services.intent import QueryIntentDetector, QueryIntent
from app.rag.deps import (
    get_ingestion_pipeline,
    get_hybrid_retriever,
    get_generation_pipeline,
    get_bm25_index,
    get_llm,
    get_vector_store,
    get_medical_agent
)
from app.rag.services.interfaces import BaseLLMAdapter, BaseVectorStoreAdapter


def safe_json_loads(json_str: str) -> dict:
    """Parses JSON safely, handling unescaped control characters and markdown code blocks."""
    clean = (json_str or "").strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        clean = "\n".join(lines).strip()

    try:
        return json.loads(clean, strict=False)
    except Exception:
        # Sanitize unescaped control characters like raw newlines inside JSON strings
        import re
        sanitized = re.sub(r'[\r\n\t]', ' ', clean)
        return json.loads(sanitized, strict=False)


router = APIRouter()

def clean_duplicate_headers(text: str) -> str:
    """
    Cleans up accidental duplicated consecutive headers or lines in markdown text.
    For example:
        ERHA Acneact Acne Spot Gel
        
        ERHA Acneact Acne Spot Gel
    becomes:
        ## ERHA Acneact Acne Spot Gel
    """
    if not text:
        return ""
    lines = text.split("\n")
    cleaned_lines = []
    prev_line = None
    for line in lines:
        stripped = line.strip()
        # Avoid repeating identical adjacent title lines (e.g. "Title\n\nTitle")
        if stripped and prev_line and stripped.lower() == prev_line.lower():
            continue
        cleaned_lines.append(line)
        if stripped:
            prev_line = stripped
    return "\n".join(cleaned_lines)


def extract_sku_and_target(user_prompt: str) -> tuple[Optional[str], Optional[str]]:
    """
    Extracts SKU value and optional product target from user prompt.
    Supports single and multi-product target prompts.
    """
    import re
    # 1. "SKU <target> : <CODE>" e.g. "SKU Acne Spot Gel: PRO-565346"
    m0 = re.search(r'\bsku\b\s+(.+?)\s*[:=]\s*([A-Za-z0-9\-_]+)', user_prompt, re.IGNORECASE)
    if m0:
        middle = m0.group(1).strip(" :_-\t")
        code = m0.group(2).strip()
        if middle and middle.lower() not in ("nomor", "kode", "no", "nya", "dokumen", "produk", "jadi", "menjadi", ""):
            return code, middle

    # 2. "tambahkan SKU PRO-565346 (untuk|pada|di) <target>"
    m1 = re.search(r'\bsku\b\s*(?:nomor|kode|no)?\s*[:=\s]?\s*([A-Za-z0-9\-_]+)\s+(?:pada|untuk|di|buat)\s+(.+)', user_prompt, re.IGNORECASE)
    if m1:
        code = m1.group(1).strip()
        target = m1.group(2).strip(" .")
        if code.lower() not in ("jadi", "menjadi", "none", "null", "tidak", "ada", "kosong", "baru", "untuk", "pada"):
            return code, target

    # 3. "ganti nomor SKU <target> (jadi|menjadi|adalah) <CODE>"
    m2 = re.search(r'\bsku\b\s*(?:nomor|kode|no)?\s+(.+?)\s+(?:jadi|menjadi|adalah)\s*([A-Za-z0-9\-_]+)', user_prompt, re.IGNORECASE)
    if m2:
        middle = m2.group(1).strip(" :_-\t")
        code = m2.group(2).strip()
        if middle and middle.lower() not in ("nomor", "kode", "no", "nya", "dokumen", "produk", "jadi", "menjadi", ""):
            return code, middle
        if code.lower() not in ("jadi", "menjadi", "none", "null", "tidak", "ada", "kosong", "baru"):
            return code, None

    # 4. "ganti SKU (jadi|menjadi|adalah|=|:) <CODE>" or "SKU: <CODE>"
    m3 = re.search(r'\bsku\b\s*(?:nomor|kode|no)?\s*(?:jadi|menjadi|adalah|=|:|\s)\s*([A-Za-z0-9\-_]+)', user_prompt, re.IGNORECASE)
    if m3:
        cand = m3.group(1).strip()
        if cand.lower() not in ("jadi", "menjadi", "none", "null", "tidak", "ada", "kosong", "baru", "untuk", "pada", "di", "nomor", "kode", "no"):
            return cand, None

    # 5. Fallback 'kode sku ...' or 'nomor sku ...'
    m4 = re.search(r'(?:nomor|kode)\s+sku\s*(?:jadi|menjadi|adalah|=|:|\s)?\s*([A-Za-z0-9\-_]+)', user_prompt, re.IGNORECASE)
    if m4:
        cand = m4.group(1).strip()
        if cand.lower() not in ("jadi", "menjadi", "none", "null", "tidak", "ada", "kosong", "baru", "untuk", "pada"):
            return cand, None

    return None, None


def extract_price_and_target(user_prompt: str) -> tuple[Optional[str], Optional[str]]:
    """
    Extracts Price value and optional product target from user prompt.
    """
    import re
    # 1. "harga <target> (jadi|menjadi|adalah|=|:) Rp 50.000"
    m1 = re.search(r'\b(?:harga|price|tarif|biaya)\b\s+(.+?)\s+(?:jadi|menjadi|adalah|=|:)\s*(?:rp\.?\s*)?([0-9\.\,]+)', user_prompt, re.IGNORECASE)
    if m1:
        middle = m1.group(1).strip(" :_-\t")
        raw_price = m1.group(2).strip()
        target_hint = middle if middle.lower() not in ("nya", "produk", "dokumen", "jadi", "menjadi", "") else None
        return f"Rp {raw_price}" if not raw_price.lower().startswith("rp") else raw_price, target_hint

    # 2. "harga (jadi|menjadi|=|:|\s)* (rp 50.000) (pada|untuk|di|buat) <target>"
    m2 = re.search(r'\b(?:harga|price|tarif|biaya)\b\s*(?:jadi|menjadi|adalah|=|:|\s)?\s*(?:rp\.?\s*)?([0-9\.\,]+)\s+(?:pada|untuk|di|buat)\s+(.+)', user_prompt, re.IGNORECASE)
    if m2:
        raw_price = m2.group(1).strip()
        target = m2.group(2).strip(" .")
        return f"Rp {raw_price}" if not raw_price.lower().startswith("rp") else raw_price, target

    # 3. Simple "harga jadi Rp 50.000" or "harga: 50.000"
    m3 = re.search(r'\b(?:harga|price|tarif|biaya)\b\s*(?:jadi|menjadi|adalah|=|:|\s)?\s*(?:rp\.?\s*)?([0-9\.\,]+)', user_prompt, re.IGNORECASE)
    if m3:
        raw_price = m3.group(1).strip()
        return f"Rp {raw_price}" if not raw_price.lower().startswith("rp") else raw_price, None

    return None, None


def apply_refinements_to_content(
    user_prompt: str,
    summary: str,
    chunks: List[Dict[str, Any]],
    title: Optional[str] = None
) -> tuple[str, List[Dict[str, Any]], Optional[str], Optional[str]]:
    """
    Applies deterministic field overrides for SKU, Price, and Title if commanded in user_prompt,
    with full support for single-product and multi-product documents.
    Ensures that modifications targeted at a specific product apply ONLY to that product's section and chunks.
    """
    import re
    updated_summary = clean_duplicate_headers(summary or "")
    updated_title = title
    extracted_sku, sku_target = extract_sku_and_target(user_prompt)
    extracted_price, price_target = extract_price_and_target(user_prompt)

    # Split summary into product sections if multi-product
    # Split by H2 headers (##) or "Informasi Produk" or "Product Overview"
    product_section_pattern = r'(?=(?:^|\n)##\s+[^\n]+|(?:^|\n)Informasi Produk\s+[^\n]+)'
    sections = [s for s in re.split(product_section_pattern, updated_summary) if s]

    if len(sections) > 1 and (extracted_sku or extracted_price):
        new_sections = []
        for sec in sections:
            sec_lower = sec.lower()
            
            # Check if this section is the target for SKU
            is_sku_target = True
            if sku_target:
                sku_target_clean = sku_target.lower()
                target_words = [w for w in re.findall(r'\b[a-zA-Z0-9]{3,}\b', sku_target_clean) if w not in ('erha', 'acneact', 'the', 'and', 'for', 'product', 'overview')]
                if target_words:
                    is_sku_target = any(tw in sec_lower for tw in target_words)

            # Check if this section is the target for Price
            is_price_target = True
            if price_target:
                price_target_clean = price_target.lower()
                target_words = [w for w in re.findall(r'\b[a-zA-Z0-9]{3,}\b', price_target_clean) if w not in ('erha', 'acneact', 'the', 'and', 'for', 'product', 'overview')]
                if target_words:
                    is_price_target = any(tw in sec_lower for tw in target_words)

            sec_updated = sec
            if extracted_sku and is_sku_target:
                if re.search(r'((?:-\s*)?\*{0,2}SKU\*{0,2}\s*:)[^\n]+', sec_updated, re.IGNORECASE):
                    sec_updated = re.sub(r'((?:-\s*)?\*{0,2}SKU\*{0,2}\s*:)[^\n]+', r'\1 ' + extracted_sku, sec_updated, count=1, flags=re.IGNORECASE)
                elif re.search(r'((?:-\s*)?\*{0,2}Product Name\*{0,2}\s*:[^\n]+)', sec_updated, re.IGNORECASE):
                    sec_updated = re.sub(r'((?:-\s*)?\*{0,2}Product Name\*{0,2}\s*:[^\n]+)', r'\1\n- **SKU**: ' + extracted_sku, sec_updated, count=1, flags=re.IGNORECASE)
                elif re.search(r'(#{0,3}\s*Product Overview\b[^\n]*)', sec_updated, re.IGNORECASE):
                    sec_updated = re.sub(r'(#{0,3}\s*Product Overview\b[^\n]*)', r'\1\n- **SKU**: ' + extracted_sku, sec_updated, count=1, flags=re.IGNORECASE)

            if extracted_price and is_price_target:
                if re.search(r'((?:-\s*)?\*{0,2}(?:Price|Harga)\*{0,2}\s*:)[^\n]+', sec_updated, re.IGNORECASE):
                    sec_updated = re.sub(r'((?:-\s*)?\*{0,2}(?:Price|Harga)\*{0,2}\s*:)[^\n]+', r'\1 ' + extracted_price, sec_updated, count=1, flags=re.IGNORECASE)
                elif re.search(r'((?:-\s*)?\*{0,2}Net Content\*{0,2}\s*:[^\n]+)', sec_updated, re.IGNORECASE):
                    sec_updated = re.sub(r'((?:-\s*)?\*{0,2}Net Content\*{0,2}\s*:[^\n]+)', r'\1\n- **Harga**: ' + extracted_price, sec_updated, count=1, flags=re.IGNORECASE)
                elif re.search(r'(#{0,3}\s*Product Overview\b[^\n]*)', sec_updated, re.IGNORECASE):
                    sec_updated = re.sub(r'(#{0,3}\s*Product Overview\b[^\n]*)', r'\1\n- **Harga**: ' + extracted_price, sec_updated, count=1, flags=re.IGNORECASE)

            new_sections.append(sec_updated)
        updated_summary = "".join(new_sections)
    else:
        # Single-product document
        if extracted_sku:
            if re.search(r'((?:-\s*)?\*{0,2}SKU\*{0,2}\s*:)[^\n]+', updated_summary, re.IGNORECASE):
                updated_summary = re.sub(r'((?:-\s*)?\*{0,2}SKU\*{0,2}\s*:)[^\n]+', r'\1 ' + extracted_sku, updated_summary, count=1, flags=re.IGNORECASE)
            else:
                if re.search(r'((?:-\s*)?\*{0,2}Brand\*{0,2}\s*:[^\n]+)', updated_summary, re.IGNORECASE):
                    updated_summary = re.sub(r'((?:-\s*)?\*{0,2}Brand\*{0,2}\s*:[^\n]+)', r'\1\n- **SKU**: ' + extracted_sku, updated_summary, count=1, flags=re.IGNORECASE)
                elif re.search(r'((?:-\s*)?\*{0,2}Product Name\*{0,2}\s*:[^\n]+)', updated_summary, re.IGNORECASE):
                    updated_summary = re.sub(r'((?:-\s*)?\*{0,2}Product Name\*{0,2}\s*:[^\n]+)', r'\1\n- **SKU**: ' + extracted_sku, updated_summary, count=1, flags=re.IGNORECASE)
                elif re.search(r'(#{0,3}\s*Product Overview\b[^\n]*)', updated_summary, re.IGNORECASE):
                    updated_summary = re.sub(r'(#{0,3}\s*Product Overview\b[^\n]*)', r'\1\n- **SKU**: ' + extracted_sku, updated_summary, count=1, flags=re.IGNORECASE)
                else:
                    updated_summary += f'\n\n- **SKU**: {extracted_sku}'

        if extracted_price:
            if re.search(r'((?:-\s*)?\*{0,2}(?:Price|Harga)\*{0,2}\s*:)[^\n]+', updated_summary, re.IGNORECASE):
                updated_summary = re.sub(r'((?:-\s*)?\*{0,2}(?:Price|Harga)\*{0,2}\s*:)[^\n]+', r'\1 ' + extracted_price, updated_summary, count=1, flags=re.IGNORECASE)
            else:
                if re.search(r'((?:-\s*)?\*{0,2}Net Content\*{0,2}\s*:[^\n]+)', updated_summary, re.IGNORECASE):
                    updated_summary = re.sub(r'((?:-\s*)?\*{0,2}Net Content\*{0,2}\s*:[^\n]+)', r'\1\n- **Harga**: ' + extracted_price, updated_summary, count=1, flags=re.IGNORECASE)
                elif re.search(r'(#{0,3}\s*Product Overview\b[^\n]*)', updated_summary, re.IGNORECASE):
                    updated_summary = re.sub(r'(#{0,3}\s*Product Overview\b[^\n]*)', r'\1\n- **Harga**: ' + extracted_price, updated_summary, count=1, flags=re.IGNORECASE)

    # 3. Synchronize chunks with targeted SKU modifications
    for chunk in chunks:
        if isinstance(chunk, dict):
            chunk_text = chunk.get("text", "")
            chunk_meta = chunk.get("metadata", {})
            chunk_prod = chunk_meta.get("product_name") or chunk_meta.get("entity") or ""
            chunk_combined = (chunk_text + " " + chunk_prod).lower()
            
            should_update_sku = True
            if extracted_sku and sku_target:
                target_words = [w for w in re.findall(r'\b[a-zA-Z0-9]{3,}\b', sku_target.lower()) if w not in ('erha', 'acneact', 'the', 'and', 'for', 'product', 'overview')]
                if target_words:
                    should_update_sku = any(tw in chunk_combined for tw in target_words)

            if should_update_sku and extracted_sku:
                if "metadata" not in chunk or not isinstance(chunk["metadata"], dict):
                    chunk["metadata"] = {}
                chunk["metadata"]["sku"] = extracted_sku
                if re.search(r'((?:-\s*)?\*{0,2}SKU\*{0,2}\s*:)[^\n]+', chunk_text, re.IGNORECASE):
                    chunk["text"] = re.sub(r'((?:-\s*)?\*{0,2}SKU\*{0,2}\s*:)[^\n]+', r'\1 ' + extracted_sku, chunk_text, count=1, flags=re.IGNORECASE)
                elif re.search(r'((?:-\s*)?\*{0,2}Brand\*{0,2}\s*:[^\n]+)', chunk_text, re.IGNORECASE):
                    chunk["text"] = re.sub(r'((?:-\s*)?\*{0,2}Brand\*{0,2}\s*:[^\n]+)', r'\1\n- **SKU**: ' + extracted_sku, chunk_text, count=1, flags=re.IGNORECASE)

    return updated_summary, chunks, updated_title, extracted_sku


def align_chunks_with_multitreatment(
    summary: str,
    chunks: List[Dict[str, Any]],
    doc_title: str,
    doc_type: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Scans structured summary for treatment/product entities (e.g. '## 1. Acne Intensive Program', '## Acne Peel Therapy')
    and aligns chunks so each chunk has the correct entity/treatment name in its metadata,
    and prepends the entity header if missing from chunk text for crystal-clear RAG retrieval.
    """
    import re
    if not summary or not chunks:
        return chunks

    # Extract all H2 treatment/product names from summary
    entity_matches = re.findall(r'(?:^|\n)##\s+(?:\d+[\.\)]\s*)?([^\n]+)', summary)
    entities = [e.strip() for e in entity_matches if e.strip() and not e.strip().lower().startswith(('kategori', 'overview', 'ringkasan', 'panduan', 'informasi'))]
    
    if not entities:
        return chunks

    sorted_entities = sorted(entities, key=len, reverse=True)

    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        chunk_text = chunk.get("text", "")
        if not chunk_text:
            continue
        if "metadata" not in chunk or not isinstance(chunk["metadata"], dict):
            chunk["metadata"] = {}
        chunk_meta = chunk["metadata"]
        chunk_lower = chunk_text.lower()
        
        # 1. Exact substring match (longest entity first)
        matched_entity = None
        for ent in sorted_entities:
            if ent.lower() in chunk_lower:
                matched_entity = ent
                break
        
        # 2. Token overlap score if no exact substring match
        if not matched_entity:
            best_score = 0
            for ent in entities:
                ent_words = [w for w in re.findall(r'\b[a-zA-Z0-9]{3,}\b', ent.lower()) if w not in ('erha', 'and', 'for', 'the', 'treatment', 'program', 'therapy', 'center')]
                if ent_words:
                    score = sum(1 for w in ent_words if w in chunk_lower) / len(ent_words)
                    if score > best_score and score >= 0.5:
                        best_score = score
                        matched_entity = ent

        if matched_entity:
            chunk_meta["product_name"] = matched_entity
            chunk_meta["entity"] = matched_entity
            chunk_meta["section"] = matched_entity
            # If chunk text doesn't start with the entity header, prepend it for retrieval clarity
            if not re.search(r'^(?:#+\s+|\d+\.\s+)' + re.escape(matched_entity), chunk_text, re.IGNORECASE):
                chunk["text"] = f"## {matched_entity}\n\n{chunk_text}"
        else:
            if not chunk_meta.get("product_name"):
                chunk_meta["product_name"] = doc_title
            # If section contains raw instruction steps, clean it to General / Title
            if str(chunk_meta.get("section", "")).strip().startswith("1."):
                chunk_meta["section"] = doc_title

        chunk_meta["title"] = doc_title
        if doc_type:
            chunk_meta["document_type"] = doc_type

    # Aggregate entity-level metadata (SKU, Price, Promo dates, Image URL) per entity across all chunks
    entity_props = {}
    for chunk in chunks:
        if not isinstance(chunk, dict) or not chunk.get("metadata"):
            continue
        m = chunk["metadata"]
        ent = m.get("entity") or m.get("product_name")
        if not ent or ent == doc_title:
            continue
        if ent not in entity_props:
            entity_props[ent] = {
                "sku": None,
                "price": None,
                "valid_from": None,
                "valid_until": None,
                "image_url": None
            }
        p = entity_props[ent]
        if m.get("sku") and not p["sku"]:
            p["sku"] = m["sku"]
        if m.get("price") and not p["price"]:
            p["price"] = m["price"]
        if m.get("valid_from") and not p["valid_from"]:
            p["valid_from"] = m["valid_from"]
        if m.get("valid_until") and not p["valid_until"]:
            p["valid_until"] = m["valid_until"]
        if m.get("image_url") and not p["image_url"]:
            p["image_url"] = m["image_url"]

    # Propagate aggregated entity metadata across ALL sub-chunks belonging to that product/treatment
    for chunk in chunks:
        if not isinstance(chunk, dict) or not chunk.get("metadata"):
            continue
        m = chunk["metadata"]
        ent = m.get("entity") or m.get("product_name")
        if ent and ent in entity_props:
            p = entity_props[ent]
            m["entity"] = ent
            m["product_name"] = ent
            m["treatment_name"] = ent
            if p["sku"] and not m.get("sku"):
                m["sku"] = p["sku"]
            if p["price"] and not m.get("price"):
                m["price"] = p["price"]
            if p["valid_from"] and not m.get("valid_from"):
                m["valid_from"] = p["valid_from"]
            if p["valid_until"] and not m.get("valid_until"):
                m["valid_until"] = p["valid_until"]
            if p["image_url"] and not m.get("image_url"):
                m["image_url"] = p["image_url"]

    return chunks


def resolve_pending_file(knowledge_id: str) -> Optional[str]:
    pending_dir = "data/pending"
    if not os.path.exists(pending_dir):
        return None
    clean_p = os.path.join(pending_dir, f"{knowledge_id}.json")
    if os.path.exists(clean_p):
        return clean_p
    parsed_p = os.path.join(pending_dir, f"{knowledge_id}_parsed.json")
    if os.path.exists(parsed_p):
        return parsed_p
    for f in os.listdir(pending_dir):
        if f.endswith(".json"):
            full_p = os.path.join(pending_dir, f)
            name_no_ext = f[:-5]
            if f.startswith(knowledge_id) or name_no_ext == knowledge_id or name_no_ext.replace("_parsed", "") == knowledge_id:
                return full_p
            try:
                with open(full_p, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                if isinstance(data, dict) and (data.get("knowledge_id") == knowledge_id or data.get("file_name") == knowledge_id):
                    return full_p
                elif isinstance(data, list) and data and isinstance(data[0], dict):
                    meta = data[0].get("metadata", {})
                    if meta.get("knowledge_id") == knowledge_id or meta.get("source_file") == knowledge_id:
                        return full_p
            except Exception:
                pass
    return None

def resolve_approved_file(knowledge_id: str) -> Optional[str]:
    approved_dir = "data/output"
    if not os.path.exists(approved_dir):
        return None
    clean_p = os.path.join(approved_dir, f"{knowledge_id}.json")
    if os.path.exists(clean_p):
        return clean_p
    parsed_p = os.path.join(approved_dir, f"{knowledge_id}_parsed.json")
    if os.path.exists(parsed_p):
        return parsed_p
    
    clean_k_id = knowledge_id.strip().lower()
    fallback_match = None

    for f in os.listdir(approved_dir):
        if f.endswith(".json") and f != "bm25_index.pkl":
            full_p = os.path.join(approved_dir, f)
            name_no_ext = f[:-5]
            if f.startswith(knowledge_id) or name_no_ext == knowledge_id or name_no_ext.replace("_parsed", "") == knowledge_id:
                return full_p
            try:
                with open(full_p, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                if isinstance(data, dict):
                    doc_kid = str(data.get("knowledge_id", "")).strip().lower()
                    doc_fname = str(data.get("file_name", "")).strip().lower()
                    doc_title = str(data.get("title", "")).strip().lower()
                    
                    if clean_k_id in (doc_kid, doc_fname, doc_title):
                        return full_p
                    if doc_title and (clean_k_id in doc_title or doc_title in clean_k_id):
                        fallback_match = full_p
                elif isinstance(data, list) and data:
                    meta = data[0].get("metadata", {})
                    doc_kid = str(meta.get("knowledge_id", "")).strip().lower()
                    doc_source = str(meta.get("source_file", "")).strip().lower()
                    doc_title = str(meta.get("title", "")).strip().lower()
                    if clean_k_id in (doc_kid, doc_source, doc_title):
                        return full_p
            except Exception:
                pass
    return fallback_match


def detect_duplicate_lifecycle(file_hash: str, file_name: str) -> Dict[str, Any]:
    """
    Evaluates the duplicate status of an uploaded file across the entire Knowledge Base:
    - State 1: PUBLISHED (in data/output or KnowledgeStatus.APPROVED) -> BLOCK
    - State 2: PENDING (in data/pending or KnowledgeStatus.PENDING/ON_REVIEW) -> ASK ADMIN (Keep/Replace)
    - State 3: NEW -> Ingest
    """
    clean_name = file_name.strip().lower()

    # 1. Check PUBLISHED / APPROVED (data/output)
    approved_dir = "data/output"
    if os.path.exists(approved_dir):
        for f in os.listdir(approved_dir):
            if f.endswith(".json") and f != "bm25_index.pkl":
                full_path = os.path.join(approved_dir, f)
                try:
                    with open(full_path, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                    ex_hash = None
                    ex_name = None
                    k_id = None
                    if isinstance(data, dict):
                        ex_hash = data.get("file_hash")
                        ex_name = data.get("file_name")
                        k_id = data.get("knowledge_id")
                        if not ex_hash and data.get("chunks"):
                            ex_hash = data["chunks"][0].get("metadata", {}).get("file_hash")
                    elif isinstance(data, list) and data:
                        meta = data[0].get("metadata", {})
                        ex_hash = meta.get("file_hash")
                        ex_name = meta.get("source_file")
                        k_id = meta.get("knowledge_id")

                    is_hash_match = bool(file_hash and ex_hash and file_hash == ex_hash)
                    is_name_match = bool(ex_name and ex_name.strip().lower() == clean_name)

                    if is_hash_match or is_name_match:
                        match_reason = "SHA-256 Checksum Match" if is_hash_match else "Filename Match"
                        return {
                            "status": "PUBLISHED",
                            "existing_file": ex_name or f,
                            "knowledge_id": k_id or f[:-5],
                            "match_reason": match_reason
                        }
                except Exception:
                    pass

    # 2. Check PENDING / ON REVIEW (data/pending)
    pending_dir = "data/pending"
    if os.path.exists(pending_dir):
        for f in os.listdir(pending_dir):
            if f.endswith(".json"):
                full_path = os.path.join(pending_dir, f)
                try:
                    with open(full_path, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                    ex_hash = None
                    ex_name = None
                    k_id = None
                    if isinstance(data, dict):
                        ex_hash = data.get("file_hash")
                        ex_name = data.get("file_name")
                        k_id = data.get("knowledge_id")
                        if not ex_hash and data.get("chunks"):
                            ex_hash = data["chunks"][0].get("metadata", {}).get("file_hash")
                    elif isinstance(data, list) and data:
                        meta = data[0].get("metadata", {})
                        ex_hash = meta.get("file_hash")
                        ex_name = meta.get("source_file")
                        k_id = meta.get("knowledge_id")

                    is_hash_match = bool(file_hash and ex_hash and file_hash == ex_hash)
                    is_name_match = bool(ex_name and ex_name.strip().lower() == clean_name)

                    if is_hash_match or is_name_match:
                        match_reason = "SHA-256 Checksum Match" if is_hash_match else "Filename Match"
                        return {
                            "status": "PENDING",
                            "existing_file": ex_name or f,
                            "knowledge_id": k_id or f[:-5],
                            "match_reason": match_reason
                        }
                except Exception:
                    pass

    return {"status": "NEW"}

def check_sha256_duplicate(file_hash: str, file_name: str) -> Optional[str]:
    """Backward-compatible helper returning duplicate filename if PUBLISHED duplicate is found."""
    res = detect_duplicate_lifecycle(file_hash, file_name)
    if res.get("status") == "PUBLISHED":
        return res.get("existing_file")
    return None

_ingestion_semaphore = asyncio.Semaphore(settings.max_ingestion_concurrency)

async def process_ingestion_background(
    knowledge_id: str,
    file_path: str,
    file_name: str,
    pipeline: IngestionPipeline,
    llm: BaseLLMAdapter,
    user_prompt: Optional[str] = None,
    file_hash: Optional[str] = None,
    batch_id: Optional[str] = None
):
    import time as _time
    t0_total = _time.time()
    timing_metrics = {
        "upload_ms": 0,
        "checksum_ms": 0,
        "parsing_ms": 0,
        "ocr_ms": 0,
        "llm_review_ms": 0,
        "embedding_ms": 0,
        "database_insert_ms": 0,
        "bm25_update_ms": 0,
        "total_ingestion_ms": 0
    }

    try:
        async with _ingestion_semaphore:
            # Temporarily configure pipeline to stage file in data/pending without indexing
            original_output_dir = pipeline.output_dir
            original_store = pipeline.vector_store
            
            pipeline.output_dir = "data/pending"
            pipeline.vector_store = None
            os.makedirs(pipeline.output_dir, exist_ok=True)
            
            t0_parse = _time.time()
            try:
                output_file = await asyncio.to_thread(pipeline.ingest_file, file_path)
            finally:
                pipeline.output_dir = original_output_dir
                pipeline.vector_store = original_store
            
            timing_metrics["parsing_ms"] = int((_time.time() - t0_parse) * 1000)
                
            # Cleanup temp file
            try:
                import gc
                gc.collect()
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as cleanup_err:
                logger.warning(f"Could not delete temporary file {file_path}: {cleanup_err}")
                
            if not output_file:
                logger.error("Ingestion failed: no output file.")
                return
                
            # Load the staged JSON containing raw parsed chunks
            with open(output_file, 'r', encoding='utf-8') as f:
                enriched_chunks = json.load(f)

            # Inject metadata cleanly into every chunk immediately
            for chunk in enriched_chunks:
                if isinstance(chunk, dict):
                    if "metadata" not in chunk:
                        chunk["metadata"] = {}
                    chunk["metadata"]["knowledge_id"] = knowledge_id
                    chunk["metadata"]["batch_id"] = batch_id
                    chunk["metadata"]["file_hash"] = file_hash
                    chunk["metadata"]["source_file"] = file_name
                    chunk.pop("suggested_categories", None)
                    chunk["metadata"].pop("document_type", None)

            full_extracted_text = "\n\n".join([c.get("text", "") for c in enriched_chunks if isinstance(c, dict) and c.get("text")])

            clean_title_fallback = os.path.splitext(file_name)[0]

            # Write initial pending state IMMEDIATELY (0.5s) so GET /pending and GET /documents work instantly
            init_image_url = None
            for c in enriched_chunks:
                if isinstance(c, dict) and c.get("metadata", {}).get("image_url"):
                    init_image_url = c["metadata"]["image_url"]
                    break

            os.makedirs("data/pending", exist_ok=True)
            pending_file_path = os.path.join("data/pending", f"{knowledge_id}.json")
            initial_staged_doc = {
                "knowledge_id": knowledge_id,
                "batch_id": batch_id,
                "file_name": file_name,
                "file_hash": file_hash,
                "title": clean_title_fallback,
                "status": "PARSING",
                "text_accuracy": "100%",
                "initial_prompt": user_prompt if user_prompt and str(user_prompt).strip() else None,
                "summary": full_extracted_text,
                "feedback": f"Dokumen {file_name} telah berhasil diekstrak dan tersimpan di area peninjauan.",
                "batch_summary": None,
                "suggested_categories": [],
                "visibility_settings": {
                    "clinics": ["all"],
                    "doctor_types": ["all"],
                    "doctors": ["all"]
                },
                "history": [],
                "chunks": enriched_chunks,
                "timing_metrics": timing_metrics
            }
            if init_image_url:
                initial_staged_doc["image_url"] = init_image_url

            with open(pending_file_path, 'w', encoding='utf-8') as f:
                json.dump(initial_staged_doc, f, indent=4, ensure_ascii=False)
                
            # ─── CANONICAL TEXT: raw parser output, NOT rewritten by LLM ───────────────────
            # The canonical_text is the verbatim content extracted by the document parser.
            # LLM is NOT allowed to rewrite, summarize, or add to this content.
            # Admin sees exactly what the document contains in the Review Dashboard.
            canonical_text = full_extracted_text
            summary = canonical_text
            text_accuracy = "100%"
            feedback = f"Dokumen '{file_name}' telah berhasil diekstrak. Silakan tinjau isi dokumen di bawah sebelum menyetujui."
            suggested_categories = []
            recommended_title = clean_title_fallback
            extracted_doc_type = "GENERAL"
            extracted_valid_from = None
            extracted_valid_until = None

            # ─── LIGHTWEIGHT AI PROCESSING ──────────────────────────────────────────────────
            # LLM is used ONLY to detect: title, document_type, valid_from, valid_until, categories.
            # LLM is STRICTLY FORBIDDEN from generating or rewriting document content.
            if llm and enriched_chunks:
                t0_llm = _time.time()
                try:
                    db_categories = []
                    try:
                        from app.core.database import AsyncSessionLocal
                        from app.models.category import Category
                        from sqlalchemy import select
                        async with AsyncSessionLocal() as session:
                            res = await session.execute(select(Category).where(Category.deleted_at.is_(None)))
                            cats = res.scalars().all()
                            db_categories = [{"id": str(c.id), "name": c.name} for c in cats]
                    except Exception as cat_err:
                        logger.warning(f"Failed to fetch categories for metadata detection: {cat_err}")

                    if not db_categories:
                        default_cats = [
                            ("9b79e362-ec70-4560-902e-fd5897c07a00", "Acne Care"),
                            ("1a23b456-ec70-4560-902e-fd5897c07a01", "Anti Aging"),
                            ("2b34c567-ec70-4560-902e-fd5897c07a02", "Dark Spot"),
                            ("3c45d678-ec70-4560-902e-fd5897c07a03", "Psoriasis Care"),
                            ("4d56e789-ec70-4560-902e-fd5897c07a04", "Scar Treatment"),
                            ("5e67f890-ec70-4560-902e-fd5897c07a05", "Wound Healing"),
                            ("6f78a901-ec70-4560-902e-fd5897c07a06", "Brightening")
                        ]
                        db_categories = [{"id": cid, "name": cname} for cid, cname in default_cats]

                    # Lightweight metadata detection prompt — reads first 3000 chars only
                    preview_text = canonical_text[:3000] if len(canonical_text) > 3000 else canonical_text

                    metadata_prompt = f"""
You are a document metadata classifier for the ERHA (PT Arya Noble) medical aesthetic knowledge base.

Your ONLY task is to analyze the document excerpt below and return metadata fields.
You are STRICTLY FORBIDDEN from generating, rewriting, summarizing, or modifying any document content.
Return ONLY the JSON metadata object — nothing else.

Document Excerpt (first 3000 chars):
{preview_text}

Available Categories:
{json.dumps(db_categories, ensure_ascii=False)}

Extract ONLY these fields:
1. **title**: A short, clean professional document title inferred from the content. Strip file extension prefixes. No "Knowledge Base" or "Ingestment" prefixes.
2. **document_type**: One of: "PRODUCT" | "TREATMENT" | "PROMOTIONAL" | "SOP" | "GENERAL"
   - PRODUCT: product catalogs, skincare items, cosmetics
   - TREATMENT: clinic treatments, aesthetic procedures, protocols
   - PROMOTIONAL: promo flyers, discounts, vouchers, flash sales
   - SOP: standard operating procedures, guidelines
   - GENERAL: anything else
3. **valid_from**: "YYYY-MM-DD" promo start date if visible, else null
4. **valid_until**: "YYYY-MM-DD" promo end date if visible, else null
5. **suggested_categories**: Array of matching category objects from Available Categories. Match ALL relevant ones.
6. **feedback**: 1 sentence in Indonesian describing the document type and content.

Return ONLY valid JSON:
{{
    "title": "detected document title",
    "document_type": "PRODUCT",
    "valid_from": null,
    "valid_until": null,
    "suggested_categories": [{{"id": "uuid", "name": "category name"}}],
    "feedback": "Dokumen ini berisi informasi mengenai produk skincare ERHA."
}}"""

                    llm_response = await asyncio.to_thread(llm.generate, metadata_prompt)
                    timing_metrics["llm_review_ms"] = int((_time.time() - t0_llm) * 1000)
                    parsed_meta = safe_json_loads(llm_response)

                    raw_title = parsed_meta.get("title") or clean_title_fallback
                    prefixes_to_strip = [
                        "knowledge ingestment", "knowledge ingestion", "knowledge ingest",
                        "ingestment", "ingestion", "knowledge base", "knowledge"
                    ]
                    recommended_title = raw_title.strip()
                    for p in prefixes_to_strip:
                        if recommended_title.lower().startswith(p):
                            recommended_title = recommended_title[len(p):].lstrip(" :-_#\t")
                    for ext in [".pdf", ".docx", ".xlsx", ".csv", ".pptx", ".ppt", ".doc", ".txt"]:
                        if recommended_title.lower().endswith(ext):
                            recommended_title = recommended_title[:-len(ext)].strip()
                    if not recommended_title:
                        recommended_title = clean_title_fallback

                    extracted_doc_type = parsed_meta.get("document_type") or "GENERAL"
                    extracted_valid_from = parsed_meta.get("valid_from")
                    extracted_valid_until = parsed_meta.get("valid_until")
                    suggested_categories = parsed_meta.get("suggested_categories", [])
                    feedback = parsed_meta.get("feedback", feedback)

                except Exception as llm_err:
                    timing_metrics["llm_review_ms"] = int((_time.time() - t0_llm) * 1000)
                    logger.warning(f"Metadata detection LLM call failed (non-critical): {llm_err}. Using parser defaults.")
                    recommended_title = clean_title_fallback
                    extracted_doc_type = "GENERAL"
                    extracted_valid_from = None
                    extracted_valid_until = None
                
        # Define document-level visibility settings
        visibility_settings = {
            "clinics": ["all"],
            "doctor_types": ["all"],
            "doctors": ["all"]
        }

        # Collect ALL document-level image URLs from parser chunks AND from AI summary
        all_doc_image_urls = []
        doc_s3_key = None
        for c in enriched_chunks:
            if isinstance(c, dict) and c.get("metadata"):
                m = c["metadata"]
                if m.get("image_url") and m["image_url"] not in all_doc_image_urls:
                    all_doc_image_urls.append(m["image_url"])
                if m.get("s3_key") and not doc_s3_key:
                    doc_s3_key = m["s3_key"]
                elif m.get("storage_key") and not doc_s3_key:
                    doc_s3_key = m["storage_key"]

        # Extract image URLs embedded in canonical summary markdown (from parser Vision LLM output)
        if summary:
            import re as _re
            for url in _re.findall(r'!\[.*?\]\((https?://[^\s\)]+)\)', summary):
                if url and url not in all_doc_image_urls:
                    all_doc_image_urls.append(url)

        # Prepend image block to summary for dashboard display (only if images not yet embedded)
        if all_doc_image_urls:
            if not any(u in summary for u in all_doc_image_urls):
                img_header_block = "\n".join([f"![{recommended_title} Image {i+1}]({u})" for i, u in enumerate(all_doc_image_urls)])
                summary = f"{img_header_block}\n\n{summary}"

        # Category names for chunk metadata
        cat_names = [c["name"] for c in suggested_categories if isinstance(c, dict) and "name" in c] if suggested_categories else []

        # Structure-aware chunking from canonical text (raw parser output — never LLM-rewritten)
        # chunk_summary_markdown splits by ## headings, extracts contextual image_url/sku/price per chunk
        # NOTE: These chunks are STAGING chunks only — final chunks are regenerated at Approve time
        if summary and summary.strip():
            try:
                from app.rag.utils.summary_chunker import chunk_summary_markdown
                enriched_chunks = chunk_summary_markdown(
                    summary=summary,
                    source_file=file_name,
                    knowledge_id=knowledge_id,
                    batch_id=batch_id,
                    file_hash=file_hash,
                    title=recommended_title,
                    doc_type=extracted_doc_type or "GENERAL",
                    categories=cat_names,
                    valid_from=str(extracted_valid_from).strip() if extracted_valid_from else None,
                    valid_until=str(extracted_valid_until).strip() if extracted_valid_until else None,
                    visibility_settings=visibility_settings,
                )
                logger.info(f"Canonical text chunking produced {len(enriched_chunks)} staging chunks.")
            except Exception as rechunk_err:
                logger.warning(f"Canonical text chunking failed, keeping parser chunks: {rechunk_err}")

        # History starts empty at ingestion — will be populated during admin Refine interactions
        # user_prompt is preserved in initial_prompt field for reference only
        history_list = []

        timing_metrics["total_ingestion_ms"] = int((_time.time() - t0_total) * 1000)

        # Structure the final pending document state in exact requested order
        staged_document = {
            "knowledge_id": knowledge_id,
            "batch_id": batch_id,
            "file_name": file_name,
            "file_hash": file_hash,
            "title": recommended_title,
            "status": "On review",
            "document_type": extracted_doc_type,
            "summary": summary,
            "image_urls": all_doc_image_urls,
            "text_accuracy": text_accuracy,
            "feedback": feedback,
            "batch_summary": None,
            "suggested_categories": suggested_categories,
            "visibility_settings": visibility_settings,
            "initial_prompt": user_prompt if user_prompt and str(user_prompt).strip() else None,
            "history": history_list,
            "chunks": enriched_chunks,
            "timing_metrics": timing_metrics
        }
        if doc_s3_key:
            staged_document["s3_key"] = doc_s3_key
            staged_document["storage_key"] = doc_s3_key
        
        # Save back to pending folder using knowledge_id in filename
        pending_file_path = os.path.join("data/pending", f"{knowledge_id}.json")
        with open(pending_file_path, 'w', encoding='utf-8') as f:
            json.dump(staged_document, f, indent=4, ensure_ascii=False)

        # Remove temporary output_file if named differently (e.g. filename_parsed.json)
        if output_file and os.path.exists(output_file) and os.path.abspath(output_file) != os.path.abspath(pending_file_path):
            try:
                os.remove(output_file)
            except Exception:
                pass

        # Update Knowledge DB table status to PENDING
        t0_db = _time.time()
        try:
            from app.core.database import AsyncSessionLocal
            from app.models.knowledge import Knowledge, KnowledgeStatus
            from sqlalchemy import select
            import uuid as _uuid

            async with AsyncSessionLocal() as session:
                try:
                    k_uuid = _uuid.UUID(str(knowledge_id))
                except ValueError:
                    k_uuid = knowledge_id

                result = await session.execute(select(Knowledge).where(Knowledge.id == k_uuid))
                k_entry = result.scalars().first()
                if k_entry:
                    k_entry.deleted_at = None
                    k_entry.status = KnowledgeStatus.PENDING
                    k_entry.title = recommended_title
                    k_entry.ai_summary = summary
                    k_entry.ai_confidence = float(text_accuracy.replace("%", "")) if isinstance(text_accuracy, str) and "%" in text_accuracy else 95.00
                    if k_entry.metadata_ is None:
                        k_entry.metadata_ = {}
                    k_entry.metadata_.update({
                        "batch_id": batch_id,
                        "file_hash": file_hash,
                        "document_type": extracted_doc_type,
                        "initial_prompt": user_prompt if user_prompt and str(user_prompt).strip() else None,
                        "history": history_list,
                        "chat_history": history_list,
                        "suggested_categories": suggested_categories,
                        "categories": [c["name"] for c in suggested_categories if isinstance(c, dict) and "name" in c] if suggested_categories else [],
                        "visibility_settings": visibility_settings,
                        "feedback": feedback,
                        "timing_metrics": timing_metrics
                    })
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(k_entry, "metadata_")
                    await session.commit()
        except Exception as db_err:
            logger.warning(f"Could not update status to PENDING in Knowledge DB table: {db_err}")

        timing_metrics["database_insert_ms"] = int((_time.time() - t0_db) * 1000)
        timing_metrics["total_ingestion_ms"] = int((_time.time() - t0_total) * 1000)

        # Update staged document with final timing metrics and save to pending folder
        staged_document["timing_metrics"] = timing_metrics
        with open(pending_file_path, 'w', encoding='utf-8') as f:
            json.dump(staged_document, f, indent=4, ensure_ascii=False)

        logger.info(
            f"\n"
            f"⏱️ [SINGLE FILE INGESTION TIMING] File: '{file_name}' (ID: {knowledge_id})\n"
            f"  - Parsing Stage        : {timing_metrics['parsing_ms']} ms\n"
            f"  - LLM Review Stage     : {timing_metrics['llm_review_ms']} ms\n"
            f"  - DB Staging Stage     : {timing_metrics['database_insert_ms']} ms\n"
            f"  - Total Ingestion Time : {timing_metrics['total_ingestion_ms']} ms\n"
        )

    except Exception as e:
        logger.error(f"Failed background processing for document: {e}")

async def trigger_batch_summary_after_all_done(batch_id: str, expected_count: int, llm: BaseLLMAdapter, user_prompt: Optional[str] = None, timeout_sec: int = 180):
    """
    Coordinator task that waits until all documents in a multi-file batch finish Parsing & LLM Review,
    then triggers synthesize_batch_executive_summary EXACTLY ONCE for the entire batch.
    """
    import time as _time
    t0 = _time.time()
    logger.info(f"🚀 [BATCH COORDINATOR] Monitoring Batch '{batch_id}' ({expected_count} files)...")

    while _time.time() - t0 < timeout_sec:
        completed_count = 0
        dirs_to_check = ["data/pending", "data/output"]
        for d in dirs_to_check:
            if os.path.exists(d):
                for f in os.listdir(d):
                    if f.endswith(".json") and f != "bm25_index.pkl":
                        try:
                            with open(os.path.join(d, f), "r", encoding="utf-8") as fj:
                                data = json.load(fj)
                            if isinstance(data, dict) and data.get("batch_id") == batch_id:
                                if data.get("summary") and data.get("status") in ["On review", "PENDING", "APPROVED"]:
                                    completed_count += 1
                        except Exception:
                            pass
        if completed_count >= expected_count:
            break
        await asyncio.sleep(1.5)

    t0_batch = _time.time()
    try:
        b_summary = await synthesize_batch_executive_summary(batch_id, llm, user_prompt=user_prompt)
        batch_duration_ms = int((_time.time() - t0_batch) * 1000)
        logger.info(
            f"\n"
            f"⏱️ [BATCH EXECUTIVE SUMMARY TIMING] Batch ID: '{batch_id}' ({expected_count} files)\n"
            f"  - Unified Batch Summary Stage : {batch_duration_ms} ms (Executed 1x for full batch)\n"
        )
    except Exception as err:
        logger.warning(f"Could not trigger unified batch summary for {batch_id}: {err}")

async def synthesize_batch_executive_summary(batch_id: str, llm: BaseLLMAdapter, user_prompt: Optional[str] = None) -> Optional[str]:
    """
    Synthesizes multiple uploaded document feedbacks/summaries into a concise, unified Executive Summary paragraph.
    Identifies whether documents are clinically/operationally interrelated or independent.
    Updates all JSON documents in data/pending and data/output for this batch, as well as DB records.
    """
    if not batch_id or not llm:
        return None

    dirs_to_check = ["data/pending", "data/output"]
    batch_docs = []
    batch_file_paths = []

    for d in dirs_to_check:
        if os.path.exists(d):
            for f in os.listdir(d):
                if f.endswith(".json") and f != "bm25_index.pkl":
                    fp = os.path.join(d, f)
                    try:
                        with open(fp, "r", encoding="utf-8") as f_json:
                            data = json.load(f_json)
                        if isinstance(data, dict) and data.get("batch_id") == batch_id:
                            batch_docs.append(data)
                            batch_file_paths.append(fp)
                    except Exception:
                        pass

    if len(batch_docs) < 2:
        return None

    docs_text_parts = []
    for i, d in enumerate(batch_docs):
        fname = d.get('file_name', '')
        title = d.get('title', '') or fname
        doctype = d.get('document_type') or d.get('type', 'General')
        ext = os.path.splitext(fname)[1].lower()

        # Use AI-detected feedback (1 sentence) as document description
        # Then supplement with up to 5 chunks of the actual parsed content
        feedback_text = d.get('feedback', '')
        chunks = d.get('chunks', [])
        chunk_samples = []
        for c in chunks[:5]:  # only first 5 chunks to keep context manageable
            c_text = c.get('text', '') if isinstance(c, dict) else str(c)
            if c_text and c_text.strip():
                chunk_samples.append(c_text.strip())

        doc_entry = f"=== DOKUMEN {i+1}: '{fname}' (Tipe: {ext or 'unknown'} | Kategori: {doctype} | Judul: {title}) ===\n"
        if feedback_text:
            doc_entry += f"Ringkasan AI: {feedback_text}\n"
        if chunk_samples:
            doc_entry += f"Sampel Isi Dokumen:\n" + "\n---\n".join(chunk_samples) + "\n"

        docs_text_parts.append(doc_entry)

    docs_text = "\n\n".join(docs_text_parts)

    user_instruction_block = ""
    effective_prompt = user_prompt or next((d.get("initial_prompt") for d in batch_docs if d.get("initial_prompt")), None)
    if effective_prompt and str(effective_prompt).strip():
        user_instruction_block = f"""
INSTRUKSI KHUSUS PENGGUNA (PRIORITAS TINGGI):
"{str(effective_prompt).strip()}"
Harap perhatikan dan penuhi instruksi pengguna di atas saat menyusun ringkasan eksekutif batch ini.
"""

    batch_prompt = f"""
Anda adalah AI Knowledge Specialist & Clinical Data Integrator untuk klinik ERHA (PT Arya Noble).
Pengguna mengunggah {len(batch_docs)} dokumen sekaligus dalam satu batch ingest.

Berikut ringkasan dan sampel isi masing-masing dokumen dalam batch ini:
{docs_text}
{user_instruction_block}
Tugas Anda:
Lakukan rekonsiliasi dan cross-reference antar dokumen di atas secara teliti.
Identifikasi apakah dokumen-dokumen ini saling berkaitan (misalnya: katalog produk + product knowledge detail, atau protokol treatment + bahan aktif).

PENTING — ATURAN AKURASI:
- HANYA gunakan informasi yang BENAR-BENAR ADA di konten dokumen di atas.
- DILARANG mengarang, mengestimasi, atau menambah informasi yang tidak tercantum.
- Jika informasi tidak tersedia di dokumen, nyatakan "tidak ditemukan di dokumen" — JANGAN mengisi dengan asumsi.

ATURAN FORMAT OUTPUT WAJIB:
- JANGAN gunakan heading/judul apapun (DILARANG menulis '### Batch Executive Summary', dsb.)
- JANGAN gunakan penomoran section seperti '1. **Status...**'
- Ikuti PERSIS struktur berikut dalam teks biasa:

[Paragraf 1 - Status Batch & Hubungan Antar Dokumen]:
Sebutkan jumlah dokumen, jenis masing-masing, dan apakah mereka saling terkait atau independen.

[Jika ada cross-reference yang ditemukan — tuliskan sebagai bullet sederhana]:
[Nama Produk/Treatment] → [informasi yang dikaitkan dari dokumen lain]

[Penutup singkat — hal yang tidak dapat dicocokkan karena data tidak ada di dokumen]
"""
    try:
        batch_summary = await asyncio.to_thread(llm.generate, batch_prompt)
        batch_summary = batch_summary.strip().strip('"').strip("'")
        
        # Clean up any accidental leading header if generated
        import re
        batch_summary = re.sub(r"^#+\s*(Batch\s+)?Executive\s+Summary\s*\n+", "", batch_summary, flags=re.IGNORECASE).strip()

        # Save batch_summary to each document's metadata maintaining exact key order
        ordered_keys = [
            "knowledge_id", "batch_id", "file_name", "file_hash", "title",
            "type", "status", "text_accuracy", "initial_prompt", "summary",
            "feedback", "batch_summary", "suggested_categories",
            "visibility_settings", "history", "chunks", "image_url"
        ]

        for fp, doc_data in zip(batch_file_paths, batch_docs):
            doc_data["batch_summary"] = batch_summary
            reordered = {}
            for k in ordered_keys:
                if k in doc_data:
                    reordered[k] = doc_data[k]
            for k, v in doc_data.items():
                if k not in reordered:
                    reordered[k] = v

            with open(fp, "w", encoding="utf-8") as out_f:
                json.dump(reordered, out_f, indent=4, ensure_ascii=False)

        # Sync batch_summary to Postgres DB records metadata_
        try:
            from app.core.database import AsyncSessionLocal
            from app.models.knowledge import Knowledge
            from sqlalchemy import select
            import uuid as _uuid

            async with AsyncSessionLocal() as session:
                for doc_data in batch_docs:
                    k_id_str = doc_data.get("knowledge_id")
                    if k_id_str:
                        try:
                            k_uuid = _uuid.UUID(str(k_id_str))
                            res = await session.execute(select(Knowledge).where(Knowledge.id == k_uuid))
                            k_obj = res.scalars().first()
                            if k_obj:
                                meta = dict(k_obj.metadata_) if isinstance(k_obj.metadata_, dict) else {}
                                meta["batch_summary"] = batch_summary
                                k_obj.metadata_ = meta
                        except Exception:
                            pass
                await session.commit()
        except Exception as db_sync_err:
            logger.warning(f"Could not sync batch_summary to DB: {db_sync_err}")

        logger.info(f"Synthesized batch executive summary for batch {batch_id}: {batch_summary[:80]}...")
        return batch_summary
    except Exception as e:
        logger.warning(f"Could not synthesize batch executive summary: {e}")
        return None

@router.post(
    "/ingest", 
    tags=["Ingestion"], 
    summary="Upload and Ingest Document",
    openapi_extra={
        "requestBody": {
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "file": {
                                "type": "array",
                                "items": {"type": "string", "format": "binary"},
                                "description": "Document file(s) to upload (PDF, DOCX, XLSX, TXT, JPG, PNG)"
                            },
                            "prompt": {
                                "type": "string",
                                "description": "Optional custom AI processing instruction"
                            },
                            "replace_existing": {
                                "type": "boolean",
                                "default": False,
                                "description": "Set to true to overwrite existing pending draft"
                            }
                        },
                        "required": ["file"]
                    }
                }
            }
        }
    }
)
async def ingest_document(
    background_tasks: BackgroundTasks,
    file: List[UploadFile] = File(..., description="Document file(s) to upload (PDF, DOCX, XLSX, TXT, JPG, PNG)"),
    prompt: Optional[str] = Form(None, description="Optional custom AI processing instruction"),
    replace_existing: bool = Form(False, description="Set to true to overwrite existing pending draft"),
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
    llm: BaseLLMAdapter = Depends(get_llm)
):
    """
    Uploads and extracts document files (PDF, DOCX, XLSX, TXT, JPG, PNG) into the staging area for review.
    """
    upload_list = file if isinstance(file, list) else [file]
    upload_list = [f for f in upload_list if f is not None and f.filename]
    if not upload_list:
        raise HTTPException(status_code=400, detail="Please upload at least one document file.")

    try:
        from app.models.knowledge import KnowledgeType
        import uuid as _uuid
        import hashlib
        
        response_items = []
        os.makedirs("data/temp", exist_ok=True)
        batch_id = str(_uuid.uuid4()) if len(upload_list) > 1 else None

        for target_file in upload_list:
            if not target_file.filename:
                continue

            k_type = KnowledgeType.GENERAL

            file_bytes = await target_file.read()
            file_hash = hashlib.sha256(file_bytes).hexdigest()

            # -------------------------------------------------------------
            # 3-WAY DUPLICATE DETECTION LIFECYCLE
            # -------------------------------------------------------------
            dup_info = detect_duplicate_lifecycle(file_hash, target_file.filename)
            dup_status = dup_info.get("status", "NEW")

            # 1. STATE: PUBLISHED -> BLOCK
            if dup_status == "PUBLISHED":
                if len(upload_list) == 1:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Dokumen '{target_file.filename}' sudah terpublikasi (PUBLISHED / APPROVED) di knowledge base aktif ({dup_info.get('match_reason')}: '{dup_info.get('existing_file')}'). Upload dibatalkan untuk menjaga keakuratan sistem dokter. Silakan gunakan menu 'Edit Knowledge' di UI jika ingin memperbarui."
                    )
                else:
                    response_items.append({
                        "file_name": target_file.filename,
                        "batch_id": batch_id,
                        "duplicate_status": "PUBLISHED",
                        "action": "BLOCKED",
                        "detail": f"Dokumen sudah terpublikasi (APPROVED) ({dup_info.get('match_reason')}: '{dup_info.get('existing_file')}'). Upload dibatalkan."
                    })
                    continue

            # 2. STATE: PENDING -> REQUIRE ADMIN CONFIRMATION (DO NOT SILENTLY OVERWRITE)
            if dup_status == "PENDING" and not replace_existing:
                existing_k_id = dup_info.get("knowledge_id")
                if len(upload_list) == 1:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Draft peninjauan untuk '{target_file.filename}' (ID: {existing_k_id}) sudah ada di antrean On Review (Pending). Upload dibatalkan agar draft lama tidak tertimpa secara diam-diam. Silakan selesaikan review draft yang ada, atau kirim konfirmasi 'replace_existing=true' untuk mengganti draft lama."
                    )
                else:
                    response_items.append({
                        "file_name": target_file.filename,
                        "existing_knowledge_id": existing_k_id,
                        "batch_id": batch_id,
                        "duplicate_status": "PENDING",
                        "action": "REQUIRE_ADMIN_CONFIRMATION",
                        "detail": f"Draft peninjauan sudah ada di daftar On Review ({dup_info.get('match_reason')}: '{dup_info.get('existing_file')}'). Kirim 'replace_existing=true' jika ingin menimpa draft ini."
                    })
                    continue

            # 3. STATE: NEW or PENDING with replace_existing=True -> PROCEED
            file_path = f"data/temp/{target_file.filename}"
            with open(file_path, "wb") as f_out:
                f_out.write(file_bytes)

            file_size = os.path.getsize(file_path)

            k_id = dup_info.get("knowledge_id") if (dup_status == "PENDING" and replace_existing) else None
            try:
                from app.core.database import AsyncSessionLocal
                from app.models.knowledge import Knowledge, KnowledgeStatus
                from app.models.user import User
                from sqlalchemy import select

                async with AsyncSessionLocal() as session:
                    user_result = await session.execute(select(User).limit(1))
                    user = user_result.scalars().first()
                    user_id = user.id if user else _uuid.uuid4()

                    custom_uuid = None
                    if k_id:
                        try:
                            custom_uuid = _uuid.UUID(k_id)
                        except ValueError:
                            pass

                    existing_doc = None
                    if custom_uuid:
                        existing_doc = await session.get(Knowledge, custom_uuid)
                    if not existing_doc:
                        res = await session.execute(
                            select(Knowledge).where(Knowledge.file_name == target_file.filename).order_by(Knowledge.created_at.desc())
                        )
                        existing_doc = res.scalars().first()

                    if existing_doc:
                        knowledge = existing_doc
                        knowledge.deleted_at = None
                        knowledge.status = KnowledgeStatus.PROCESSING
                        knowledge.ai_summary = "Processing..."
                        knowledge.original_path = file_path
                        knowledge.mime_type = target_file.content_type
                        knowledge.file_size = file_size
                        if knowledge.metadata_ is None:
                            knowledge.metadata_ = {}
                        knowledge.metadata_["batch_id"] = batch_id
                        knowledge.metadata_["file_hash"] = file_hash
                        if dup_status == "PENDING" and replace_existing:
                            knowledge.metadata_["replaced_at"] = str(asyncio.get_event_loop().time())
                        await session.commit()
                        await session.refresh(knowledge)
                        k_id = str(knowledge.id)
                    else:
                        metadata = {
                            "batch_id": batch_id,
                            "file_hash": file_hash
                        }
                        knowledge = Knowledge(
                            id=custom_uuid if custom_uuid else _uuid.uuid4(),
                            type=k_type,
                            title=target_file.filename,
                            file_name=target_file.filename,
                            original_path=file_path,
                            mime_type=target_file.content_type,
                            file_size=file_size,
                            status=KnowledgeStatus.PROCESSING,
                            uploaded_by=user_id,
                            ai_summary="Processing...",
                            ai_confidence=0.0,
                            metadata_=metadata
                        )
                        session.add(knowledge)
                        await session.commit()
                        await session.refresh(knowledge)
                        k_id = str(knowledge.id)
            except Exception as db_err:
                logger.warning(f"Could not create or update Knowledge DB record for {target_file.filename}: {db_err}")
                if not k_id:
                    k_id = str(_uuid.uuid4())

            # Upload original document to knowledge-documents MinIO bucket
            original_s3_key = None
            try:
                from app.services.storage import upload_document
                doc_upload = upload_document(
                    content=file_bytes,
                    filename=target_file.filename,
                    document_id=k_id,
                    content_type=target_file.content_type or "application/octet-stream"
                )
                if doc_upload.get("status") == "success":
                    original_s3_key = doc_upload["s3_key"]
                    logger.info(f"📄 Original document uploaded to MinIO: {original_s3_key}")
            except Exception as minio_err:
                logger.warning(f"Could not upload original document to MinIO: {minio_err}")

            # Spawn concurrent background ingestion task
            asyncio.create_task(
                process_ingestion_background(
                    k_id,
                    file_path,
                    target_file.filename,
                    pipeline,
                    llm,
                    prompt,
                    file_hash,
                    batch_id
                )
            )

            status_display = "On review (Replaced)" if (dup_status == "PENDING" and replace_existing) else "On review"
            response_items.append({
                "knowledge_id": k_id,
                "batch_id": batch_id,
                "file_name": target_file.filename,
                "original_s3_key": original_s3_key,
                "duplicate_status": "PENDING_REPLACED" if (dup_status == "PENDING" and replace_existing) else "NEW",
                "status": status_display
            })

        # Spawn batch coordinator task if multi-file batch upload
        if batch_id and len(response_items) > 1 and llm:
            asyncio.create_task(
                trigger_batch_summary_after_all_done(batch_id, len(response_items), llm, user_prompt=prompt)
            )

        return {
            "status": "success",
            "batch_id": batch_id,
            "total_files": len(upload_list),
            "processed_files": len([r for r in response_items if r.get("knowledge_id")]),
            "message": f"Successfully queued {len(response_items)} document(s) for ingestion." if not batch_id else f"Processed {len(response_items)} document(s) in Batch '{batch_id}'.",
            "documents": response_items
        }

    except Exception as e:
        logger.error(f"Failed to ingest document(s): {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest/text", tags=["Ingestion"], summary="Ingest Knowledge By Text Only")
async def ingest_text_only(
    req: TextIngestRequest,
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
    llm: BaseLLMAdapter = Depends(get_llm)
):
    """
    ✍️ Ingest Knowledge By Text Saja:
    Memasukkan materi pengetahuan secara langsung via teks tanpa melampirkan file.
    Sistem secara otomatis mengonversi teks menjadi dokumen terstruktur `.md`,
    melakukan rekonstruksi struktur/normalisasi, mengunggah ke MinIO `knowledge-documents`,
    dan menempatkan draft di area peninjauan On Review (Pending).
    """
    if not req.text_content or not req.text_content.strip():
        raise HTTPException(status_code=400, detail="Text content cannot be empty.")

    try:
        from app.models.knowledge import KnowledgeType, Knowledge, KnowledgeStatus
        from app.models.user import User
        from app.rag.utils.normalizer import normalize_document_text
        from app.services.storage import upload_document
        from app.core.database import AsyncSessionLocal
        from sqlalchemy import select
        import uuid as _uuid
        import hashlib
        import re

        raw_text = req.text_content.strip()

        # 1. Determine or infer title
        doc_title = req.title.strip() if req.title and req.title.strip() else None
        if not doc_title:
            first_line = raw_text.split('\n')[0].strip().lstrip('#').strip()
            if first_line and len(first_line) <= 80:
                doc_title = first_line
            else:
                doc_title = f"Pengetahuan Teks {int(asyncio.get_event_loop().time())}"

        # Clean title for filename
        clean_filename_base = re.sub(r'[^\w\s-]', '', doc_title).strip().replace(' ', '_')
        if not clean_filename_base:
            clean_filename_base = "knowledge_text"
        filename = f"{clean_filename_base}.md"

        # 2. Normalize text into structured markdown
        normalized_markdown = normalize_document_text(raw_text)
        if not normalized_markdown.startswith('#'):
            normalized_markdown = f"# {doc_title}\n\n" + normalized_markdown

        file_bytes = normalized_markdown.encode('utf-8')
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        # 3. Duplicate detection
        dup_info = detect_duplicate_lifecycle(file_hash, filename)
        dup_status = dup_info.get("status", "NEW")

        if dup_status == "PUBLISHED":
            raise HTTPException(
                status_code=400,
                detail=f"Materi teks '{doc_title}' sudah terpublikasi (APPROVED) di knowledge base. Silakan gunakan menu Edit Knowledge jika ingin memperbarui."
            )

        if dup_status == "PENDING" and not req.replace_existing:
            raise HTTPException(
                status_code=409,
                detail=f"Draft peninjauan untuk '{doc_title}' sudah ada di antrean On Review. Kirim 'replace_existing=true' untuk mengganti draft lama."
            )

        # 4. Save temp .md file
        os.makedirs("data/temp", exist_ok=True)
        file_path = f"data/temp/{filename}"
        with open(file_path, "wb") as f_out:
            f_out.write(file_bytes)

        file_size = len(file_bytes)

        # 5. Create or update Knowledge DB record
        k_id = dup_info.get("knowledge_id") if (dup_status == "PENDING" and req.replace_existing) else None
        async with AsyncSessionLocal() as session:
            user_result = await session.execute(select(User).limit(1))
            user = user_result.scalars().first()
            user_id = user.id if user else _uuid.uuid4()

            custom_uuid = None
            if k_id:
                try:
                    custom_uuid = _uuid.UUID(k_id)
                except ValueError:
                    pass

            existing_doc = None
            if custom_uuid:
                existing_doc = await session.get(Knowledge, custom_uuid)

            if existing_doc:
                knowledge = existing_doc
                knowledge.title = doc_title
                knowledge.status = KnowledgeStatus.PROCESSING
                knowledge.ai_summary = "Processing..."
                knowledge.original_path = file_path
                knowledge.mime_type = "text/markdown"
                knowledge.file_size = file_size
                if knowledge.metadata_ is None:
                    knowledge.metadata_ = {}
                knowledge.metadata_["file_hash"] = file_hash
                await session.commit()
                await session.refresh(knowledge)
                k_id = str(knowledge.id)
            else:
                knowledge = Knowledge(
                    id=custom_uuid if custom_uuid else _uuid.uuid4(),
                    type=KnowledgeType.GENERAL,
                    title=doc_title,
                    file_name=filename,
                    original_path=file_path,
                    mime_type="text/markdown",
                    file_size=file_size,
                    status=KnowledgeStatus.PROCESSING,
                    uploaded_by=user_id,
                    ai_summary="Processing...",
                    ai_confidence=0.0,
                    metadata_={"file_hash": file_hash}
                )
                session.add(knowledge)
                await session.commit()
                await session.refresh(knowledge)
                k_id = str(knowledge.id)

        # 6. Upload .md document to MinIO
        original_s3_key = None
        try:
            doc_upload = upload_document(
                content=file_bytes,
                filename=filename,
                document_id=k_id,
                content_type="text/markdown"
            )
            if doc_upload.get("status") == "success":
                original_s3_key = doc_upload["s3_key"]
        except Exception as minio_err:
            logger.warning(f"Could not upload text .md document to MinIO: {minio_err}")

        # 7. Process background ingestion for staging draft
        asyncio.create_task(
            process_ingestion_background(
                k_id,
                file_path,
                filename,
                pipeline,
                llm,
                req.prompt,
                file_hash,
                None
            )
        )

        return {
            "status": "success",
            "knowledge_id": k_id,
            "file_name": filename,
            "title": doc_title,
            "original_s3_key": original_s3_key,
            "message": f"Berhasil mengonversi teks menjadi dokumen '{filename}' dan menempatkannya di area peninjauan (On Review)."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Text ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/ingest/pending/{knowledge_id}", tags=["Ingestion"], summary="Get Pending Details", response_model=PendingDocumentResponse)
async def get_pending_details(knowledge_id: str = Path(..., description="Pending document identifier (UUID)")):
    """
    Retrieves extracted text, summary, and metadata of a pending staged document.
    """
    target_file = resolve_pending_file(knowledge_id) or resolve_approved_file(knowledge_id)
    if not target_file:
        # Fallback check in PostgreSQL DB for PROCESSING status
        try:
            from app.core.database import AsyncSessionLocal
            from app.models.knowledge import Knowledge
            import uuid as _uuid
            async with AsyncSessionLocal() as session:
                custom_uuid = None
                try:
                    custom_uuid = _uuid.UUID(knowledge_id)
                except ValueError:
                    pass
                
                k_doc = None
                if custom_uuid:
                    k_doc = await session.get(Knowledge, custom_uuid)
                else:
                    from sqlalchemy import select
                    res = await session.execute(select(Knowledge).where(Knowledge.file_name == knowledge_id).order_by(Knowledge.created_at.desc()))
                    k_doc = res.scalars().first()
                    
                if k_doc:
                    return {
                        "knowledge_id": str(k_doc.id),
                        "file_name": k_doc.file_name,
                        "title": k_doc.title,
                        "status": "PROCESSING",
                        "summary": "Document processing in progress...",
                        "text_accuracy": "100%",
                        "feedback": "Pemrosesan dokumen sedang berlangsung di background.",
                        "suggested_categories": [],
                        "chunks": []
                    }
        except Exception as db_err:
            logger.warning(f"DB fallback check failed for {knowledge_id}: {db_err}")

        raise HTTPException(status_code=404, detail=f"Document '{knowledge_id}' not found.")
        
    try:
        with open(target_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            if "knowledge_id" not in data:
                data["knowledge_id"] = knowledge_id
            data.pop("type", None)
            if "status" not in data or not data["status"]:
                data["status"] = "Approved" if "output" in target_file else "On review"
            if "title" not in data or not data["title"]:
                data["title"] = data.get("file_name", "document.pdf")
            if not data.get("image_url") and data.get("chunks"):
                for c in data["chunks"]:
                    if isinstance(c, dict) and c.get("metadata", {}).get("image_url"):
                        data["image_url"] = c["metadata"]["image_url"]
                        break

            # Return in exact PendingDocumentResponse schema order
            ordered_data = {
                "knowledge_id": data.get("knowledge_id"),
                "batch_id": data.get("batch_id"),
                "file_name": data.get("file_name", "document.pdf"),
                "file_hash": data.get("file_hash"),
                "title": data.get("title"),
                "status": data.get("status", "On review"),
                "document_type": data.get("document_type"),
                "valid_from": data.get("valid_from"),
                "valid_until": data.get("valid_until"),
                "summary": data.get("summary", ""),
                "image_url": data.get("image_url"),
                "text_accuracy": data.get("text_accuracy", "100%"),
                "feedback": data.get("feedback", ""),
                "batch_summary": data.get("batch_summary"),
                "suggested_categories": data.get("suggested_categories", []),
                "visibility_settings": data.get("visibility_settings", {
                    "clinics": ["all"],
                    "doctor_types": ["all"],
                    "doctors": ["all"]
                }),
                "initial_prompt": data.get("initial_prompt"),
                "history": data.get("history", []),
                "chunks": data.get("chunks", [])
            }
            if data.get("timing_metrics"):
                ordered_data["timing_metrics"] = data.get("timing_metrics")
            return ordered_data
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read document details: {e}")


@router.post("/ingest/pending/{knowledge_id}/refine", tags=["Ingestion"], summary="Refine Pending Document", response_model=PendingDocumentResponse)
async def refine_pending_document(
    knowledge_id: str = Path(..., description="Pending document identifier (UUID)"),
    request: str = Form(..., description="Prompt instructions to refine summary"),
    llm: BaseLLMAdapter = Depends(get_llm),
    file_attachment: Optional[UploadFile] = File(None, description="Optional supporting file attachment")
):
    """
    Refines a pending document summary using custom natural language AI instructions.
    """
    # Parse request: accept plain text prompt, JSON {"prompt":"...","history":[...]}, or RefineRequest object
    if isinstance(request, str):
        try:
            parsed = json.loads(request)
            if isinstance(parsed, dict) and "prompt" in parsed:
                request = RefineRequest.model_validate(parsed)
            else:
                request = RefineRequest(prompt=request, history=[])
        except (json.JSONDecodeError, ValueError):
            request = RefineRequest(prompt=request, history=[])

    pending_file = resolve_pending_file(knowledge_id)
    if not pending_file:
        raise HTTPException(status_code=404, detail=f"Pending document '{knowledge_id}' not found.")
            
    try:
        with open(pending_file, "r", encoding="utf-8") as f:
            staged_data = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read staged document: {e}")
        
    if not llm:
        raise HTTPException(status_code=500, detail="LLM adapter is not configured. Cannot perform refinement.")
        
    try:
        # 0. Parse attached file if provided
        attached_file_context = ""
        attached_file_name = ""
        if file_attachment:
            try:
                temp_dir = "data/temp"
                os.makedirs(temp_dir, exist_ok=True)
                attached_file_name = getattr(file_attachment, "filename", "attached_refine_doc")
                temp_file_path = os.path.join(temp_dir, f"refine_{knowledge_id}_{attached_file_name}")
                
                content_bytes = await file_attachment.read()
                with open(temp_file_path, "wb") as f:
                    f.write(content_bytes)
                
                from app.rag.utils.parser import DocumentParser
                parser = DocumentParser()
                parse_res = parser.parse_file(temp_file_path)
                
                if parse_res and parse_res.pages:
                    extracted_pages = [p.get("text", "") for p in parse_res.pages if p.get("text")]
                    extracted_text = "\n\n".join(extracted_pages)
                    attached_file_context = (
                        f"\n\n--- NEWLY ATTACHED SUPPLEMENTARY FILE: '{attached_file_name}' ---\n"
                        f"{extracted_text}\n"
                        f"--- END OF ATTACHED FILE CONTENT ---\n"
                    )
                    logger.info(f"📄 Successfully parsed attached file '{attached_file_name}' for pending refine (knowledge_id='{knowledge_id}').")
                
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
            except Exception as att_err:
                logger.warning(f"Failed to parse attached file in pending refine: {att_err}")

        # Fetch categories from DB for LLM recommendation
        db_categories = []
        try:
            from app.core.database import AsyncSessionLocal
            from app.models.category import Category
            from sqlalchemy import select
            async with AsyncSessionLocal() as session:
                res = await session.execute(select(Category).where(Category.deleted_at.is_(None)))
                cats = res.scalars().all()
                db_categories = [{"id": str(c.id), "name": c.name} for c in cats]
        except Exception as cat_err:
            logger.warning(f"Failed to fetch categories for refine prompt: {cat_err}")

        if not db_categories:
            default_cats = [
                ("9b79e362-ec70-4560-902e-fd5897c07a00", "Acne Care"),
                ("1a23b456-ec70-4560-902e-fd5897c07a01", "Anti Aging"),
                ("2b34c567-ec70-4560-902e-fd5897c07a02", "Dark Spot"),
                ("3c45d678-ec70-4560-902e-fd5897c07a03", "Psoriasis Care"),
                ("4d56e789-ec70-4560-902e-fd5897c07a04", "Scar Treatment"),
                ("5e67f890-ec70-4560-902e-fd5897c07a05", "Wound Healing"),
                ("6f78a901-ec70-4560-902e-fd5897c07a06", "Brightening")
            ]
            db_categories = [{"id": cid, "name": cname} for cid, cname in default_cats]

        history_str = ""
        if request.history:
            for msg in request.history:
                role = "User" if getattr(msg, "role", "") == "user" else "Assistant"
                content = getattr(msg, "content", "")
                history_str += f"{role}: {content}\n"
        else:
            history_str = "No previous refinement history.\n"

        # ─── DUAL-MODE PROMPT: SURGICAL EDIT vs MERGE ────────────────────────────────
        if attached_file_context:
            # ═══ MERGE MODE: Combine attached file into existing document ═══
            refine_prompt = f"""
You are a document merger for the ERHA (PT Arya Noble) knowledge base.
Your job is to COMBINE the content from a newly attached file into the existing document,
following the admin's specific instructions on how to merge.

======================================================================
ADMIN MERGE INSTRUCTION:
"{request.prompt}"
======================================================================

Conversation History (for context only):
{history_str}

EXISTING DOCUMENT CONTENT:
{json.dumps(staged_data.get("summary", ""), ensure_ascii=False)}

{attached_file_context}

MERGE RULES:
1. **FOLLOW ADMIN INSTRUCTION**: The admin's instruction tells you HOW to combine the attached file.
   - e.g. "gabungkan data produk baru dari file ini" → merge new product data into existing document.
   - e.g. "tambahkan informasi harga dari file terlampir" → extract pricing from attached file and add to existing doc.
2. **PRESERVE EXISTING CONTENT**: All existing document content that is NOT being merged/replaced MUST be kept VERBATIM.
3. **USE ATTACHED FILE DATA ONLY**: Only add information that actually exists in the attached file. Do NOT fabricate.
4. **CONSISTENT STRUCTURE**: Maintain the existing markdown heading structure (## sections). Add new sections if needed.
5. **FEEDBACK**: Write 1 short Indonesian sentence describing what was merged (e.g. "Data harga dari file terlampir telah ditambahkan ke dokumen.").

Available System Categories (update if relevant):
{json.dumps(db_categories, ensure_ascii=False)}

Return a valid JSON object ONLY (do NOT wrap in ```json blocks):
{{
    "knowledge_id": "{staged_data.get('knowledge_id', knowledge_id)}",
    "file_name": "{staged_data.get('file_name', knowledge_id)}",
    "title": "{staged_data.get('title', 'Document Title')}",
    "status": "On review",
    "summary": "The merged document with attached file content integrated per admin instruction",
    "text_accuracy": "100%",
    "feedback": "Deskripsi singkat apa yang di-merge.",
    "suggested_categories": [
        {{"id": "category_id", "name": "category_name"}}
    ]
}}
"""
        else:
            # ═══ SURGICAL EDIT MODE: Apply exact changes only ═══
            refine_prompt = f"""
You are a precise text editor for the ERHA (PT Arya Noble) knowledge base.
Your ONLY job is to apply the admin's explicit edit instruction to the document below.
You are NOT a content writer. You are NOT allowed to rewrite, rephrase, restructure, or improve any content.

======================================================================
ADMIN EDIT INSTRUCTION (THE ONLY THING YOU ARE ALLOWED TO CHANGE):
"{request.prompt}"
======================================================================

Conversation History (for context only):
{history_str}

CURRENT DOCUMENT CONTENT (canonical_text — preserve verbatim unless instructed):
{json.dumps(staged_data.get("summary", ""), ensure_ascii=False)}

STRICT EDITING RULES (VIOLATING ANY RULE IS A CRITICAL FAILURE):
1. **SURGICAL CHANGES ONLY**: Apply ONLY the change(s) explicitly requested in the Admin Edit Instruction.
   - If instruction says "hapus bagian Warnings" → remove only the Warnings section. Leave all other sections exactly as-is.
   - If instruction says "ganti nama produk X menjadi Y" → change only that product name. Leave all other text unchanged.
   - If instruction says "tambahkan SPF45 di Active Ingredients" → insert that line only. Do not modify surrounding text.
2. **VERBATIM PRESERVATION**: Every word, sentence, paragraph, table, and bullet NOT targeted by the instruction MUST be returned character-for-character as-is.
   - DO NOT rephrase any sentence not explicitly commanded.
   - DO NOT reformat or restructure any section not explicitly commanded.
   - DO NOT add explanations, transitions, or commentary not in the original.
3. **ZERO NEW CONTENT**: You are FORBIDDEN from adding any information not present in the original document AND not in the admin's instruction.
   - If admin says "tambahkan keterangan X" → you may add exactly that keterangan X.
   - You may NOT add anything else.
4. **CATEGORIES**: Only update `suggested_categories` if the admin instruction explicitly asks for it.
5. **FEEDBACK**: Write 1 short Indonesian sentence describing exactly what was changed (e.g. "Bagian Warnings telah dihapus sesuai instruksi.").

Available System Categories (only if instruction asks to change categories):
{json.dumps(db_categories, ensure_ascii=False)}

Return a valid JSON object ONLY (do NOT wrap in ```json blocks):
{{
    "knowledge_id": "{staged_data.get('knowledge_id', knowledge_id)}",
    "file_name": "{staged_data.get('file_name', knowledge_id)}",
    "title": "{staged_data.get('title', 'Document Title')}",
    "status": "On review",
    "summary": "VERBATIM document text with ONLY the instructed change(s) applied",
    "text_accuracy": "100%",
    "feedback": "Deskripsi singkat perubahan yang diterapkan.",
    "suggested_categories": [
        {{"id": "category_id", "name": "category_name"}}
    ]
}}
"""
        
        llm_response = await asyncio.to_thread(llm.generate, refine_prompt)
        
        updated_data = safe_json_loads(llm_response)

        # Comprehensive metadata preservation across refinement rounds
        k_id = staged_data.get("knowledge_id", knowledge_id)
        updated_data["knowledge_id"] = k_id
        
        # Preserve core physical document properties from initial staging
        for prop in ["file_name", "file_hash", "batch_id", "title", "document_type", "valid_from", "valid_until", "image_url", "s3_key", "storage_key", "batch_summary", "initial_prompt", "visibility_settings"]:
            if prop in staged_data and staged_data.get(prop) is not None:
                if prop not in updated_data or updated_data.get(prop) is None:
                    updated_data[prop] = staged_data.get(prop)

        # Remove legacy type if present
        updated_data.pop("type", None)

        # Apply deterministic refinements for SKU, Price
        cur_summary = updated_data.get("summary") or staged_data.get("summary", "")
        cur_title = updated_data.get("title") or staged_data.get("title") or staged_data.get("file_name", k_id)
        
        refined_summary, _, refined_title, refined_sku = apply_refinements_to_content(
            user_prompt=request.prompt,
            summary=cur_summary,
            chunks=[],
            title=cur_title
        )
        updated_data["summary"] = refined_summary
        if refined_title:
            updated_data["title"] = refined_title
        if refined_sku:
            updated_data["sku"] = refined_sku
            updated_data["feedback"] = f"Nomor SKU berhasil diperbarui menjadi {refined_sku}."

        # Build updated multi-turn conversation history
        existing_hist = staged_data.get("history", [])
        if not isinstance(existing_hist, list):
            existing_hist = []
        new_hist = list(existing_hist)
        new_hist.append({"role": "user", "content": request.prompt})
        new_hist.append({"role": "assistant", "content": updated_data.get("summary", "")})
        updated_data["history"] = new_hist

        vis_settings = updated_data.get("visibility_settings") or staged_data.get("visibility_settings", {})
        doc_img_url = updated_data.get("image_url") or staged_data.get("image_url")
        doc_file_hash = updated_data.get("file_hash") or staged_data.get("file_hash")
        doc_batch_id = updated_data.get("batch_id") or staged_data.get("batch_id")
        doc_file_name = updated_data.get("file_name") or staged_data.get("file_name", k_id)
        doc_title = updated_data.get("title") or staged_data.get("title") or doc_file_name
        doc_type = updated_data.get("document_type") or staged_data.get("document_type")
        doc_valid_from = updated_data.get("valid_from") or staged_data.get("valid_from")
        doc_valid_until = updated_data.get("valid_until") or staged_data.get("valid_until")

        # ─── RE-CHUNK from updated summary (same pipeline as Approve) ─────────────
        # Do NOT use LLM-returned chunks. Always re-chunk from summary for consistency.
        cat_names = []
        raw_cats = updated_data.get("suggested_categories", staged_data.get("suggested_categories", []))
        for c in raw_cats:
            if isinstance(c, dict) and "name" in c:
                cat_names.append(c["name"])
            elif isinstance(c, str):
                cat_names.append(c)

        updated_chunks = []
        if refined_summary and refined_summary.strip():
            try:
                from app.rag.utils.summary_chunker import chunk_summary_markdown
                updated_chunks = chunk_summary_markdown(
                    summary=refined_summary,
                    source_file=doc_file_name,
                    knowledge_id=k_id,
                    batch_id=doc_batch_id,
                    file_hash=doc_file_hash or "",
                    title=doc_title,
                    doc_type=doc_type or "GENERAL",
                    categories=cat_names,
                    valid_from=str(doc_valid_from).strip() if doc_valid_from else None,
                    valid_until=str(doc_valid_until).strip() if doc_valid_until else None,
                    visibility_settings=vis_settings if isinstance(vis_settings, dict) else {},
                )
                logger.info(f"Refine Pending: re-chunked summary into {len(updated_chunks)} chunks.")
            except Exception as rechunk_err:
                logger.warning(f"Refine Pending: re-chunking failed, using LLM chunks: {rechunk_err}")
                updated_chunks = updated_data.get("chunks", staged_data.get("chunks", []))
                # Patch metadata on fallback chunks
                for chunk in updated_chunks:
                    if isinstance(chunk, dict):
                        if "metadata" not in chunk:
                            chunk["metadata"] = {}
                        chunk["metadata"]["knowledge_id"] = k_id
        
        # Save the updated data back in exact requested schema order
        final_updated_data = {
            "knowledge_id": k_id,
            "batch_id": doc_batch_id,
            "file_name": doc_file_name,
            "file_hash": doc_file_hash,
            "title": doc_title,
            "status": updated_data.get("status") or staged_data.get("status", "On review"),
            "document_type": doc_type,
            "valid_from": doc_valid_from,
            "valid_until": doc_valid_until,
            "summary": updated_data.get("summary", ""),
            "image_url": doc_img_url,
            "image_urls": staged_data.get("image_urls", []),
            "text_accuracy": updated_data.get("text_accuracy") or staged_data.get("text_accuracy", "100%"),
            "feedback": updated_data.get("feedback") or staged_data.get("feedback", ""),
            "batch_summary": updated_data.get("batch_summary") or staged_data.get("batch_summary"),
            "suggested_categories": raw_cats,
            "visibility_settings": vis_settings,
            "initial_prompt": updated_data.get("initial_prompt") or staged_data.get("initial_prompt"),
            "history": new_hist,
            "chunks": updated_chunks
        }
        if staged_data.get("timing_metrics"):
            final_updated_data["timing_metrics"] = staged_data.get("timing_metrics")

        # If part of a multi-file batch, re-synthesize updated batch executive summary
        batch_id_val = final_updated_data.get("batch_id")
        if batch_id_val and llm:
            try:
                b_summary = await synthesize_batch_executive_summary(batch_id_val, llm)
                if b_summary:
                    final_updated_data["batch_summary"] = b_summary
            except Exception as b_err:
                logger.warning(f"Could not update batch summary after refine: {b_err}")

        with open(pending_file, "w", encoding="utf-8") as f:
            json.dump(final_updated_data, f, indent=4, ensure_ascii=False)
            
        return final_updated_data
    except Exception as e:
        logger.error(f"Refinement failed for document '{knowledge_id}': {e}")
        raise HTTPException(status_code=500, detail=f"Failed to refine document: {e}")


@router.get("/ingest/documents", tags=["Ingestion"], summary="List All Documents", response_model=List[DocumentListItem])
async def list_all_documents():
    """
    Retrieves all knowledge base documents across Approved, On review, and Processing statuses.
    """
    pending_dir = "data/pending"
    approved_dir = "data/output"
    
    docs = []
    seen_ids = set()
    
    # 1. Scan pending (which are nested object schemas)
    if os.path.exists(pending_dir):
        for f in os.listdir(pending_dir):
            if f.endswith(".json"):
                file_path = os.path.join(pending_dir, f)
                try:
                    with open(file_path, "r", encoding="utf-8") as f_json:
                        data = json.load(f_json)
                    if isinstance(data, dict):
                        chunks = data.get("chunks", [])
                        first_chunk_meta = chunks[0].get("metadata", {}) if chunks and isinstance(chunks[0], dict) else {}
                        fallback_id = f.replace("_parsed.json", "").replace(".json", "")
                        k_id = str(data.get("knowledge_id", first_chunk_meta.get("knowledge_id", fallback_id)))

                        doc_type = data.get("type") or first_chunk_meta.get("type") or first_chunk_meta.get("document_type") or None
                        if doc_type:
                            doc_type = doc_type.capitalize()

                        docs.append(DocumentListItem(
                            knowledge_id=k_id,
                            batch_id=data.get("batch_id") or first_chunk_meta.get("batch_id"),
                            file_name=data.get("file_name", fallback_id),
                            product_name=first_chunk_meta.get("product_name"),
                            status=data.get("status", "On review"),
                            processed_at=first_chunk_meta.get("processed_at"),
                            chunks_count=len(chunks)
                        ))
                        seen_ids.add(k_id)
                except Exception as err:
                    logger.warning(f"Error parsing pending metadata for {f}: {err}")
                    
    # 2. Scan approved
    if os.path.exists(approved_dir):
        for f in os.listdir(approved_dir):
            if f.endswith(".json"):
                file_path = os.path.join(approved_dir, f)
                try:
                    with open(file_path, "r", encoding="utf-8") as f_json:
                        data = json.load(f_json)
                    
                    raw_id = f.replace("_parsed.json", "").replace(".json", "")
                    k_id = raw_id
                    file_name = raw_id
                    product_name = None
                    doc_type = None
                    processed_at = None
                    chunks = []
                    
                    if isinstance(data, dict):
                        k_id = str(data.get("knowledge_id", k_id))
                        file_name = data.get("file_name", file_name)
                        doc_type = data.get("type") or doc_type
                        chunks = data.get("chunks", [])
                        if chunks and isinstance(chunks[0], dict):
                            first_meta = chunks[0].get("metadata", {})
                            product_name = first_meta.get("product_name")
                            doc_type = data.get("type") or first_meta.get("type") or first_meta.get("document_type") or None
                            processed_at = first_meta.get("processed_at")
                    elif isinstance(data, list):
                        chunks = data
                        if chunks and isinstance(chunks[0], dict):
                            first_meta = chunks[0].get("metadata", {})
                            k_id = str(first_meta.get("knowledge_id", k_id))
                            file_name = first_meta.get("source_file", file_name)
                            product_name = first_meta.get("product_name")
                            doc_type = first_meta.get("type") or first_meta.get("document_type") or None
                            processed_at = first_meta.get("processed_at")
                            
                    if doc_type:
                        doc_type = doc_type.capitalize()

                    if k_id not in seen_ids:
                        batch_id_val = None
                        if isinstance(data, dict):
                            batch_id_val = data.get("batch_id")
                            if not batch_id_val and chunks and isinstance(chunks[0], dict):
                                batch_id_val = chunks[0].get("metadata", {}).get("batch_id")
                        elif isinstance(data, list) and chunks and isinstance(chunks[0], dict):
                            batch_id_val = chunks[0].get("metadata", {}).get("batch_id")

                        docs.append(DocumentListItem(
                            knowledge_id=k_id,
                            batch_id=batch_id_val,
                            file_name=file_name,
                            product_name=product_name,
                            status="Approved",
                            processed_at=processed_at,
                            chunks_count=len(chunks)
                        ))
                        seen_ids.add(k_id)
                except Exception as err:
                    logger.warning(f"Error parsing approved metadata for {f}: {err}")

    # 3. Fallback DB sync: Include records from PostgreSQL Knowledge table that aren't in JSON files yet
    try:
        from app.core.database import AsyncSessionLocal
        from app.models.knowledge import Knowledge
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            stmt = select(Knowledge).where(Knowledge.deleted_at.is_(None)).order_by(Knowledge.created_at.desc())
            res = await session.execute(stmt)
            k_records = res.scalars().all()
            
            for k in k_records:
                str_id = str(k.id)
                if str_id not in seen_ids:
                    st_val = k.status.value if hasattr(k.status, "value") else str(k.status)
                    status_display = "Approved" if st_val.upper() == "APPROVED" else ("On review" if st_val.upper() in ("PENDING", "PROCESSING") else "On review")
                    
                    docs.append(DocumentListItem(
                        knowledge_id=str_id,
                        file_name=k.file_name or k.title or "Untitled Document",
                        product_name=k.title,
                        status=status_display,
                        processed_at=k.created_at.strftime("%Y-%m-%d %H:%M:%S") if k.created_at else None,
                        chunks_count=0
                    ))
                    seen_ids.add(str_id)
    except Exception as db_err:
        logger.warning(f"DB fallback query in list_all_documents failed: {db_err}")

    return docs


@router.get("/ingest/approved/{knowledge_id}", tags=["Ingestion"], summary="Get Approved Document Details", response_model=ApprovedDocumentResponse)
async def get_approved_document_details(knowledge_id: str = Path(..., description="Approved document identifier (UUID)")):
    """
    Retrieves full summary, metadata, and text chunks of an approved document.
    """
    approved_file = resolve_approved_file(knowledge_id)
    if not approved_file:
        raise HTTPException(
            status_code=404, 
            detail=f"Document '{knowledge_id}' is not approved yet (currently in 'On review' status). Use GET /api/ai/ingest/pending/{knowledge_id} instead."
        )
        
    try:
        with open(approved_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        summary = ""
        categories = []
        chunks = []
        file_name = knowledge_id
        title = knowledge_id

        if isinstance(data, dict):
            summary = data.get("summary", "")
            categories = data.get("categories", [])
            chunks = data.get("chunks", [])
            file_name = data.get("file_name", knowledge_id)
            title = data.get("title", file_name)
        elif isinstance(data, list):
            chunks = data
            if chunks and isinstance(chunks[0], dict):
                first_meta = chunks[0].get("metadata", {})
                file_name = first_meta.get("source_file", knowledge_id)
                title = first_meta.get("title", file_name)
                summary = first_meta.get("summary", "")
                cat = first_meta.get("document_type")
        parsed_categories = []
        for c in categories:
            if isinstance(c, dict) and "name" in c:
                parsed_categories.append(c["name"])
            elif isinstance(c, str):
                parsed_categories.append(c)

        vis_settings = (data.get("visibility_settings") if isinstance(data, dict) else None) or {
            "clinics": ["all"],
            "doctor_types": ["all"],
            "doctors": ["all"]
        }

        return ApprovedDocumentResponse(
            knowledge_id=knowledge_id,
            batch_id=data.get("batch_id") if isinstance(data, dict) else None,
            file_name=file_name,
            file_hash=data.get("file_hash") if isinstance(data, dict) else None,
            title=title,
            status="Approved",
            document_type=data.get("document_type") if isinstance(data, dict) else None,
            valid_from=data.get("valid_from") if isinstance(data, dict) else None,
            valid_until=data.get("valid_until") if isinstance(data, dict) else None,
            summary=summary,
            image_url=data.get("image_url") if isinstance(data, dict) else None,
            batch_summary=data.get("batch_summary") if isinstance(data, dict) else None,
            categories=parsed_categories,
            visibility_settings=vis_settings,
            chunks=chunks
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to read approved document '{knowledge_id}': {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read approved document: {e}")


@router.put("/ingest/approved/{knowledge_id}", tags=["Ingestion"], summary="Edit Approved Document")
async def edit_approved_document(
    knowledge_id: str = Path(..., description="Approved document identifier"),
    request: EditApprovedDocumentRequest = ...,
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
    bm25: BM25Index = Depends(get_bm25_index),
    vector_store: BaseVectorStoreAdapter = Depends(get_vector_store)
):
    """
    Updates summary, categories, and metadata of an approved document and re-indexes vector embeddings.
    """
    approved_file = resolve_approved_file(knowledge_id)
    if not approved_file:
        raise HTTPException(status_code=404, detail=f"Approved document '{knowledge_id}' not found.")

    try:
        with open(approved_file, "r", encoding="utf-8") as f:
            existing_doc = json.load(f)

        updated_summary = request.summary if request.summary is not None else existing_doc.get("summary", "")
        updated_categories = request.categories if (request.categories is not None and len(request.categories) > 0) else existing_doc.get("categories", [])
        updated_title = request.title if request.title is not None else existing_doc.get("file_name", knowledge_id)
        updated_doc_type = request.document_type if request.document_type is not None else existing_doc.get("document_type")
        updated_valid_from = request.valid_from if request.valid_from is not None else existing_doc.get("valid_from")
        updated_valid_until = request.valid_until if request.valid_until is not None else existing_doc.get("valid_until")
        updated_chunks = existing_doc.get("chunks", [])

        vis_settings = request.visibility_settings.model_dump() if request.visibility_settings else existing_doc.get("visibility_settings", {
            "clinics": ["all"],
            "doctor_types": ["all"],
            "doctors": ["all"]
        })

        if updated_summary and updated_summary.strip():
            try:
                from app.rag.utils.summary_chunker import chunk_summary_markdown
                updated_chunks = chunk_summary_markdown(
                    summary=updated_summary,
                    source_file=existing_doc.get("file_name", updated_title),
                    knowledge_id=knowledge_id,
                    batch_id=existing_doc.get("batch_id"),
                    file_hash=existing_doc.get("file_hash", ""),
                    title=updated_title,
                    doc_type=updated_doc_type or "GENERAL",
                    categories=updated_categories,
                    visibility_settings=vis_settings,
                )
            except Exception as rechunk_err:
                logger.warning(f"Update approved re-chunking failed: {rechunk_err}")

        approved_doc_structure = {
            "knowledge_id": knowledge_id,
            "batch_id": existing_doc.get("batch_id") if isinstance(existing_doc, dict) else None,
            "file_name": existing_doc.get("file_name", ""),
            "file_hash": existing_doc.get("file_hash") if isinstance(existing_doc, dict) else None,
            "title": updated_title,
            "status": "Approved",
            "document_type": updated_doc_type,
            "valid_from": updated_valid_from,
            "valid_until": updated_valid_until,
            "summary": updated_summary,
            "image_url": existing_doc.get("image_url") if isinstance(existing_doc, dict) else None,
            "batch_summary": existing_doc.get("batch_summary") if isinstance(existing_doc, dict) else None,
            "categories": updated_categories,
            "visibility_settings": vis_settings,
            "chunks": updated_chunks
        }
        with open(approved_file, "w", encoding="utf-8") as f:
            json.dump(approved_doc_structure, f, indent=4, ensure_ascii=False)

        target_store = (pipeline.vector_store if pipeline and pipeline.vector_store else vector_store)
        if target_store:
            logger.info(f"Re-indexing PGVector for knowledge_id '{knowledge_id}'...")
            target_store.delete_document(knowledge_id)
            target_store.insert_chunks(updated_chunks)

        if bm25:
            logger.info(f"Re-indexing BM25 for knowledge_id '{knowledge_id}'...")
            bm25.remove_file_chunks(knowledge_id)
            bm25.add_chunks(updated_chunks)
            bm25.save(settings.bm25_index_path)

        if target_store and hasattr(target_store, "upsert_knowledge_category"):
            target_store.upsert_knowledge_category(
                knowledge_id=knowledge_id,
                file_name=updated_title,
                categories=updated_categories,
                summary=updated_summary
            )

        return approved_doc_structure
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Edit approved document failed for '{knowledge_id}': {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update approved document: {e}")


@router.put("/ingest/pending/{knowledge_id}", tags=["Ingestion"], summary="Edit Pending Document")
async def edit_pending_document(
    knowledge_id: str = Path(..., description="Pending document identifier (UUID)"),
    request: EditApprovedDocumentRequest = ...
):
    """
    Updates summary, categories, and metadata of a pending staged document.
    """
    pending_file = resolve_pending_file(knowledge_id)
    if not pending_file:
        raise HTTPException(status_code=404, detail=f"Pending document '{knowledge_id}' not found.")

    try:
        with open(pending_file, "r", encoding="utf-8") as f:
            existing_doc = json.load(f)

        updated_summary = request.summary if request.summary is not None else existing_doc.get("summary", "")
        updated_categories = request.categories if (request.categories is not None and len(request.categories) > 0) else existing_doc.get("suggested_categories", [])
        updated_title = request.title if request.title is not None else existing_doc.get("file_name", existing_doc.get("title", knowledge_id))
        updated_doc_type = request.document_type if request.document_type is not None else existing_doc.get("document_type")
        updated_valid_from = request.valid_from if request.valid_from is not None else existing_doc.get("valid_from")
        updated_valid_until = request.valid_until if request.valid_until is not None else existing_doc.get("valid_until")

        # Normalize suggested_categories to list of dicts for pending json
        normalized_categories = []
        if updated_categories:
            if isinstance(updated_categories[0], str):
                normalized_categories = [{"name": c} for c in updated_categories]
            else:
                normalized_categories = updated_categories
                
        existing_doc["summary"] = updated_summary
        existing_doc["title"] = updated_title
        if updated_doc_type is not None:
            existing_doc["document_type"] = updated_doc_type
        if updated_valid_from is not None:
            existing_doc["valid_from"] = updated_valid_from
        if updated_valid_until is not None:
            existing_doc["valid_until"] = updated_valid_until

        if updated_categories is not None and len(updated_categories) > 0:
            existing_doc["suggested_categories"] = normalized_categories
            
        vis_settings = request.visibility_settings.model_dump() if request.visibility_settings else existing_doc.get("visibility_settings", {
            "clinics": ["all"],
            "doctor_types": ["all"],
            "doctors": ["all"]
        })
        existing_doc["visibility_settings"] = vis_settings

        str_categories = [c["name"] if isinstance(c, dict) else c for c in normalized_categories]
        if updated_summary and updated_summary.strip():
            try:
                from app.rag.utils.summary_chunker import chunk_summary_markdown
                updated_chunks = chunk_summary_markdown(
                    summary=updated_summary,
                    source_file=existing_doc.get("file_name", updated_title),
                    knowledge_id=knowledge_id,
                    batch_id=existing_doc.get("batch_id"),
                    file_hash=existing_doc.get("file_hash", ""),
                    title=updated_title,
                    doc_type=updated_doc_type or "GENERAL",
                    categories=str_categories,
                    visibility_settings=vis_settings,
                )
                existing_doc["chunks"] = updated_chunks
            except Exception as rechunk_err:
                logger.warning(f"Update pending re-chunking failed: {rechunk_err}")

        with open(pending_file, "w", encoding="utf-8") as f:
            json.dump(existing_doc, f, indent=4, ensure_ascii=False)

        return existing_doc
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Edit pending document failed for '{knowledge_id}': {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update pending document: {e}")


@router.post("/ingest/approved/{knowledge_id}/refine", tags=["Ingestion"], summary="Refine Approved Document")
async def refine_approved_document(
    knowledge_id: str = Path(..., description="Approved document identifier (UUID)"),
    request: str = Form(..., description="Prompt instructions to refine summary"),
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
    bm25: BM25Index = Depends(get_bm25_index),
    vector_store: BaseVectorStoreAdapter = Depends(get_vector_store),
    llm: BaseLLMAdapter = Depends(get_llm),
    file_attachment: Optional[UploadFile] = File(None, description="Optional supporting file attachment")
):
    """
    Refines an approved document summary using AI prompt instructions and updates RAG index.
    """
    # Parse request: accept plain text prompt, JSON {"prompt":"...","history":[...]}, or RefineRequest object
    if isinstance(request, str):
        try:
            parsed = json.loads(request)
            if isinstance(parsed, dict) and "prompt" in parsed:
                request = RefineRequest.model_validate(parsed)
            else:
                request = RefineRequest(prompt=request, history=[])
        except (json.JSONDecodeError, ValueError):
            request = RefineRequest(prompt=request, history=[])

    approved_file = resolve_approved_file(knowledge_id)
    if not approved_file:
        raise HTTPException(status_code=404, detail=f"Approved document '{knowledge_id}' not found.")

    if not llm:
        raise HTTPException(status_code=500, detail="LLM adapter is not configured.")

    try:
        with open(approved_file, "r", encoding="utf-8") as f:
            existing_doc = json.load(f)

        # 0. Parse attached file if provided
        attached_file_context = ""
        attached_file_name = ""
        if file_attachment:
            try:
                temp_dir = "data/temp"
                os.makedirs(temp_dir, exist_ok=True)
                attached_file_name = getattr(file_attachment, "filename", "attached_refine_doc")
                temp_file_path = os.path.join(temp_dir, f"refine_approved_{knowledge_id}_{attached_file_name}")
                
                content_bytes = await file_attachment.read()
                with open(temp_file_path, "wb") as f:
                    f.write(content_bytes)
                
                from app.rag.utils.parser import DocumentParser
                parser = DocumentParser()
                parse_res = parser.parse_file(temp_file_path)
                
                if parse_res and parse_res.pages:
                    extracted_pages = [p.get("text", "") for p in parse_res.pages if p.get("text")]
                    extracted_text = "\n\n".join(extracted_pages)
                    attached_file_context = (
                        f"\n\n--- NEWLY ATTACHED SUPPLEMENTARY FILE: '{attached_file_name}' ---\n"
                        f"{extracted_text}\n"
                        f"--- END OF ATTACHED FILE CONTENT ---\n"
                    )
                    logger.info(f"📄 Successfully parsed attached file '{attached_file_name}' for approved refine (knowledge_id='{knowledge_id}').")
                
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
            except Exception as att_err:
                logger.warning(f"Failed to parse attached file in approved refine: {att_err}")

        db_categories = []
        try:
            from app.core.database import AsyncSessionLocal
            from app.models.category import Category
            from sqlalchemy import select
            async with AsyncSessionLocal() as session:
                res = await session.execute(select(Category).where(Category.deleted_at.is_(None)))
                cats = res.scalars().all()
                db_categories = [{"id": str(c.id), "name": c.name} for c in cats]
        except Exception as cat_err:
            logger.warning(f"Failed to fetch categories: {cat_err}")

        history_str = ""
        if request.history:
            for msg in request.history:
                role = "User" if getattr(msg, "role", "") == "user" else "Assistant"
                content = getattr(msg, "content", "")
                history_str += f"{role}: {content}\n"
        else:
            history_str = "No previous refinement history.\n"

        # ─── DUAL-MODE PROMPT: SURGICAL EDIT vs MERGE ────────────────────────────────
        if attached_file_context:
            # ═══ MERGE MODE: Combine attached file into existing approved document ═══
            refine_prompt = f"""
You are a document merger for the ERHA (PT Arya Noble) knowledge base.
Your job is to COMBINE the content from a newly attached file into the existing approved document,
following the admin's specific instructions on how to merge.

======================================================================
ADMIN MERGE INSTRUCTION:
"{request.prompt}"
======================================================================

Conversation History (for context only):
{history_str}

EXISTING APPROVED DOCUMENT CONTENT:
{json.dumps(existing_doc.get("summary", ""), ensure_ascii=False)}

{attached_file_context}

MERGE RULES:
1. **FOLLOW ADMIN INSTRUCTION**: The admin's instruction tells you HOW to combine the attached file.
   - e.g. "gabungkan data produk baru dari file ini" → merge new product data into existing document.
   - e.g. "tambahkan informasi harga dari file terlampir" → extract pricing from attached file and add to existing doc.
2. **PRESERVE EXISTING CONTENT**: All existing document content that is NOT being merged/replaced MUST be kept VERBATIM.
3. **USE ATTACHED FILE DATA ONLY**: Only add information that actually exists in the attached file. Do NOT fabricate.
4. **CONSISTENT STRUCTURE**: Maintain the existing markdown heading structure (## sections). Add new sections if needed.
5. **CATEGORIES**: Only update `categories` if the merged content introduces new topics.

Available System Categories (update if relevant):
{json.dumps(db_categories, ensure_ascii=False)}

Return a valid JSON object ONLY (do NOT wrap in ```json blocks):
{{
    "summary": "The merged document with attached file content integrated per admin instruction",
    "categories": ["category_name"]
}}
"""
        else:
            # ═══ SURGICAL EDIT MODE: Apply exact changes only ═══
            refine_prompt = f"""
You are a precise text editor for the ERHA (PT Arya Noble) knowledge base.
Your ONLY job is to apply the admin's explicit edit instruction to the approved document below.
You are NOT a content writer. You are NOT allowed to rewrite, rephrase, restructure, or improve any content.

======================================================================
ADMIN EDIT INSTRUCTION (THE ONLY THING YOU ARE ALLOWED TO CHANGE):
"{request.prompt}"
======================================================================

Conversation History (for context only):
{history_str}

CURRENT APPROVED DOCUMENT CONTENT (preserve verbatim unless instructed):
{json.dumps(existing_doc.get("summary", ""), ensure_ascii=False)}

STRICT EDITING RULES (VIOLATING ANY RULE IS A CRITICAL FAILURE):
1. **SURGICAL CHANGES ONLY**: Apply ONLY the change(s) explicitly requested in the Admin Edit Instruction.
   - If instruction says "hapus bagian Warnings" → remove only that section. Leave all other sections exactly as-is.
   - If instruction says "ganti nama produk X menjadi Y" → change only that product name. Leave all other text unchanged.
   - If instruction says "tambahkan SPF45 di Active Ingredients" → insert that line only.
2. **VERBATIM PRESERVATION**: Every word, sentence, paragraph, table, and bullet NOT targeted by the instruction MUST be returned character-for-character as-is.
   - DO NOT rephrase any sentence not explicitly commanded.
   - DO NOT reformat or restructure any section not explicitly commanded.
   - DO NOT add explanations, transitions, or commentary not in the original.
3. **ZERO NEW CONTENT**: You are FORBIDDEN from adding any information not present in the original document AND not in the admin's instruction.
4. **CATEGORIES**: Only update `categories` if the admin instruction explicitly asks for it.

Available System Categories (only if instruction asks to change categories):
{json.dumps(db_categories, ensure_ascii=False)}

Return a valid JSON object ONLY (do NOT wrap in ```json blocks):
{{
    "summary": "VERBATIM document text with ONLY the instructed change(s) applied",
    "categories": ["category_name"]
}}
"""
        
        llm_res = await asyncio.to_thread(llm.generate, refine_prompt)
        parsed_refined = safe_json_loads(llm_res)
        updated_summary = parsed_refined.get("summary", existing_doc.get("summary", ""))
        updated_categories = parsed_refined.get("categories", existing_doc.get("categories", []))
        file_name = existing_doc.get("file_name", knowledge_id)
        doc_type = existing_doc.get("document_type") if isinstance(existing_doc, dict) else None
        doc_title = existing_doc.get("title", file_name) if isinstance(existing_doc, dict) else file_name
        doc_valid_from = existing_doc.get("valid_from") if isinstance(existing_doc, dict) else None
        doc_valid_until = existing_doc.get("valid_until") if isinstance(existing_doc, dict) else None

        # Apply deterministic refinements for SKU, Price, and chunk synchronization
        refined_summary, _, refined_title, refined_sku = apply_refinements_to_content(
            user_prompt=request.prompt,
            summary=updated_summary,
            chunks=[],
            title=doc_title
        )
        updated_summary = refined_summary

        # ─── RE-CHUNK from updated summary (same as Approve flow) ────────────────────
        # Do NOT use LLM-returned chunks directly — always re-chunk from summary
        # to ensure consistent, well-structured chunks go into the vector DB.
        vis_settings = existing_doc.get("visibility_settings") or {
            "clinics": ["all"], "doctor_types": ["all"], "doctors": ["all"]
        }
        cat_names = []
        for c in updated_categories:
            if isinstance(c, dict) and "name" in c:
                cat_names.append(c["name"])
            elif isinstance(c, str):
                cat_names.append(c)

        updated_chunks = []
        if updated_summary and updated_summary.strip():
            try:
                from app.rag.utils.summary_chunker import chunk_summary_markdown
                updated_chunks = chunk_summary_markdown(
                    summary=updated_summary,
                    source_file=file_name,
                    knowledge_id=knowledge_id,
                    batch_id=existing_doc.get("batch_id") if isinstance(existing_doc, dict) else None,
                    file_hash=existing_doc.get("file_hash", "") if isinstance(existing_doc, dict) else "",
                    title=doc_title,
                    doc_type=doc_type or "GENERAL",
                    categories=cat_names,
                    valid_from=str(doc_valid_from).strip() if doc_valid_from else None,
                    valid_until=str(doc_valid_until).strip() if doc_valid_until else None,
                    visibility_settings=vis_settings,
                )
                logger.info(f"Refine Approved: re-chunked summary into {len(updated_chunks)} chunks for re-indexing.")
            except Exception as rechunk_err:
                logger.warning(f"Refine Approved: re-chunking failed, falling back to LLM chunks: {rechunk_err}")
                # Fallback: use LLM chunks with metadata patch
                updated_chunks = parsed_refined.get("chunks", existing_doc.get("chunks", []))
                for chunk in updated_chunks:
                    if isinstance(chunk, dict):
                        if "metadata" not in chunk:
                            chunk["metadata"] = {}
                        chunk["metadata"]["knowledge_id"] = knowledge_id
                        if cat_names:
                            chunk["metadata"]["category"] = cat_names[0]
                            chunk["metadata"]["categories"] = cat_names
                        if doc_type:
                            chunk["metadata"]["document_type"] = doc_type

        approved_doc_structure = {
            "knowledge_id": knowledge_id,
            "batch_id": existing_doc.get("batch_id") if isinstance(existing_doc, dict) else None,
            "file_name": file_name,
            "file_hash": existing_doc.get("file_hash") if isinstance(existing_doc, dict) else None,
            "title": doc_title,
            "status": "Approved",
            "document_type": doc_type,
            "valid_from": doc_valid_from,
            "valid_until": doc_valid_until,
            "summary": updated_summary,
            "image_url": existing_doc.get("image_url") if isinstance(existing_doc, dict) else None,
            "image_urls": existing_doc.get("image_urls", []) if isinstance(existing_doc, dict) else [],
            "batch_summary": existing_doc.get("batch_summary") if isinstance(existing_doc, dict) else None,
            "categories": cat_names,
            "suggested_categories": existing_doc.get("suggested_categories", []) if isinstance(existing_doc, dict) else [],
            "visibility_settings": vis_settings,
            "chunks": updated_chunks
        }
        # If part of a multi-file batch, re-synthesize updated batch executive summary
        batch_id_val = approved_doc_structure.get("batch_id")
        if batch_id_val and llm:
            try:
                b_summary = await synthesize_batch_executive_summary(batch_id_val, llm)
                if b_summary:
                    approved_doc_structure["batch_summary"] = b_summary
            except Exception as b_err:
                logger.warning(f"Could not update batch summary after refine approved: {b_err}")

        with open(approved_file, "w", encoding="utf-8") as f:
            json.dump(approved_doc_structure, f, indent=4, ensure_ascii=False)

        # Sync canonical JSON to MinIO after refine
        try:
            from app.services.storage import upload_canonical_json
            upload_canonical_json(knowledge_id, approved_doc_structure)
        except Exception as canon_err:
            logger.warning(f"Could not sync canonical JSON to MinIO after refine: {canon_err}")

        target_store = (pipeline.vector_store if pipeline and pipeline.vector_store else vector_store)
        if target_store:
            logger.info(f"Re-indexing PGVector for knowledge_id '{knowledge_id}'...")
            target_store.delete_document(knowledge_id)
            target_store.insert_chunks(updated_chunks)

        if bm25:
            logger.info(f"Re-indexing BM25 for knowledge_id '{knowledge_id}'...")
            bm25.remove_file_chunks(knowledge_id)
            bm25.add_chunks(updated_chunks)
            bm25.save(settings.bm25_index_path)

        if target_store and hasattr(target_store, "upsert_knowledge_category"):
            target_store.upsert_knowledge_category(
                knowledge_id=knowledge_id,
                file_name=file_name,
                categories=updated_categories,
                summary=updated_summary
            )

        return approved_doc_structure
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Refine approved document failed for '{knowledge_id}': {e}")
        raise HTTPException(status_code=500, detail=f"Failed to refine approved document: {e}")


@router.post("/ingest/approve/{knowledge_id}", tags=["Ingestion"], summary="Approve Document")
async def approve_document(
    knowledge_id: str = Path(..., description="Document ID(s) to approve (supports single ID or comma-separated list)"),
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
    bm25: BM25Index = Depends(get_bm25_index)
):
    """
    Approves pending staged document(s) and indexes them into vector and BM25 search databases.
    """
    targets = [k.strip() for k in knowledge_id.split(",") if k and k.strip() and k.strip().lower() not in ("string", "all")]

    if not targets:
        raise HTTPException(status_code=400, detail="At least one valid knowledge_id must be provided.")

    approved_results = []
    for target_id in targets:
        pending_file = resolve_pending_file(target_id)
        if not pending_file:
            logger.warning(f"Pending document '{target_id}' not found for approval, skipping.")
            continue
            
        try:
            with open(pending_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            chunks = data.get("chunks", []) if isinstance(data, dict) else data
            k_id = data.get("knowledge_id", target_id) if isinstance(data, dict) else target_id
            file_name = data.get("file_name", target_id) if isinstance(data, dict) else target_id
            doc_title = data.get("title", file_name) if isinstance(data, dict) else file_name
            doc_type = data.get("document_type") if isinstance(data, dict) else None
            doc_valid_from = data.get("valid_from") if isinstance(data, dict) else None
            doc_valid_until = data.get("valid_until") if isinstance(data, dict) else None
            
            # Re-chunk from the LATEST summary (admin may have refined it)
            # This ensures chunks always match the approved summary content
            approve_summary = data.get("summary", "") if isinstance(data, dict) else ""
            raw_cats = data.get("categories") or data.get("suggested_categories") or []
            parsed_cats = []
            if isinstance(raw_cats, list):
                for c in raw_cats:
                    if isinstance(c, dict) and "name" in c:
                        parsed_cats.append(c["name"])
                    elif isinstance(c, str):
                        parsed_cats.append(c)

            vis_settings = data.get("visibility_settings") or {
                "clinics": ["all"],
                "doctor_types": ["all"],
                "doctors": ["all"]
            }

            if approve_summary and approve_summary.strip():
                try:
                    from app.rag.utils.summary_chunker import chunk_summary_markdown
                    chunks = chunk_summary_markdown(
                        summary=approve_summary,
                        source_file=file_name,
                        knowledge_id=k_id,
                        batch_id=data.get("batch_id") if isinstance(data, dict) else None,
                        file_hash=data.get("file_hash", "") if isinstance(data, dict) else "",
                        title=doc_title,
                        doc_type=doc_type or "GENERAL",
                        categories=parsed_cats,
                        valid_from=str(doc_valid_from).strip() if doc_valid_from else None,
                        valid_until=str(doc_valid_until).strip() if doc_valid_until else None,
                        visibility_settings=vis_settings,
                    )
                    logger.info(f"Approve: re-chunked summary into {len(chunks)} structure-aware chunks for indexing.")
                except Exception as rechunk_err:
                    logger.warning(f"Approve: re-chunking failed, using existing chunks: {rechunk_err}")

            if pipeline.vector_store:
                logger.info(f"Indexing chunks for knowledge_id {k_id} into vector store...")
                pipeline.vector_store.insert_chunks(chunks)
            else:
                logger.warning("No vector store instance available for indexing.")
                
            if bm25:
                logger.info(f"Indexing chunks for knowledge_id {k_id} into BM25 index...")
                bm25.add_chunks(chunks)
                bm25.save(settings.bm25_index_path)

            os.makedirs("data/output", exist_ok=True)
            approved_file = os.path.join("data/output", f"{k_id}.json")
            staging_hist = data.get("history", []) if isinstance(data, dict) else []
            initial_prompt_val = data.get("initial_prompt") if isinstance(data, dict) else None

            approved_doc_structure = {
                "knowledge_id": k_id,
                "batch_id": data.get("batch_id") if isinstance(data, dict) else None,
                "file_name": file_name,
                "file_hash": data.get("file_hash") if isinstance(data, dict) else None,
                "title": doc_title,
                "status": "Approved",
                "document_type": doc_type,
                "summary": approve_summary,
                "image_urls": data.get("image_urls", []) if isinstance(data, dict) else [],
                "batch_summary": data.get("batch_summary") if isinstance(data, dict) else None,
                "initial_prompt": initial_prompt_val,
                "staging_history": staging_hist,
                "history": [],
                "categories": parsed_cats,
                "suggested_categories": raw_cats,
                "visibility_settings": vis_settings,
                "chunks": chunks
            }
            with open(approved_file, "w", encoding="utf-8") as f:
                json.dump(approved_doc_structure, f, indent=4, ensure_ascii=False)
                
            if os.path.exists(pending_file):
                os.remove(pending_file)

            # Upload canonical JSON to MinIO knowledge-documents bucket
            try:
                from app.services.storage import upload_canonical_json
                canon_result = upload_canonical_json(k_id, approved_doc_structure)
                if canon_result.get("status") == "success":
                    logger.info(f"📋 Canonical JSON uploaded to MinIO for '{k_id}': {canon_result['s3_key']}")
            except Exception as canon_err:
                logger.warning(f"Could not upload canonical JSON to MinIO for '{k_id}': {canon_err}")
                
            # Dual-sync update to Knowledge DB table
            try:
                from app.core.database import AsyncSessionLocal
                from app.models.knowledge import Knowledge, KnowledgeStatus
                from sqlalchemy import select
                import uuid as _uuid
                async with AsyncSessionLocal() as session:
                    try:
                        k_uuid = _uuid.UUID(k_id)
                        stmt_k = select(Knowledge).where(Knowledge.id == k_uuid, Knowledge.deleted_at.is_(None))
                    except ValueError:
                        stmt_k = select(Knowledge).where(Knowledge.file_name.ilike(f"%{file_name}%"), Knowledge.deleted_at.is_(None))
                    res_k = await session.execute(stmt_k)
                    k_entry = res_k.scalars().first()
                    if k_entry:
                        k_entry.status = KnowledgeStatus.APPROVED
                        if k_entry.metadata_ is None:
                            k_entry.metadata_ = {}
                        if staging_hist:
                            k_entry.metadata_["staging_history"] = staging_hist
                        k_entry.metadata_["history"] = []
                        k_entry.metadata_["chat_history"] = []
                        if initial_prompt_val:
                            k_entry.metadata_["initial_prompt"] = initial_prompt_val
                        from sqlalchemy.orm.attributes import flag_modified
                        flag_modified(k_entry, "metadata_")
                        await session.commit()
            except Exception as db_err:
                logger.warning(f"Could not dual-sync approved status to Knowledge DB table for {k_id}: {db_err}")

            approved_results.append(k_id)
        except Exception as e:
            logger.error(f"Approval failed for document '{target_id}': {e}")

    return {
        "status": "success", 
        "message": f"Successfully approved {len(approved_results)} document(s).", 
        "approved_ids": approved_results
    }


@router.delete("/ingest/documents/{knowledge_id}", tags=["Ingestion"], summary="Delete Document Endpoint")
async def delete_document_endpoint(
    knowledge_id: str = Path(..., description="Document ID(s) to delete (supports single ID, comma-separated list, or 'all')"),
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
    bm25: BM25Index = Depends(get_bm25_index),
    vector_store: BaseVectorStoreAdapter = Depends(get_vector_store)
):
    """
    Deletes document(s) from Knowledge Base and vector search index (supports single ID, comma-separated IDs, or 'all').
    """
    raw_targets = [k.strip() for k in knowledge_id.split(",") if k and k.strip() and k.strip().lower() != "string"]
    if not raw_targets:
        raise HTTPException(status_code=400, detail="At least one valid knowledge_id must be provided.")

    target_store = (pipeline.vector_store if pipeline and pipeline.vector_store else vector_store)
    deleted_ids = []

    # If user passes 'all', delegate to reset
    if any(t.lower() == "all" for t in raw_targets):
        await reset_database(vector_store=target_store, bm25=bm25)
        return {"status": "success", "message": "Successfully deleted all documents.", "deleted_ids": ["all"]}

    pending_dir = "data/pending"
    approved_dir = "data/output"

    for k_id in raw_targets:
        was_deleted = False

        # 1. Scan JSON files in pending and output by knowledge_id OR file_name
        for folder in [pending_dir, approved_dir]:
            if os.path.exists(folder):
                for f in os.listdir(folder):
                    if f.endswith(".json"):
                        f_path = os.path.join(folder, f)
                        try:
                            with open(f_path, "r", encoding="utf-8") as fp:
                                f_data = json.load(fp)
                            doc_id = str(f_data.get("knowledge_id", "")) if isinstance(f_data, dict) else ""
                            doc_name = str(f_data.get("file_name", "")) if isinstance(f_data, dict) else ""
                            f_no_ext = f.replace(".json", "").replace("_parsed", "")

                            if k_id in (doc_id, doc_name, f_no_ext, f) or k_id.lower() in doc_name.lower():
                                os.remove(f_path)
                                if target_store:
                                    target_store.delete_document(doc_id or f_no_ext)
                                if bm25:
                                    bm25.remove_file_chunks(doc_id or f_no_ext)
                                    bm25.save(settings.bm25_index_path)
                                was_deleted = True
                                logger.info(f"Deleted JSON file and vectors for '{k_id}' ({f_path})")
                        except Exception as file_err:
                            logger.warning(f"Error checking/deleting file {f}: {file_err}")

        # 2. Soft-delete in PostgreSQL Knowledge DB table
        try:
            from app.core.database import AsyncSessionLocal
            from app.models.knowledge import Knowledge
            from sqlalchemy import select, func, or_
            import uuid as _uuid

            async with AsyncSessionLocal() as session:
                custom_uuid = None
                try:
                    custom_uuid = _uuid.UUID(k_id)
                except ValueError:
                    pass

                if custom_uuid:
                    stmt = select(Knowledge).where(
                        or_(Knowledge.id == custom_uuid, Knowledge.file_name.ilike(f"%{k_id}%")),
                        Knowledge.deleted_at.is_(None)
                    )
                else:
                    stmt = select(Knowledge).where(
                        or_(Knowledge.file_name.ilike(f"%{k_id}%"), Knowledge.title.ilike(f"%{k_id}%")),
                        Knowledge.deleted_at.is_(None)
                    )

                res = await session.execute(stmt)
                db_docs = res.scalars().all()
                
                # Fallback: scan all non-deleted records if still not found
                if not db_docs:
                    all_res = await session.execute(select(Knowledge).where(Knowledge.deleted_at.is_(None)))
                    all_docs = all_res.scalars().all()
                    db_docs = [d for d in all_docs if str(d.id).lower() == k_id.lower() or (d.file_name and k_id.lower() in d.file_name.lower())]

                for d_doc in db_docs:
                    d_doc.deleted_at = func.now()
                if db_docs:
                    await session.commit()
                    was_deleted = True
                    logger.info(f"Soft-deleted {len(db_docs)} record(s) in PostgreSQL Knowledge DB for '{k_id}'")
        except Exception as db_err:
            logger.warning(f"Could not soft-delete Knowledge DB record for '{k_id}': {db_err}")

        if was_deleted:
            deleted_ids.append(k_id)

    return {"status": "success", "message": f"Successfully deleted {len(deleted_ids)} document(s).", "deleted_ids": deleted_ids}




async def run_chat_pipeline(
    query: str,
    file: Optional[UploadFile] = None,
    attachment_text: Optional[str] = None,
    doctor_name: Optional[str] = None,
    history: Optional[List[Any]] = None,
    user_context: Optional[UserContext] = None,
    knowledge_id: Optional[str] = None,
    batch_id: Optional[str] = None,
    categories: Optional[List[str]] = None,
    top_k: int = 8,
    pipeline: GenerationPipeline = None
) -> ChatResponse:
    if not pipeline:
        raise HTTPException(status_code=500, detail="Generation pipeline is not initialized.")

    # 1. Extract text from uploaded file if present
    file_attachment_text = attachment_text
    if file and hasattr(file, "read"):
        try:
            from app.rag.services.attachment_parser import AttachmentParser
            parser = AttachmentParser()
            extracted_text, attach_meta = await parser.extract_from_upload(file)
            if extracted_text and not extracted_text.startswith("[Error") and not extracted_text.startswith("[Dokumen tidak"):
                file_name_str = getattr(file, "filename", "File Terlampir")
                file_attachment_text = f"[Dokumen Pasien Terlampir: {file_name_str}]\n{extracted_text.strip()}"
                logger.info(
                    f"📎 [ChatPipeline] Extracted {attach_meta.get('chars', 0)} chars "
                    f"from '{file_name_str}' via {attach_meta.get('method', '?')} "
                    f"in {attach_meta.get('extraction_ms', 0)}ms"
                )
        except Exception as e:
            logger.error(f"❌ [ChatPipeline] AttachmentParser failed: {e}")

    # 2. Build effective query with attachment text
    effective_query = query
    if file_attachment_text:
        effective_query = (
            f"{query}\n\n"
            f"--- DOKUMEN PASIEN TERLAMPIR ---\n"
            f"{file_attachment_text}"
        )

    # 3. Format history
    raw_history = []
    if history:
        for msg in history:
            if isinstance(msg, dict):
                r = msg.get("role", "")
                c = msg.get("content", "")
            else:
                r = getattr(msg, "role", "")
                c = getattr(msg, "content", "")
            if r and c:
                raw_history.append({"role": r, "content": c})

    # 4. Build metadata filter for RBAC & Scope
    filter_metadata = {}
    if categories:
        valid_cats = [c.strip() for c in categories if c and c.strip().lower() not in ("string", "")]
        if valid_cats:
            filter_metadata["categories"] = valid_cats

    if knowledge_id:
        filter_metadata["knowledge_id"] = str(knowledge_id)
    if batch_id:
        filter_metadata["batch_id"] = str(batch_id)

    if user_context:
        filter_metadata["clinics"] = user_context.branch_ids + ["all"]
        filter_metadata["doctor_types"] = [user_context.dr_type, "all"]
        filter_metadata["doctors"] = [user_context.user_id, "all"]
        if user_context.excluded_categories:
            filter_metadata["excluded_categories"] = user_context.excluded_categories

    parsed_filter = filter_metadata if filter_metadata else None

    # Doctor name for greeting
    doc_name = doctor_name
    if not doc_name and user_context and getattr(user_context, "doctor_name", None):
        doc_name = user_context.doctor_name

    # Check pending document context if knowledge_id is unapproved
    pending_doc_context = None
    if knowledge_id:
        k_id_str = str(knowledge_id)
        p_path = os.path.join("data/pending", f"{k_id_str}.json")
        if not os.path.exists(p_path):
            p_path = os.path.join("data/pending", f"{k_id_str}_parsed.json")
        if os.path.exists(p_path):
            try:
                with open(p_path, "r", encoding="utf-8") as pf:
                    p_json = json.load(pf)
                if isinstance(p_json, dict):
                    p_summary = p_json.get("summary", "")
                    p_chunks = p_json.get("chunks", [])
                    ctx_parts = []
                    if p_summary:
                        ctx_parts.append(f"### DOKUMEN: {p_json.get('title', k_id_str)}\n{p_summary}")
                    for c in p_chunks[:top_k]:
                        c_txt = c.get("text", "") if isinstance(c, dict) else str(c)
                        if c_txt and c_txt not in p_summary:
                            ctx_parts.append(c_txt)
                    if ctx_parts:
                        pending_doc_context = "\n\n---\n\n".join(ctx_parts)
            except Exception as pe:
                logger.warning(f"Could not load pending doc context: {pe}")

    try:
        if pending_doc_context:
            system_prompt = getattr(pipeline, "system_prompt", "")
            preview_prompt = f"""
            {system_prompt}

            Context Dokumen yang Sedang Ditinjau:
            {pending_doc_context}

            Pertanyaan Pengguna:
            {effective_query}
            """
            llm_adapter = getattr(pipeline, "llm_adapter", None)
            if llm_adapter:
                preview_answer = await asyncio.to_thread(llm_adapter.generate, preview_prompt)
                return ChatResponse(
                    query=query,
                    answer=preview_answer.strip(),
                    context=pending_doc_context[:2000],
                    results=[{"text": pending_doc_context[:500], "score": 1.0, "metadata": {"knowledge_id": knowledge_id, "status": "On review"}}],
                    agent_used=False
                )

        response = pipeline.generate_answer(
            query=effective_query,
            top_k=top_k,
            filter_metadata=parsed_filter,
            rerank=False,
            history=raw_history,
            doctor_name=doc_name
        )

        if isinstance(response, ChatResponse):
            return response
        elif isinstance(response, dict):
            return ChatResponse(
                query=response.get("query", query),
                answer=response.get("answer", ""),
                context=response.get("context", ""),
                results=response.get("results", []),
                agent_used=response.get("agent_used", False)
            )
        return response

    except Exception as e:
        logger.error(f"Unified Chat generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat", response_model=ChatResponse, tags=["Generation"], summary="Chat Endpoint")
async def chat_endpoint(
    request: Request,
    prompt: Optional[str] = Form(
        None, 
        description="Clinical query or medical instruction from doctor"
    ),
    file: Optional[UploadFile] = File(
        None, 
        description="Optional patient medical record / profile document attachment (PDF, DOCX, XLSX, TXT, JPG, PNG)"
    ),
    doctor_name: Optional[str] = Form(
        None, 
        description="Optional doctor name for personalized greeting"
    ),
    pipeline: GenerationPipeline = Depends(get_generation_pipeline)
):
    """
    Unified RAG Chatbot endpoint for clinical medical queries and optional patient document attachment.
    """
    try:
        content_type = request.headers.get("content-type", "") if hasattr(request, "headers") else ""

        # Mode 1: JSON Body (application/json)
        if "application/json" in content_type:
            try:
                body = await request.json()
                q_str = body.get("prompt") or body.get("query") or ""
                if not q_str:
                    raise HTTPException(status_code=400, detail="Field 'prompt' or 'query' is required in JSON body.")

                return await run_chat_pipeline(
                    query=q_str,
                    attachment_text=body.get("attachment_text"),
                    doctor_name=body.get("doctor_name") or doctor_name,
                    history=body.get("history"),
                    categories=body.get("categories"),
                    top_k=body.get("top_k", 8),
                    knowledge_id=body.get("knowledge_id"),
                    batch_id=body.get("batch_id"),
                    pipeline=pipeline
                )
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid JSON body: {e}")

        # Mode 2: Form Data / Swagger UI
        else:
            if not prompt:
                raise HTTPException(status_code=400, detail="Field 'prompt' is required.")

            return await run_chat_pipeline(
                query=prompt,
                file=file,
                doctor_name=doctor_name,
                pipeline=pipeline
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unified Chat generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# EVALUATION ENDPOINT (Automated RAGAS Benchmark & Developer Quality Monitoring)
# =============================================================================

@router.post(
    "/evaluation", 
    response_model=RAGEvaluationResponse, 
    tags=["Evaluation"], 
    summary="Run RAG Evaluation Benchmark"
)
async def run_rag_evaluation(
    payload: Optional[Union[RAGEvaluationRequest, List[RAGEvaluationItem], List[Dict[str, Any]], Dict[str, Any]]] = Body(
        default=None,
        description="Benchmark configuration or test dataset list (leave empty {} or null for default benchmark suite)"
    ),
    retriever: HybridRetriever = Depends(get_hybrid_retriever),
    pipeline: GenerationPipeline = Depends(get_generation_pipeline),
    llm: BaseLLMAdapter = Depends(get_llm)
):
    """
    Evaluates retrieval accuracy (Hit Rate@K, MRR@K) and LLM reliability (Faithfulness, Answer Relevance) using RAGAS Framework.
    """
    parsed_dataset = None
    parsed_top_k = 5
    parsed_eval_gen = True

    if payload is not None:
        if isinstance(payload, RAGEvaluationRequest):
            if payload.dataset:
                parsed_dataset = [d.model_dump() for d in payload.dataset]
        elif isinstance(payload, list):
            parsed_dataset = []
            for item in payload:
                if isinstance(item, RAGEvaluationItem):
                    parsed_dataset.append(item.model_dump())
                elif isinstance(item, dict):
                    d_item = dict(item)
                    if "expected_file" in d_item and "expected_document" not in d_item:
                        d_item["expected_document"] = d_item["expected_file"]
                    parsed_dataset.append(d_item)
        elif isinstance(payload, dict):
            if "dataset" in payload and isinstance(payload["dataset"], list):
                parsed_dataset = []
                for item in payload["dataset"]:
                    if isinstance(item, dict):
                        d_item = dict(item)
                        if "expected_file" in d_item and "expected_document" not in d_item:
                            d_item["expected_document"] = d_item["expected_file"]
                        parsed_dataset.append(d_item)
                    else:
                        parsed_dataset.append(item)

    try:
        results = RAGEvaluator.evaluate_full(
            retriever=retriever,
            generation_pipeline=pipeline,
            llm_adapter=llm,
            dataset=parsed_dataset,
            top_k=parsed_top_k,
            rerank=True,
            rerank_top_n=3,
            evaluate_generation=parsed_eval_gen
        )
        return RAGEvaluationResponse(**results)
    except Exception as e:
        logger.error(f"RAG evaluation benchmark failed: {e}")
        raise HTTPException(status_code=500, detail=f"RAG evaluation benchmark failed: {str(e)}")


# =============================================================================
# QUERY GENERAL ENDPOINT (Knowledge Base Explorer, Editor & Deletion via Prompt)
# Akses tergantung RBAC role dari CIS. System prompt dari AppConfig DB.
# =============================================================================

class QueryGeneralRequest(BaseModel):
    """Request schema for Query General endpoint (Simplified: Prompt-only)."""
    prompt: str = Field(
        ..., 
        description="Prompt teks dari user untuk menelusuri (read), mengedit (update), atau menghapus (delete) dokumen KB",
        example="Apakah ada produk ERHA Age Corrector di database?"
    )
    history: List[dict] = Field(
        default=[], 
        description="Riwayat percakapan sebelumnya (opsional)"
    )

    @model_validator(mode="before")
    @classmethod
    def handle_query_alias(cls, values):
        if isinstance(values, dict):
            # Backward-compatibility: if client sent 'query' instead of 'prompt', map it
            if "prompt" not in values and "query" in values:
                values["prompt"] = values["query"]
        return values

class QueryGeneralResponse(BaseModel):
    """Response schema for Query General endpoint."""
    prompt: str = Field(..., description="Prompt yang dikirimkan user")
    answer: str = Field(..., description="Jawaban dan konfirmasi dari AI")
    action: str = Field("read", description="Aksi yang dijalankan: 'read', 'edit_applied', 'delete_applied'")
    target_knowledge_id: Optional[str] = Field(None, description="ID dokumen yang diproses (jika ada update/delete)")
    total_found: int = Field(0, description="Jumlah data relevan yang ditemukan di KB")
    results: List[Dict[str, Any]] = Field(default=[], description="Potongan knowledge base yang ditemukan")

def _extract_kb_action(llm_answer: str) -> Optional[Dict[str, Any]]:
    """
    Parses the LLM response to extract a JSON action block.
    Supports 2-step action lifecycle: edit_preview, edit_execute, delete_preview, delete_execute, edit, delete, cancel.
    """
    import re as _re
    pattern = r'```json\s*\n?\s*(\{[^`]+?\})\s*\n?\s*```'
    matches = _re.findall(pattern, llm_answer, _re.DOTALL)
    
    for match in matches:
        try:
            parsed = json.loads(match.strip())
            if isinstance(parsed, dict):
                action = parsed.get("action")
                if action in ("edit_preview", "edit_execute", "edit", "delete_preview", "delete_execute", "delete", "cancel"):
                    return parsed
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _apply_kb_edit(
    knowledge_id: str,
    field: str,
    new_value: str,
    vector_store,
    bm25_index
) -> Dict[str, Any]:
    """
    Applies an edit for ANY topic/field to a KB document (approved or pending) and re-indexes.
    Preserves all other fields, metadata, and document summaries 100% intact.
    Automatically synchronizes chunk text content for vector & BM25 search.
    """
    target_file = resolve_approved_file(knowledge_id) or resolve_pending_file(knowledge_id)
    if not target_file:
        return {"success": False, "error": f"Dokumen dengan ID/Nama '{knowledge_id}' tidak ditemukan di Knowledge Base."}

    try:
        with open(target_file, "r", encoding="utf-8") as f:
            existing_doc = json.load(f)

        doc_kid = str(existing_doc.get("knowledge_id") or knowledge_id)
        old_value = None
        clean_field = (field or "").strip().lower()
        formatted_val = str(new_value).strip()

        # Update root document JSON fields while preserving summary & other attributes
        if clean_field in ("price", "harga", "biaya"):
            old_value = existing_doc.get("price") or existing_doc.get("metadata", {}).get("price")
            existing_doc["price"] = formatted_val
            if "metadata" not in existing_doc or not isinstance(existing_doc["metadata"], dict):
                existing_doc["metadata"] = {}
            existing_doc["metadata"]["price"] = formatted_val

        elif clean_field in ("summary", "deskripsi", "ringkasan"):
            # Protect summary: Do not overwrite summary with AI chatbot conversational confirmation text
            conv_phrases = ["berhasil diubah", "berhasil diperbarui", "telah diubah", "telah diperbarui", "berhasil diterapkan", "berhasil dihapus"]
            if any(phrase in formatted_val.lower() for phrase in conv_phrases):
                logger.warning(f"[QUERY-GENERAL] Rejected chatbot conversational response as summary value: {formatted_val}")
                return {"success": False, "error": "Value summary tidak boleh berupa kalimat konfirmasi percakapan chatbot."}
            old_value = existing_doc.get("summary", "")
            existing_doc["summary"] = formatted_val

        elif clean_field in ("title", "nama", "nama_produk"):
            old_value = existing_doc.get("title", existing_doc.get("file_name", ""))
            existing_doc["title"] = formatted_val

        elif clean_field in ("valid_until", "expiry_date", "end_date", "periode", "masa_berlaku"):
            old_value = existing_doc.get("valid_until")
            existing_doc["valid_until"] = formatted_val

        elif clean_field in ("valid_from", "start_date"):
            old_value = existing_doc.get("valid_from")
            existing_doc["valid_from"] = formatted_val

        elif clean_field in ("document_type", "tipe", "jenis_dokumen"):
            old_value = existing_doc.get("document_type")
            existing_doc["document_type"] = formatted_val

        elif clean_field in ("categories", "kategori"):
            old_value = existing_doc.get("categories", [])
            try:
                parsed_cats = json.loads(new_value) if isinstance(new_value, str) else new_value
                if isinstance(parsed_cats, list):
                    existing_doc["categories"] = parsed_cats
                else:
                    existing_doc["categories"] = [str(parsed_cats)]
            except (json.JSONDecodeError, ValueError):
                existing_doc["categories"] = [formatted_val]

        else:
            # Universal fallback for ANY custom topic/field requested by admin/dept functional
            old_value = existing_doc.get(clean_field) or existing_doc.get("metadata", {}).get(clean_field)
            existing_doc[clean_field] = formatted_val
            if "metadata" not in existing_doc or not isinstance(existing_doc["metadata"], dict):
                existing_doc["metadata"] = {}
            existing_doc["metadata"][clean_field] = formatted_val

        chunks = existing_doc.get("chunks", [])
        primary_cat = existing_doc.get("categories", [None])[0] if existing_doc.get("categories") else None
        import re as _re

        for chunk in chunks:
            if isinstance(chunk, dict):
                if "metadata" not in chunk:
                    chunk["metadata"] = {}
                chunk["metadata"]["knowledge_id"] = doc_kid

                # Universal metadata assignment for the target field
                chunk["metadata"][clean_field] = formatted_val

                # Specific chunk text updates for maximum search synchronization
                chunk_text = chunk.get("text", "")
                if chunk_text:
                    if clean_field in ("price", "harga", "biaya"):
                        price_pattern = r'((?:Harga|Price|Biaya):\s*)(?:Rp\.?\s*)?[\d\.\,\-]+'
                        if _re.search(price_pattern, chunk_text, _re.IGNORECASE):
                            chunk["text"] = _re.sub(price_pattern, rf'\g<1>Rp {formatted_val}', chunk_text, flags=_re.IGNORECASE)
                        else:
                            chunk["text"] = chunk_text.strip() + f"\n- **Harga**: Rp {formatted_val}"

                    elif clean_field in ("title", "nama", "nama_produk"):
                        chunk["metadata"]["source_file"] = formatted_val
                        chunk["metadata"]["title"] = formatted_val
                        chunk["metadata"]["product_name"] = formatted_val
                        if _re.search(r'^(#+\s*)(.+)$', chunk_text, _re.MULTILINE):
                            chunk["text"] = _re.sub(r'^(#+\s*)(.+)$', rf'\g<1>{formatted_val}', chunk_text, count=1, flags=_re.MULTILINE)
                        elif _re.search(r'(Product Name:\s*)(.+)', chunk_text, _re.IGNORECASE):
                            chunk["text"] = _re.sub(r'(Product Name:\s*)(.+)', rf'\g<1>{formatted_val}', chunk_text, count=1, flags=_re.IGNORECASE)

                    elif clean_field in ("valid_until", "expiry_date", "end_date", "periode", "masa_berlaku"):
                        promo_pattern = r'((?:Periode Promo|Valid Until|Berlaku Hingga|Masa Berlaku):\s*)(.+)'
                        if _re.search(promo_pattern, chunk_text, _re.IGNORECASE):
                            chunk["text"] = _re.sub(promo_pattern, rf'\g<1>{formatted_val}', chunk_text, flags=_re.IGNORECASE)
                        else:
                            chunk["text"] = chunk_text.strip() + f"\n- **Berlaku Hingga**: {formatted_val}"

                    elif clean_field in ("ingredients", "kandungan", "bahan_aktif", "komposisi"):
                        ing_pattern = r'((?:Key Ingredients|Kandungan Aktif|Bahan Aktif|Komposisi):\s*)(.+)'
                        if _re.search(ing_pattern, chunk_text, _re.IGNORECASE):
                            chunk["text"] = _re.sub(ing_pattern, rf'\g<1>{formatted_val}', chunk_text, flags=_re.IGNORECASE)
                        else:
                            chunk["text"] = chunk_text.strip() + f"\n- **Kandungan Aktif**: {formatted_val}"

                    elif clean_field in ("how_to_use", "cara_pakai", "aturan_pakai", "dosis"):
                        use_pattern = r'((?:How to Use|Cara Pakai|Aturan Pakai|Dosis):\s*)(.+)'
                        if _re.search(use_pattern, chunk_text, _re.IGNORECASE):
                            chunk["text"] = _re.sub(use_pattern, rf'\g<1>{formatted_val}', chunk_text, flags=_re.IGNORECASE)
                        else:
                            chunk["text"] = chunk_text.strip() + f"\n- **Cara Pakai**: {formatted_val}"

                    elif clean_field in ("suitable_for", "indikasi", "cocok_untuk"):
                        ind_pattern = r'((?:Suitable For|Indikasi|Diperuntukkan):\s*)(.+)'
                        if _re.search(ind_pattern, chunk_text, _re.IGNORECASE):
                            chunk["text"] = _re.sub(ind_pattern, rf'\g<1>{formatted_val}', chunk_text, flags=_re.IGNORECASE)
                        else:
                            chunk["text"] = chunk_text.strip() + f"\n- **Indikasi**: {formatted_val}"

                    elif clean_field in ("summary", "deskripsi", "ringkasan"):
                        chunk["metadata"]["summary"] = formatted_val

                if primary_cat:
                    chunk["metadata"]["category"] = primary_cat
                if existing_doc.get("categories"):
                    chunk["metadata"]["categories"] = existing_doc["categories"]

        with open(target_file, "w", encoding="utf-8") as f:
            json.dump(existing_doc, f, indent=4, ensure_ascii=False)

        if vector_store:
            logger.info(f"[QUERY-GENERAL] Re-indexing PGVector for '{doc_kid}'...")
            vector_store.delete_document(doc_kid)
            vector_store.insert_chunks(chunks)

        if bm25_index:
            logger.info(f"[QUERY-GENERAL] Re-indexing BM25 for '{doc_kid}'...")
            bm25_index.remove_file_chunks(doc_kid)
            bm25_index.add_chunks(chunks)
            bm25_index.save(settings.bm25_index_path)

        if vector_store and hasattr(vector_store, "upsert_knowledge_category"):
            vector_store.upsert_knowledge_category(
                knowledge_id=doc_kid,
                file_name=existing_doc.get("title", existing_doc.get("file_name", doc_kid)),
                categories=existing_doc.get("categories", []),
                summary=existing_doc.get("summary", "")
            )

        logger.info(f"[QUERY-GENERAL] Successfully edited '{doc_kid}' field='{field}'")
        return {
            "success": True,
            "knowledge_id": doc_kid,
            "field": field,
            "old_value": str(old_value)[:200] if old_value else None,
            "new_value": str(new_value)[:200]
        }

    except Exception as e:
        logger.error(f"[QUERY-GENERAL] Failed to apply edit for '{knowledge_id}': {e}")
        return {"success": False, "error": str(e)}

def _apply_kb_delete(
    knowledge_id: str,
    vector_store,
    bm25_index
) -> Dict[str, Any]:
    """
    Deletes a KB document (approved or pending), removes JSON files, clears PGVector & BM25 indices,
    soft-deletes PostgreSQL DB record, and cleans MinIO files.
    """
    pending_dir = "data/pending"
    approved_dir = "data/output"
    was_deleted = False
    deleted_title = None
    target_kid = knowledge_id

    clean_target = (knowledge_id or "").strip().lower()

    # 1. Batch Delete Expired Promos if requested
    if clean_target in ("expired", "expired_promos", "promo_expired", "promo expired", "promo bulan lalu", "semua promo expired", "promo yang sudah expired"):
        from datetime import datetime, timezone
        from app.rag.services.rag_retriever import parse_date_safely
        today = datetime.now(timezone.utc).date()
        deleted_items = []

        for folder in [pending_dir, approved_dir]:
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
                                was_deleted = True
                                logger.info(f"[QUERY-GENERAL] Deleted expired promo file: {doc_title} ({f_path})")
                        except Exception as err:
                            logger.warning(f"[QUERY-GENERAL] Error checking file {f} for expiry deletion: {err}")

        if bm25_index and deleted_items:
            bm25_index.save(settings.bm25_index_path)

        if deleted_items:
            return {
                "success": True,
                "knowledge_id": "expired_promos",
                "title": f"{len(deleted_items)} Promo Expired Dihapus: {'; '.join(deleted_items)}"
            }
        else:
            return {
                "success": True,
                "knowledge_id": "none",
                "title": "Tidak ada dokumen promo expired yang ditemukan di basis pengetahuan."
            }

    # 2. Regular Single/Specific Document Deletion (Search pending and approved)
    for folder in [pending_dir, approved_dir]:
        if os.path.exists(folder):
            for f in os.listdir(folder):
                if f.endswith(".json") and f != "bm25_index.pkl":
                    f_path = os.path.join(folder, f)
                    try:
                        with open(f_path, "r", encoding="utf-8") as fp:
                            f_data = json.load(fp)
                        doc_id = str(f_data.get("knowledge_id", "")).strip().lower() if isinstance(f_data, dict) else ""
                        doc_title = str(f_data.get("title", f_data.get("file_name", ""))) if isinstance(f_data, dict) else ""
                        f_no_ext = f.replace(".json", "").replace("_parsed", "").lower()

                        if clean_target in (doc_id, f_no_ext, f.lower(), doc_title.lower()) or (doc_title and clean_target in doc_title.lower()):
                            os.remove(f_path)
                            was_deleted = True
                            deleted_title = doc_title or f
                            target_kid = f_data.get("knowledge_id") or knowledge_id
                            logger.info(f"[QUERY-GENERAL] Deleted JSON file {f_path} for knowledge_id='{target_kid}'")
                    except Exception as err:
                        logger.warning(f"[QUERY-GENERAL] Error checking file {f}: {err}")

    if vector_store:
        try:
            vector_store.delete_document(target_kid)
            logger.info(f"[QUERY-GENERAL] Deleted PGVector embeddings for '{target_kid}'")
        except Exception as e:
            logger.warning(f"[QUERY-GENERAL] Vector store delete error for '{target_kid}': {e}")

    if bm25_index:
        try:
            bm25_index.remove_file_chunks(target_kid)
            bm25_index.save(settings.bm25_index_path)
            logger.info(f"[QUERY-GENERAL] Removed BM25 chunks for '{target_kid}'")
        except Exception as e:
            logger.warning(f"[QUERY-GENERAL] BM25 delete error for '{target_kid}': {e}")

    # 5. Soft-delete PostgreSQL Knowledge DB record
    try:
        from app.core.database import AsyncSessionLocal
        from app.models.knowledge import Knowledge
        from sqlalchemy import select, func
        import uuid as _uuid
        import asyncio

        async def _soft_delete_db():
            async with AsyncSessionLocal() as session:
                custom_uuid = None
                try:
                    custom_uuid = _uuid.UUID(target_kid)
                except ValueError:
                    pass
                k_rec = None
                if custom_uuid:
                    k_rec = await session.get(Knowledge, custom_uuid)
                else:
                    res = await session.execute(select(Knowledge).where(Knowledge.file_name == target_kid).order_by(Knowledge.created_at.desc()))
                    k_rec = res.scalars().first()

                if k_rec:
                    k_rec.deleted_at = func.now()
                    await session.commit()
                    logger.info(f"[QUERY-GENERAL] Soft-deleted Knowledge DB record '{target_kid}'")

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_soft_delete_db())
            else:
                loop.run_until_complete(_soft_delete_db())
        except Exception:
            asyncio.run(_soft_delete_db())
    except Exception as db_err:
        logger.warning(f"[QUERY-GENERAL] DB soft delete error for '{target_kid}': {db_err}")

    if was_deleted:
        return {"success": True, "knowledge_id": target_kid, "title": deleted_title}
    return {"success": False, "error": f"Dokumen dengan ID/Nama '{knowledge_id}' tidak ditemukan di database."}



async def _resolve_query_general_prompt(db_session) -> str:
    """
    Resolves the system prompt for Query General:
    1. AppConfig DB key: AI_PROMPT_QUERY_GENERAL (admin-configurable via CIS)
    2. DEFAULT_QUERY_GENERAL_PROMPT (hardcoded fallback)
    """
    try:
        from app.models.config import AppConfig
        from sqlalchemy import select
        stmt = select(AppConfig.value).where(AppConfig.key == "AI_PROMPT_QUERY_GENERAL")
        result = await db_session.execute(stmt)
        db_prompt = result.scalar_one_or_none()
        if db_prompt and db_prompt.strip():
            return db_prompt.strip()
    except Exception as e:
        logger.warning(f"[QUERY-GENERAL] Failed to fetch system prompt from DB: {e}")

    from app.rag.services.rag_generator import DEFAULT_QUERY_GENERAL_PROMPT
    return DEFAULT_QUERY_GENERAL_PROMPT


@router.post("/query-general", response_model=QueryGeneralResponse, tags=["Query General"], summary="Query General Endpoint")
async def query_general_endpoint(
    request: QueryGeneralRequest,
    pipeline: GenerationPipeline = Depends(get_generation_pipeline),
    vector_store: BaseVectorStoreAdapter = Depends(get_vector_store),
    bm25: BM25Index = Depends(get_bm25_index)
):
    """
    Interactively explores, edits, or deletes knowledge base documents using natural language prompt instructions.
    """
    if not pipeline:
        raise HTTPException(status_code=500, detail="Generation pipeline is not initialized.")

    try:
        user_prompt = request.prompt

        # 0. Resolve system prompt from DB (or fallback)
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db_session:
            system_prompt = await _resolve_query_general_prompt(db_session)

        # 1. Retrieve from KB without filters (admin/user sees all approved data, including expired promos for exploration)
        search_query = GenerationPipeline.contextualize_retrieval_query(user_prompt, request.history)

        retrieval_response = pipeline.retriever.retrieve(
            query=search_query,
            top_k=10,
            filter_metadata=None,
            rerank=False,
            include_expired=True
        )

        results = retrieval_response.get("results", [])
        context = retrieval_response.get("context", "")

        is_context_empty = (
            not results
            or context in ("Maaf, saya tidak menemukan informasi.", "No relevant context found.")
            or len(context.strip()) == 0
        )

        context_for_prompt = context if not is_context_empty else "(Tidak ada dokumen yang ditemukan di Knowledge Base untuk kueri ini.)"

        # 2. Check for Pending Confirmation from Previous Conversation History
        target_vs = (pipeline.retriever.vector_store if pipeline.retriever and hasattr(pipeline.retriever, 'vector_store') else vector_store)
        target_bm25 = (pipeline.retriever.bm25_index if pipeline.retriever and hasattr(pipeline.retriever, 'bm25_index') else bm25)

        clean_user_prompt = user_prompt.strip().lower()
        last_preview_action = None
        if request.history and len(request.history) >= 1:
            last_msg = request.history[-1]
            if last_msg.get("role") in ("assistant", "Assistant"):
                last_preview_action = _extract_kb_action(last_msg.get("content", ""))

        is_affirmative = any(word in clean_user_prompt for word in ["ya", "setuju", "ok", "oke", "lanjut", "terapkan", "hapus", "ya hapus", "ya, hapus"])
        is_negative = any(word in clean_user_prompt for word in ["batal", "tidak", "cancel", "jangan", "ngga", "gak"])

        action_type = "read"
        target_kid = None
        answer = ""

        # CASE A: Confirmation for pending EDIT_PREVIEW
        if last_preview_action and last_preview_action.get("action") in ("edit_preview", "edit") and (is_affirmative or is_negative):
            kid = last_preview_action.get("knowledge_id")
            field = last_preview_action.get("field", "summary")
            new_val = last_preview_action.get("new_value", "")

            if is_affirmative and not is_negative:
                edit_res = _apply_kb_edit(kid, field, new_val, target_vs, target_bm25)
                if edit_res.get("success"):
                    action_type = "edit_executed"
                    target_kid = kid
                    answer = (
                        f"📝 **Perubahan Berhasil Diterapkan!**\n\n"
                        f"Perubahan pada dokumen telah berhasil disimpan dan diindeks secara resmi ke dalam **Basis Data Pengetahuan ERHA**.\n\n"
                        f"- **Dokumen ID**: `{kid}`\n"
                        f"- **Bagian yang Diperbarui**: {field}\n"
                        f"- **Nilai Baru**: {new_val}\n"
                        f"- **Status**: Aktif & Terpublikasi"
                    )
                else:
                    action_type = "edit_failed"
                    answer = f"⚠️ **Gagal menerapkan perubahan pada dokumen**: {edit_res.get('error', 'Terjadi kesalahan sistem.')}"
            else:
                action_type = "cancelled"
                answer = "😊 Baik, perubahan dokumen telah dibatalkan atas permintaan Anda. Tidak ada data yang diubah."

        # CASE B: Confirmation for pending DELETE_PREVIEW
        elif last_preview_action and last_preview_action.get("action") in ("delete_preview", "delete") and (is_affirmative or is_negative):
            kid = last_preview_action.get("knowledge_id")

            if is_affirmative and not is_negative:
                del_res = _apply_kb_delete(kid, target_vs, target_bm25)
                if del_res.get("success"):
                    action_type = "delete_executed"
                    target_kid = kid
                    doc_title = del_res.get("title", kid)
                    answer = (
                        f"🗑️ **Dokumen Berhasil Dihapus!**\n\n"
                        f"Dokumen **'{doc_title}'** telah berhasil dihapus secara permanen dari **Basis Data Pengetahuan ERHA**.\n\n"
                        f"- **Nama Dokumen**: `{doc_title}`\n"
                        f"- **Dokumen ID**: `{kid}`\n"
                        f"- **Status**: Terhapus Bersih (Dokumen, Foto, dan Indikator Pencarian)"
                    )
                else:
                    action_type = "delete_failed"
                    answer = f"⚠️ **Gagal menghapus dokumen**: {del_res.get('error', 'Dokumen tidak ditemukan.')}"
            else:
                action_type = "cancelled"
                answer = "😊 Baik, penghapusan dokumen telah dibatalkan atas permintaan Anda. Dokumen tetap aman tersimpan."

        # CASE C: Normal Prompt Processing via LLM
        else:
            history_str = ""
            if request.history:
                for msg in request.history:
                    role = "User" if msg.get("role") == "user" else "Assistant"
                    content = msg.get("content", "")
                    history_str += f"{role}: {content}\n"
            else:
                history_str = "No previous conversation.\n"

            full_prompt = (
                f"{system_prompt}\n\n"
                f"--- DATA KNOWLEDGE BASE YANG DITEMUKAN ---\n"
                f"{context_for_prompt}\n\n"
                f"--- RIWAYAT PERCAKAPAN ---\n"
                f"{history_str}\n"
                f"User: {user_prompt}\n"
                f"Assistant:"
            )

            import asyncio
            answer = await asyncio.to_thread(pipeline.llm_adapter.generate, full_prompt)

            from app.rag.services.guardrails import OutputGuard
            answer = OutputGuard.redact_pii(answer)

            action_data = _extract_kb_action(answer)
            if action_data:
                act = action_data.get("action")
                kid = action_data.get("knowledge_id")

                if act in ("edit_preview", "edit"):
                    action_type = "edit_preview"
                    target_kid = kid
                elif act in ("delete_preview", "delete"):
                    action_type = "delete_preview"
                    target_kid = kid
                elif act == "cancel":
                    action_type = "cancelled"
                elif act in ("edit_execute", "edit_applied"):
                    action_type = "edit_executed"
                    target_kid = kid
                elif act in ("delete_execute", "delete_applied"):
                    action_type = "delete_executed"
                    target_kid = kid

        logger.info(
            f"[QUERY-GENERAL] prompt='{user_prompt}' | "
            f"action={action_type} | results={len(results)} | answer_len={len(answer)}"
        )

        return QueryGeneralResponse(
            prompt=user_prompt,
            answer=answer,
            action=action_type,
            target_knowledge_id=target_kid,
            total_found=len(results),
            results=results
        )

    except Exception as e:
        logger.error(f"Query General endpoint failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/ingest/reset", tags=["Ingestion"], summary="Reset Database")
async def reset_database(
    vector_store: BaseVectorStoreAdapter = Depends(get_vector_store),
    bm25: BM25Index = Depends(get_bm25_index)
):
    """
    Clears all documents, text chunks, and vector embeddings from the Knowledge Base.
    """
    errors = []
    
    try:
        # 1. Clear vector store
        if vector_store:
            logger.info("Clearing PGVector database...")
            vector_store.clear_all()
        else:
            logger.warning("No vector store instance available for clearing.")
            
        # 2. Clear BM25
        if bm25:
            logger.info("Clearing BM25 index...")
            bm25.clear()
            bm25.save(settings.bm25_index_path)
            
        # 3. Clean files in data/pending/, data/output/, data/temp/ (including images)
        cleanup_extensions = (".json", ".pdf", ".docx", ".doc", ".txt", ".xlsx", ".xls", ".csv", ".pptx", ".ppt", ".jpg", ".jpeg", ".png", ".webp")
        for folder in ["data/pending", "data/output", "data/temp"]:
            if os.path.exists(folder):
                for f in os.listdir(folder):
                    if f.lower().endswith(cleanup_extensions):
                        try:
                            os.remove(os.path.join(folder, f))
                        except Exception as file_err:
                            logger.warning(f"Could not remove file {f}: {file_err}")

        # 3.5. Clear MinIO S3 Object Storage (images & knowledge-documents buckets)
        try:
            from app.services.storage import clear_all_buckets
            minio_res = clear_all_buckets()
            logger.info(f"MinIO bucket reset completed: {minio_res}")
        except Exception as minio_err:
            logger.warning(f"MinIO bucket reset failed: {minio_err}")

        # 4. Soft-delete all records in PostgreSQL Knowledge table (MUST succeed)
        try:
            from app.core.database import AsyncSessionLocal
            from app.models.knowledge import Knowledge
            from sqlalchemy import select, func

            async with AsyncSessionLocal() as session:
                res = await session.execute(select(Knowledge).where(Knowledge.deleted_at.is_(None)))
                k_records = res.scalars().all()
                for k in k_records:
                    k.deleted_at = func.now()
                if k_records:
                    await session.commit()
                    logger.info(f"Soft-deleted {len(k_records)} Knowledge records in PostgreSQL DB.")
        except Exception as db_err:
            error_msg = f"CRITICAL: Failed to soft-delete Knowledge records in PostgreSQL: {db_err}"
            logger.error(error_msg)
            errors.append(error_msg)

        if errors:
            return {
                "status": "partial_success",
                "message": f"Knowledge base partially cleared. {len(errors)} error(s) occurred during reset.",
                "errors": errors
            }
                            
        return {"status": "success", "message": "Knowledge base (PGVector, BM25, staged/approved files, and PostgreSQL Knowledge DB) has been successfully cleared."}
    except Exception as e:
        logger.error(f"Reset database failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))




