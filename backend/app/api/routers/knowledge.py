from loguru import logger
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Request, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, text, or_
from app.models.category import Category, UserCategoryExclusion
from app.models.branch import UserBranch
from typing import List, Optional, Dict, Any
import uuid
import json
import os

from app.core.database import get_db
from app.api.dependencies import get_current_user, RequireAccess
from app.models.user import User, UserType
from app.models.knowledge import Knowledge, KnowledgeStatus, KnowledgeType
from app.models.project import Project
from app.models.chat import ChatSession, ChatMessage as DBChatMessage, ChatRole, ChatStatus
from app.schemas.knowledge import (
    KnowledgeCreate, KnowledgeUpdateStatus, KnowledgeResponse, KnowledgeProjectUpdate,
    GeneralChatSessionResponse, GeneralChatMessageItem, GeneralChatMessageSendRequest
)
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
    chat_endpoint,
    query_general_endpoint,
    QueryGeneralRequest,
    QueryGeneralResponse
)
from app.rag.schemas import EditApprovedDocumentRequest, RefineRequest, ChatMessage, ChatRequest, ChatResponse, UserContext

router = APIRouter(tags=["Knowledge"])

@router.get("/quota")
async def get_ingestion_quota_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:read"))
):
    """Fetch monthly knowledge ingestion token quota and warning status."""
    _, quota_info = await check_ingestion_quota(db)
    return quota_info

@router.post("/general-session", response_model=GeneralChatSessionResponse)
@router.post("/general-session/", response_model=GeneralChatSessionResponse)
async def create_general_chat_session(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:read"))
):
    """Create a new persistent General Knowledge Assistant chat session."""
    session = ChatSession(
        user_id=current_user.id,
        session_type="GENERAL_ASSISTANT",
        status=ChatStatus.ACTIVE
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return GeneralChatSessionResponse(
        id=session.id,
        user_id=session.user_id,
        session_type=session.session_type,
        status=session.status.value,
        messages=[],
        created_at=session.created_at,
        updated_at=session.updated_at
    )

@router.get("/general-session/{session_id}", response_model=GeneralChatSessionResponse)
@router.get("/general-session/{session_id}/", response_model=GeneralChatSessionResponse)
async def get_general_chat_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:read"))
):
    """Retrieve saved messages for a persistent General Knowledge Assistant session."""
    stmt = select(ChatSession).where(
        ChatSession.id == session_id,
        ChatSession.session_type == "GENERAL_ASSISTANT"
    )
    res = await db.execute(stmt)
    session = res.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="General chat session not found")

    msg_stmt = select(DBChatMessage).where(
        DBChatMessage.session_id == session_id
    ).order_by(DBChatMessage.created_at.asc())
    msg_res = await db.execute(msg_stmt)
    db_msgs = msg_res.scalars().all()

    formatted_msgs = []
    for m in db_msgs:
        att = m.attachments or {}
        formatted_msgs.append(GeneralChatMessageItem(
            id=m.id,
            role=m.role.value.lower(),
            content=m.content,
            action=att.get("action"),
            target_knowledge_id=att.get("target_knowledge_id"),
            total_found=att.get("total_found"),
            attachments=att,
            created_at=m.created_at
        ))

    return GeneralChatSessionResponse(
        id=session.id,
        user_id=session.user_id,
        session_type=session.session_type,
        status=session.status.value,
        messages=formatted_msgs,
        created_at=session.created_at,
        updated_at=session.updated_at
    )

@router.post("/general-session/{session_id}/messages", response_model=GeneralChatSessionResponse)
@router.post("/general-session/{session_id}/messages/", response_model=GeneralChatSessionResponse)
async def send_general_chat_message(
    session_id: uuid.UUID,
    payload: GeneralChatMessageSendRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:read")),
    pipeline = Depends(get_generation_pipeline),
    vector_store = Depends(get_vector_store),
    bm25 = Depends(get_bm25_index)
):
    """Append message to persistent session, execute RAG search/management, and persist response in DB."""
    stmt = select(ChatSession).where(
        ChatSession.id == session_id,
        ChatSession.session_type == "GENERAL_ASSISTANT"
    )
    res = await db.execute(stmt)
    session = res.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="General chat session not found")

    # Fetch existing conversation history
    msg_stmt = select(DBChatMessage).where(
        DBChatMessage.session_id == session_id
    ).order_by(DBChatMessage.created_at.asc())
    msg_res = await db.execute(msg_stmt)
    db_msgs = msg_res.scalars().all()

    history_payload = [
        {"role": m.role.value.lower(), "content": m.content}
        for m in db_msgs
    ]

    # 1. Save User Message in PostgreSQL
    user_db_msg = DBChatMessage(
        session_id=session_id,
        role=ChatRole.USER,
        content=payload.prompt,
        attachments=payload.attachments
    )
    db.add(user_db_msg)
    await db.flush()

    # 2. Run Query General RAG endpoint
    rag_request = QueryGeneralRequest(
        prompt=payload.prompt,
        history=history_payload
    )
    ai_res = await query_general_endpoint(
        request=rag_request,
        pipeline=pipeline,
        vector_store=vector_store,
        bm25=bm25
    )

    # 3. Save Assistant Message in PostgreSQL
    assistant_att = {
        "action": ai_res.action,
        "target_knowledge_id": ai_res.target_knowledge_id,
        "total_found": ai_res.total_found
    }
    assistant_db_msg = DBChatMessage(
        session_id=session_id,
        role=ChatRole.ASSISTANT,
        content=ai_res.answer,
        attachments=assistant_att
    )
    db.add(assistant_db_msg)
    await db.commit()

    return await get_general_chat_session(session_id, db, current_user)

@router.post("/query-general", response_model=QueryGeneralResponse)
@router.post("/query-general/", response_model=QueryGeneralResponse)
async def knowledge_query_general(
    request: QueryGeneralRequest,
    current_user: User = Depends(RequireAccess("knowledge:read")),
    pipeline = Depends(get_generation_pipeline),
    vector_store = Depends(get_vector_store),
    bm25 = Depends(get_bm25_index)
):
    """
    Main Backend wrapper for Query General Endpoint — Knowledge Base Explorer, Editor & Deletion via Natural Language Prompt.
    """
    return await query_general_endpoint(
        request=request,
        pipeline=pipeline,
        vector_store=vector_store,
        bm25=bm25
    )

@router.get("/", response_model=List[KnowledgeResponse])
async def list_knowledge(
    project_id: Optional[uuid.UUID] = Query(None, description="Optional project filter"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:read"))
):
    # 1. Fetch DB records
    stmt = select(Knowledge).where(Knowledge.deleted_at.is_(None))
    if project_id:
        stmt = stmt.where(Knowledge.project_id == project_id)
    stmt = stmt.order_by(Knowledge.created_at.desc())
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
            project_id=item.project_id,
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
    
    # Query soft-deleted IDs and file names to prevent zombie resurrection
    del_stmt = select(Knowledge.id, Knowledge.file_name).where(Knowledge.deleted_at.is_not(None))
    del_res = await db.execute(del_stmt)
    deleted_records = del_res.all()
    deleted_ids = {str(row[0]).lower() for row in deleted_records}
    deleted_files = {str(row[1]).lower() for row in deleted_records if row[1]}
    
    seen_ids = set(db_by_id.keys()).union(deleted_ids)
    staged_responses = []

    for folder in ["data/pending", "data/output"]:
        if os.path.exists(folder):
            for f in os.listdir(folder):
                if f.endswith(".json") and f != "bm25_index.pkl":
                    file_path = os.path.join(folder, f)
                    try:
                        with open(file_path, "r", encoding="utf-8") as fp:
                            data = json.load(fp)
                        if isinstance(data, dict):
                            raw_id = str(data.get("knowledge_id") or f.replace("_parsed.json", "").replace(".json", "")).lower()
                            file_name = str(data.get("file_name", f))
                            
                            # Clean up and skip if this matches any soft-deleted record
                            if raw_id in deleted_ids or file_name.lower() in deleted_files:
                                try:
                                    os.remove(file_path)
                                    logger.info(f"Purged stale/deleted staging file during list scan: {file_path}")
                                except Exception:
                                    pass
                                continue

                            if raw_id not in seen_ids:
                                seen_ids.add(raw_id)
                                try:
                                    k_uuid = uuid.UUID(str(raw_id))
                                except ValueError:
                                    k_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, str(raw_id))

                                title = data.get("title", file_name)
                                summary = data.get("summary", "")
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
    # 1. Try fetching from DB
    stmt = select(Knowledge).where(Knowledge.id == knowledge_id)
    result = await db.execute(stmt)
    knowledge = result.scalar_one_or_none()
    
    if knowledge:
        if knowledge.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Knowledge document not found")
        # OUT-OF-BAND SYNC: Fetch latest AI summary & metadata from RAG JSON files
        try:
            target_file = resolve_pending_file(str(knowledge_id)) or resolve_approved_file(str(knowledge_id))
            if target_file and os.path.exists(target_file):
                with open(target_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                latest_summary = data.get("summary", "")
                latest_title = data.get("title", "")
                
                updated = False
                if latest_summary and knowledge.ai_summary != latest_summary:
                    knowledge.ai_summary = latest_summary
                    updated = True
                if latest_title and knowledge.title != latest_title:
                    knowledge.title = latest_title
                    updated = True
                if updated:
                    await db.commit()
                    await db.refresh(knowledge)
                
                if isinstance(data, dict):
                    merged_meta = dict(knowledge.metadata_) if isinstance(knowledge.metadata_, dict) else {}
                    merged_meta.update(data)
                    # If approved, ensure active history is clean while staging_history and edit_history are retained
                    if knowledge.status == KnowledgeStatus.APPROVED:
                        merged_meta["history"] = []
                        merged_meta["chat_history"] = []
                        if "staging_history" in data:
                            merged_meta["staging_history"] = data["staging_history"]
                        elif isinstance(knowledge.metadata_, dict) and "staging_history" in knowledge.metadata_:
                            merged_meta["staging_history"] = knowledge.metadata_["staging_history"]
                        if "edit_history" in data:
                            merged_meta["edit_history"] = data["edit_history"]
                        elif isinstance(knowledge.metadata_, dict) and "edit_history" in knowledge.metadata_:
                            merged_meta["edit_history"] = knowledge.metadata_["edit_history"]
                    else:
                        if "history" not in data and "history" in merged_meta:
                            merged_meta["history"] = merged_meta["history"]
                        if "chat_history" not in data and "chat_history" in merged_meta:
                            merged_meta["chat_history"] = merged_meta["chat_history"]
                    knowledge.metadata_ = merged_meta
        except Exception as e:
            logger.warning(f"Error loading RAG JSON: {e}")
            
        return knowledge

    # 2. Fallback check in RAG staging files (data/pending or data/output)
    # Ensure ID is not soft-deleted
    del_check_stmt = select(Knowledge.id).where(Knowledge.id == knowledge_id, Knowledge.deleted_at.is_not(None))
    del_check = await db.execute(del_check_stmt)
    if del_check.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Knowledge document not found")

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
                k_type = KnowledgeType.GENERAL

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
        type=KnowledgeType.GENERAL,
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
        Knowledge.deleted_at.is_(None),
        or_(
            Knowledge.metadata_.op("->>")("batch_id") == batch_id,
            Knowledge.metadata_.op("->>")("upload_batch_id") == batch_id
        )
    ).order_by(Knowledge.created_at.desc())
    result = await db.execute(stmt)
    docs = list(result.scalars().all())
    
    # Query soft-deleted IDs for this batch so they are never resurrected by directory scanning
    del_stmt = select(Knowledge.id).where(
        Knowledge.deleted_at.is_not(None),
        or_(
            Knowledge.metadata_.op("->>")("batch_id") == batch_id,
            Knowledge.metadata_.op("->>")("upload_batch_id") == batch_id
        )
    )
    del_res = await db.execute(del_stmt)
    deleted_ids = {str(d_id) for d_id in del_res.scalars().all()}
    
    enriched_docs = []
    seen_ids = set(deleted_ids)

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
                                if str(raw_id).lower() in {d.lower() for d in deleted_ids}:
                                    try:
                                        os.remove(file_path)
                                    except Exception:
                                        pass
                                    continue
                                if str(raw_id) not in seen_ids:
                                    seen_ids.add(str(raw_id))
                                    try:
                                        k_uuid = uuid.UUID(str(raw_id))
                                    except ValueError:
                                        k_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, str(raw_id))

                                    file_name = data.get("file_name", f)
                                    title = data.get("title", file_name)
                                    summary = data.get("summary", "")
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

@router.post("/batch/{batch_id}/approve")
async def approve_batch_knowledge(
    request: Request,
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:write"))
):
    """Approve all pending staged documents in a batch ingestion session and index them into vector & BM25 search databases."""
    pipeline = get_ingestion_pipeline(request)
    bm25 = get_bm25_index(request)

    from sqlalchemy import or_
    stmt = select(Knowledge).where(
        Knowledge.deleted_at.is_(None),
        or_(
            Knowledge.metadata_.op("->>")("batch_id") == batch_id,
            Knowledge.metadata_.op("->>")("upload_batch_id") == batch_id
        )
    )
    result = await db.execute(stmt)
    db_docs = list(result.scalars().all())

    # Scan pending directory for any files matching batch_id
    pending_dir = "data/pending"
    target_ids = set()
    for d in db_docs:
        target_ids.add(str(d.id))

    if os.path.exists(pending_dir):
        for f in os.listdir(pending_dir):
            if f.endswith(".json") and f != "bm25_index.pkl":
                fp = os.path.join(pending_dir, f)
                try:
                    with open(fp, "r", encoding="utf-8") as jf:
                        data = json.load(jf)
                    if isinstance(data, dict):
                        b_id = data.get("batch_id") or data.get("upload_batch_id")
                        if not b_id and data.get("chunks"):
                            b_id = data["chunks"][0].get("metadata", {}).get("batch_id") or data["chunks"][0].get("metadata", {}).get("upload_batch_id")
                        if b_id == batch_id:
                            k_id = data.get("knowledge_id") or f.replace("_parsed.json", "").replace(".json", "")
                            if k_id:
                                target_ids.add(str(k_id))
                except Exception:
                    pass

    if not target_ids:
        raise HTTPException(status_code=404, detail=f"No documents found for batch '{batch_id}'.")

    # Read pending histories before approval moves/deletes files
    doc_histories = {}
    for tid in target_ids:
        p_file = resolve_pending_file(tid)
        if p_file and os.path.exists(p_file):
            try:
                with open(p_file, "r", encoding="utf-8") as f:
                    s_data = json.load(f)
                    if s_data.get("history"):
                        doc_histories[tid] = s_data.get("history")
            except Exception:
                pass

    ids_param = ",".join(target_ids)
    res = await approve_document(ids_param, pipeline=pipeline, bm25=bm25)

    # Sync DB statuses
    from sqlalchemy.orm.attributes import flag_modified
    for doc in db_docs:
        doc.status = KnowledgeStatus.APPROVED
        doc.approved_by = current_user.id
        doc_str_id = str(doc.id)
        if doc_str_id in doc_histories:
            if doc.metadata_ is None:
                doc.metadata_ = {}
            doc.metadata_["history"] = doc_histories[doc_str_id]
            doc.metadata_["chat_history"] = doc_histories[doc_str_id]
            flag_modified(doc, "metadata_")

    await db.commit()
    return res

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

    from app.rag.router import run_chat_pipeline
    return await run_chat_pipeline(
        query=request.query,
        attachment_text=request.attachment_text,
        doctor_name=current_user.name or request.doctor_name,
        user_context=request.user_context,
        history=request.history,
        categories=request.categories,
        top_k=request.top_k,
        knowledge_id=request.knowledge_id,
        batch_id=request.batch_id,
        pipeline=pipeline
    )

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain",
    "text/csv",
    "image/jpeg",
    "image/png",
    "image/webp"
}

@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_knowledge_file(
    request: Request,
    background_tasks: BackgroundTasks,
    file: List[UploadFile] = File(...),
    project_id: Optional[uuid.UUID] = Form(None),
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

    ingest_res = await ingest_document(
        background_tasks=background_tasks,
        file=file,
        prompt=prompt,
        pipeline=pipeline,
        llm=llm
    )

    if project_id and isinstance(ingest_res, dict):
        docs = ingest_res.get("documents", [])
        for doc in docs:
            k_id = doc.get("knowledge_id")
            if k_id:
                try:
                    k_uuid = uuid.UUID(str(k_id))
                    stmt = select(Knowledge).where(Knowledge.id == k_uuid)
                    res = await db.execute(stmt)
                    k_obj = res.scalar_one_or_none()
                    if k_obj:
                        k_obj.project_id = project_id
                        await db.commit()
                except Exception:
                    pass

    return ingest_res

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
        k_type = KnowledgeType.GENERAL
        
        if target_file and os.path.exists(target_file):
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    file_name = data.get("file_name", file_name)
                    summary = data.get("summary", "")
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
    
    # Read pending file history before it gets moved/deleted by approve_document
    pending_file = resolve_pending_file(str(knowledge_id))
    staged_history = []
    if pending_file and os.path.exists(pending_file):
        try:
            with open(pending_file, "r", encoding="utf-8") as f:
                staged_data = json.load(f)
                staged_history = staged_data.get("history", [])
        except Exception:
            pass

    res = await approve_document(str(knowledge_id), pipeline=pipeline, bm25=bm25)
    
    # Ensure DB status is updated and conversation history is retained in metadata_
    stmt = select(Knowledge).where(Knowledge.id == knowledge_id)
    result = await db.execute(stmt)
    k_entry = result.scalar_one_or_none()
    if k_entry:
        k_entry.status = KnowledgeStatus.APPROVED
        k_entry.approved_by = current_user.id
        if k_entry.metadata_ is None:
            k_entry.metadata_ = {}
        if staged_history:
            k_entry.metadata_["staging_history"] = staged_history
        k_entry.metadata_["history"] = []
        k_entry.metadata_["chat_history"] = []
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(k_entry, "metadata_")
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
    # Guard: Check if DB record exists and is not soft-deleted
    stmt = select(Knowledge).where(Knowledge.id == knowledge_id)
    db_res = await db.execute(stmt)
    k_entry = db_res.scalar_one_or_none()
    
    if k_entry and k_entry.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Knowledge document not found")

    pipeline = get_ingestion_pipeline(request)
    bm25 = get_bm25_index(request)
    vector_store = get_vector_store(request)
    
    p_file = resolve_pending_file(str(knowledge_id))
    a_file = resolve_approved_file(str(knowledge_id))

    # DB fallback if JSON file is missing from disk but exists in PostgreSQL
    if not p_file and not a_file and k_entry:
        if k_entry.status == KnowledgeStatus.APPROVED:
            a_file = os.path.join("data/output", f"{knowledge_id}.json")
            os.makedirs("data/output", exist_ok=True)
            doc_data = {
                "knowledge_id": str(knowledge_id),
                "file_name": k_entry.file_name or str(knowledge_id),
                "title": k_entry.title or k_entry.file_name or "Knowledge Document",
                "status": "Approved",
                "summary": k_entry.ai_summary or "",
                "categories": k_entry.metadata_.get("categories", []) if k_entry.metadata_ else [],
                "visibility_settings": k_entry.metadata_.get("visibility_settings", {"clinics": ["all"], "doctor_types": ["all"], "doctors": ["all"]}) if k_entry.metadata_ else {"clinics": ["all"], "doctor_types": ["all"], "doctors": ["all"]},
                "chunks": k_entry.metadata_.get("chunks", [{"text": k_entry.ai_summary or k_entry.title or "", "metadata": {"knowledge_id": str(knowledge_id)}}]) if k_entry.metadata_ else [{"text": k_entry.ai_summary or k_entry.title or "", "metadata": {"knowledge_id": str(knowledge_id)}}]
            }
            with open(a_file, "w", encoding="utf-8") as f:
                json.dump(doc_data, f, indent=4, ensure_ascii=False)
        else:
            p_file = os.path.join("data/pending", f"{knowledge_id}.json")
            os.makedirs("data/pending", exist_ok=True)
            doc_data = {
                "knowledge_id": str(knowledge_id),
                "file_name": k_entry.file_name or str(knowledge_id),
                "title": k_entry.title or k_entry.file_name or "Knowledge Document",
                "status": "On review",
                "summary": k_entry.ai_summary or "",
                "chunks": k_entry.metadata_.get("chunks", [{"text": k_entry.ai_summary or k_entry.title or "", "metadata": {"knowledge_id": str(knowledge_id)}}]) if k_entry.metadata_ else [{"text": k_entry.ai_summary or k_entry.title or "", "metadata": {"knowledge_id": str(knowledge_id)}}]
            }
            with open(p_file, "w", encoding="utf-8") as f:
                json.dump(doc_data, f, indent=4, ensure_ascii=False)

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
    if k_entry:
        if payload.title:
            k_entry.title = payload.title
        if payload.summary:
            k_entry.ai_summary = payload.summary
            k_entry.content = payload.summary

        k_entry.type = KnowledgeType.GENERAL
            
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:write")),
    llm: BaseLLMAdapter = Depends(get_llm)
):
    """
    Refines either a pending (On review) or approved document using natural language prompt 
    and optional attached file upload (PDF/Docx/TXT/Image).
    """
    content_type = request.headers.get("content-type", "")
    prompt = ""
    history = []
    file_attachment: Optional[UploadFile] = None

    if "multipart/form-data" in content_type:
        form = await request.form()
        prompt = str(form.get("prompt", "") or "")
        history_raw = form.get("history", "[]")
        if isinstance(history_raw, str):
            try:
                history_json = json.loads(history_raw)
                history = [
                    ChatMessage(role=m.get("role", "user"), content=m.get("content", ""))
                    if isinstance(m, dict) else m
                    for m in history_json
                ]
            except Exception:
                history = []
        elif isinstance(history_raw, list):
            history = [
                ChatMessage(role=m.get("role", "user"), content=m.get("content", ""))
                if isinstance(m, dict) else m
                for m in history_raw
            ]
            
        file_obj = form.get("file")
        if isinstance(file_obj, UploadFile):
            file_attachment = file_obj
    else:
        try:
            body = await request.json()
            prompt = str(body.get("prompt", "") or "")
            history_raw = body.get("history", [])
            history = [
                ChatMessage(role=m.get("role", "user"), content=m.get("content", ""))
                if isinstance(m, dict) else m
                for m in history_raw
            ]
        except Exception:
            prompt = ""
            history = []

    payload = RefineRequest(prompt=prompt, history=history)

    # Process attached file if provided
    if file_attachment:
        try:
            temp_dir = "data/temp"
            os.makedirs(temp_dir, exist_ok=True)
            attached_file_name = getattr(file_attachment, "filename", "attached_doc")
            temp_file_path = os.path.join(temp_dir, f"refine_supp_{knowledge_id}_{attached_file_name}")
            content_bytes = await file_attachment.read()
            with open(temp_file_path, "wb") as f:
                f.write(content_bytes)

            from app.rag.utils.parser import DocumentParser
            parser = DocumentParser()
            parse_res = parser.parse_file(temp_file_path)
            extracted_text = ""
            if parse_res:
                if parse_res.pages:
                    extracted_pages = [p.get("text", "") for p in parse_res.pages if p.get("text")]
                    extracted_text = "\n\n".join(extracted_pages)
                elif parse_res.docling_doc:
                    try:
                        extracted_text = parse_res.docling_doc.export_to_markdown()
                    except Exception:
                        extracted_text = ""

            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)

            if extracted_text:
                file_note = (
                    f"\n\n[SUPPLEMENTARY ATTACHED FILE CONTENT: '{attached_file_name}']\n"
                    f"{extracted_text}\n"
                    f"[END OF ATTACHED FILE CONTENT]"
                )
                payload.prompt = f"{payload.prompt}\n{file_note}" if payload.prompt else file_note
                logger.info(f"📄 Successfully attached file '{attached_file_name}' ({len(extracted_text)} chars) to refine request for knowledge_id='{knowledge_id}'")

            await file_attachment.seek(0)
        except Exception as file_err:
            logger.warning(f"Failed to process attached file in refine_knowledge: {file_err}")

    p_file = resolve_pending_file(str(knowledge_id))
    a_file = resolve_approved_file(str(knowledge_id))
    
    # DB fallback if JSON file is missing from disk
    if not p_file and not a_file:
        stmt = select(Knowledge).where(Knowledge.id == knowledge_id, Knowledge.deleted_at.is_(None))
        db_res = await db.execute(stmt)
        k_entry = db_res.scalar_one_or_none()
        if k_entry:
            if k_entry.status == KnowledgeStatus.APPROVED:
                a_file = os.path.join("data/output", f"{knowledge_id}.json")
                os.makedirs("data/output", exist_ok=True)
                doc_data = {
                    "knowledge_id": str(knowledge_id),
                    "file_name": k_entry.file_name or str(knowledge_id),
                    "title": k_entry.title or k_entry.file_name or "Knowledge Document",
                    "status": "Approved",
                    "summary": k_entry.ai_summary or "",
                    "categories": k_entry.metadata_.get("categories", []) if k_entry.metadata_ else [],
                    "visibility_settings": k_entry.metadata_.get("visibility_settings", {"clinics": ["all"], "doctor_types": ["all"], "doctors": ["all"]}) if k_entry.metadata_ else {"clinics": ["all"], "doctor_types": ["all"], "doctors": ["all"]},
                    "chunks": k_entry.metadata_.get("chunks", [{"text": k_entry.ai_summary or k_entry.title or "", "metadata": {"knowledge_id": str(knowledge_id)}}]) if k_entry.metadata_ else [{"text": k_entry.ai_summary or k_entry.title or "", "metadata": {"knowledge_id": str(knowledge_id)}}]
                }
                with open(a_file, "w", encoding="utf-8") as f:
                    json.dump(doc_data, f, indent=4, ensure_ascii=False)
            else:
                p_file = os.path.join("data/pending", f"{knowledge_id}.json")
                os.makedirs("data/pending", exist_ok=True)
                doc_data = {
                    "knowledge_id": str(knowledge_id),
                    "file_name": k_entry.file_name or str(knowledge_id),
                    "title": k_entry.title or k_entry.file_name or "Knowledge Document",
                    "status": "On review",
                    "summary": k_entry.ai_summary or "",
                    "chunks": k_entry.metadata_.get("chunks", [{"text": k_entry.ai_summary or k_entry.title or "", "metadata": {"knowledge_id": str(knowledge_id)}}]) if k_entry.metadata_ else [{"text": k_entry.ai_summary or k_entry.title or "", "metadata": {"knowledge_id": str(knowledge_id)}}]
                }
                with open(p_file, "w", encoding="utf-8") as f:
                    json.dump(doc_data, f, indent=4, ensure_ascii=False)

    if p_file:
        res = await refine_pending_document(str(knowledge_id), payload, llm, file_attachment=file_attachment)
    elif a_file:
        pipeline = get_ingestion_pipeline(request)
        bm25 = get_bm25_index(request)
        vector_store = get_vector_store(request)
        res = await refine_approved_document(str(knowledge_id), payload, pipeline, bm25, vector_store, llm, file_attachment=file_attachment)
    else:
        raise HTTPException(status_code=404, detail="Document not found for refinement.")

    # Synchronize DB record with refined output
    try:
        stmt = select(Knowledge).where(Knowledge.id == knowledge_id)
        db_res = await db.execute(stmt)
        k_entry = db_res.scalar_one_or_none()
        if k_entry and isinstance(res, dict):
            if res.get("title"):
                k_entry.title = res.get("title")
            if res.get("summary"):
                k_entry.ai_summary = res.get("summary")
            if k_entry.metadata_ is None:
                k_entry.metadata_ = {}
            if res.get("categories") is not None:
                k_entry.metadata_["categories"] = res.get("categories")
            elif res.get("suggested_categories") is not None:
                k_entry.metadata_["categories"] = [c.get("name") if isinstance(c, dict) else str(c) for c in res.get("suggested_categories", [])]
            if res.get("visibility_settings") is not None:
                k_entry.metadata_["visibility_settings"] = res.get("visibility_settings")
            if res.get("chunks") is not None:
                k_entry.metadata_["chunks"] = res.get("chunks")

            # Persist chat turns in metadata
            if k_entry.status == KnowledgeStatus.APPROVED:
                existing_edit_hist = k_entry.metadata_.get("edit_history") or []
                if not isinstance(existing_edit_hist, list):
                    existing_edit_hist = []
                new_edit_hist = list(existing_edit_hist)
                if payload.prompt:
                    new_edit_hist.append({
                        "role": "user",
                        "content": payload.prompt,
                        "created_at": datetime.now(timezone.utc).isoformat()
                    })
                if res.get("summary"):
                    new_edit_hist.append({
                        "role": "assistant",
                        "content": res.get("summary"),
                        "created_at": datetime.now(timezone.utc).isoformat()
                    })
                k_entry.metadata_["edit_history"] = new_edit_hist
            else:
                existing_history = k_entry.metadata_.get("history") or k_entry.metadata_.get("chat_history") or []
                if not isinstance(existing_history, list):
                    existing_history = []
                
                new_history = list(existing_history)
                if payload.prompt:
                    new_history.append({
                        "role": "user",
                        "content": payload.prompt,
                        "created_at": datetime.now(timezone.utc).isoformat()
                    })
                if res.get("summary"):
                    new_history.append({
                        "role": "assistant",
                        "content": res.get("summary"),
                        "created_at": datetime.now(timezone.utc).isoformat()
                    })

                k_entry.metadata_["history"] = new_history
                k_entry.metadata_["chat_history"] = new_history

            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(k_entry, "metadata_")
            await db.commit()
    except Exception as sync_err:
        logger.warning(f"Failed to sync refined knowledge to DB row: {sync_err}")

    return res

@router.put("/{knowledge_id}/project", response_model=KnowledgeResponse)
@router.patch("/{knowledge_id}/project", response_model=KnowledgeResponse)
async def update_knowledge_project(
    knowledge_id: uuid.UUID,
    payload: KnowledgeProjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:write"))
):
    """Attach or detach a knowledge document to/from a project workspace."""
    stmt = select(Knowledge).where(Knowledge.id == knowledge_id, Knowledge.deleted_at.is_(None))
    result = await db.execute(stmt)
    knowledge = result.scalar_one_or_none()
    
    if payload.project_id:
        p_stmt = select(Project).where(Project.id == payload.project_id, Project.deleted_at.is_(None))
        p_res = await db.execute(p_stmt)
        if not p_res.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Project not found")

    target_file = resolve_pending_file(str(knowledge_id)) or resolve_approved_file(str(knowledge_id))

    if not knowledge:
        file_name = "document.pdf"
        summary = ""
        k_type = KnowledgeType.GENERAL
        data = {}
        if target_file and os.path.exists(target_file):
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    file_name = data.get("file_name", file_name)
                    summary = data.get("summary", "")
            except Exception:
                pass

        doc_status = KnowledgeStatus.APPROVED if (target_file and "output" in target_file) else KnowledgeStatus.PENDING
        knowledge = Knowledge(
            id=knowledge_id,
            title=file_name,
            file_name=file_name,
            original_path=f"data/temp/{file_name}",
            mime_type="application/pdf",
            type=k_type,
            status=doc_status,
            ai_summary=summary,
            ai_confidence=95.0,
            uploaded_by=current_user.id,
            project_id=payload.project_id,
            metadata_=data
        )
        db.add(knowledge)
    else:
        knowledge.project_id = payload.project_id

    # Keep staging JSON file project_id in sync if exists
    if target_file and os.path.exists(target_file):
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                j_data = json.load(f)
            if isinstance(j_data, dict):
                j_data["project_id"] = str(payload.project_id) if payload.project_id else None
                with open(target_file, "w", encoding="utf-8") as f:
                    json.dump(j_data, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    await db.commit()
    await db.refresh(knowledge)
    return knowledge

@router.delete("/{knowledge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge(
    request: Request,
    knowledge_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(RequireAccess("knowledge:delete"))
):
    kid_str = str(knowledge_id)
    
    # 1. Fetch DB record to gather all identifiers
    stmt = select(Knowledge).where(Knowledge.id == knowledge_id)
    result = await db.execute(stmt)
    knowledge = result.scalar_one_or_none()
    
    file_name = knowledge.file_name if knowledge else None
    
    # Mark soft-deleted in PostgreSQL
    if knowledge:
        knowledge.deleted_at = datetime.now(timezone.utc)
        await db.commit()
        
    # 2. Collect all identifier variants for multi-key purge
    identifiers_to_purge = {kid_str, f"{kid_str}_parsed", f"{kid_str}.json", f"{kid_str}_parsed.json"}
    if file_name:
        base_name, _ = os.path.splitext(file_name)
        identifiers_to_purge.update({
            file_name,
            base_name,
            f"{file_name}_parsed",
            f"{file_name}_parsed.json",
            f"{file_name}.json"
        })

    # 3. Clean physical files from data/pending, data/output, data/temp
    for folder in ["data/pending", "data/output", "data/temp"]:
        if os.path.exists(folder):
            for f in os.listdir(folder):
                f_path = os.path.join(folder, f)
                if not os.path.isfile(f_path):
                    continue
                
                f_lower = f.lower()
                should_delete = False
                
                for ident in identifiers_to_purge:
                    if ident.lower() == f_lower or f_lower.startswith(ident.lower()):
                        should_delete = True
                        break
                        
                if not should_delete and f.endswith(".json") and f != "bm25_index.pkl":
                    try:
                        with open(f_path, "r", encoding="utf-8") as fp:
                            f_data = json.load(fp)
                        if isinstance(f_data, dict):
                            doc_kid = str(f_data.get("knowledge_id", ""))
                            doc_fname = str(f_data.get("file_name", ""))
                            if doc_kid == kid_str or (file_name and doc_fname.lower() == file_name.lower()):
                                should_delete = True
                    except Exception:
                        pass
                        
                if should_delete:
                    try:
                        os.remove(f_path)
                        logger.info(f"Purged staging/temp file for knowledge deletion: {f_path}")
                    except Exception as err:
                        logger.warning(f"Failed to remove file {f_path}: {err}")

    # 4. Clean Vector Store Chunks (PGVector)
    vector_store = get_vector_store(request)
    if vector_store:
        for ident in identifiers_to_purge:
            try:
                vector_store.delete_document(ident)
            except Exception as vs_err:
                logger.debug(f"vector_store.delete_document({ident}) notice: {vs_err}")

    # Direct SQL cleanup on vector store table to ensure 100% vector purge
    try:
        from app.rag.config import settings as rag_settings
        table_name = rag_settings.pg_collection_name
        cleanup_query = text(f"""
            DELETE FROM {table_name} 
            WHERE source_file = :kid 
               OR source_file ILIKE :kid_pattern
               OR (:fname IS NOT NULL AND (source_file = :fname OR source_file ILIKE :fname_pattern))
               OR metadata ->> 'knowledge_id' = :kid
               OR (:fname IS NOT NULL AND metadata ->> 'file_name' = :fname)
        """)
        await db.execute(cleanup_query, {
            "kid": kid_str,
            "kid_pattern": f"%{kid_str}%",
            "fname": file_name,
            "fname_pattern": f"%{file_name}%" if file_name else None
        })
        await db.commit()
    except Exception as sql_err:
        logger.warning(f"Direct vector store table purge warning: {sql_err}")

    # 5. Clean BM25 Index
    bm25 = get_bm25_index(request)
    if bm25:
        for ident in identifiers_to_purge:
            try:
                bm25.remove_file_chunks(ident)
            except Exception as bm_err:
                logger.debug(f"bm25.remove_file_chunks({ident}) notice: {bm_err}")
        try:
            from app.rag.config import settings
            bm25.save(settings.bm25_index_path)
        except Exception as save_err:
            logger.debug(f"BM25 index save error: {save_err}")

    # 6. Fallback RAG endpoint call
    pipeline = get_ingestion_pipeline(request)
    try:
        await delete_document_endpoint(kid_str, pipeline, bm25, vector_store)
    except Exception:
        pass
                
    return None
