from loguru import logger
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Request, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, text, or_, case
from app.models.category import Category, UserCategoryExclusion
from app.models.branch import UserBranch
from typing import List, Optional, Dict, Any
import uuid
import json
import os
import mimetypes
import re

from app.core.database import get_db
from app.api.dependencies import get_current_user, RequireAccess
from app.models.user import User, UserType
from app.models.knowledge import Knowledge, KnowledgeStatus, KnowledgeType
from app.models.pending_operation import PendingOperation
from app.models.project import Project
from app.models.chat import ChatSession, ChatMessage as DBChatMessage, ChatRole, ChatStatus
from app.schemas.knowledge import (
    KnowledgeCreate, KnowledgeUpdateStatus, KnowledgeResponse, KnowledgeProjectUpdate,
    KnowledgeTextIngestRequest, KnowledgeTextIngestResponse,
    GeneralChatSessionResponse, GeneralChatMessageItem, GeneralChatMessageSendRequest,
    BatchVisibilityUpdateRequest
)
from app.services.token_service import (
    check_ingestion_quota,
    record_ingestion_token_usage,
    record_chat_token_usage
)
from app.core.token_counter import count_chat_prompt_tokens, count_chat_completion_tokens
from datetime import datetime, timezone, timedelta

from app.rag.deps import get_ingestion_pipeline, get_llm, get_bm25_index, get_vector_store, get_generation_pipeline
from app.rag.services.interfaces import BaseLLMAdapter
from app.rag.router import (
    ingest_document, 
    ingest_text_only,
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
from app.rag.schemas import (
    EditApprovedDocumentRequest, 
    RefineRequest, 
    ChatMessage, 
    ChatRequest, 
    ChatResponse, 
    UserContext,
    TextIngestRequest
)

router = APIRouter(tags=["Knowledge"])

async def sanitize_knowledge_categories(db: AsyncSession, categories: Optional[List[Any]]) -> List[str]:
    """
    Safely sanitizes category lists against active database categories.
    Excludes any soft-deleted categories (Category.deleted_at is not None).
    """
    if not categories:
        return []
    try:
        stmt = select(Category.name).where(Category.deleted_at.is_(None))
        res = await db.execute(stmt)
        active_cats = {c.strip().lower(): c for c in res.scalars().all() if c}

        cleaned = []
        for cat in categories:
            if isinstance(cat, dict):
                c_name = str(cat.get("name") or "").strip()
            else:
                c_name = str(cat).strip()
            if c_name and c_name.lower() in active_cats:
                cleaned.append(active_cats[c_name.lower()])
        return cleaned
    except Exception as err:
        logger.warning(f"Error sanitizing knowledge categories: {err}")
        # Fallback to normalized strings if DB check fails
        return [str(c.get("name") if isinstance(c, dict) else c).strip() for c in categories if c]

def sanitize_history_turns(history_list: Optional[List[Any]], default_attachment: Optional[str] = None) -> List[Dict[str, Any]]:
    """Clean internal supplementary attachment tags and preserve attachmentName on user turns."""
    if not history_list or not isinstance(history_list, list):
        return []
    clean_list = []
    for item in history_list:
        if not isinstance(item, dict):
            clean_list.append(item)
            continue
        turn = dict(item)
        content = turn.get("content", "")
        if turn.get("role") == "user" and content and isinstance(content, str):
            supp_match = re.search(r"\[SUPPLEMENTARY ATTACHED FILE CONTENT:\s*['\"]?([^'\"\n]+)['\"]?\][\s\S]*?\[END OF ATTACHED FILE CONTENT\]", content, flags=re.IGNORECASE)
            if supp_match:
                att_name = supp_match.group(1).strip()
                if not turn.get("attachmentName"):
                    turn["attachmentName"] = att_name
                if not turn.get("attachmentNames"):
                    turn["attachmentNames"] = [att_name]
                content = content.replace(supp_match.group(0), "").strip()

            newly_match = re.search(r"---\s*NEWLY ATTACHED SUPPLEMENTARY FILE:\s*['\"]?([^'\"\n]+)['\"]?\s*---[\s\S]*?---\s*END OF ATTACHED FILE CONTENT\s*---", content, flags=re.IGNORECASE)
            if newly_match:
                att_name = newly_match.group(1).strip()
                if not turn.get("attachmentName"):
                    turn["attachmentName"] = att_name
                if not turn.get("attachmentNames"):
                    turn["attachmentNames"] = [att_name]
                content = content.replace(newly_match.group(0), "").strip()

            if default_attachment and not turn.get("attachmentName"):
                turn["attachmentName"] = default_attachment
                turn["attachmentNames"] = [default_attachment]

            turn["content"] = content
        clean_list.append(turn)
    return clean_list


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
        ChatSession.session_type == "GENERAL_ASSISTANT",
        ChatSession.user_id == current_user.id
    )
    res = await db.execute(stmt)
    session = res.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="General chat session not found")

    msg_stmt = select(DBChatMessage).where(
        DBChatMessage.session_id == session_id
    ).order_by(
        DBChatMessage.created_at.asc(),
        case((DBChatMessage.role == ChatRole.USER, 1), else_=2)
    )
    msg_res = await db.execute(msg_stmt)
    db_msgs = msg_res.scalars().all()

    # Collect all operation IDs to resolve their execution status (confirmed, cancelled, pending)
    op_ids = []
    for m in db_msgs:
        att = m.attachments or {}
        op_id_str = att.get("operation_id")
        if op_id_str:
            try:
                op_ids.append(uuid.UUID(str(op_id_str)))
            except Exception:
                pass

    op_status_map = {}
    if op_ids:
        op_stmt = select(PendingOperation).where(PendingOperation.id.in_(op_ids))
        op_res = await db.execute(op_stmt)
        for op_obj in op_res.scalars().all():
            op_status_map[str(op_obj.id)] = op_obj.status

    formatted_msgs = []
    for m in db_msgs:
        att = dict(m.attachments) if isinstance(m.attachments, dict) else {}
        op_id_str = att.get("operation_id")
        op_status = op_status_map.get(str(op_id_str)) if op_id_str else None
        if op_status:
            att["operation_status"] = op_status

        formatted_msgs.append(GeneralChatMessageItem(
            id=m.id,
            role=m.role.value.lower(),
            content=m.content,
            action=att.get("action"),
            type=att.get("type"),
            operation_id=op_id_str,
            operation_status=op_status,
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
        ChatSession.session_type == "GENERAL_ASSISTANT",
        ChatSession.user_id == current_user.id
    )
    res = await db.execute(stmt)
    session = res.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="General chat session not found")

    # Fetch existing conversation history with deterministic user-first tie-breaker
    msg_stmt = select(DBChatMessage).where(
        DBChatMessage.session_id == session_id
    ).order_by(
        DBChatMessage.created_at.asc(),
        case((DBChatMessage.role == ChatRole.USER, 1), else_=2)
    )
    msg_res = await db.execute(msg_stmt)
    db_msgs = msg_res.scalars().all()

    history_payload = [
        {"role": m.role.value.lower(), "content": m.content}
        for m in db_msgs
    ]

    now_utc = datetime.now(timezone.utc)

    # 1. Save User Message in PostgreSQL with explicit timestamp
    user_db_msg = DBChatMessage(
        session_id=session_id,
        role=ChatRole.USER,
        content=payload.prompt,
        attachments=payload.attachments,
        created_at=now_utc
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

    # 3. Save Assistant Message in PostgreSQL with sequenced timestamp (+100ms) to ensure chronological consistency
    assistant_att = {
        "action": ai_res.action,
        "type": ai_res.type,
        "operation_id": ai_res.operation_id,
        "target_knowledge_id": ai_res.target_knowledge_id,
        "total_found": ai_res.total_found
    }
    assistant_db_msg = DBChatMessage(
        session_id=session_id,
        role=ChatRole.ASSISTANT,
        content=ai_res.answer,
        attachments=assistant_att,
        created_at=now_utc + timedelta(milliseconds=100)
    )
    db.add(assistant_db_msg)
    await db.commit()

    # Record token usage for the active user
    in_tokens = count_chat_prompt_tokens(
        user_query=payload.prompt,
        history=history_payload
    )
    out_tokens = count_chat_completion_tokens(ai_res.answer or "")
    await record_chat_token_usage(
        db=db,
        user_id=current_user.id,
        branch_id=None,
        input_tokens=in_tokens,
        output_tokens=out_tokens
    )

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

@router.post("/operations/{operation_id}/confirm")
@router.post("/operations/{operation_id}/confirm/")
async def confirm_pending_operation(
    operation_id: uuid.UUID,
    session_id: Optional[uuid.UUID] = Query(None, description="Optional chat session to log confirmation"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:read")),
    pipeline = Depends(get_generation_pipeline),
    vector_store = Depends(get_vector_store),
    bm25 = Depends(get_bm25_index)
):
    """
    Explicitly confirm and execute a pending CRUD operation on the Knowledge Base.
    Guarantees deterministic CRUD execution without relying on LLM decisions.
    """
    from app.rag.services.general_knowledge_service import GeneralKnowledgeService

    stmt = select(PendingOperation).where(PendingOperation.id == operation_id)
    res = await db.execute(stmt)
    op = res.scalar_one_or_none()

    if not op:
        raise HTTPException(status_code=404, detail="Operasi tidak ditemukan atau telah kedaluwarsa.")

    now_utc = datetime.now(timezone.utc)

    if op.status == "confirmed":
        return {
            "type": "info",
            "action": f"{op.action}_applied",
            "operation_id": str(op.id),
            "target_knowledge_id": op.knowledge_id,
            "batch_id": op.batch_id,
            "message": "Operasi ini sudah pernah dikonfirmasi sebelumnya."
        }

    if op.status == "cancelled":
        return {
            "type": "cancelled",
            "action": "cancelled",
            "operation_id": str(op.id),
            "message": "Operasi ini telah dibatalkan sebelumnya."
        }

    if op.expires_at < now_utc:
        op.status = "expired"
        await db.commit()
        return {
            "type": "error",
            "action": f"{op.action}_expired",
            "operation_id": str(op.id),
            "message": "Operasi telah kedaluwarsa (melebihi batas waktu 30 menit). Silakan ulangi instruksi Anda di chat."
        }

    affected_kids = (op.metadata_ or {}).get("affected_knowledge_ids") or [op.knowledge_id]

    if op.action == "edit":
        edit_results = []
        for kid in affected_kids:
            res = await GeneralKnowledgeService.apply_edit(
                knowledge_id=kid,
                field=op.field or "summary",
                new_value=op.new_value or "",
                vector_store=vector_store,
                bm25_index=bm25,
                pipeline=pipeline,
                target_item=op.target_item,
                db=db,
                auto_approve=True  # General Prompt confirm = auto-approve, immediately active in RAG
            )
            edit_results.append(res)

        any_success = any(r.get("success") for r in edit_results)
        if any_success:
            op.status = "confirmed"
            op.confirmed_at = now_utc

            if len(affected_kids) > 1:
                success_msg = f"Changes to '{op.target_item or op.knowledge_id}' were successfully applied to {len(affected_kids)} Knowledge Base documents."
            else:
                success_msg = edit_results[0].get("message") or f"Changes to '{op.target_item or op.knowledge_id}' were successfully applied to the Knowledge Base."

            if session_id:
                try:
                    db.add(DBChatMessage(
                        session_id=session_id,
                        role=ChatRole.ASSISTANT,
                        content=success_msg,
                        attachments={"action": "edit_applied", "operation_id": str(op.id), "target_knowledge_id": op.knowledge_id, "affected_knowledge_ids": affected_kids},
                        created_at=now_utc + timedelta(milliseconds=100)
                    ))
                except Exception as e:
                    logger.warning(f"[ConfirmOp] Could not log to session {session_id}: {e}")

            await db.commit()
            return {
                "type": "success",
                "action": "edit_applied",
                "operation_id": str(op.id),
                "target_knowledge_id": op.knowledge_id,
                "affected_knowledge_ids": affected_kids,
                "batch_id": op.batch_id,
                "message": success_msg
            }
        else:
            errors = [r.get("error", "Unknown error") for r in edit_results if not r.get("success")]
            return {
                "type": "error",
                "action": "edit_failed",
                "operation_id": str(op.id),
                "message": f"Gagal menerapkan perubahan: {'; '.join(errors)}"
            }

    elif op.action == "delete":
        del_results = []
        meta_dict = op.metadata_ or {}
        affected_docs_map = {d["knowledge_id"]: d.get("target_item") for d in meta_dict.get("affected_docs", []) if isinstance(d, dict) and "knowledge_id" in d}

        for kid in affected_kids:
            doc_target = affected_docs_map.get(kid) or op.target_item
            res = await GeneralKnowledgeService.apply_delete(
                knowledge_id=kid,
                target_item=doc_target,
                vector_store=vector_store,
                bm25_index=bm25,
                db=db
            )
            del_results.append(res)

        any_success = any(r.get("success") for r in del_results)
        if any_success:
            op.status = "confirmed"
            op.confirmed_at = now_utc

            if len(affected_kids) > 1:
                success_msg = f"Item '{op.target_item or op.knowledge_id}' was successfully deleted from {len(affected_kids)} Knowledge Base documents."
            else:
                success_msg = del_results[0].get("message") or f"Item/document '{op.target_item or op.knowledge_id}' was successfully deleted from the Knowledge Base."

            if session_id:
                try:
                    db.add(DBChatMessage(
                        session_id=session_id,
                        role=ChatRole.ASSISTANT,
                        content=success_msg,
                        attachments={"action": "delete_applied", "operation_id": str(op.id), "target_knowledge_id": op.knowledge_id, "affected_knowledge_ids": affected_kids},
                        created_at=now_utc + timedelta(milliseconds=100)
                    ))
                except Exception as e:
                    logger.warning(f"[ConfirmOp] Could not log to session {session_id}: {e}")

            await db.commit()
            return {
                "type": "success",
                "action": "delete_applied",
                "operation_id": str(op.id),
                "target_knowledge_id": op.knowledge_id,
                "affected_knowledge_ids": affected_kids,
                "batch_id": op.batch_id,
                "message": success_msg
            }
        else:
            errors = [r.get("error", "Unknown error") for r in del_results if not r.get("success")]
            return {
                "type": "error",
                "action": "delete_failed",
                "operation_id": str(op.id),
                "message": f"Failed to delete item: {'; '.join(errors)}"
            }

    else:
        raise HTTPException(status_code=400, detail=f"Operation action '{op.action}' is not supported.")

@router.post("/operations/{operation_id}/cancel")
@router.post("/operations/{operation_id}/cancel/")
async def cancel_pending_operation(
    operation_id: uuid.UUID,
    session_id: Optional[uuid.UUID] = Query(None, description="Optional chat session to log cancellation"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:read"))
):
    """
    Explicitly cancel a pending CRUD operation.
    """
    stmt = select(PendingOperation).where(PendingOperation.id == operation_id)
    res = await db.execute(stmt)
    op = res.scalar_one_or_none()

    if not op:
        raise HTTPException(status_code=404, detail="Operation not found.")

    if op.status == "confirmed":
        return {
            "type": "info",
            "action": "already_confirmed",
            "operation_id": str(op.id),
            "message": "Operation has already been confirmed previously."
        }

    op.status = "cancelled"
    now_utc = datetime.now(timezone.utc)

    if session_id:
        try:
            db.add(DBChatMessage(
                session_id=session_id,
                role=ChatRole.ASSISTANT,
                content="Operation cancelled. No changes were applied to the Knowledge Base.",
                attachments={"action": "cancelled", "operation_id": str(op.id)},
                created_at=now_utc + timedelta(milliseconds=100)
            ))
        except Exception as e:
            logger.warning(f"[CancelOp] Could not log to session {session_id}: {e}")

    await db.commit()
    return {
        "type": "cancelled",
        "action": "cancelled",
        "operation_id": str(op.id),
        "message": "Operation successfully cancelled. No changes were made to the Knowledge Base."
    }

from app.schemas.pagination import PaginatedResponse
from typing import List, Optional, Union
import math

@router.get("/", response_model=Union[PaginatedResponse[KnowledgeResponse], List[KnowledgeResponse]])
async def list_knowledge(
    project_id: Optional[uuid.UUID] = Query(None, description="Optional project filter"),
    search: Optional[str] = Query(None, description="Optional text search query"),
    status: Optional[str] = Query(None, description="Optional status filter"),
    page: Optional[int] = Query(None, ge=1, description="Page number"),
    page_size: Optional[int] = Query(None, ge=1, le=100, description="Items per page"),
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
    del_proj_stmt = select(Project.id).where(Project.deleted_at.is_not(None))
    del_proj_res = await db.execute(del_proj_stmt)
    deleted_proj_ids = set(del_proj_res.scalars().all())

    db_by_id = {str(item.id): item for item in db_items}
    updated_db = False
    db_responses: List[KnowledgeResponse] = []

    for item in db_items:
        if item.project_id and item.project_id in deleted_proj_ids:
            item.project_id = None
            updated_db = True

    for item in db_items:
        k_id_str = str(item.id)
        if item.status == KnowledgeStatus.APPROVED:
            target_file = resolve_approved_file(k_id_str)
        else:
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
    
    # Query soft-deleted IDs to prevent zombie resurrection (match strictly by unique UUID)
    del_stmt = select(Knowledge.id).where(Knowledge.deleted_at.is_not(None))
    del_res = await db.execute(del_stmt)
    deleted_records = del_res.all()
    deleted_ids = {str(row[0]).lower() for row in deleted_records}
    
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
                            
                            # Clean up and skip if this matches a soft-deleted UUID
                            if raw_id in deleted_ids:
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

    all_items = db_responses + staged_responses

    # Sanitize categories across all returned items to exclude soft-deleted records
    try:
        cat_stmt = select(Category.name).where(Category.deleted_at.is_(None))
        cat_res = await db.execute(cat_stmt)
        active_cat_set = {c.strip().lower(): c for c in cat_res.scalars().all() if c}
        for item in all_items:
            if isinstance(item.metadata_, dict):
                if "categories" in item.metadata_ and isinstance(item.metadata_["categories"], list):
                    item.metadata_["categories"] = [
                        active_cat_set[str(c.get("name") if isinstance(c, dict) else c).strip().lower()]
                        for c in item.metadata_["categories"]
                        if str(c.get("name") if isinstance(c, dict) else c).strip().lower() in active_cat_set
                    ]
                if "suggested_categories" in item.metadata_ and isinstance(item.metadata_["suggested_categories"], list):
                    item.metadata_["suggested_categories"] = [
                        active_cat_set[str(c.get("name") if isinstance(c, dict) else c).strip().lower()]
                        for c in item.metadata_["suggested_categories"]
                        if str(c.get("name") if isinstance(c, dict) else c).strip().lower() in active_cat_set
                    ]
    except Exception as err:
        logger.warning(f"Error sanitizing categories in list_knowledge: {err}")

    if status and status != "ALL":
        all_items = [item for item in all_items if item.status == status]

    if search:
        s_clean = search.lower().strip()
        all_items = [
            item for item in all_items
            if s_clean in (item.title or "").lower()
            or s_clean in (item.file_name or "").lower()
            or s_clean in (item.ai_summary or "").lower()
            or s_clean in (item.content or "").lower()
        ]

    if page is not None:
        p_size = page_size or 10
        total = len(all_items)
        total_pages = max(1, math.ceil(total / p_size))
        start_idx = (page - 1) * p_size
        items = all_items[start_idx : start_idx + p_size]

        return PaginatedResponse[KnowledgeResponse](
            items=items,
            total=total,
            page=page,
            page_size=p_size,
            total_pages=total_pages
        )

    return all_items

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
            if knowledge.status == KnowledgeStatus.APPROVED:
                target_file = resolve_approved_file(str(knowledge_id))
            else:
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
                    # If document is actively processing, keep active history empty so no stale bubbles render
                    if knowledge.status == KnowledgeStatus.PROCESSING:
                        merged_meta["history"] = []
                        merged_meta["chat_history"] = []
                    # If approved, ensure active history is clean while staging_history and edit_history are retained
                    elif knowledge.status == KnowledgeStatus.APPROVED:
                        merged_meta["history"] = []
                        merged_meta["chat_history"] = []
                        db_edit_hist = knowledge.metadata_.get("edit_history") if isinstance(knowledge.metadata_, dict) else []
                        file_edit_hist = data.get("edit_history") if isinstance(data, dict) else []
                        merged_meta["edit_history"] = sanitize_history_turns(db_edit_hist if len(db_edit_hist or []) >= len(file_edit_hist or []) else file_edit_hist)

                        db_stage_hist = knowledge.metadata_.get("staging_history") if isinstance(knowledge.metadata_, dict) else []
                        file_stage_hist = data.get("staging_history") if isinstance(data, dict) else []
                        merged_meta["staging_history"] = db_stage_hist if len(db_stage_hist or []) >= len(file_stage_hist or []) else file_stage_hist
                    else:
                        db_hist = knowledge.metadata_.get("history") if isinstance(knowledge.metadata_, dict) else []
                        file_hist = data.get("history") if isinstance(data, dict) else []
                        merged_meta["history"] = sanitize_history_turns(db_hist if len(db_hist or []) >= len(file_hist or []) else file_hist)
                        merged_meta["chat_history"] = merged_meta["history"]
                        if isinstance(knowledge.metadata_, dict):
                            if "initial_summary" not in merged_meta and "initial_summary" in knowledge.metadata_:
                                merged_meta["initial_summary"] = knowledge.metadata_["initial_summary"]
                            if "initial_prompt" not in merged_meta and "initial_prompt" in knowledge.metadata_:
                                merged_meta["initial_prompt"] = knowledge.metadata_["initial_prompt"]
                    if "categories" in merged_meta:
                        merged_meta["categories"] = await sanitize_knowledge_categories(db, merged_meta.get("categories"))
                    if "suggested_categories" in merged_meta:
                        merged_meta["suggested_categories"] = await sanitize_knowledge_categories(db, merged_meta.get("suggested_categories"))
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
                if "categories" in data:
                    data["categories"] = await sanitize_knowledge_categories(db, data.get("categories"))
                if "suggested_categories" in data:
                    data["suggested_categories"] = await sanitize_knowledge_categories(db, data.get("suggested_categories"))
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
                merged_meta = {**db_meta, **data}
                if "history" in merged_meta:
                    merged_meta["history"] = sanitize_history_turns(merged_meta["history"])
                    merged_meta["chat_history"] = merged_meta["history"]
                if "edit_history" in merged_meta:
                    merged_meta["edit_history"] = sanitize_history_turns(merged_meta["edit_history"])
                knowledge_dict["metadata_"] = merged_meta
                # Sync status from pending/output files
                new_status = KnowledgeStatus.APPROVED if "output" in target_file else KnowledgeStatus.PENDING
                if knowledge_dict.get("status") != new_status and knowledge_dict.get("status") != KnowledgeStatus.APPROVED:
                    knowledge_dict["status"] = new_status
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

                                    if "history" in data:
                                        data["history"] = sanitize_history_turns(data["history"])
                                        data["chat_history"] = data["history"]
                                    if "edit_history" in data:
                                        data["edit_history"] = sanitize_history_turns(data["edit_history"])

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

    # Check if ANY document in batch is still actively PROCESSING
    is_any_processing = any(
        (doc.get("status") if isinstance(doc, dict) else getattr(doc, "status", None)) == KnowledgeStatus.PROCESSING
        for doc in enriched_docs
    )

    # Synthesize unified batch executive summary if multiple documents and NOT ANY doc is still processing
    if len(enriched_docs) >= 2 and not is_any_processing and llm:
        # Check if ALL non-failed documents already have a consistent batch summary
        has_full_batch_summary = all(
            bool((doc.get("metadata_") if isinstance(doc, dict) else (doc.metadata_ or {})).get("batch_summary"))
            for doc in enriched_docs
            if (doc.get("status") if isinstance(doc, dict) else getattr(doc, "status", None)) != KnowledgeStatus.REJECTED
        )
        if not has_full_batch_summary:
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

    # MinIO Staging Scan fallback for batch_id
    try:
        from app.services.storage import _get_client, _staging_bucket
        s3 = _get_client()
        if s3:
            res_s3 = s3.list_objects_v2(Bucket=_staging_bucket())
            for obj in res_s3.get("Contents", []):
                k = obj["Key"]
                if k.endswith(".json"):
                    try:
                        resp = s3.get_object(Bucket=_staging_bucket(), Key=k)
                        data = json.loads(resp["Body"].read().decode("utf-8"))
                        b_id = data.get("batch_id") or data.get("upload_batch_id")
                        if not b_id and data.get("chunks"):
                            b_id = data["chunks"][0].get("metadata", {}).get("batch_id") or data["chunks"][0].get("metadata", {}).get("upload_batch_id")
                        if b_id == batch_id:
                            k_id = data.get("knowledge_id") or k.replace(".json", "")
                            if k_id:
                                target_ids.add(str(k_id))
                    except Exception:
                        pass
    except Exception:
        pass

    if not target_ids:
        # Fallback to batch_id directly so approve_document can expand it
        target_ids.add(batch_id)

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

    # Sync DB statuses for all matched documents
    from sqlalchemy.orm.attributes import flag_modified
    approved_ids = res.get("approved_ids", []) if isinstance(res, dict) else []
    for aid in approved_ids:
        try:
            aid_uuid = uuid.UUID(aid)
            stmt_u = select(Knowledge).where(Knowledge.id == aid_uuid)
            res_u = await db.execute(stmt_u)
            doc_u = res_u.scalar_one_or_none()
            if doc_u:
                doc_u.status = KnowledgeStatus.APPROVED
                doc_u.approved_by = current_user.id
                
                # Sync finalized summary, content, and title from approved output
                a_file = resolve_approved_file(aid)
                if a_file and os.path.exists(a_file):
                    try:
                        with open(a_file, "r", encoding="utf-8") as af:
                            a_data = json.load(af)
                        if isinstance(a_data, dict):
                            if a_data.get("summary"):
                                doc_u.ai_summary = a_data.get("summary")
                                doc_u.content = a_data.get("summary")
                            if a_data.get("title"):
                                doc_u.title = a_data.get("title")
                            if a_data.get("categories"):
                                doc_u.metadata_ = doc_u.metadata_ or {}
                                doc_u.metadata_["categories"] = a_data.get("categories")
                    except Exception:
                        pass

                if aid in doc_histories:
                    if doc_u.metadata_ is None:
                        doc_u.metadata_ = {}
                    doc_u.metadata_["history"] = doc_histories[aid]
                    doc_u.metadata_["chat_history"] = doc_histories[aid]
                    flag_modified(doc_u, "metadata_")
        except Exception:
            pass

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

@router.put("/batch/{batch_id}/visibility")
async def update_batch_visibility(
    request: Request,
    batch_id: str,
    payload: BatchVisibilityUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:write"))
):
    """Update visibility settings for all documents in a batch ingestion session with MinIO as source of truth."""
    from sqlalchemy.orm.attributes import flag_modified
    from app.services.storage import (
        _get_client, _staging_bucket, _approved_bucket,
        get_staging_json, get_approved_json,
        upload_staging_json, upload_approved_json
    )

    # 1. Query Postgres DB for documents in this batch
    stmt = select(Knowledge).where(
        Knowledge.deleted_at.is_(None),
        or_(
            Knowledge.metadata_.op("->>")("batch_id") == batch_id,
            Knowledge.metadata_.op("->>")("upload_batch_id") == batch_id
        )
    )
    result = await db.execute(stmt)
    db_docs = list(result.scalars().all())

    vis_dict = payload.visibility_settings
    target_ids = set()
    for d in db_docs:
        target_ids.add(str(d.id))

    # 2. MinIO-First Scan: Find all batch documents directly from MinIO buckets
    try:
        s3 = _get_client()
        if s3:
            # Check staging bucket in MinIO
            res_staging = s3.list_objects_v2(Bucket=_staging_bucket())
            for obj in res_staging.get("Contents", []):
                k = obj["Key"]
                if k.endswith(".json"):
                    try:
                        resp = s3.get_object(Bucket=_staging_bucket(), Key=k)
                        data = json.loads(resp["Body"].read().decode("utf-8"))
                        b_id = data.get("batch_id") or data.get("upload_batch_id")
                        if not b_id and data.get("chunks"):
                            b_id = data["chunks"][0].get("metadata", {}).get("batch_id") or data["chunks"][0].get("metadata", {}).get("upload_batch_id")
                        if b_id == batch_id:
                            k_id = data.get("knowledge_id") or k.replace(".json", "")
                            if k_id:
                                target_ids.add(str(k_id))
                    except Exception:
                        pass

            # Check approved bucket in MinIO
            res_approved = s3.list_objects_v2(Bucket=_approved_bucket())
            for obj in res_approved.get("Contents", []):
                k = obj["Key"]
                if k.endswith(".json"):
                    try:
                        resp = s3.get_object(Bucket=_approved_bucket(), Key=k)
                        data = json.loads(resp["Body"].read().decode("utf-8"))
                        b_id = data.get("batch_id") or data.get("upload_batch_id")
                        if not b_id and data.get("chunks"):
                            b_id = data["chunks"][0].get("metadata", {}).get("batch_id") or data["chunks"][0].get("metadata", {}).get("upload_batch_id")
                        if b_id == batch_id:
                            k_id = data.get("knowledge_id") or k.replace(".json", "")
                            if k_id:
                                target_ids.add(str(k_id))
                    except Exception:
                        pass
    except Exception as s3_scan_err:
        logger.debug(f"MinIO batch scan note: {s3_scan_err}")

    # Fallback scan of local pending directory if MinIO was empty or offline
    pending_dir = "data/pending"
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

    # 3. Update MinIO Objects (Source of Truth) for all identified documents
    for tid in target_ids:
        # A. Update Staging JSON (MinIO 'staging' bucket as source of truth)
        p_data = get_staging_json(tid)
        if p_data:
            p_data["visibility_settings"] = vis_dict
            if isinstance(p_data.get("chunks"), list):
                for ch in p_data["chunks"]:
                    if isinstance(ch, dict):
                        if "metadata" not in ch or not isinstance(ch["metadata"], dict):
                            ch["metadata"] = {}
                        ch["metadata"]["clinics"] = vis_dict.get("clinics", ["all"])
                        ch["metadata"]["doctor_types"] = vis_dict.get("doctor_types", ["all"])
                        ch["metadata"]["doctors"] = vis_dict.get("doctors", ["all"])
                        ch["metadata"]["visibility_settings"] = vis_dict
            upload_staging_json(tid, p_data)

        # B. Update Approved JSON (MinIO 'approved' bucket as source of truth)
        a_data = get_approved_json(tid)
        if a_data:
            a_data["visibility_settings"] = vis_dict
            if isinstance(a_data.get("chunks"), list):
                for ch in a_data["chunks"]:
                    if isinstance(ch, dict):
                        if "metadata" not in ch or not isinstance(ch["metadata"], dict):
                            ch["metadata"] = {}
                        ch["metadata"]["clinics"] = vis_dict.get("clinics", ["all"])
                        ch["metadata"]["doctor_types"] = vis_dict.get("doctor_types", ["all"])
                        ch["metadata"]["doctors"] = vis_dict.get("doctors", ["all"])
                        ch["metadata"]["visibility_settings"] = vis_dict
            upload_approved_json(tid, a_data)

    # 4. Sync PostgreSQL database records and chunks metadata
    for doc in db_docs:
        if doc.metadata_ is None:
            doc.metadata_ = {}
        doc.metadata_["visibility_settings"] = vis_dict
        if isinstance(doc.metadata_.get("chunks"), list):
            for ch in doc.metadata_["chunks"]:
                if isinstance(ch, dict):
                    if "metadata" not in ch or not isinstance(ch["metadata"], dict):
                        ch["metadata"] = {}
                    ch["metadata"]["clinics"] = vis_dict.get("clinics", ["all"])
                    ch["metadata"]["doctor_types"] = vis_dict.get("doctor_types", ["all"])
                    ch["metadata"]["doctors"] = vis_dict.get("doctors", ["all"])
                    ch["metadata"]["visibility_settings"] = vis_dict
        flag_modified(doc, "metadata_")

    await db.commit()
    return {
        "status": "success",
        "message": f"Updated visibility settings for {len(target_ids) or len(db_docs)} document(s) in batch",
        "batch_id": batch_id,
        "visibility_settings": vis_dict
    }

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
    "image/jpg",
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
    replace_existing: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:write")),
    llm: BaseLLMAdapter = Depends(get_llm)
):
    upload_list = file if isinstance(file, list) else [file]
    for target_file in upload_list:
        raw_ctype = (target_file.content_type or "").lower().strip()
        if raw_ctype not in ALLOWED_MIME_TYPES:
            guessed_type, _ = mimetypes.guess_type(target_file.filename or "")
            if not guessed_type or guessed_type.lower().strip() not in ALLOWED_MIME_TYPES:
                raise HTTPException(
                    status_code=400,
                    detail=f"File type '{target_file.content_type}' not allowed for file '{target_file.filename}'. Allowed types: PDF, Word, Excel, PowerPoint, Text, CSV, and Images."
                )
        
    # Check monthly ingestion quota (soft warning / notice model for Staff/Admin)
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
    await record_chat_token_usage(
        db=db,
        user_id=current_user.id,
        branch_id=None,
        input_tokens=estimated_doc_tokens,
        output_tokens=200 * len(upload_list)
    )

    ingest_res = await ingest_document(
        background_tasks=background_tasks,
        file=file,
        prompt=prompt,
        replace_existing=replace_existing,
        pipeline=pipeline,
        llm=llm
    )

    if isinstance(ingest_res, dict):
        docs = ingest_res.get("documents", [])
        batch_id = ingest_res.get("batch_id")
        for doc in docs:
            k_id = doc.get("knowledge_id")
            if k_id:
                try:
                    k_uuid = uuid.UUID(str(k_id))
                    stmt = select(Knowledge).where(Knowledge.id == k_uuid)
                    res = await db.execute(stmt)
                    k_obj = res.scalar_one_or_none()
                    if k_obj:
                        modified = False
                        if k_obj.metadata_ is None:
                            k_obj.metadata_ = {}
                        # Clear stale chat history and prior feedback from re-uploaded or replaced documents
                        k_obj.metadata_["history"] = []
                        k_obj.metadata_["chat_history"] = []
                        k_obj.metadata_["staging_history"] = []
                        k_obj.metadata_["edit_history"] = []
                        k_obj.metadata_.pop("feedback", None)
                        k_obj.metadata_.pop("batch_summary", None)
                        k_obj.metadata_.pop("initial_summary", None)

                        if batch_id:
                            k_obj.metadata_["batch_id"] = batch_id
                            modified = True
                        if project_id:
                            k_obj.project_id = project_id
                            modified = True
                        if prompt and str(prompt).strip():
                            k_obj.metadata_["initial_prompt"] = str(prompt).strip()
                        else:
                            k_obj.metadata_.pop("initial_prompt", None)
                        from sqlalchemy.orm.attributes import flag_modified
                        flag_modified(k_obj, "metadata_")
                        modified = True
                        if modified:
                            await db.commit()
                except Exception as up_err:
                    logger.warning(f"Error updating knowledge record after upload: {up_err}")

    return ingest_res

@router.post("/text", response_model=KnowledgeTextIngestResponse, status_code=status.HTTP_202_ACCEPTED)
@router.post("/text/", response_model=KnowledgeTextIngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_knowledge_text_endpoint(
    request: Request,
    payload: KnowledgeTextIngestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:write")),
    llm: BaseLLMAdapter = Depends(get_llm)
):
    """
    Ingest raw knowledge text material directly without requiring a file attachment.
    Converts raw text into structured markdown, checks duplicates, uploads to MinIO,
    and initializes background staging for approval review.
    """
    if not payload.text_content or not payload.text_content.strip():
        raise HTTPException(status_code=400, detail="Text content cannot be empty.")

    # 1. Check monthly ingestion quota (soft warning / notice model for Staff/Admin)
    allowed, quota_info = await check_ingestion_quota(db)
    if quota_info.get("exceeded"):
        logger.warning(f"Monthly knowledge ingestion threshold exceeded ({quota_info['tokens_used']:,} / {quota_info['token_limit']:,} tokens). Ingestion proceeding with soft warning.")
    elif quota_info.get("warning"):
        logger.info(f"Monthly knowledge ingestion threshold near limit ({quota_info['percentage']}% used).")

    # 2. Record estimated ingestion token usage
    estimated_tokens = max(100, len(payload.text_content.split()) * 2)
    await record_ingestion_token_usage(
        db=db,
        input_tokens=estimated_tokens,
        output_tokens=150,
        documents_count=1
    )
    await record_chat_token_usage(
        db=db,
        user_id=current_user.id,
        branch_id=None,
        input_tokens=estimated_tokens,
        output_tokens=150
    )

    pipeline = get_ingestion_pipeline(request)
    rag_req = TextIngestRequest(
        text_content=payload.text_content,
        title=payload.title,
        prompt=payload.prompt,
        replace_existing=payload.replace_existing
    )

    ingest_res = await ingest_text_only(
        req=rag_req,
        pipeline=pipeline,
        llm=llm
    )

    # 3. Associate project_id & uploaded_by if provided
    k_id = ingest_res.get("knowledge_id")
    if k_id:
        try:
            k_uuid = uuid.UUID(str(k_id))
            stmt = select(Knowledge).where(Knowledge.id == k_uuid)
            res = await db.execute(stmt)
            k_obj = res.scalar_one_or_none()
            if k_obj:
                k_obj.uploaded_by = current_user.id
                if payload.project_id:
                    k_obj.project_id = payload.project_id
                await db.commit()

            # Keep project_id in pending JSON file in sync
            if payload.project_id:
                p_file = resolve_pending_file(str(k_id))
                if p_file and os.path.exists(p_file):
                    try:
                        with open(p_file, "r", encoding="utf-8") as pf:
                            pj_data = json.load(pf)
                        if isinstance(pj_data, dict):
                            pj_data["project_id"] = str(payload.project_id)
                            with open(p_file, "w", encoding="utf-8") as pf:
                                json.dump(pj_data, pf, indent=4, ensure_ascii=False)
                    except Exception:
                        pass
        except Exception as err:
            logger.warning(f"Could not link user or project to text ingestion: {err}")

    return KnowledgeTextIngestResponse(
        status=ingest_res.get("status", "success"),
        knowledge_id=str(k_id),
        file_name=ingest_res.get("file_name", ""),
        title=ingest_res.get("title", ""),
        original_s3_key=ingest_res.get("original_s3_key"),
        message=ingest_res.get("message", "Document text ingestion initiated.")
    )

@router.post("/{knowledge_id}/replace-file", status_code=status.HTTP_202_ACCEPTED)
async def replace_knowledge_file_endpoint(
    knowledge_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    prompt: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RequireAccess("knowledge:write")),
    llm: BaseLLMAdapter = Depends(get_llm)
):
    """
    Replace the file attachment of a specific Knowledge Document (e.g. after a parsing failure or rejected draft)
    and re-trigger the background parsing and AI generation pipeline in-place.
    """
    stmt = select(Knowledge).where(Knowledge.id == knowledge_id, Knowledge.deleted_at.is_(None))
    res = await db.execute(stmt)
    k_entry = res.scalar_one_or_none()
    if not k_entry:
        raise HTTPException(status_code=404, detail="Knowledge document not found.")

    raw_ctype = (file.content_type or "").lower().strip()
    if raw_ctype not in ALLOWED_MIME_TYPES:
        guessed_type, _ = mimetypes.guess_type(file.filename or "")
        if not guessed_type or guessed_type.lower().strip() not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"File type '{file.content_type}' not allowed for file '{file.filename}'. Allowed types: PDF, Word, Excel, PowerPoint, Text, CSV, and Images."
            )

    pipeline = get_ingestion_pipeline(request)
    
    # Update DB record status back to PROCESSING and reset previous error
    k_entry.status = KnowledgeStatus.PROCESSING
    k_entry.file_name = file.filename
    if k_entry.metadata_ is None:
        k_entry.metadata_ = {}
    k_entry.metadata_["error"] = None
    k_entry.metadata_["status"] = "PROCESSING"
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(k_entry, "metadata_")
    await db.commit()

    # Trigger ingest_document with replace_existing=True
    effective_prompt = prompt or (k_entry.metadata_.get("initial_prompt") if isinstance(k_entry.metadata_, dict) else None)
    ingest_res = await ingest_document(
        background_tasks=background_tasks,
        file=[file],
        prompt=effective_prompt,
        replace_existing=True,
        pipeline=pipeline,
        llm=llm
    )

    return {
        "status": "success",
        "knowledge_id": str(knowledge_id),
        "file_name": file.filename,
        "message": "File replacement initiated. Document is now re-processing in background."
    }

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
        
        # Read the newly approved document to sync finalized summary, content, and title to DB
        a_file = resolve_approved_file(str(knowledge_id))
        if a_file and os.path.exists(a_file):
            try:
                with open(a_file, "r", encoding="utf-8") as af:
                    a_data = json.load(af)
                if isinstance(a_data, dict):
                    if a_data.get("summary"):
                        k_entry.ai_summary = a_data.get("summary")
                        k_entry.content = a_data.get("summary")
                    if a_data.get("title"):
                        k_entry.title = a_data.get("title")
                    if a_data.get("categories"):
                        k_entry.metadata_ = k_entry.metadata_ or {}
                        k_entry.metadata_["categories"] = a_data.get("categories")
                    if a_data.get("chunks"):
                        k_entry.metadata_ = k_entry.metadata_ or {}
                        k_entry.metadata_["chunks"] = a_data.get("chunks")
            except Exception as read_err:
                logger.debug(f"Note syncing approved file to DB: {read_err}")

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
        m_dict = dict(k_entry.metadata_) if isinstance(k_entry.metadata_, dict) else {}
        if k_entry.status == KnowledgeStatus.APPROVED:
            a_file = os.path.join("data/output", f"{knowledge_id}.json")
            os.makedirs("data/output", exist_ok=True)
            doc_data = {
                "knowledge_id": str(knowledge_id),
                "batch_id": m_dict.get("batch_id"),
                "file_name": k_entry.file_name or str(knowledge_id),
                "title": k_entry.title or k_entry.file_name or "Knowledge Document",
                "status": "Approved",
                "summary": k_entry.ai_summary or "",
                "initial_prompt": m_dict.get("initial_prompt"),
                "staging_history": m_dict.get("staging_history", []),
                "edit_history": m_dict.get("edit_history", []),
                "timing_metrics": m_dict.get("timing_metrics"),
                "batch_summary": m_dict.get("batch_summary"),
                "image_urls": m_dict.get("image_urls", []),
                "categories": m_dict.get("categories", []),
                "visibility_settings": m_dict.get("visibility_settings", {"clinics": ["all"], "doctor_types": ["all"], "doctors": ["all"]}),
                "chunks": m_dict.get("chunks", [{"text": k_entry.ai_summary or k_entry.title or "", "metadata": {"knowledge_id": str(knowledge_id)}}])
            }
            with open(a_file, "w", encoding="utf-8") as f:
                json.dump(doc_data, f, indent=4, ensure_ascii=False)
            try:
                from app.services.storage import upload_approved_json
                upload_approved_json(str(knowledge_id), doc_data)
            except Exception:
                pass
        else:
            p_file = os.path.join("data/pending", f"{knowledge_id}.json")
            os.makedirs("data/pending", exist_ok=True)
            doc_data = {
                "knowledge_id": str(knowledge_id),
                "batch_id": m_dict.get("batch_id"),
                "file_name": k_entry.file_name or str(knowledge_id),
                "title": k_entry.title or k_entry.file_name or "Knowledge Document",
                "status": "On review",
                "summary": k_entry.ai_summary or "",
                "initial_prompt": m_dict.get("initial_prompt"),
                "history": m_dict.get("history", []),
                "staging_history": m_dict.get("staging_history", []),
                "timing_metrics": m_dict.get("timing_metrics"),
                "batch_summary": m_dict.get("batch_summary"),
                "image_urls": m_dict.get("image_urls", []),
                "suggested_categories": m_dict.get("suggested_categories", []),
                "chunks": m_dict.get("chunks", [{"text": k_entry.ai_summary or k_entry.title or "", "metadata": {"knowledge_id": str(knowledge_id)}}])
            }
            with open(p_file, "w", encoding="utf-8") as f:
                json.dump(doc_data, f, indent=4, ensure_ascii=False)
            try:
                from app.services.storage import upload_staging_json
                upload_staging_json(str(knowledge_id), doc_data)
            except Exception:
                pass

    # 1. Update or create staging draft in data/pending/{knowledge_id}.json with latest payload & refined draft content
    staged_data = {}
    if p_file and os.path.exists(p_file):
        try:
            with open(p_file, "r", encoding="utf-8") as pf:
                staged_data = json.load(pf)
        except Exception as read_p_err:
            logger.warning(f"Failed to read staging draft for edit: {read_p_err}")
    elif a_file and os.path.exists(a_file):
        try:
            with open(a_file, "r", encoding="utf-8") as af:
                staged_data = json.load(af)
        except Exception as read_a_err:
            logger.warning(f"Failed to read approved JSON for edit: {read_a_err}")

    # Determine final summary, title, categories, visibility, and chunks
    staged_sum = staged_data.get("summary", "")
    hist = staged_data.get("history") or staged_data.get("edit_history") or []
    if isinstance(hist, list):
        for turn in reversed(hist):
            if isinstance(turn, dict) and turn.get("role") == "assistant" and turn.get("content"):
                if len(turn["content"]) > 50 and "\n" in turn["content"]:
                    staged_sum = turn["content"]
                    break

    if payload.summary and payload.summary.strip() and payload.summary != (k_entry.ai_summary or ""):
        final_summary = payload.summary
    else:
        final_summary = staged_sum or staged_data.get("summary", "") or (k_entry.ai_summary if k_entry else "")

    final_title = (payload.title.strip() if (payload.title and payload.title.strip()) else None) or staged_data.get("title") or (k_entry.title if k_entry else "Knowledge Document")
    final_categories = payload.categories if (payload.categories is not None and len(payload.categories) > 0) else staged_data.get("categories", staged_data.get("suggested_categories", []))
    final_vis = payload.visibility_settings.model_dump() if payload.visibility_settings else staged_data.get("visibility_settings", {"clinics": ["all"], "doctor_types": ["all"], "doctors": ["all"]})
    final_chunks = payload.chunks if (payload.chunks is not None and len(payload.chunks) > 0) else staged_data.get("chunks")

    # Update staged_data dictionary
    staged_data["knowledge_id"] = str(knowledge_id)
    staged_data["title"] = final_title
    staged_data["summary"] = final_summary
    staged_data["categories"] = final_categories
    staged_data["suggested_categories"] = final_categories
    staged_data["visibility_settings"] = final_vis
    if final_chunks:
        staged_data["chunks"] = final_chunks

    # Save to data/pending/{knowledge_id}.json so approve_document can promote it
    os.makedirs("data/pending", exist_ok=True)
    pending_file = os.path.join("data/pending", f"{knowledge_id}.json")
    with open(pending_file, "w", encoding="utf-8") as pf:
        json.dump(staged_data, pf, indent=4, ensure_ascii=False)

    try:
        from app.services.storage import upload_staging_json
        upload_staging_json(str(knowledge_id), staged_data)
    except Exception:
        pass

    # 2. Execute full RAG approval/promotion pipeline: promote JSON to output/ & MinIO, update PostgreSQL DB, re-index PGVector & BM25
    res = await approve_document(
        knowledge_id=str(knowledge_id),
        pipeline=pipeline,
        bm25=bm25
    )

    # Sync updates back to the PostgreSQL DB row for both approved and pending documents
    if k_entry:
        if payload.title or (isinstance(res, dict) and res.get("title")):
            k_entry.title = (res.get("title") if isinstance(res, dict) and res.get("title") else payload.title) or k_entry.title
        if payload.summary or (isinstance(res, dict) and res.get("summary")):
            final_sum = (res.get("summary") if isinstance(res, dict) and res.get("summary") else payload.summary) or k_entry.ai_summary
            k_entry.ai_summary = final_sum
            k_entry.content = final_sum

        k_entry.type = KnowledgeType.GENERAL
            
        if k_entry.metadata_ is None:
            k_entry.metadata_ = {}

        existing_meta = dict(k_entry.metadata_) if isinstance(k_entry.metadata_, dict) else {}
            
        if payload.categories is not None:
            sanitized_cats = await sanitize_knowledge_categories(db, payload.categories)
            k_entry.metadata_["categories"] = sanitized_cats
        elif isinstance(res, dict) and res.get("categories"):
            sanitized_cats = await sanitize_knowledge_categories(db, res.get("categories"))
            k_entry.metadata_["categories"] = sanitized_cats
            
        if payload.visibility_settings is not None:
            k_entry.metadata_["visibility_settings"] = payload.visibility_settings.model_dump()
        elif isinstance(res, dict) and res.get("visibility_settings"):
            k_entry.metadata_["visibility_settings"] = res.get("visibility_settings")
            
        # Ensure batch_id, chunks, images, and image_urls from res are preserved
        if isinstance(res, dict):
            if res.get("batch_id") and "batch_id" not in k_entry.metadata_:
                k_entry.metadata_["batch_id"] = res["batch_id"]
            if payload.chunks:
                k_entry.metadata_["chunks"] = payload.chunks
            elif res.get("chunks"):
                k_entry.metadata_["chunks"] = res["chunks"]

            # Cascade current visibility settings and document categories to all DB chunks
            current_vis = k_entry.metadata_.get("visibility_settings") or {"clinics": ["all"], "doctor_types": ["all"], "doctors": ["all"]}
            current_cats = k_entry.metadata_.get("categories") or []
            if isinstance(k_entry.metadata_.get("chunks"), list):
                for ch in k_entry.metadata_["chunks"]:
                    if isinstance(ch, dict):
                        if "metadata" not in ch or not isinstance(ch["metadata"], dict):
                            ch["metadata"] = {}
                        ch["metadata"]["clinics"] = current_vis.get("clinics", ["all"])
                        ch["metadata"]["doctor_types"] = current_vis.get("doctor_types", ["all"])
                        ch["metadata"]["doctors"] = current_vis.get("doctors", ["all"])
                        ch["metadata"]["visibility_settings"] = current_vis
                        ch["metadata"]["categories"] = current_cats
                        ch["metadata"]["category"] = current_cats[0] if current_cats else ""

            if res.get("image_urls") and "image_urls" not in k_entry.metadata_:
                k_entry.metadata_["image_urls"] = res["image_urls"]
            if res.get("images") and "images" not in k_entry.metadata_:
                k_entry.metadata_["images"] = res["images"]
            if res.get("edit_history"):
                k_entry.metadata_["edit_history"] = res["edit_history"]
            if res.get("staging_history"):
                k_entry.metadata_["staging_history"] = res["staging_history"]

        # Ensure existing images array with granular role metadata and image_urls in DB metadata are never lost
        if "images" not in k_entry.metadata_ and "images" in existing_meta:
            k_entry.metadata_["images"] = existing_meta["images"]
        if "image_urls" not in k_entry.metadata_ and "image_urls" in existing_meta:
            k_entry.metadata_["image_urls"] = existing_meta["image_urls"]

        # Ensure SQLAlchemy sees the mutation in the JSON column
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(k_entry, "metadata_")
        
        await db.commit()
        await db.refresh(k_entry)

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

    logger.info(f"Incoming refine request for knowledge_id='{knowledge_id}', Content-Type='{content_type}'")

    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
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
            
        # Check all possible form keys and duck typing for UploadFile (Starlette creates starlette.datastructures.UploadFile)
        for key in ["file", "attached_file", "files"]:
            val = form.get(key)
            if val and hasattr(val, "filename") and val.filename and hasattr(val, "read"):
                file_attachment = val
                break
        if not file_attachment:
            for k, val in form.items():
                if hasattr(val, "filename") and val.filename and hasattr(val, "read"):
                    file_attachment = val
                    break

        if file_attachment:
            logger.info(f"📎 Attached file successfully extracted: '{file_attachment.filename}' (type={type(file_attachment)})")
        else:
            logger.info(f"Form received without valid file attachment (form keys: {list(form.keys())})")
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
            raw_attached_name = getattr(file_attachment, "filename", "attached_doc")
            clean_attached_name = re.sub(r'[^a-zA-Z0-9._-]', '_', str(raw_attached_name or "attached_doc"))
            clean_attached_name = re.sub(r'_+', '_', clean_attached_name)
            attached_file_name = clean_attached_name
            temp_file_path = os.path.join(temp_dir, f"refine_supp_{knowledge_id}_{attached_file_name}")
            content_bytes = await file_attachment.read()
            try:
                await file_attachment.seek(0)
            except Exception:
                pass
            with open(temp_file_path, "wb") as f:
                f.write(content_bytes)

            from app.rag.utils.parser import DocumentParser
            parser = DocumentParser()
            parse_res = parser.parse_file(temp_file_path)
            extracted_text = ""
            all_attached_images = []

            if parse_res:
                if parse_res.pages:
                    extracted_pages = [p.get("text", "") for p in parse_res.pages if p.get("text")]
                    extracted_text = "\n\n".join(extracted_pages)
                    # Collect all embedded / standalone image URLs across all pages/slides/sheets
                    for p in parse_res.pages:
                        if p.get("image_urls") and isinstance(p["image_urls"], list):
                            for u in p["image_urls"]:
                                if u and u not in all_attached_images:
                                    all_attached_images.append(u)
                        if p.get("image_url") and p["image_url"] not in all_attached_images:
                            all_attached_images.append(p["image_url"])
                elif parse_res.docling_doc:
                    try:
                        extracted_text = parse_res.docling_doc.export_to_markdown()
                    except Exception as exp_err:
                        logger.warning(f"Docling export to markdown failed for attached file: {exp_err}")
                        extracted_text = ""

            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)

            if extracted_text or all_attached_images:
                # Cap extremely large spreadsheets/documents to 10,000 chars to avoid LLM context blowout
                content_snippet = extracted_text
                if len(content_snippet) > 10000:
                    content_snippet = content_snippet[:10000] + "\n\n... [KONTEN FILE TERLAMPIR DIPOTONG KARENA PANJANG] ..."

                media_note = ""
                replace_guidance = ""
                if all_attached_images:
                    media_lines = [f"- Attached Image {i+1}: {url}" for i, url in enumerate(all_attached_images)]
                    primary_img = all_attached_images[0]
                    media_note = (
                        f"\n\n[ATTACHED MEDIA ASSET URLS FOR THIS TURN:\n"
                        + "\n".join(media_lines)
                        + f"\nCRITICAL INSTRUCTION: If the admin instruction adds a product or section, embed the exact URL '{primary_img}' inside that product's '### Detail Produk' block as ![Product Name]({primary_img}). "
                        f"If updating/replacing an image, swap the old image tag with ![Product Name]({primary_img}). DO NOT output placeholder text like 'URL_GAMBAR' or 'new_image'. "
                        f"NEVER create an 'Asset Media' heading or append raw media asset lists at the end of the summary.]\n"
                    )

                file_note = (
                    f"\n\n[SUPPLEMENTARY ATTACHED FILE CONTENT: '{attached_file_name}']\n"
                    f"{content_snippet}{media_note}\n"
                    f"[END OF ATTACHED FILE CONTENT]"
                )
                payload.prompt = f"{payload.prompt}\n{file_note}" if payload.prompt else file_note
                logger.info(f"📄 Successfully attached file '{attached_file_name}' ({len(extracted_text)} chars, {len(all_attached_images)} images) to refine request for knowledge_id='{knowledge_id}'")

            # If images were extracted/attached, update image_urls in existing pending/approved files
            if all_attached_images:
                for target_json_file in [resolve_pending_file(str(knowledge_id)), resolve_approved_file(str(knowledge_id))]:
                    if target_json_file and os.path.exists(target_json_file):
                        try:
                            with open(target_json_file, "r", encoding="utf-8") as jf:
                                jdata = json.load(jf)
                            if "image_urls" not in jdata or not isinstance(jdata["image_urls"], list):
                                jdata["image_urls"] = []
                            for u in all_attached_images:
                                if u not in jdata["image_urls"]:
                                    jdata["image_urls"].append(u)
                            if not jdata.get("image_url") and all_attached_images:
                                jdata["image_url"] = all_attached_images[0]
                            with open(target_json_file, "w", encoding="utf-8") as jf:
                                json.dump(jdata, jf, indent=4, ensure_ascii=False)
                            try:
                                from app.services.storage import upload_staging_json, upload_approved_json
                                if "pending" in target_json_file:
                                    upload_staging_json(str(knowledge_id), jdata)
                                elif "output" in target_json_file:
                                    upload_approved_json(str(knowledge_id), jdata)
                            except Exception:
                                pass
                        except Exception as update_err:
                            logger.debug(f"Could not pre-update image_urls in {target_json_file}: {update_err}")

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
            m_dict = dict(k_entry.metadata_) if isinstance(k_entry.metadata_, dict) else {}
            if k_entry.status == KnowledgeStatus.APPROVED:
                a_file = os.path.join("data/output", f"{knowledge_id}.json")
                os.makedirs("data/output", exist_ok=True)
                doc_data = {
                    "knowledge_id": str(knowledge_id),
                    "batch_id": m_dict.get("batch_id"),
                    "file_name": k_entry.file_name or str(knowledge_id),
                    "title": k_entry.title or k_entry.file_name or "Knowledge Document",
                    "status": "Approved",
                    "summary": k_entry.ai_summary or "",
                    "initial_prompt": m_dict.get("initial_prompt"),
                    "staging_history": m_dict.get("staging_history", []),
                    "edit_history": m_dict.get("edit_history", []),
                    "timing_metrics": m_dict.get("timing_metrics"),
                    "batch_summary": m_dict.get("batch_summary"),
                    "image_urls": m_dict.get("image_urls", []),
                    "categories": m_dict.get("categories", []),
                    "visibility_settings": m_dict.get("visibility_settings", {"clinics": ["all"], "doctor_types": ["all"], "doctors": ["all"]}),
                    "chunks": m_dict.get("chunks", [{"text": k_entry.ai_summary or k_entry.title or "", "metadata": {"knowledge_id": str(knowledge_id)}}])
                }
                with open(a_file, "w", encoding="utf-8") as f:
                    json.dump(doc_data, f, indent=4, ensure_ascii=False)
                try:
                    from app.services.storage import upload_approved_json
                    upload_approved_json(str(knowledge_id), doc_data)
                except Exception:
                    pass
            else:
                p_file = os.path.join("data/pending", f"{knowledge_id}.json")
                os.makedirs("data/pending", exist_ok=True)
                doc_data = {
                    "knowledge_id": str(knowledge_id),
                    "batch_id": m_dict.get("batch_id"),
                    "file_name": k_entry.file_name or str(knowledge_id),
                    "title": k_entry.title or k_entry.file_name or "Knowledge Document",
                    "status": "On review",
                    "summary": k_entry.ai_summary or "",
                    "initial_prompt": m_dict.get("initial_prompt"),
                    "history": m_dict.get("history", []),
                    "staging_history": m_dict.get("staging_history", []),
                    "timing_metrics": m_dict.get("timing_metrics"),
                    "batch_summary": m_dict.get("batch_summary"),
                    "image_urls": m_dict.get("image_urls", []),
                    "suggested_categories": m_dict.get("suggested_categories", []),
                    "chunks": m_dict.get("chunks", [{"text": k_entry.ai_summary or k_entry.title or "", "metadata": {"knowledge_id": str(knowledge_id)}}])
                }
                with open(p_file, "w", encoding="utf-8") as f:
                    json.dump(doc_data, f, indent=4, ensure_ascii=False)
                try:
                    from app.services.storage import upload_staging_json
                    upload_staging_json(str(knowledge_id), doc_data)
                except Exception:
                    pass

    stmt_check = select(Knowledge).where(Knowledge.id == knowledge_id, Knowledge.deleted_at.is_(None))
    res_check = await db.execute(stmt_check)
    k_check = res_check.scalar_one_or_none()

    if (k_check and k_check.status == KnowledgeStatus.APPROVED) or (not p_file and a_file):
        pipeline = get_ingestion_pipeline(request)
        bm25 = get_bm25_index(request)
        vector_store = get_vector_store(request)
        res = await refine_approved_document(str(knowledge_id), payload, pipeline, bm25, vector_store, llm, file_attachment=file_attachment)
    elif p_file:
        res = await refine_pending_document(str(knowledge_id), payload, llm, file_attachment=file_attachment)
    else:
        raise HTTPException(status_code=404, detail="Document not found for refinement.")

    # Synchronize DB record with refined output
    try:
        stmt = select(Knowledge).where(Knowledge.id == knowledge_id)
        db_res = await db.execute(stmt)
        k_entry = db_res.scalar_one_or_none()
        if k_entry and isinstance(res, dict):
            # For pending documents, update live summary and title directly in DB
            # For approved documents, preserve approved baseline in DB until admin explicitly approves
            if k_entry.status != KnowledgeStatus.APPROVED:
                if res.get("title"):
                    k_entry.title = res.get("title")
                if res.get("summary"):
                    k_entry.ai_summary = res.get("summary")
                    k_entry.content = res.get("summary")

            if k_entry.metadata_ is None:
                k_entry.metadata_ = {}

            # Preserve initial summary before any updates
            if "initial_summary" not in k_entry.metadata_ and k_entry.ai_summary:
                k_entry.metadata_["initial_summary"] = k_entry.ai_summary

            if res.get("batch_id") and "batch_id" not in k_entry.metadata_:
                k_entry.metadata_["batch_id"] = res.get("batch_id")
            if res.get("categories") is not None:
                k_entry.metadata_["categories"] = await sanitize_knowledge_categories(db, res.get("categories"))
            elif res.get("suggested_categories") is not None:
                raw_cats = [c.get("name") if isinstance(c, dict) else str(c) for c in res.get("suggested_categories", [])]
                k_entry.metadata_["categories"] = await sanitize_knowledge_categories(db, raw_cats)
            if res.get("visibility_settings") is not None:
                k_entry.metadata_["visibility_settings"] = res.get("visibility_settings")
            if res.get("chunks") is not None:
                k_entry.metadata_["chunks"] = res.get("chunks")
            if res.get("image_url"):
                k_entry.metadata_["image_url"] = res.get("image_url")
            if res.get("image_urls"):
                k_entry.metadata_["image_urls"] = res.get("image_urls")
            if res.get("images"):
                k_entry.metadata_["images"] = res.get("images")

            prompt_str = prompt or (payload.get("prompt") if isinstance(payload, dict) else getattr(payload, "prompt", ""))
            initial_prompt = k_entry.metadata_.get("initial_prompt")
            initial_summary = k_entry.metadata_.get("initial_summary") or k_entry.ai_summary
            active_attached_file_name = clean_attached_name if file_attachment else None

            # Persist chat turns in metadata
            if k_entry.status == KnowledgeStatus.APPROVED:
                existing_edit_hist = k_entry.metadata_.get("edit_history") or []
                if not isinstance(existing_edit_hist, list):
                    existing_edit_hist = []

                full_edit_hist = list(existing_edit_hist)
                if not full_edit_hist:
                    if initial_prompt:
                        full_edit_hist.append({
                            "role": "user",
                            "content": initial_prompt,
                            "attachmentName": k_entry.file_name,
                            "created_at": k_entry.created_at.isoformat() if k_entry.created_at else datetime.now(timezone.utc).isoformat()
                        })
                    if initial_summary:
                        full_edit_hist.append({
                            "role": "assistant",
                            "content": initial_summary,
                            "created_at": k_entry.created_at.isoformat() if k_entry.created_at else datetime.now(timezone.utc).isoformat()
                        })

                if prompt_str:
                    user_turn: Dict[str, Any] = {
                        "role": "user",
                        "content": prompt_str,
                        "created_at": datetime.now(timezone.utc).isoformat()
                    }
                    if active_attached_file_name:
                        user_turn["attachmentName"] = active_attached_file_name
                        user_turn["attachmentNames"] = [active_attached_file_name]
                    full_edit_hist.append(user_turn)
                if res.get("summary"):
                    full_edit_hist.append({
                        "role": "assistant",
                        "content": res.get("summary"),
                        "created_at": datetime.now(timezone.utc).isoformat()
                    })

                full_edit_hist = sanitize_history_turns(full_edit_hist, default_attachment=active_attached_file_name)
                k_entry.metadata_["edit_history"] = full_edit_hist
                res["edit_history"] = full_edit_hist
                if a_file and os.path.exists(a_file):
                    try:
                        with open(a_file, "r", encoding="utf-8") as af_r:
                            cur_af = json.load(af_r)
                        if isinstance(cur_af, dict):
                            cur_af["edit_history"] = full_edit_hist
                            cur_af["initial_summary"] = initial_summary
                            with open(a_file, "w", encoding="utf-8") as af_w:
                                json.dump(cur_af, af_w, indent=4, ensure_ascii=False)
                    except Exception:
                        pass
            else:
                # Prefer synchronized history returned by refine_pending_document to prevent double appending
                if isinstance(res, dict) and res.get("history") and isinstance(res.get("history"), list):
                    full_history = res.get("history")
                else:
                    existing_history = k_entry.metadata_.get("history") or k_entry.metadata_.get("chat_history") or []
                    if not isinstance(existing_history, list):
                        existing_history = []

                    full_history = list(existing_history)

                    # Initialize with Turn 0 if history doesn't already contain it
                    if not full_history:
                        if initial_prompt:
                            full_history.append({
                                "role": "user",
                                "content": initial_prompt,
                                "attachmentName": k_entry.file_name,
                                "created_at": k_entry.created_at.isoformat() if k_entry.created_at else datetime.now(timezone.utc).isoformat()
                            })
                        if initial_summary:
                            full_history.append({
                                "role": "assistant",
                                "content": initial_summary,
                                "created_at": k_entry.created_at.isoformat() if k_entry.created_at else datetime.now(timezone.utc).isoformat()
                            })

                    if prompt_str:
                        user_turn: Dict[str, Any] = {
                            "role": "user",
                            "content": prompt_str,
                            "created_at": datetime.now(timezone.utc).isoformat()
                        }
                        if active_attached_file_name:
                            user_turn["attachmentName"] = active_attached_file_name
                            user_turn["attachmentNames"] = [active_attached_file_name]
                        full_history.append(user_turn)
                    if res.get("summary"):
                        full_history.append({
                            "role": "assistant",
                            "content": res.get("summary"),
                            "created_at": datetime.now(timezone.utc).isoformat()
                        })

                full_history = sanitize_history_turns(full_history, default_attachment=active_attached_file_name)
                k_entry.metadata_["history"] = full_history
                k_entry.metadata_["chat_history"] = full_history
                res["history"] = full_history
                res["initial_summary"] = initial_summary

                # Also sync back to pending staging json file
                if p_file and os.path.exists(p_file):
                    try:
                        with open(p_file, "r", encoding="utf-8") as pf_r:
                            cur_pf = json.load(pf_r)
                        if isinstance(cur_pf, dict):
                            cur_pf["history"] = full_history
                            cur_pf["initial_summary"] = initial_summary
                            with open(p_file, "w", encoding="utf-8") as pf_w:
                                json.dump(cur_pf, pf_w, indent=4, ensure_ascii=False)
                    except Exception as pf_err:
                        logger.warning(f"Failed to update p_file with full history: {pf_err}")

            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(k_entry, "metadata_")
            await db.commit()
    except Exception as sync_err:
        logger.warning(f"Failed to sync refined knowledge to DB row: {sync_err}")

    # Record token usage for refinement turn
    refine_prompt = payload.prompt or ""
    in_tokens = count_chat_prompt_tokens(
        user_query=refine_prompt,
        history=[{"role": m.role, "content": m.content} for m in payload.history or []]
    )
    refined_out = str(res.get("summary") or res.get("answer") or "") if isinstance(res, dict) else ""
    out_tokens = count_chat_completion_tokens(refined_out)
    await record_chat_token_usage(
        db=db,
        user_id=current_user.id,
        branch_id=None,
        input_tokens=in_tokens,
        output_tokens=out_tokens
    )

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
    
    # 0. Register active background job cancellation immediately
    try:
        from app.rag.router import cancel_ingestion_job
        cancel_ingestion_job(kid_str)
    except Exception:
        pass

    # 1. Fetch DB record to gather all identifiers and metadata BEFORE modifying state
    stmt = select(Knowledge).where(Knowledge.id == knowledge_id)
    result = await db.execute(stmt)
    knowledge = result.scalar_one_or_none()
    
    file_name = knowledge.file_name if knowledge else None
    d_meta = knowledge.metadata_ if knowledge and isinstance(knowledge.metadata_, dict) else {}
    ai_summary = knowledge.ai_summary if knowledge else ""
    batch_id = str(d_meta.get("batch_id") or "").strip()

    pipeline = get_ingestion_pipeline(request)
    bm25 = get_bm25_index(request)
    vector_store = get_vector_store(request)

    # 2. Execute RAG deletion endpoint FIRST while local JSONs and DB state are intact
    # This ensures RAG can read all metadata, discover embedded images in JSON/DB, and purge MinIO & vectors
    try:
        await delete_document_endpoint(kid_str, pipeline=pipeline, bm25=bm25, vector_store=vector_store)
        logger.info(f"RAG delete_document_endpoint completed successfully for '{kid_str}'")
    except Exception as rag_del_err:
        logger.warning(f"RAG delete_document_endpoint notice for '{kid_str}': {rag_del_err}")

    # 3. Collect all identifier variants for secondary fail-safe multi-key purge
    identifiers_to_purge = {kid_str, f"{kid_str}_parsed", f"{kid_str}.json", f"{kid_str}_parsed.json"}
    if batch_id:
        identifiers_to_purge.update({batch_id, f"{batch_id}_parsed", f"{batch_id}.json", f"{batch_id}_parsed.json"})
    if file_name:
        base_name, _ = os.path.splitext(file_name)
        identifiers_to_purge.update({
            file_name,
            base_name,
            f"{file_name}_parsed",
            f"{file_name}_parsed.json",
            f"{file_name}.json"
        })

    # 4. Clean any remaining physical files from data/pending, data/output, data/approved, data/temp, data/storage
    for folder in ["data/pending", "data/output", "data/approved", "data/temp", "data/storage", "data/uploads", "data/images"]:
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
                            doc_bid = str(f_data.get("batch_id") or (f_data.get("metadata") or {}).get("batch_id") or "")
                            if doc_kid == kid_str or (batch_id and doc_bid == batch_id) or (file_name and doc_fname.lower() == file_name.lower()):
                                should_delete = True
                    except Exception:
                        pass
                        
                if should_delete:
                    try:
                        os.remove(f_path)
                        logger.info(f"Purged staging/temp file for knowledge deletion: {f_path}")
                    except Exception as err:
                        logger.warning(f"Failed to remove file {f_path}: {err}")

    # 5. Fail-safe MinIO purge for document assets & embedded images
    try:
        from app.services.storage import delete_knowledge_images_and_assets
        delete_knowledge_images_and_assets(
            kid_str,
            doc_data={"summary": ai_summary, "metadata": d_meta, "batch_id": batch_id, "image_urls": d_meta.get("image_urls", [])}
        )
    except Exception as s3_del_err:
        logger.debug(f"MinIO secondary delete note for {kid_str}: {s3_del_err}")

    # 6. Fail-safe Vector Store Chunks (PGVector) & Direct SQL table cleanup
    if vector_store:
        for ident in identifiers_to_purge:
            try:
                vector_store.delete_document(ident)
            except Exception as vs_err:
                logger.debug(f"vector_store.delete_document({ident}) notice: {vs_err}")

    try:
        from app.rag.config import settings as rag_settings
        table_name = rag_settings.pg_collection_name
        if file_name:
            cleanup_query = text(f"""
                DELETE FROM {table_name} 
                WHERE source_file = :kid 
                   OR source_file = :fname
                   OR metadata ->> 'knowledge_id' = :kid
                   OR metadata ->> 'file_name' = :fname
            """)
            await db.execute(cleanup_query, {
                "kid": kid_str,
                "fname": file_name
            })
        else:
            cleanup_query = text(f"""
                DELETE FROM {table_name} 
                WHERE source_file = :kid 
                   OR metadata ->> 'knowledge_id' = :kid
            """)
            await db.execute(cleanup_query, {
                "kid": kid_str
            })
    except Exception as sql_err:
        logger.warning(f"Direct vector store table purge warning: {sql_err}")

    # 7. Fail-safe Clean BM25 Index
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

    # 8. Mark soft-deleted in current PostgreSQL session and commit
    if knowledge:
        knowledge.deleted_at = datetime.now(timezone.utc)
    await db.commit()
                
    return None
