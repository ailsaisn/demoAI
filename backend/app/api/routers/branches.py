from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List
import uuid

from app.core.database import get_db
from app.api.dependencies import get_current_user, RequireAccess
from app.models.user import User, UserType, UserTokenUsage
from app.models.branch import Branch, UserBranch
from app.models.category import Category, UserCategoryExclusion
from app.schemas.branch import BranchCreate, BranchUpdate, BranchResponse
from datetime import datetime, timezone

router = APIRouter(tags=["Branches"])

async def _hydrate_branch(branch: Branch, db: AsyncSession) -> dict:
    branch_dict = {
        "id": branch.id,
        "external_id": branch.external_id,
        "name": branch.name,
        "code": branch.code,
        "ecosystem": branch.ecosystem,
        "token_limit": branch.token_limit,
        "created_at": branch.created_at,
        "updated_at": branch.updated_at,
        "used": 0,
        "remaining": branch.token_limit,
        "doctors": []
    }
    
    # Check global token mode
    from app.models.config import AppConfig
    cfg_stmt = select(AppConfig.value).where(AppConfig.key == "GLOBAL_TOKEN_LIMIT_ACTIVE")
    cfg_res = await db.execute(cfg_stmt)
    cfg_val = cfg_res.scalar_one_or_none()
    is_global_mode = (cfg_val or "false").lower() == "true"

    effective_branch_limit = branch.token_limit
    if is_global_mode:
        gl_stmt = select(AppConfig.value).where(AppConfig.key == "GLOBAL_TOKEN_LIMIT")
        gl_res = await db.execute(gl_stmt)
        gl_val = gl_res.scalar_one_or_none()
        if gl_val and gl_val.isdigit() and int(gl_val) > 0:
            effective_branch_limit = int(gl_val)
            branch_dict["tokensMonth"] = effective_branch_limit
            branch_dict["token_limit"] = effective_branch_limit

    current_ym = datetime.now(timezone.utc).strftime("%Y-%m")

    # 1. Total tokens used for this branch in current month
    stmt_branch_used = select(func.sum(UserTokenUsage.tokens_used)).where(
        UserTokenUsage.branch_id == branch.id,
        UserTokenUsage.year_month == current_ym
    )
    result_branch_used = await db.execute(stmt_branch_used)
    branch_used = result_branch_used.scalar() or 0
    branch_dict["used"] = branch_used
    branch_dict["remaining"] = max(0, (effective_branch_limit or 0) - branch_used)

    # 2. Get doctors assigned to this branch (active connections only)
    stmt = (
        select(User)
        .join(UserBranch, UserBranch.user_id == User.id)
        .where(
            UserBranch.branch_id == branch.id,
            UserBranch.status == 1,
            UserBranch.deleted_at.is_(None),
            User.type == UserType.DOCTOR,
            User.deleted_at.is_(None)
        )
    )
    result = await db.execute(stmt)
    doctors = result.scalars().all()
    
    for doc in doctors:
        # Get doctor's total tokens used
        stmt_token = select(func.sum(UserTokenUsage.tokens_used)).where(
            UserTokenUsage.user_id == doc.id,
            UserTokenUsage.year_month == current_ym
        )
        result_token = await db.execute(stmt_token)
        doc_tokens_used = result_token.scalar() or 0
        
        # Get speciality
        stmt_cat = select(Category).where(
            Category.deleted_at.is_(None),
            ~Category.id.in_(
                select(UserCategoryExclusion.category_id).where(UserCategoryExclusion.user_id == doc.id)
            )
        )
        result_cat = await db.execute(stmt_cat)
        cat = result_cat.scalar() # just get first category
        speciality = cat.name if cat else ""
        
        if is_global_mode:
            status = "Active"
            dr_type_clean = (doc.dr_type or "").upper()
            t_key = "TOKEN_LIMIT_SPKK" if any(k in dr_type_clean for k in ["SPDVE", "SP.DVE", "SPKK", "SP.KK", "SPDV"]) else ("TOKEN_LIMIT_GP" if any(k in dr_type_clean for k in ["GP", "GP PLUS", "UMUM"]) else "TOKEN_LIMIT_DEFAULT")
            t_stmt = select(AppConfig.value).where(AppConfig.key == t_key)
            t_res = await db.execute(t_stmt)
            t_val = t_res.scalar_one_or_none()
            max_tokens = int(t_val) if (t_val and t_val.isdigit()) else (doc.token_limit or 500000)
            tokens_left = max(0, max_tokens - doc_tokens_used)
            if max_tokens > 0 and doc_tokens_used >= max_tokens * 0.9:
                status = "Warning"
            elif branch_used >= (effective_branch_limit or 1) * 0.9:
                status = "Warning"
        else:
            status = "Active"
            max_tokens = doc.token_limit or 0
            tokens_left = max(0, max_tokens - doc_tokens_used)
            if doc.token_limit and doc.token_limit > 0 and doc_tokens_used >= doc.token_limit * 0.9:
                status = "Warning"
            
        branch_dict["doctors"].append({
            "id": doc.id,
            "name": doc.name,
            "speciality": speciality,
            "tokensLeft": tokens_left,
            "status": status,
            "maxTokens": max_tokens,
            "employee_id": doc.employee_id,
            "dr_type": doc.dr_type,
            "user_type_code": doc.user_type_code,
            "ecosystem": doc.ecosystem
        })
        
    return branch_dict

@router.get("/", response_model=List[BranchResponse])
async def list_branches(
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(RequireAccess("branches:read"))
):
    stmt = select(Branch).where(Branch.deleted_at.is_(None))
    result = await db.execute(stmt)
    branches = result.scalars().all()
    return [await _hydrate_branch(b, db) for b in branches]

@router.get("/{branch_id}", response_model=BranchResponse)
async def get_branch(
    branch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(RequireAccess("branches:read"))
):
    stmt = select(Branch).where(Branch.id == branch_id, Branch.deleted_at.is_(None))
    result = await db.execute(stmt)
    branch = result.scalar_one_or_none()
    
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
        
    return await _hydrate_branch(branch, db)



@router.put("/{branch_id}", response_model=BranchResponse)
async def update_branch(
    branch_id: uuid.UUID,
    branch_in: BranchUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(RequireAccess("branches:write"))
):
    stmt = select(Branch).where(Branch.id == branch_id, Branch.deleted_at.is_(None))
    result = await db.execute(stmt)
    branch = result.scalar_one_or_none()
    
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
        
    update_data = branch_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(branch, field, value)
        
    await db.commit()
    await db.refresh(branch)
    return await _hydrate_branch(branch, db)


