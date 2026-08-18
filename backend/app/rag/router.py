import os
import json
import asyncio
from typing import List, Optional, Dict, Any
from loguru import logger
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, BackgroundTasks, Path, Body

import uuid

from app.rag.schemas import (
    ChatRequest, 
    ChatResponse, 
    EvaluationItem,
    DocumentListItem,
    PendingDocumentResponse,
    RefineRequest,
    EditApprovedDocumentRequest,
    ApprovedDocumentResponse,
    RAGEvaluationItem,
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
    for f in os.listdir(approved_dir):
        if f.endswith(".json"):
            full_p = os.path.join(approved_dir, f)
            name_no_ext = f[:-5]
            if f.startswith(knowledge_id) or name_no_ext == knowledge_id or name_no_ext.replace("_parsed", "") == knowledge_id:
                return full_p
            try:
                with open(full_p, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                if isinstance(data, dict) and (data.get("knowledge_id") == knowledge_id or data.get("file_name") == knowledge_id):
                    return full_p
                elif isinstance(data, list) and data:
                    meta = data[0].get("metadata", {})
                    if meta.get("knowledge_id") == knowledge_id or meta.get("source_file") == knowledge_id:
                        return full_p
            except Exception:
                pass
    return None

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
    doc_type_display: str = "Product",
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
                    chunk["metadata"]["type"] = doc_type_display.lower()
                    chunk["metadata"].pop("suggested_categories", None)
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
                "type": doc_type_display,
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
                
            summary = full_extracted_text
            text_accuracy = "100%"
            feedback = f"Dokumen {file_name} telah berhasil diekstrak dan tersimpan di area peninjauan."
            suggested_categories = []
            
            if llm and enriched_chunks:
                t0_llm = _time.time()
                try:
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
                        logger.warning(f"Failed to fetch categories for review prompt: {cat_err}")
                    
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

                    # Build full extracted markdown text from enriched_chunks
                    full_extracted_text = "\n\n".join([c.get("text", "") for c in enriched_chunks if isinstance(c, dict) and c.get("text")])
                    summary = full_extracted_text

                    user_instruction_block = f"""
                    CRITICAL USER CUSTOM INSTRUCTION (HIGHEST PRIORITY):
                    "{user_prompt}"
                    You MUST follow and fulfill the user's custom instruction above (e.g. translate to Indonesian, reformat, highlight specific sections, etc.) when generating the summary.
                    """ if user_prompt and str(user_prompt).strip() else ""

                    review_prompt = f"""
                    You are a world-class AI Knowledge Engineer and Specialist for ERHA (PT Arya Noble) knowledge base.
                    Your task is to refine, validate, and structure the extracted document content into clean, comprehensive, production-grade Markdown matching ChatGPT / Claude standards.

                    Extracted Document Content:
                    {full_extracted_text}

                    Available System Categories:
                    {json.dumps(db_categories, ensure_ascii=False)}

                    {user_instruction_block}

                    FLEXIBLE & COMPREHENSIVE STRUCTURING GUIDELINES:
                    1. **Adaptive Structure for Any Document Type**:
                       - Documents can be of ANY nature (e.g. Skincare/Cosmetics, Treatment Protocols, SOP / Clinic Guidelines, Training Slides / Presentations, Research / Clinical Literature, Price Lists, FAQ, Device/Equipment Guides, etc.).
                       - Dynamically structure the Markdown using clear hierarchical headers (`# [Document Title]`, `## Section`, `### Subsection`), bold key terms (`**`), structured bullet points (`-`), and crisp Markdown tables (`| Col 1 | Col 2 |`) tailored to the document's actual topic.
                    2. **100% Content & Information Preservation**:
                       - ALL key points, steps, specifications, numbers, ingredients/substances, parameters, tables, questions/answers, and details present in the raw text MUST be fully retained and organized.
                       - DO NOT omit, over-condense, or skip substantive sections. Ensure all factual information from the uploaded file is thoroughly represented.
                    3. **Professional Markdown Formatting**:
                       - Fix any OCR noise, broken line breaks, or formatting typos while preserving 100% factual accuracy.
                       - Start directly with `# [Document Title]`. Do NOT add meta introductions like "Here is the summary".

                    Perform the following tasks:
                    1. **AI Recommended Title (`title`)**: Provide a clean, short, professional document title WITHOUT any prefixes like "Knowledge Ingestment" or "Knowledge Base" (e.g. "Standard Operating Procedure (SOP) Brightening Center" or "ERHA Acne Spot Gel Protocol").
                    2. **Structured Full Document Markdown (`summary`)**: Present the complete content in beautifully organized Markdown matching the document's domain.
                    3. **Multi-Category Selection (`suggested_categories`)**: Recommend ALL relevant matching categories (array of objects with "id" and "name") from Available System Categories.
                    4. **Dynamic Executive Feedback (`feedback`)**: Provide a crisp 1-2 sentence executive summary in Indonesian explaining exactly what this specific document covers and its main points.
                    5. **Text Accuracy (`text_accuracy`)**: Grade the overall text confidence score (e.g. "99%" or "100%").

                    Return a valid JSON object ONLY:
                    {{
                        "title": "Standard Operating Procedure (SOP) Brightening Center",
                        "summary": "# Document Title\\n\\n## 1. Section 1\\n- Content...",
                        "feedback": "Dokumen ini memuat panduan lengkap mengenai [topik dokumen], mencakup [poin-poin utama yang dibahas].",
                        "text_accuracy": "100%",
                        "suggested_categories": [
                            {{
                                "id": "9b79e362-ec70-4560-902e-fd5897c07a00",
                                "name": "Acne Care"
                            }}
                        ]
                    }}
                    """
                    llm_response = await asyncio.to_thread(llm.generate, review_prompt)
                    timing_metrics["llm_review_ms"] = int((_time.time() - t0_llm) * 1000)
                    parsed_review = safe_json_loads(llm_response)
                    raw_title = parsed_review.get("title") or clean_title_fallback

                    # Strip unwanted prefixes from title
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

                    summary = parsed_review.get("summary", summary)
                    text_accuracy = parsed_review.get("text_accuracy", "100%")
                    feedback = parsed_review.get("feedback", feedback)
                    suggested_categories = parsed_review.get("suggested_categories", [])
                            
                except Exception as llm_err:
                    timing_metrics["llm_review_ms"] = int((_time.time() - t0_llm) * 1000)
                    logger.error(f"Failed to process AI review: {llm_err}")
                    recommended_title = clean_title_fallback
                    if not summary or summary == "":
                        summary = "\n\n".join([c.get("text", "") for c in enriched_chunks if isinstance(c, dict) and c.get("text")])
                    if not suggested_categories and db_categories:
                        suggested_categories = [db_categories[0]]
                    feedback = f"Dokumen {file_name} telah berhasil diekstrak dan tersimpan di area peninjauan. Pemrosesan analisis AI otomatis sementara tertunda (kuota token API perlu diperbarui). Seluruh isi teks dokumen dapat ditinjau di bawah."
                
        # Define document-level visibility settings
        visibility_settings = {
            "clinics": ["all"],
            "doctor_types": ["all"],
            "doctors": ["all"]
        }

        # Inject metadata cleanly into every chunk with granular category priority and visibility settings
        cat_names = [c["name"] for c in suggested_categories if isinstance(c, dict) and "name" in c] if suggested_categories else []
        for chunk in enriched_chunks:
            if isinstance(chunk, dict):
                if "metadata" not in chunk:
                    chunk["metadata"] = {}
                chunk["metadata"]["knowledge_id"] = knowledge_id
                chunk["metadata"]["source_file"] = file_name
                chunk["metadata"]["type"] = doc_type_display.lower()
                chunk["metadata"]["clinics"] = visibility_settings["clinics"]
                chunk["metadata"]["doctor_types"] = visibility_settings["doctor_types"]
                chunk["metadata"]["doctors"] = visibility_settings["doctors"]
                
                # Chunk-level category priority, falling back to smart content matching or document-level categories
                chunk_specific_cat = chunk.get("chunk_category")
                if not chunk_specific_cat and cat_names:
                    chunk_txt_lower = (chunk.get("text", "") + " " + str(chunk.get("metadata", {}).get("section", ""))).lower()
                    for cat_candidate in cat_names:
                        if cat_candidate.lower() in chunk_txt_lower:
                            chunk_specific_cat = cat_candidate
                            break

                if chunk_specific_cat:
                    chunk["metadata"]["category"] = chunk_specific_cat
                    chunk["metadata"]["categories"] = [chunk_specific_cat] + [c for c in cat_names if c != chunk_specific_cat]
                elif cat_names:
                    chunk["metadata"]["category"] = cat_names[0]
                    chunk["metadata"]["categories"] = cat_names
                    
                chunk.pop("chunk_category", None)
                chunk["metadata"].pop("suggested_categories", None)
                chunk["metadata"].pop("document_type", None)

        # Preserve image_url, s3_key, storage_key and prepend visual image tag if present
        doc_image_url = None
        doc_s3_key = None
        for c in enriched_chunks:
            if isinstance(c, dict) and c.get("metadata"):
                m = c["metadata"]
                if m.get("image_url") and not doc_image_url:
                    doc_image_url = m["image_url"]
                if m.get("s3_key") and not doc_s3_key:
                    doc_s3_key = m["s3_key"]
                elif m.get("storage_key") and not doc_s3_key:
                    doc_s3_key = m["storage_key"]

        if doc_image_url:
            if doc_image_url not in summary:
                summary = f"![{recommended_title}]({doc_image_url})\n\n{summary}"
            if enriched_chunks and isinstance(enriched_chunks[0], dict):
                if doc_image_url not in enriched_chunks[0].get("text", ""):
                    enriched_chunks[0]["text"] = f"![{recommended_title}]({doc_image_url})\n\n{enriched_chunks[0].get('text', '')}"
                enriched_chunks[0]["metadata"]["image_url"] = doc_image_url
                if doc_s3_key:
                    enriched_chunks[0]["metadata"]["s3_key"] = doc_s3_key
                    enriched_chunks[0]["metadata"]["storage_key"] = doc_s3_key

        history_list = []
        if user_prompt and str(user_prompt).strip():
            history_list = [
                {"role": "user", "content": str(user_prompt).strip()},
                {"role": "assistant", "content": summary}
            ]

        timing_metrics["total_ingestion_ms"] = int((_time.time() - t0_total) * 1000)

        # Structure the final pending document state in exact requested order
        staged_document = {
            "knowledge_id": knowledge_id,
            "batch_id": batch_id,
            "file_name": file_name,
            "file_hash": file_hash,
            "title": recommended_title,
            "type": doc_type_display,
            "status": "On review",
            "text_accuracy": text_accuracy,
            "initial_prompt": user_prompt if user_prompt and str(user_prompt).strip() else None,
            "summary": summary,
            "feedback": feedback,
            "batch_summary": None,
            "suggested_categories": suggested_categories,
            "visibility_settings": visibility_settings,
            "history": history_list,
            "chunks": enriched_chunks,
            "timing_metrics": timing_metrics
        }
        if doc_image_url:
            staged_document["image_url"] = doc_image_url
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
            
        # If this document is part of a multi-file batch, synthesize a unified Batch Executive Summary
        if batch_id and llm:
            try:
                await synthesize_batch_executive_summary(batch_id, llm)
            except Exception as batch_summary_err:
                logger.warning(f"Could not synthesize batch summary: {batch_summary_err}")

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
                    k_entry.status = KnowledgeStatus.PENDING
                    k_entry.title = recommended_title
                    k_entry.ai_summary = summary
                    k_entry.ai_confidence = float(text_accuracy.replace("%", "")) if isinstance(text_accuracy, str) and "%" in text_accuracy else 95.00
                    if k_entry.metadata_ is None:
                        k_entry.metadata_ = {}
                    k_entry.metadata_["timing_metrics"] = timing_metrics
                    await session.commit()
        except Exception as db_err:
            logger.warning(f"Could not update status to PENDING in Knowledge DB table: {db_err}")

        timing_metrics["database_insert_ms"] = int((_time.time() - t0_db) * 1000)
        timing_metrics["total_ingestion_ms"] = int((_time.time() - t0_total) * 1000)

        # Update staged document with final timing metrics
        staged_document["timing_metrics"] = timing_metrics
        with open(pending_file_path, 'w', encoding='utf-8') as f:
            json.dump(staged_document, f, indent=4, ensure_ascii=False)

        logger.info(
            f"\n"
            f"⏱️ [INGESTION TIMING] File: '{file_name}' (ID: {knowledge_id})\n"
            f"  - Parsing Stage        : {timing_metrics['parsing_ms']} ms\n"
            f"  - LLM Review Stage     : {timing_metrics['llm_review_ms']} ms\n"
            f"  - DB Staging Stage     : {timing_metrics['database_insert_ms']} ms\n"
            f"  - Total Ingestion Time : {timing_metrics['total_ingestion_ms']} ms\n"
        )

    except Exception as e:
        logger.error(f"Failed background processing for document: {e}")

async def synthesize_batch_executive_summary(batch_id: str, llm: BaseLLMAdapter) -> Optional[str]:
    """
    Synthesizes multiple uploaded document feedbacks/summaries into a concise, unified Executive Summary paragraph.
    Identifies whether documents are clinically/operationally interrelated or independent.
    Updates all JSON documents in data/pending for this batch.
    """
    if not batch_id or not llm:
        return None

    pending_dir = "data/pending"
    if not os.path.exists(pending_dir):
        return None

    batch_docs = []
    batch_file_paths = []

    for f in os.listdir(pending_dir):
        if f.endswith(".json"):
            fp = os.path.join(pending_dir, f)
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

    docs_text = "\n\n".join([
        f"- Dokumen {i+1} ('{d.get('file_name', '')}' - {d.get('title', '')}):\n  Tipe/Kategori: {d.get('type', 'General')}\n  Deskripsi/Poin Utama: {d.get('feedback', '') or d.get('summary', '')[:250]}"
        for i, d in enumerate(batch_docs)
    ])

    batch_prompt = f"""
Anda adalah AI Knowledge Specialist untuk klinik ERHA (PT Arya Noble).
Pengguna baru saja mengunggah {len(batch_docs)} dokumen sekaligus dalam satu batch ingest.

Berikut rincian dokumen yang diunggah dalam batch ini:
{docs_text}

Tugas Anda:
Buatlah SATU paragraf "Executive Summary" (Bahasa Indonesia) yang singkat, padat, profesional, dan jelas (3-5 kalimat).
Ketentuan Wajib:
1. Rangkum topik utama dari seluruh dokumen yang diunggah dalam batch ini.
2. Analisis hubungan antar dokumen:
   - Jika dokumen saling berhubungan (misal: SOP treatment + katalog produk pendukung, atau protokol jerawat aktif + dark spot enhancer), jelaskan keterkaitan alur klinis/fungsionalnya.
   - Jika dokumen tidak berhubungan langsung (topik berbeda/independen), jelaskan secara ringkas masing-masing fokus dokumennya.
3. Langsung mulai dengan kalimat ringkasan (tanpa awalan seperti "Berikut adalah...", tanpa judul, dan tanpa bullet points).
"""
    try:
        batch_summary = await asyncio.to_thread(llm.generate, batch_prompt)
        batch_summary = batch_summary.strip().strip('"').strip("'")

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
                                "description": "Primary document file(s) to upload. Select 1 or multiple files (Choose File)"
                            },
                            "category_type": {
                                "type": "string",
                                "default": "Product",
                                "description": "Category Type: 'Product', 'Treatment', 'Promotional', or 'Other'"
                            },
                            "prompt": {
                                "type": "string",
                                "description": "Optional custom AI instruction for document processing (e.g. translation, reformatting, custom sectioning)"
                            },
                            "replace_existing": {
                                "type": "boolean",
                                "default": False,
                                "description": "Explicit confirmation by Admin to replace/overwrite an existing PENDING draft"
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
    file: List[UploadFile] = File(..., description="Primary document file(s) to upload (Choose File)"),
    category_type: str = Form("Product", description="Category Type: 'Product', 'Treatment', 'Promotional', or 'Other'"),
    prompt: Optional[str] = Form(None, description="Optional custom AI instruction for document processing (e.g. translation, reformatting, custom sectioning)"),
    replace_existing: bool = Form(False, description="Set to true if admin explicitly confirms replacing/overwriting existing PENDING draft(s)"),
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
    llm: BaseLLMAdapter = Depends(get_llm)
):
    """
    API endpoint to upload and stage document(s) for ingestion.
    Supports Batch Ingestion with Batch ID, SHA-256 Checksum calculation, and 3-Way Duplicate Detection:
    - PUBLISHED / APPROVED -> BLOCKED (Protects active clinic knowledge base)
    - PENDING / ON REVIEW  -> Requires Admin Confirmation (replace_existing=True) to prevent silent overwrite
    - NEW                  -> Proceed with AI staging
    """
    upload_list = file if isinstance(file, list) else [file]
    upload_list = [f for f in upload_list if f is not None and f.filename]
    if not upload_list:
        raise HTTPException(status_code=400, detail="Please upload at least one document file.")

    try:
        raw_type = (category_type or "").strip().upper()
        from app.models.knowledge import KnowledgeType
        import uuid as _uuid
        import hashlib
        
        response_items = []
        os.makedirs("data/temp", exist_ok=True)
        batch_id = str(_uuid.uuid4()) if len(upload_list) > 1 else None

        for target_file in upload_list:
            if not target_file.filename:
                continue

            if "PRODUCT" in raw_type:
                k_type = KnowledgeType.PRODUCT
                doc_type_display = "Product"
            elif "TREATMENT" in raw_type:
                k_type = KnowledgeType.TREATMENT
                doc_type_display = "Treatment"
            elif "PROMO" in raw_type:
                k_type = KnowledgeType.PROMOTIONAL
                doc_type_display = "Promotional"
            elif "OTHER" in raw_type or "LAIN" in raw_type:
                k_type = KnowledgeType.GENERAL
                doc_type_display = "Other"
            else:
                fn_lower = target_file.filename.lower()
                if any(w in fn_lower for w in ["product", "gel", "cream", "serum", "lotion", "cleanser", "acne", "brochure"]):
                    k_type = KnowledgeType.PRODUCT
                    doc_type_display = "Product"
                elif any(w in fn_lower for w in ["treatment", "procedure", "terapi", "tindakan"]):
                    k_type = KnowledgeType.TREATMENT
                    doc_type_display = "Treatment"
                elif any(w in fn_lower for w in ["promo", "discount", "voucher"]):
                    k_type = KnowledgeType.PROMOTIONAL
                    doc_type_display = "Promotional"
                else:
                    k_type = KnowledgeType.GENERAL
                    doc_type_display = "Other"

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
                        knowledge.type = k_type
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

            # Spawn concurrent background ingestion task
            asyncio.create_task(
                process_ingestion_background(
                    k_id,
                    file_path,
                    target_file.filename,
                    pipeline,
                    llm,
                    doc_type_display,
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
                "type": doc_type_display,
                "duplicate_status": "PENDING_REPLACED" if (dup_status == "PENDING" and replace_existing) else "NEW",
                "status": status_display
            })

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


@router.get("/ingest/pending/{knowledge_id}", tags=["Ingestion"], response_model=PendingDocumentResponse)
async def get_pending_details(knowledge_id: str):
    """
    Retrieves the full staged review details and text chunks of a document for inspection.
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
                    raw_type = k_doc.type.value if hasattr(k_doc.type, "value") else str(k_doc.type)
                    return {
                        "knowledge_id": str(k_doc.id),
                        "file_name": k_doc.file_name,
                        "title": k_doc.title,
                        "type": raw_type.capitalize() if raw_type else "Product",
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
            if "type" not in data or not data["type"]:
                data["type"] = "Product"
            if "status" not in data or not data["status"]:
                data["status"] = "Approved" if "output" in target_file else "On review"
            if "title" not in data or not data["title"]:
                data["title"] = data.get("file_name", "document.pdf")
            if not data.get("image_url") and data.get("chunks"):
                for c in data["chunks"]:
                    if isinstance(c, dict) and c.get("metadata", {}).get("image_url"):
                        data["image_url"] = c["metadata"]["image_url"]
                        break
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read document details: {e}")


@router.post("/ingest/pending/{knowledge_id}/refine", tags=["Ingestion"], response_model=PendingDocumentResponse)
async def refine_pending_document(
    knowledge_id: str,
    request: RefineRequest,
    llm: BaseLLMAdapter = Depends(get_llm)
):
    """
    Interactively refine a staged document's summary, feedback, or text chunks 
    using natural language instructions (conversational feedback).
    """
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

        # Prompt Gemini to refine the staged data based on instructions & history
        refine_prompt = f"""
        You are an intelligent medical aesthetic AI validator for ERHA (PT Arya Noble) knowledge base.
        You are refining a staged document's review data based on user instructions and multi-turn conversation history.
        
        Staged Document:
        {json.dumps(staged_data, indent=2, ensure_ascii=False)}
        
        Available System Categories:
        {json.dumps(db_categories, ensure_ascii=False)}
        
        Conversation History:
        {history_str}
        
        Latest User Instruction:
        "{request.prompt}"
        
        Refine the document with Smart Chunk Category Tagging & Invalid Category Safety Rules:
        1. If the instruction asks to update or correct text (e.g. "perbaiki struktur", "translate ke Indonesia"), update the "summary" and the "text" in the "chunks" list.
        2. **Smart Category Re-mapping**: If categories are added/removed/updated in "suggested_categories", evaluate each chunk's text and update its `metadata.category` and `metadata.categories` array to match ONLY the relevant category for that chunk.
        3. **Invalid Category Alert Guard**: If a requested category has NO factual/medical basis anywhere in the document chunks (e.g. adding "Psoriasis Care" to a pure Acne document), DO NOT tag any chunk with that category. Append an executive warning note in `feedback` (e.g. "⚠️ Warning: Category 'Psoriasis Care' has no matching content in this document and was excluded from chunk search filters.").
        4. Recalculate or update the "text_accuracy" and "feedback" to accurately reflect the changes made.
        
        You must return a valid JSON object ONLY. Do not wrap in markdown block code like ```json.
        The JSON object must have EXACTLY the same structure as the Staged Document, containing these keys:
        {{
            "knowledge_id": "id",
            "file_name": "filename",
            "type": "Product",
            "status": "On review",
            "summary": "updated summary markdown",
            "text_accuracy": "100%",
            "feedback": "updated executive feedback bubble with any category warnings if applicable",
            "suggested_categories": [
                {{"id": "category_id", "name": "category_name"}}
            ],
            "chunks": [
                {{
                    "text": "updated chunk text",
                    "metadata": {{
                        "knowledge_id": "id",
                        "source_file": "filename",
                        "category": "Acne Care",
                        "categories": ["Acne Care"]
                    }}
                }}
            ]
        }}
        """
        
        llm_response = await asyncio.to_thread(llm.generate, refine_prompt)
        
        updated_data = safe_json_loads(llm_response)

        k_id = staged_data.get("knowledge_id", knowledge_id)
        updated_data["knowledge_id"] = k_id

        # Preserve initial_prompt and visibility_settings
        if "initial_prompt" not in updated_data and "initial_prompt" in staged_data:
            updated_data["initial_prompt"] = staged_data.get("initial_prompt")
        if "visibility_settings" not in updated_data and "visibility_settings" in staged_data:
            updated_data["visibility_settings"] = staged_data.get("visibility_settings")

        # Build updated multi-turn conversation history
        existing_hist = staged_data.get("history", [])
        if not isinstance(existing_hist, list):
            existing_hist = []
        new_hist = list(existing_hist)
        new_hist.append({"role": "user", "content": request.prompt})
        new_hist.append({"role": "assistant", "content": updated_data.get("summary", "")})
        updated_data["history"] = new_hist

        for chunk in updated_data.get("chunks", []):
            if isinstance(chunk, dict):
                if "metadata" not in chunk:
                    chunk["metadata"] = {}
                chunk["metadata"]["knowledge_id"] = k_id
        
        # Save the updated data back
        with open(pending_file, "w", encoding="utf-8") as f:
            json.dump(updated_data, f, indent=4, ensure_ascii=False)
            
        return updated_data
    except Exception as e:
        logger.error(f"Refinement failed for document '{knowledge_id}': {e}")
        raise HTTPException(status_code=500, detail=f"Failed to refine document: {e}")


@router.get("/ingest/documents", tags=["Ingestion"], response_model=List[DocumentListItem])
async def list_all_documents():
    """
    List all documents in the system with their status ('Approved', 'On review', or 'Processing') and basic metadata.
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

                        doc_type = data.get("type") or first_chunk_meta.get("type") or first_chunk_meta.get("document_type") or "Product"
                        if doc_type:
                            doc_type = doc_type.capitalize()

                        docs.append(DocumentListItem(
                            knowledge_id=k_id,
                            file_name=data.get("file_name", fallback_id),
                            product_name=first_chunk_meta.get("product_name"),
                            type=doc_type,
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
                    doc_type = "Product"
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
                            doc_type = data.get("type") or first_meta.get("type") or first_meta.get("document_type") or doc_type
                            processed_at = first_meta.get("processed_at")
                    elif isinstance(data, list):
                        chunks = data
                        if chunks and isinstance(chunks[0], dict):
                            first_meta = chunks[0].get("metadata", {})
                            k_id = str(first_meta.get("knowledge_id", k_id))
                            file_name = first_meta.get("source_file", file_name)
                            product_name = first_meta.get("product_name")
                            doc_type = first_meta.get("type") or first_meta.get("document_type") or doc_type
                            processed_at = first_meta.get("processed_at")
                            
                    if doc_type:
                        doc_type = doc_type.capitalize()

                    if k_id not in seen_ids:
                        docs.append(DocumentListItem(
                            knowledge_id=k_id,
                            file_name=file_name,
                            product_name=product_name,
                            type=doc_type,
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
                    raw_type = k.type.value if hasattr(k.type, "value") else str(k.type)
                    
                    docs.append(DocumentListItem(
                        knowledge_id=str_id,
                        file_name=k.file_name or k.title or "Untitled Document",
                        product_name=k.title,
                        type=raw_type.capitalize() if raw_type else "Product",
                        status=status_display,
                        processed_at=k.created_at.strftime("%Y-%m-%d %H:%M:%S") if k.created_at else None,
                        chunks_count=0
                    ))
                    seen_ids.add(str_id)
    except Exception as db_err:
        logger.warning(f"DB fallback query in list_all_documents failed: {db_err}")

    return docs


@router.get("/ingest/approved/{knowledge_id}", tags=["Ingestion"], response_model=ApprovedDocumentResponse)
async def get_approved_document_details(knowledge_id: str):
    """
    Retrieves detail data (chunks, summary, categories) of an approved document for frontend edit form rendering.
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
            file_name=file_name,
            title=title,
            status="Approved",
            summary=summary,
            categories=parsed_categories,
            visibility_settings=vis_settings,
            chunks=chunks
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to read approved document '{knowledge_id}': {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read approved document: {e}")


@router.put("/ingest/approved/{knowledge_id}", tags=["Ingestion"])
async def edit_approved_document(
    knowledge_id: str,
    request: EditApprovedDocumentRequest,
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
    bm25: BM25Index = Depends(get_bm25_index),
    vector_store: BaseVectorStoreAdapter = Depends(get_vector_store)
):
    """
    Edits an approved document's summary and categories manually (from UI Save Form).
    Automatically re-indexes into PGVector & BM25, and updates PostgreSQL KnowledgeCategory table.
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
        updated_chunks = existing_doc.get("chunks", [])

        vis_settings = request.visibility_settings.model_dump() if request.visibility_settings else existing_doc.get("visibility_settings", {
            "clinics": ["all"],
            "doctor_types": ["all"],
            "doctors": ["all"]
        })

        primary_cat = updated_categories[0] if updated_categories else None
        for chunk in updated_chunks:
            if isinstance(chunk, dict):
                if "metadata" not in chunk:
                    chunk["metadata"] = {}
                chunk["metadata"]["knowledge_id"] = knowledge_id
                chunk["metadata"]["source_file"] = updated_title
                if primary_cat:
                    chunk["metadata"]["document_type"] = primary_cat
                if updated_categories:
                    chunk["metadata"]["categories"] = updated_categories
                if updated_summary:
                    chunk["metadata"]["summary"] = updated_summary
                if vis_settings:
                    chunk["metadata"]["clinics"] = vis_settings.get("clinics", ["all"])
                    chunk["metadata"]["doctor_types"] = vis_settings.get("doctor_types", ["all"])
                    chunk["metadata"]["doctors"] = vis_settings.get("doctors", ["all"])

        approved_doc_structure = {
            "knowledge_id": knowledge_id,
            "file_name": existing_doc.get("file_name", ""),
            "title": updated_title,
            "status": "Approved",
            "summary": updated_summary,
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


@router.put("/ingest/pending/{knowledge_id}", tags=["Ingestion"])
async def edit_pending_document(
    knowledge_id: str,
    request: EditApprovedDocumentRequest
):
    """
    Edits a pending document's summary and categories manually (from UI Save Form).
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

        # Normalize suggested_categories to list of dicts for pending json
        normalized_categories = []
        if updated_categories:
            if isinstance(updated_categories[0], str):
                normalized_categories = [{"name": c} for c in updated_categories]
            else:
                normalized_categories = updated_categories
                
        existing_doc["summary"] = updated_summary
        existing_doc["title"] = updated_title
        if updated_categories is not None and len(updated_categories) > 0:
            existing_doc["suggested_categories"] = normalized_categories
            
        updated_chunks = existing_doc.get("chunks", existing_doc.get("corrected_chunks", existing_doc.get("raw_chunks", [])))
        primary_cat = updated_categories[0] if updated_categories else None
        str_categories = [c["name"] if isinstance(c, dict) else c for c in normalized_categories]
        
        for chunk in updated_chunks:
            if isinstance(chunk, dict):
                if "metadata" not in chunk:
                    chunk["metadata"] = {}
                if str_categories:
                    chunk["metadata"]["categories"] = str_categories
                if primary_cat:
                    chunk["metadata"]["document_type"] = primary_cat["name"] if isinstance(primary_cat, dict) else primary_cat
                if updated_summary:
                    chunk["metadata"]["summary"] = updated_summary

        with open(pending_file, "w", encoding="utf-8") as f:
            json.dump(existing_doc, f, indent=4, ensure_ascii=False)

        return existing_doc
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Edit pending document failed for '{knowledge_id}': {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update pending document: {e}")


@router.post("/ingest/approved/{knowledge_id}/refine", tags=["Ingestion"])
async def refine_approved_document(
    knowledge_id: str,
    request: RefineRequest,
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
    bm25: BM25Index = Depends(get_bm25_index),
    vector_store: BaseVectorStoreAdapter = Depends(get_vector_store),
    llm: BaseLLMAdapter = Depends(get_llm)
):
    """
    Refines an approved document's summary, categories, and chunks using natural language AI instructions.
    Automatically re-indexes into PGVector & BM25, and updates PostgreSQL KnowledgeCategory table.
    """
    approved_file = resolve_approved_file(knowledge_id)
    if not approved_file:
        raise HTTPException(status_code=404, detail=f"Approved document '{knowledge_id}' not found.")

    if not llm:
        raise HTTPException(status_code=500, detail="LLM adapter is not configured.")

    try:
        with open(approved_file, "r", encoding="utf-8") as f:
            existing_doc = json.load(f)

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

        refine_prompt = f"""
        You are an intelligent medical aesthetic AI validator for ERHA (PT Arya Noble) knowledge base.
        You are refining an APPROVED document based on user instructions and multi-turn conversation history.
        
        Document Data:
        {json.dumps(existing_doc, indent=2, ensure_ascii=False)}
        
        Available Categories:
        {json.dumps(db_categories, ensure_ascii=False)}
        
        Conversation History:
        {history_str}
        
        Latest User Instruction:
        "{request.prompt}"
        
        Refine the document summary, categories, or chunks according to the instruction.
        Return a valid JSON object ONLY (do not wrap in markdown code block) with keys:
        {{
            "summary": "updated summary markdown",
            "categories": ["category_name"],
            "chunks": [ {{ "text": "...", "metadata": {{}} }} ]
        }}
        """
        
        llm_res = await asyncio.to_thread(llm.generate, refine_prompt)
        clean_json = llm_res.strip()
        if clean_json.startswith("```"):
            lines = clean_json.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            clean_json = "\n".join(lines).strip()
            
        parsed_refined = json.loads(clean_json)
        updated_summary = parsed_refined.get("summary", existing_doc.get("summary", ""))
        updated_categories = parsed_refined.get("categories", existing_doc.get("categories", []))
        updated_chunks = parsed_refined.get("chunks", existing_doc.get("chunks", []))
        file_name = existing_doc.get("file_name", knowledge_id)

        primary_cat = updated_categories[0] if updated_categories else None
        for chunk in updated_chunks:
            if isinstance(chunk, dict):
                if "metadata" not in chunk:
                    chunk["metadata"] = {}
                chunk["metadata"]["knowledge_id"] = knowledge_id
                if primary_cat:
                    chunk["metadata"]["document_type"] = primary_cat
                if updated_categories:
                    chunk["metadata"]["categories"] = updated_categories
                if updated_summary:
                    chunk["metadata"]["summary"] = updated_summary

        approved_doc_structure = {
            "knowledge_id": knowledge_id,
            "file_name": file_name,
            "status": "Approved",
            "summary": updated_summary,
            "categories": updated_categories,
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


@router.post("/ingest/approve/{knowledge_id}", tags=["Ingestion"])
async def approve_document(
    knowledge_id: str = Path(..., description="Knowledge ID(s) to approve. Supports single ID (e.g. 'uuid1') or comma-separated IDs for batch approval (e.g. 'uuid1,uuid2,uuid3')"),
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
    bm25: BM25Index = Depends(get_bm25_index)
):
    """
    Approves staged document(s) and indexes them into PGVector & BM25 database.
    Supports single document approval or comma-separated batch approval in 1 click.
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
            
            for chunk in chunks:
                if isinstance(chunk, dict):
                    if "metadata" not in chunk:
                        chunk["metadata"] = {}
                    chunk["metadata"]["knowledge_id"] = k_id
                    chunk["metadata"]["source_file"] = doc_title
                    
                    # Ensure categories are preserved
                    cats = data.get("suggested_categories", data.get("categories", []))
                    str_cats = [c["name"] if isinstance(c, dict) else c for c in cats]
                    if str_cats:
                        chunk["metadata"]["categories"] = str_cats
                    if "summary" not in chunk["metadata"] and "summary" in data:
                        chunk["metadata"]["summary"] = data.get("summary")
                    
            if pipeline.vector_store:
                logger.info(f"Indexing chunks for knowledge_id {k_id} into vector store...")
                pipeline.vector_store.insert_chunks(chunks)
            else:
                logger.warning("No vector store instance available for indexing.")
                
            if bm25:
                logger.info(f"Indexing chunks for knowledge_id {k_id} into BM25 index...")
                bm25.add_chunks(chunks)
                bm25.save(settings.bm25_index_path)
                
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

            os.makedirs("data/output", exist_ok=True)
            approved_file = os.path.join("data/output", f"{k_id}.json")
            approved_doc_structure = {
                "knowledge_id": k_id,
                "batch_id": data.get("batch_id") if isinstance(data, dict) else None,
                "file_name": file_name,
                "file_hash": data.get("file_hash") if isinstance(data, dict) else None,
                "title": doc_title,
                "type": data.get("type", "Product") if isinstance(data, dict) else "Product",
                "document_type": data.get("document_type", "product") if isinstance(data, dict) else "product",
                "status": "Approved",
                "summary": data.get("summary", "") if isinstance(data, dict) else "",
                "categories": parsed_cats,
                "suggested_categories": raw_cats,
                "visibility_settings": vis_settings,
                "chunks": chunks
            }
            with open(approved_file, "w", encoding="utf-8") as f:
                json.dump(approved_doc_structure, f, indent=4, ensure_ascii=False)
                
            if os.path.exists(pending_file):
                os.remove(pending_file)
                
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


@router.delete("/ingest/documents/{knowledge_id}", tags=["Ingestion"])
async def delete_document_endpoint(
    knowledge_id: str,
    pipeline: IngestionPipeline = Depends(get_ingestion_pipeline),
    bm25: BM25Index = Depends(get_bm25_index),
    vector_store: BaseVectorStoreAdapter = Depends(get_vector_store)
):
    """
    Deletes document(s) across all statuses (Pending or Approved).
    Supports single ID, comma-separated IDs (e.g. 'id1,id2,id3'), filename, or 'all'.
    Removes physical JSON files, PGVector embeddings, BM25 indices, and performs soft-delete in PostgreSQL.
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


@router.get("/search", tags=["Retrieval"])
async def search_hybrid(
    query: str = Query(..., description="Search query string"),
    categories: Optional[List[str]] = Query(None, description="Optional category filters (e.g. ['Acne Care'])"),
    document_type: Optional[str] = Query(None, description="Optional document category filter ('Product', 'Treatment', or 'Promotional')"),
    top_k: int = Query(8, description="Number of passage matches to return"),
    retriever: HybridRetriever = Depends(get_hybrid_retriever)
):
    """
    Advanced Hybrid Search (PGVector Dense Embeddings + BM25 Sparse Keyword Match) 
    with Reciprocal Rank Fusion (RRF).
    """
    if not retriever:
        raise HTTPException(status_code=500, detail="Hybrid retriever is not initialized.")
        
    filter_metadata = {}
    if document_type and document_type.strip().lower() not in ("string", ""):
        filter_metadata["document_type"] = document_type
    if categories:
        valid_cats = [c.strip() for c in categories if c and c.strip().lower() not in ("string", "")]
        if valid_cats:
            filter_metadata["categories"] = valid_cats
        
    parsed_filter = filter_metadata if filter_metadata else None
            
    try:
        hits = retriever.retrieve(
            query=query, 
            top_k=top_k, 
            filter_metadata=parsed_filter, 
            rerank=False,
            rerank_top_n=top_k
        )
        return hits
    except Exception as e:
        logger.error(f"Search endpoint failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chat", response_model=ChatResponse, tags=["Generation"])
async def chat_endpoint(
    request: ChatRequest,
    pipeline: GenerationPipeline = Depends(get_generation_pipeline)
):
    """
    Production Unified RAG Chat Endpoint. Single entry point for query processing,
    dynamic complexity routing, evidence validation, clinical safety gate, and LLM response synthesis.
    """
    if not pipeline:
        raise HTTPException(status_code=500, detail="Generation pipeline is not initialized.")

    raw_history = []
    if request.history:
        for msg in request.history:
            if isinstance(msg, dict):
                r = msg.get("role", "")
                c = msg.get("content", "")
            else:
                r = getattr(msg, "role", "")
                c = getattr(msg, "content", "")
            if r and c:
                raw_history.append({"role": r, "content": c})

    filter_metadata = {}
    if request.document_type and request.document_type.strip().lower() not in ("string", ""):
        filter_metadata["document_type"] = request.document_type
    if request.categories:
        valid_cats = [c.strip() for c in request.categories if c and c.strip().lower() not in ("string", "")]
        if valid_cats:
            filter_metadata["categories"] = valid_cats
        
    if request.user_context:
        filter_metadata["clinics"] = request.user_context.branch_ids + ["all"]
        filter_metadata["doctor_types"] = [request.user_context.dr_type, "all"]
        filter_metadata["doctors"] = [request.user_context.user_id, "all"]
        if request.user_context.excluded_categories:
            filter_metadata["excluded_categories"] = request.user_context.excluded_categories

    parsed_filter = filter_metadata if filter_metadata else None
    
    try:
        response = pipeline.generate_answer(
            query=request.query,
            top_k=request.top_k,
            filter_metadata=parsed_filter,
            rerank=False,
            history=raw_history
        )
        
        if isinstance(response, ChatResponse):
            return response
        elif isinstance(response, dict):
            return ChatResponse(
                query=response.get("query", request.query),
                answer=response.get("answer", ""),
                context=response.get("context", ""),
                results=response.get("results", []),
                agent_used=response.get("agent_used", False)
            )
        return response

    except Exception as e:
        logger.error(f"Unified Chat generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))




@router.post("/ingest/reset", tags=["Ingestion"])
async def reset_database(
    vector_store: BaseVectorStoreAdapter = Depends(get_vector_store),
    bm25: BM25Index = Depends(get_bm25_index)
):
    """
    Clears the entire RAG knowledge base. Drops and recreates the PGVector collection, 
    resets the BM25 index, and deletes all files inside data/pending/ and data/output/.
    """
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
            
        # 3. Clean files in data/pending/ and data/output/ (delete all .json staged/approved documents)
        for folder in ["data/pending", "data/output", "data/temp"]:
            if os.path.exists(folder):
                for f in os.listdir(folder):
                    if f.endswith(".json") or f.endswith(".pdf") or f.endswith(".docx") or f.endswith(".txt") or f.endswith(".xlsx") or f.endswith(".csv"):
                        try:
                            os.remove(os.path.join(folder, f))
                        except Exception as file_err:
                            logger.warning(f"Could not remove file {f}: {file_err}")

        # 4. Soft-delete all records in PostgreSQL Knowledge table
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
            logger.warning(f"Could not clear Knowledge table in DB during reset: {db_err}")
                            
        return {"status": "success", "message": "Knowledge base (PGVector, BM25, staged/approved files, and PostgreSQL Knowledge DB) has been successfully cleared."}
    except Exception as e:
        logger.error(f"Reset database failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/evaluation", 
    tags=["Evaluation"], 
    response_model=RAGEvaluationResponse,
    summary="Run RAG Evaluation Benchmark"
)
async def run_rag_evaluation(
    dataset: List[RAGEvaluationItem] = Body(
        ..., 
        description="Dataset queries and expected source files for accuracy evaluation benchmark"
    ),
    top_k: int = Query(5, description="Number of retrieved passages to evaluate"),
    retriever: HybridRetriever = Depends(get_hybrid_retriever),
    generation_pipeline: GenerationPipeline = Depends(get_generation_pipeline),
    llm: BaseLLMAdapter = Depends(get_llm)
):
    """
    Runs automated RAG evaluation benchmark measuring Hit Rate@K, MRR@K, Faithfulness, and Accuracy Percentage.
    """
    if not dataset:
        raise HTTPException(status_code=400, detail="Dataset must contain at least 1 evaluation item.")

    formatted_dataset = []
    for item in dataset:
        gt = {"source_file": item.expected_file}
        formatted_dataset.append({
            "query": item.query,
            "ground_truth": gt,
            "expected_answer": item.expected_answer
        })

    eval_results = RAGEvaluator.evaluate_full(
        retriever=retriever,
        generation_pipeline=generation_pipeline,
        llm_adapter=llm,
        dataset=formatted_dataset,
        top_k=top_k,
        evaluate_generation=False
    )

    return RAGEvaluationResponse(
        hit_rate=round(eval_results["hit_rate"], 4),
        mrr=round(eval_results["mrr"], 4),
        faithfulness=eval_results.get("faithfulness"),
        answer_relevance=eval_results.get("answer_relevance"),
        total_queries=eval_results["total_queries"]
    )

