from loguru import logger
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Request, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.category import Category, UserCategoryExclusion
from app.models.branch import UserBranch
from sqlalchemy import select, and_, func
from typing import List, Optional
import uuid
import json
import os

from app.core.database import get_db
from app.api.dependencies import get_current_user, RequireAccess
from app.models.user import User, UserType
from app.models.knowledge import Knowledge, KnowledgeStatus, KnowledgeType
from app.schemas.knowledge import KnowledgeCreate, KnowledgeUpdateStatus, KnowledgeResponse
from app.services.token_service import check_ingestion_quota, record_ingestion_token_usage
from datetime import datetime, timezone

from app.rag.deps import get_ingestion_pipeline, get_llm, get_bm25_index, get_vector_store, get_generation_pipeline
from app.rag.services.interfaces import BaseLLMAdapter
from app.rag.router import (
    ingest_document, 
    approve_document, 
    edit_approved_document,
    edit_pending_document,
    refine_pending_document,
    refine_approved_document,
    delete_document_endpoint,
    resolve_pending_file,
    resolve_approved_file,
    synthesize_batch_executive_summary,
    chat_endpoint
)
from app.rag.schemas import EditApprovedDocumentRequest, RefineRequest, ChatRequest, ChatResponse, UserContext

router = APIRouter(tags=["Knowledge"])

@router.get("/quota")
async def get_ingestion_quota_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:read"))
):
    """Fetch monthly knowledge ingestion token quota and warning status."""
    _, quota_info = await check_ingestion_quota(db)
    return quota_info

@router.get("/", response_model=List[KnowledgeResponse])
async def list_knowledge(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:read"))
):
    # 1. Fetch DB records
    stmt = select(Knowledge).where(Knowledge.deleted_at.is_(None)).order_by(Knowledge.created_at.desc())
    result = await db.execute(stmt)
    db_items = list(result.scalars().all())

    # 2. Out-of-band sync DB items with RAG staging files (data/pending or data/output)
    db_by_id = {str(item.id): item for item in db_items}
    updated_db = False
    db_responses: List[KnowledgeResponse] = []

    for item in db_items:
        k_id_str = str(item.id)
        target_file = resolve_pending_file(k_id_str) or resolve_approved_file(k_id_str)
        item_metadata = dict(item.metadata_) if isinstance(item.metadata_, dict) else {}

        if target_file and os.path.exists(target_file):
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    new_status = KnowledgeStatus.APPROVED if "output" in target_file else KnowledgeStatus.PENDING
                    if item.status != new_status and item.status != KnowledgeStatus.APPROVED:
                        item.status = new_status
                        updated_db = True
                    latest_summary = data.get("summary", "")
                    if latest_summary and item.ai_summary != latest_summary:
                        item.ai_summary = latest_summary
                        updated_db = True
                    latest_title = data.get("title", "")
                    if latest_title and item.title != latest_title:
                        item.title = latest_title
                        updated_db = True
                    item_metadata = {**item_metadata, **data}
            except Exception as e:
                pass

        # Build KnowledgeResponse before any commit to prevent MissingGreenlet from expired attributes
        db_responses.append(KnowledgeResponse(
            id=item.id,
            title=item.title,
            content=item.content,
            file_name=item.file_name,
            original_path=item.original_path,
            mime_type=item.mime_type,
            file_size=item.file_size,
            type=item.type,
            status=item.status,
            ai_summary=item.ai_summary,
            ai_confidence=item.ai_confidence,
            uploaded_by=item.uploaded_by,
            approved_by=item.approved_by,
            metadata_=item_metadata,
            created_at=item.created_at,
            updated_at=item.updated_at
        ))

    if updated_db:
        try:
            await db.commit()
        except Exception:
            pass

    # 3. Fallback scan: Include any staged JSON files from data/pending or data/output missing in DB
    now = datetime.now(timezone.utc)
    seen_ids = set(db_by_id.keys())
    staged_responses = []

    for folder in ["data/pending", "data/output"]:
        if os.path.exists(folder):
            for f in os.listdir(folder):
                if f.endswith(".json"):
                    file_path = os.path.join(folder, f)
                    try:
                        with open(file_path, "r", encoding="utf-8") as fp:
                            data = json.load(fp)
                        if isinstance(data, dict):
                            raw_id = data.get("knowledge_id") or f.replace("_parsed.json", "").replace(".json", "")
                            if str(raw_id) not in seen_ids:
                                seen_ids.add(str(raw_id))
                                try:
                                    k_uuid = uuid.UUID(str(raw_id))
                                except ValueError:
                                    k_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, str(raw_id))

                                file_name = data.get("file_name", f)
                                title = data.get("title", file_name)
                                summary = data.get("summary", "")
                                raw_type = str(data.get("type", "PRODUCT")).upper()
                                k_type = KnowledgeType.PRODUCT
                                if "TREATMENT" in raw_type:
                                    k_type = KnowledgeType.TREATMENT
                                elif "PROMO" in raw_type:
                                    k_type = KnowledgeType.PROMOTIONAL
                                elif "OTHER" in raw_type or "LAIN" in raw_type:
                                    k_type = KnowledgeType.GENERAL

                                doc_status = KnowledgeStatus.APPROVED if "output" in folder else KnowledgeStatus.PENDING

                                staged_responses.append(KnowledgeResponse(
                                    id=k_uuid,
                                    title=title,
                                    content=summary,
                                    file_name=file_name,
                                    original_path=f"data/temp/{file_name}",
                                    mime_type="application/pdf",
                                    file_size=None,
                                    type=k_type,
                                    status=doc_status,
                                    ai_summary=summary,
                                    ai_confidence=95.0,
                                    uploaded_by=current_user.id,
                                    approved_by=None,
                                    metadata_=data,
                                    created_at=now,
                                    updated_at=now
                                ))
                    except Exception as err:
                        pass

    return db_responses + staged_responses

@router.get("/{knowledge_id}", response_model=KnowledgeResponse)
async def get_knowledge(
    knowledge_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:read"))
):
    # 1. Try fetching from DB (ignoring soft-delete filter to prevent 404)
    stmt = select(Knowledge).where(Knowledge.id == knowledge_id)
    result = await db.execute(stmt)
    knowledge = result.scalar_one_or_none()
    
    if knowledge:
        # OUT-OF-BAND SYNC: Fetch latest AI summary from RAG JSON files
        try:
            target_file = resolve_pending_file(str(knowledge_id)) or resolve_approved_file(str(knowledge_id))
            if target_file and os.path.exists(target_file):
                with open(target_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                latest_summary = data.get("summary", "")
                if latest_summary and knowledge.ai_summary != latest_summary:
                    knowledge.ai_summary = latest_summary
                    await db.commit()
                    await db.refresh(knowledge)
                # Inject full RAG data into metadata manually
                knowledge_dict = KnowledgeResponse.model_validate(knowledge).model_dump(by_alias=False)
                knowledge_dict["metadata_"] = data
                return knowledge_dict
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Error loading RAG JSON: {e}")
            
        return knowledge

    # 2. Fallback check in RAG staging files (data/pending or data/output)
    target_file = resolve_pending_file(str(knowledge_id)) or resolve_approved_file(str(knowledge_id))
    now = datetime.now(timezone.utc)
    
    if target_file and os.path.exists(target_file):
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            doc_status = KnowledgeStatus.APPROVED if "output" in target_file else KnowledgeStatus.PENDING
            if isinstance(data, dict):
                file_name = data.get("file_name", "document.pdf")
                title = data.get("title", file_name)
                summary = data.get("summary", "")
                raw_type = str(data.get("type", "PRODUCT")).upper()
                k_type = KnowledgeType.PRODUCT
                if "TREATMENT" in raw_type:
                    k_type = KnowledgeType.TREATMENT
                elif "PROMO" in raw_type:
                    k_type = KnowledgeType.PROMOTIONAL

                return KnowledgeResponse(
                    id=knowledge_id,
                    title=title,
                    content=summary,
                    file_name=file_name,
                    original_path=f"data/temp/{file_name}",
                    mime_type="application/pdf",
                    file_size=None,
                    type=k_type,
                    status=doc_status,
                    ai_summary=summary,
                    ai_confidence=95.0,
                    uploaded_by=current_user.id,
                    approved_by=None,
                    metadata_=data,
                    created_at=now,
                    updated_at=now
                )
        except Exception as err:
            pass

    # 3. Dynamic processing fallback (for documents still being parsed in background)
    return KnowledgeResponse(
        id=knowledge_id,
        title="Processing Document...",
        content="Document is currently being parsed and vectorized in background...",
        file_name="processing_document.pdf",
        original_path="data/temp/processing_document.pdf",
        mime_type="application/pdf",
        file_size=None,
        type=KnowledgeType.PRODUCT,
        status=KnowledgeStatus.PROCESSING,
        ai_summary="Document processing in progress...",
        ai_confidence=0.0,
        uploaded_by=current_user.id,
        approved_by=None,
        metadata_={"status": "PROCESSING"},
        created_at=now,
        updated_at=now
    )

@router.get("/batch/{batch_id}", response_model=List[KnowledgeResponse])
async def get_knowledge_batch(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:read")),
    llm: BaseLLMAdapter = Depends(get_llm)
):
    """Fetch all knowledge documents uploaded in a specific batch."""
    from sqlalchemy import or_
    stmt = select(Knowledge).where(
        or_(
            Knowledge.metadata_.op("->>")("batch_id") == batch_id,
            Knowledge.metadata_.op("->>")("upload_batch_id") == batch_id
        )
    ).order_by(Knowledge.created_at.desc())
    result = await db.execute(stmt)
    docs = list(result.scalars().all())
    
    enriched_docs = []
    seen_ids = set()

    for knowledge in docs:
        seen_ids.add(str(knowledge.id))
        try:
            target_file = resolve_pending_file(str(knowledge.id)) or resolve_approved_file(str(knowledge.id))
            if target_file and os.path.exists(target_file):
                with open(target_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                latest_summary = data.get("summary", "")
                if latest_summary and knowledge.ai_summary != latest_summary:
                    knowledge.ai_summary = latest_summary
                
                knowledge_dict = KnowledgeResponse.model_validate(knowledge).model_dump(by_alias=False)
                # Merge existing DB metadata with JSON data, JSON takes precedence for RAG fields
                db_meta = knowledge_dict.get("metadata_") or {}
                knowledge_dict["metadata_"] = {**db_meta, **data}
                enriched_docs.append(knowledge_dict)
            else:
                enriched_docs.append(knowledge)
        except Exception:
            enriched_docs.append(knowledge)
            
    # Also scan data/pending and data/output for any staged JSON files matching this batch
    now = datetime.now(timezone.utc)
    for folder in ["data/pending", "data/output"]:
        if os.path.exists(folder):
            for f in os.listdir(folder):
                if f.endswith(".json") and f != "bm25_index.pkl":
                    file_path = os.path.join(folder, f)
                    try:
                        with open(file_path, "r", encoding="utf-8") as fp:
                            data = json.load(fp)
                        if isinstance(data, dict):
                            doc_batch = data.get("batch_id") or data.get("upload_batch_id")
                            if not doc_batch and data.get("chunks"):
                                doc_batch = data["chunks"][0].get("metadata", {}).get("batch_id") or data["chunks"][0].get("metadata", {}).get("upload_batch_id")

                            if doc_batch == batch_id:
                                raw_id = data.get("knowledge_id") or f.replace("_parsed.json", "").replace(".json", "")
                                if str(raw_id) not in seen_ids:
                                    seen_ids.add(str(raw_id))
                                    try:
                                        k_uuid = uuid.UUID(str(raw_id))
                                    except ValueError:
                                        k_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, str(raw_id))

                                    file_name = data.get("file_name", f)
                                    title = data.get("title", file_name)
                                    summary = data.get("summary", "")
                                    raw_type = str(data.get("type", "PRODUCT")).upper()
                                    k_type = KnowledgeType.PRODUCT
                                    if "TREATMENT" in raw_type:
                                        k_type = KnowledgeType.TREATMENT
                                    elif "PROMO" in raw_type:
                                        k_type = KnowledgeType.PROMOTIONAL
                                    elif "OTHER" in raw_type or "LAIN" in raw_type:
                                        k_type = KnowledgeType.GENERAL

                                    doc_status = KnowledgeStatus.APPROVED if "output" in folder else KnowledgeStatus.PENDING

                                    enriched_docs.append(KnowledgeResponse(
                                        id=k_uuid,
                                        title=title,
                                        content=summary,
                                        file_name=file_name,
                                        original_path=f"data/temp/{file_name}",
                                        mime_type="application/pdf",
                                        file_size=None,
                                        type=k_type,
                                        status=doc_status,
                                        ai_summary=summary,
                                        ai_confidence=95.0,
                                        uploaded_by=current_user.id,
                                        approved_by=None,
                                        metadata_=data,
                                        created_at=now,
                                        updated_at=now
                                    ))
                    except Exception:
                        pass

    # Synthesize unified batch executive summary if multiple documents and not yet generated
    if len(enriched_docs) >= 2 and llm:
        has_batch_summary = any(
            (doc.get("metadata_") if isinstance(doc, dict) else (doc.metadata_ or {})).get("batch_summary")
            for doc in enriched_docs
        )
        if not has_batch_summary:
            try:
                gen_summary = await synthesize_batch_executive_summary(batch_id, llm)
                if gen_summary:
                    for doc in enriched_docs:
                        if isinstance(doc, dict):
                            if "metadata_" not in doc or not doc["metadata_"]:
                                doc["metadata_"] = {}
                            doc["metadata_"]["batch_summary"] = gen_summary
                        elif hasattr(doc, "metadata_"):
                            if not doc.metadata_:
                                doc.metadata_ = {}
                            doc.metadata_["batch_summary"] = gen_summary
            except Exception as e:
                logger.warning(f"On-the-fly batch summary synthesis skipped: {e}")

    return enriched_docs

@router.post("/chat", response_model=ChatResponse)
async def knowledge_chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:read")),
    pipeline = Depends(get_generation_pipeline)
):
    # Fetch user branches (active connections only)
    stmt_branches = select(UserBranch.branch_id).where(
        UserBranch.user_id == current_user.id,
        UserBranch.status == 1,
        UserBranch.deleted_at.is_(None)
    )
    result_branches = await db.execute(stmt_branches)
    branch_ids = [str(b_id) for b_id in result_branches.scalars().all()]
    
    # Fetch excluded category names
    stmt_exclusions = (
        select(Category.name)
        .join(UserCategoryExclusion, UserCategoryExclusion.category_id == Category.id)
        .where(UserCategoryExclusion.user_id == current_user.id)
    )
    result_exclusions = await db.execute(stmt_exclusions)
    excluded_cats = [name for name in result_exclusions.scalars().all()]

    # Inject context
    request.user_context = UserContext(
        user_id=str(current_user.id),
        dr_type=current_user.dr_type or "all",
        branch_ids=branch_ids,
        excluded_categories=excluded_cats
    )

    return await chat_endpoint(request=request, pipeline=pipeline)

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
    "image/jpeg",
    "image/png"
}

@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_knowledge_file(
    request: Request,
    background_tasks: BackgroundTasks,
    file: List[UploadFile] = File(...),
    category_type: str = Form("Product"),
    prompt: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:write")),
    llm: BaseLLMAdapter = Depends(get_llm)
):
    upload_list = file if isinstance(file, list) else [file]
    for target_file in upload_list:
        if target_file.content_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(status_code=400, detail=f"File type {target_file.content_type} not allowed for file {target_file.filename}")
        
    # Check monthly ingestion quota (soft warning / notice model)
    allowed, quota_info = await check_ingestion_quota(db)
    if quota_info.get("exceeded"):
        logger.warning(f"Monthly knowledge ingestion threshold exceeded ({quota_info['tokens_used']:,} / {quota_info['token_limit']:,} tokens). Ingestion proceeding with soft warning.")
    elif quota_info.get("warning"):
        logger.info(f"Monthly knowledge ingestion threshold near limit ({quota_info['percentage']}% used).")

    pipeline = get_ingestion_pipeline(request)
    
    # Record estimated/base ingestion token usage for each document
    estimated_doc_tokens = 500 * len(upload_list) # Base parsing overhead estimation
    await record_ingestion_token_usage(
        db=db,
        input_tokens=estimated_doc_tokens,
        output_tokens=200 * len(upload_list),
        documents_count=len(upload_list)
    )

    return await ingest_document(
        background_tasks=background_tasks,
        file=file,
        category_type=category_type,
        prompt=prompt,
        pipeline=pipeline,
        llm=llm
    )

@router.put("/{knowledge_id}/status", response_model=KnowledgeResponse)
@router.patch("/{knowledge_id}/status", response_model=KnowledgeResponse)
async def update_knowledge_status(
    knowledge_id: uuid.UUID,
    status_in: KnowledgeUpdateStatus,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:write"))
):
    # 1. Try DB lookup (without deleted_at filter)
    stmt = select(Knowledge).where(Knowledge.id == knowledge_id)
    result = await db.execute(stmt)
    knowledge = result.scalar_one_or_none()
    
    if not knowledge:
        # Fallback: check RAG staging file to auto-create Knowledge DB record if missing
        target_file = resolve_pending_file(str(knowledge_id)) or resolve_approved_file(str(knowledge_id))
        
        file_name = "document.pdf"
        summary = ""
        k_type = KnowledgeType.PRODUCT
        
        if target_file and os.path.exists(target_file):
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    file_name = data.get("file_name", file_name)
                    summary = data.get("summary", "")
                    raw_type = str(data.get("type", "PRODUCT")).upper()
                    if "TREATMENT" in raw_type:
                        k_type = KnowledgeType.TREATMENT
                    elif "PROMO" in raw_type:
                        k_type = KnowledgeType.PROMOTIONAL
            except Exception:
                pass
                
        knowledge = Knowledge(
            id=knowledge_id,
            title=file_name,
            file_name=file_name,
            original_path=f"data/temp/{file_name}",
            mime_type="application/pdf",
            type=k_type,
            status=status_in.status,
            ai_summary=summary,
            ai_confidence=95.0,
            uploaded_by=current_user.id
        )
        db.add(knowledge)
    else:
        knowledge.status = status_in.status
        knowledge.deleted_at = None

    if status_in.status == KnowledgeStatus.APPROVED:
        knowledge.approved_by = current_user.id
        
    await db.commit()
    await db.refresh(knowledge)
    return knowledge

@router.post("/{knowledge_id}/approve")
async def approve_knowledge(
    request: Request,
    knowledge_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:write"))
):
    pipeline = get_ingestion_pipeline(request)
    bm25 = get_bm25_index(request)
    
    res = await approve_document(str(knowledge_id), pipeline=pipeline, bm25=bm25)
    
    # Ensure DB status is updated
    stmt = select(Knowledge).where(Knowledge.id == knowledge_id)
    result = await db.execute(stmt)
    k_entry = result.scalar_one_or_none()
    if k_entry:
        k_entry.status = KnowledgeStatus.APPROVED
        k_entry.approved_by = current_user.id
        await db.commit()


    return res

@router.put("/{knowledge_id}")
async def edit_knowledge(
    request: Request,
    knowledge_id: uuid.UUID,
    payload: EditApprovedDocumentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:write"))
):
    pipeline = get_ingestion_pipeline(request)
    bm25 = get_bm25_index(request)
    vector_store = get_vector_store(request)
    
    p_file = resolve_pending_file(str(knowledge_id))
    if p_file:
        res = await edit_pending_document(
            knowledge_id=str(knowledge_id),
            request=payload
        )
    else:
        res = await edit_approved_document(
            knowledge_id=str(knowledge_id),
            request=payload,
            pipeline=pipeline,
            bm25=bm25,
            vector_store=vector_store
        )

    # Sync updates back to the DB row
    stmt = select(Knowledge).where(Knowledge.id == knowledge_id)
    db_res = await db.execute(stmt)
    k_entry = db_res.scalar_one_or_none()
    
    if k_entry:
        if payload.title:
            k_entry.title = payload.title
        if payload.summary:
            k_entry.ai_summary = payload.summary
            
        if k_entry.metadata_ is None:
            k_entry.metadata_ = {}
            
        if payload.categories is not None:
            k_entry.metadata_["categories"] = payload.categories
            
        if payload.visibility_settings is not None:
            k_entry.metadata_["visibility_settings"] = payload.visibility_settings.model_dump()
            
        # Ensure SQLAlchemy sees the mutation in the JSON column
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(k_entry, "metadata_")
        
        await db.commit()

    return res

@router.post("/{knowledge_id}/refine")
async def refine_knowledge(
    request: Request,
    knowledge_id: uuid.UUID,
    payload: RefineRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:write")),
    llm: BaseLLMAdapter = Depends(get_llm)
):
    p_file = resolve_pending_file(str(knowledge_id))
    a_file = resolve_approved_file(str(knowledge_id))
    
    if p_file:
        return await refine_pending_document(str(knowledge_id), payload, llm)
    elif a_file:
        pipeline = get_ingestion_pipeline(request)
        bm25 = get_bm25_index(request)
        vector_store = get_vector_store(request)
        return await refine_approved_document(str(knowledge_id), payload, pipeline, bm25, vector_store, llm)
    else:
        raise HTTPException(status_code=404, detail="Document not found for refinement.")

@router.delete("/{knowledge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge(
    request: Request,
    knowledge_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(RequireAccess("knowledge:delete"))
):
    # 1. Soft-delete DB record if present
    stmt = select(Knowledge).where(Knowledge.id == knowledge_id)
    result = await db.execute(stmt)
    knowledge = result.scalar_one_or_none()
    
    if knowledge:
        knowledge.deleted_at = datetime.now(timezone.utc)
        await db.commit()
        
    # 2. Hard delete vector store embeddings and JSON files via RAG subsystem
    pipeline = get_ingestion_pipeline(request)
    bm25 = get_bm25_index(request)
    vector_store = get_vector_store(request)
    
    try:
        await delete_document_endpoint(str(knowledge_id), pipeline, bm25, vector_store)
    except Exception:
        pass
                
    return None
