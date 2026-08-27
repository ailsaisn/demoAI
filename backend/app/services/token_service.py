import uuid
from typing import Tuple, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from loguru import logger

from app.models.user import User, UserType, UserTokenUsage
from app.models.branch import Branch
from app.models.config import AppConfig
from app.models.ingestion_usage import IngestionTokenUsage
from app.core.config import settings


async def get_app_config_value(db: AsyncSession, key: str, default: Optional[str] = None) -> Optional[str]:
    stmt = select(AppConfig.value).where(AppConfig.key == key)
    res = await db.execute(stmt)
    val = res.scalar_one_or_none()
    return val if val is not None else default


async def check_chat_token_quota(
    db: AsyncSession,
    user: User,
    branch_id: Optional[uuid.UUID]
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Check whether a chat request is allowed based on the active token allocation mode:
    - Mode ON (Global Config = ON):
      * Token limit is determined per branch (Shared Branch Pool).
      * No individual doctor limit per branch (doctor can chat as long as their active branch has tokens).
    - Mode OFF (Global Config = OFF):
      * Strict individual limit per doctor.
      * Strict individual limit per branch.
    - Staff / Admin / Functional Dept:
      * Tracked by usage without hard doctor blocking.
    """
    # 1. Staff and Admin accounts are tracked by usage without hard doctor block
    if user.type == UserType.STAFF:
        return True, "OK", {"mode": "staff_by_usage"}

    current_ym = datetime.now(timezone.utc).strftime("%Y-%m")
    is_global_mode = (await get_app_config_value(db, "GLOBAL_TOKEN_LIMIT_ACTIVE", "false")).lower() == "true"

    branch = None
    if branch_id:
        b_stmt = select(Branch).where(Branch.id == branch_id, Branch.deleted_at.is_(None))
        branch_res = await db.execute(b_stmt)
        branch = branch_res.scalar_one_or_none()

    if is_global_mode:
        # --- Mode ON: Token determined per branch pool + optional doctor custom override ---
        global_branch_limit_str = await get_app_config_value(db, "GLOBAL_TOKEN_LIMIT", None)
        branch_limit = int(global_branch_limit_str) if (global_branch_limit_str and global_branch_limit_str.isdigit()) else (branch.token_limit if branch else 0)

        if branch and branch_limit > 0:
            branch_usage_stmt = select(func.sum(UserTokenUsage.tokens_used)).where(
                UserTokenUsage.branch_id == branch.id,
                UserTokenUsage.year_month == current_ym
            )
            branch_used = (await db.execute(branch_usage_stmt)).scalar() or 0
            if branch_used >= branch_limit:
                return False, f"Branch '{branch.name}' monthly token pool ({branch_limit:,}) is exhausted for this month.", {
                    "mode": "global_shared",
                    "branch_limit": branch_limit,
                    "branch_used": branch_used,
                    "reason": "branch_limit_exceeded"
                }

        # Check individual override if explicitly configured
        if user.token_limit is not None and user.token_limit > 0:
            doc_usage_stmt = select(func.sum(UserTokenUsage.tokens_used)).where(
                UserTokenUsage.user_id == user.id,
                UserTokenUsage.year_month == current_ym
            )
            doc_used = (await db.execute(doc_usage_stmt)).scalar() or 0
            if doc_used >= user.token_limit:
                return False, f"Individual monthly token limit ({user.token_limit:,}) has been exceeded.", {
                    "mode": "global_override",
                    "doc_limit": user.token_limit,
                    "doc_used": doc_used,
                    "reason": "individual_doctor_limit_exceeded"
                }

        return True, "OK", {"mode": "global_shared"}

    else:
        # --- Mode OFF: Strict individual doctor limit & strict individual branch limit ---
        # 1. Individual doctor limit
        if user.token_limit is not None and user.token_limit > 0:
            doc_usage_stmt = select(func.sum(UserTokenUsage.tokens_used)).where(
                UserTokenUsage.user_id == user.id,
                UserTokenUsage.year_month == current_ym
            )
            doc_used = (await db.execute(doc_usage_stmt)).scalar() or 0
            if doc_used >= user.token_limit:
                return False, f"Individual monthly token limit ({user.token_limit:,}) has been exceeded.", {
                    "mode": "individual",
                    "doc_limit": user.token_limit,
                    "doc_used": doc_used,
                    "reason": "individual_doctor_limit_exceeded"
                }

        # 2. Individual branch limit
        if branch and branch.token_limit > 0:
            branch_usage_stmt = select(func.sum(UserTokenUsage.tokens_used)).where(
                UserTokenUsage.branch_id == branch.id,
                UserTokenUsage.year_month == current_ym
            )
            branch_used = (await db.execute(branch_usage_stmt)).scalar() or 0
            if branch_used >= branch.token_limit:
                return False, f"Branch '{branch.name}' monthly token limit ({branch.token_limit:,}) has been reached.", {
                    "mode": "individual",
                    "branch_limit": branch.token_limit,
                    "branch_used": branch_used,
                    "reason": "branch_limit_exceeded"
                }

        return True, "OK", {"mode": "individual"}


async def record_chat_token_usage(
    db: AsyncSession,
    user_id: uuid.UUID,
    branch_id: Optional[uuid.UUID],
    input_tokens: int,
    output_tokens: int
):
    """
    Record prompt (input) and completion (output) tokens for a doctor chat turn.
    """
    if input_tokens <= 0 and output_tokens <= 0:
        return

    total_tokens = input_tokens + output_tokens
    current_ym = datetime.now(timezone.utc).strftime("%Y-%m")

    stmt = select(UserTokenUsage).where(
        UserTokenUsage.user_id == user_id,
        UserTokenUsage.branch_id == branch_id,
        UserTokenUsage.year_month == current_ym
    )
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()

    if record:
        record.input_tokens += input_tokens
        record.output_tokens += output_tokens
        record.tokens_used += total_tokens
    else:
        record = UserTokenUsage(
            user_id=user_id,
            branch_id=branch_id,
            year_month=current_ym,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tokens_used=total_tokens
        )
        db.add(record)

    await db.commit()
    logger.info(f"Recorded chat token usage for user {user_id}, branch {branch_id}: in={input_tokens}, out={output_tokens}, total={total_tokens}")


async def check_ingestion_quota(db: AsyncSession) -> Tuple[bool, Dict[str, Any]]:
    """
    Check monthly ingestion token limit (Global Token Threshold) and calculate warning state (>= 90%) and exceeded state (>= 100%).
    Returns is_allowed=True (soft warning/notice model) to avoid disrupting document knowledge ingestion.
    """
    config_val = await get_app_config_value(db, "GLOBAL_TOKEN_THRESHOLD", None)
    if not config_val or not config_val.isdigit():
        config_val = await get_app_config_value(db, "INGESTION_MONTHLY_TOKEN_LIMIT", None)

    if config_val and config_val.isdigit():
        limit = int(config_val)
    else:
        limit = getattr(settings, "INGESTION_MONTHLY_TOKEN_LIMIT", 1000000)

    current_ym = datetime.now(timezone.utc).strftime("%Y-%m")

    stmt = select(IngestionTokenUsage).where(IngestionTokenUsage.year_month == current_ym)
    result = await db.execute(stmt)
    usage = result.scalar_one_or_none()

    used = usage.tokens_used if usage else 0
    docs_count = usage.documents_count if usage else 0
    percentage = (used / limit * 100) if limit > 0 else 0.0

    is_warning = (percentage >= 90.0 and percentage < 100.0) if limit > 0 else False
    is_exceeded = (percentage >= 100.0) if limit > 0 else False
    is_allowed = True # Soft warning: ingestion proceeds without blocking

    return is_allowed, {
        "year_month": current_ym,
        "tokens_used": used,
        "input_tokens": usage.input_tokens if usage else 0,
        "output_tokens": usage.output_tokens if usage else 0,
        "token_limit": limit,
        "percentage": round(percentage, 1),
        "documents_count": docs_count,
        "warning": is_warning,
        "exceeded": is_exceeded
    }


async def record_ingestion_token_usage(
    db: AsyncSession,
    input_tokens: int,
    output_tokens: int,
    documents_count: int = 1
):
    """
    Record document processing, chunking, and AI summary tokens for ingestion.
    """
    if input_tokens <= 0 and output_tokens <= 0 and documents_count <= 0:
        return

    total_tokens = input_tokens + output_tokens
    current_ym = datetime.now(timezone.utc).strftime("%Y-%m")

    stmt = select(IngestionTokenUsage).where(IngestionTokenUsage.year_month == current_ym)
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()

    if record:
        record.input_tokens += input_tokens
        record.output_tokens += output_tokens
        record.tokens_used += total_tokens
        record.documents_count += documents_count
    else:
        record = IngestionTokenUsage(
            year_month=current_ym,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tokens_used=total_tokens,
            documents_count=documents_count
        )
        db.add(record)

    await db.commit()
    logger.info(f"Recorded ingestion token usage: in={input_tokens}, out={output_tokens}, total={total_tokens}, docs={documents_count}")


async def record_knowledge_not_found_event(
    db: AsyncSession,
    user_id: uuid.UUID,
    branch_id: Optional[uuid.UUID],
    user_query: str
):
    """
    Records a KNOWLEDGE_NOT_FOUND alert when a doctor asks a question that yields no matching KB context.
    Publishes real-time notification to Admin SSE channel and logs audit alert.
    """
    logger.warning(
        f"⚠️ [KNOWLEDGE_NOT_FOUND_ALERT] User '{user_id}' (Branch: '{branch_id}') "
        f"asked: '{user_query}' — No matching KB documents found."
    )
    try:
        from app.core.broadcaster import broadcaster
        import json
        event_payload = json.dumps({
            "event_type": "KNOWLEDGE_NOT_FOUND",
            "user_id": str(user_id),
            "branch_id": str(branch_id) if branch_id else None,
            "query": user_query,
            "message": f"Pertanyaan dokter tidak ditemukan di Knowledge Base: '{user_query}'"
        })
        await broadcaster.publish(event_payload)
    except Exception as err:
        logger.debug(f"Broadcasting KNOWLEDGE_NOT_FOUND event failed: {err}")

