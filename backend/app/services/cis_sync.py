import os
import logging
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from cryptography.hazmat.primitives import serialization

from app.models.user import User, UserType
from app.models.branch import Branch, UserBranch
from app.core.config import settings

logger = logging.getLogger(__name__)

def get_cis_public_key():
    """Load RSA Public Key supporting PEM (PKCS#1 / PKCS#8) and OpenSSH (ssh-rsa) formats."""
    if settings.CIS_RSA_PUBLIC_KEY:
        raw_key = settings.CIS_RSA_PUBLIC_KEY.replace("\\n", "\n")
        key_bytes = raw_key.encode("utf-8")
    elif settings.CIS_RSA_PUBLIC_KEY_PATH:
        path = settings.CIS_RSA_PUBLIC_KEY_PATH
        if not os.path.isabs(path):
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            path = os.path.join(base_dir, path)
            
        if not os.path.exists(path):
            raise RuntimeError(f"CIS RSA Public Key file not found at: {path}")
            
        with open(path, "rb") as f:
            key_bytes = f.read()
    else:
        raise RuntimeError("CIS RSA Public Key is not configured in environment variables (CIS_RSA_PUBLIC_KEY or CIS_RSA_PUBLIC_KEY_PATH).")

    key_str = key_bytes.decode("utf-8", errors="ignore").strip()
    if key_str.startswith("ssh-rsa"):
        return serialization.load_ssh_public_key(key_bytes)
    return serialization.load_pem_public_key(key_bytes)

async def upsert_branch_payload(db: AsyncSession, data: Dict[str, Any]) -> Branch:
    """Upsert a branch record from pushed webhook data payload."""
    raw_id = data.get("id") or data.get("branch_id")
    if raw_id is None:
        raise ValueError("Missing branch id in payload")
    
    external_id = int(raw_id)
    name = data.get("name", "")
    code = data.get("code")
    ecosystem = data.get("ecosystem", "Erha")
    status = str(data.get("status", "1"))
    
    stmt = select(Branch).where(
        func.lower(Branch.ecosystem) == ecosystem.lower(),
        Branch.external_id == external_id
    )
    branch = (await db.execute(stmt)).scalar_one_or_none()
    
    is_inactive = (status == "0")
    
    if not branch:
        branch = Branch(
            external_id=external_id,
            name=name,
            code=code,
            ecosystem=ecosystem
        )
        if is_inactive:
            branch.deleted_at = datetime.now(timezone.utc)
        db.add(branch)
    else:
        branch.name = name
        branch.code = code
        branch.ecosystem = ecosystem
        if is_inactive:
            branch.deleted_at = datetime.now(timezone.utc)
        else:
            branch.deleted_at = None
        
    await db.flush()
    return branch

async def delete_branch_payload(db: AsyncSession, branch_id: Any, ecosystem: Optional[str] = None):
    """Soft delete a branch record."""
    external_id = int(branch_id)
    stmt = select(Branch).where(Branch.external_id == external_id)
    if ecosystem:
        stmt = stmt.where(func.lower(Branch.ecosystem) == ecosystem.lower())
    branch = (await db.execute(stmt)).scalar_one_or_none()
    if branch:
        branch.deleted_at = datetime.now(timezone.utc)
        await db.flush()

async def upsert_doctor_payload(db: AsyncSession, data: Dict[str, Any]) -> User:
    """Upsert a doctor record from pushed webhook payload, including nested user_branchs."""
    raw_id = data.get("id") or data.get("cis_id") or data.get("doctor_cis_id")
    if raw_id is None:
        raise ValueError("Missing doctor id in payload")
        
    cis_id = int(raw_id)
    name = data.get("name", "")
    email = data.get("email")
    employee_id = data.get("nik") or data.get("employee_id")
    dr_type = data.get("user_type_name") or data.get("dr_type")
    user_type_code = str(data.get("user_type")) if data.get("user_type") is not None else None
    ecosystem = data.get("ecosystem", "Erha")
    status = str(data.get("status", "1"))
    
    stmt = select(User).where(User.cis_id == cis_id)
    user = (await db.execute(stmt)).scalar_one_or_none()
    
    is_inactive = (status == "0")
    
    if not user:
        user = User(
            email=email or f"doc_{cis_id}@placeholder.com",
            name=name,
            cis_id=cis_id,
            employee_id=employee_id,
            dr_type=dr_type,
            user_type_code=user_type_code,
            ecosystem=ecosystem,
            type=UserType.DOCTOR,
            token_limit=0
        )
        if is_inactive:
            user.deleted_at = datetime.now(timezone.utc)
        db.add(user)
    else:
        user.name = name
        if email:
            user.email = email
        user.employee_id = employee_id
        user.dr_type = dr_type
        if user_type_code:
            user.user_type_code = user_type_code
        user.ecosystem = ecosystem
        if is_inactive:
            user.deleted_at = datetime.now(timezone.utc)
        else:
            user.deleted_at = None
        
    await db.flush()

    # Process nested branch associations if provided in doctor payload
    branches_list = data.get("user_branchs") or data.get("user_branches")
    if branches_list and isinstance(branches_list, list):
        for item in branches_list:
            b_raw_id = item.get("branch_id")
            b_code = item.get("branch_code")
            b_status = str(item.get("status", "1"))
            
            branch = None
            if b_code:
                b_stmt = select(Branch).where(
                    func.lower(Branch.ecosystem) == user.ecosystem.lower(),
                    Branch.code == b_code
                )
                branch = (await db.execute(b_stmt)).scalar_one_or_none()
            
            if not branch and b_raw_id is not None:
                b_stmt = select(Branch).where(
                    func.lower(Branch.ecosystem) == user.ecosystem.lower(),
                    Branch.external_id == int(b_raw_id)
                )
                branch = (await db.execute(b_stmt)).scalar_one_or_none()

            if not branch:
                logger.warning(f"Branch not found for doctor branch mapping: {item}")
                continue

            ub_stmt = select(UserBranch).where(UserBranch.user_id == user.id, UserBranch.branch_id == branch.id)
            ub = (await db.execute(ub_stmt)).scalar_one_or_none()
            
            try:
                status_val = int(b_status)
            except (ValueError, TypeError):
                status_val = 1

            if not ub:
                ub = UserBranch(user_id=user.id, branch_id=branch.id, status=status_val)
                if status_val == 0:
                    ub.deleted_at = datetime.now(timezone.utc)
                db.add(ub)
            else:
                ub.status = status_val
                if status_val == 0:
                    ub.deleted_at = datetime.now(timezone.utc)
                else:
                    ub.deleted_at = None
                    
        await db.flush()

    return user

async def upsert_user_branch_payload(db: AsyncSession, data_list: List[Dict[str, Any]]):
    """Process a list of user-branch association updates."""
    for item in data_list:
        raw_user_id = item.get("user_id")
        raw_branch_id = item.get("branch_id")
        branch_code = item.get("branch_code")
        status = str(item.get("status", "1"))
        
        if raw_user_id is None or (raw_branch_id is None and not branch_code):
            logger.warning(f"Skipping user_branch mapping, missing user_id or branch info: {item}")
            continue
            
        user_cis_id = int(raw_user_id)
        
        u_stmt = select(User).where(User.cis_id == user_cis_id)
        user = (await db.execute(u_stmt)).scalar_one_or_none()
        
        if not user:
            logger.warning(f"Skipping user_branch mapping, user ({user_cis_id}) not found")
            continue

        branch = None
        if branch_code:
            b_stmt = select(Branch).where(
                func.lower(Branch.ecosystem) == user.ecosystem.lower(),
                Branch.code == branch_code
            )
            branch = (await db.execute(b_stmt)).scalar_one_or_none()
            
        if not branch and raw_branch_id is not None:
            branch_external_id = int(raw_branch_id)
            b_stmt = select(Branch).where(
                func.lower(Branch.ecosystem) == user.ecosystem.lower(),
                Branch.external_id == branch_external_id
            )
            branch = (await db.execute(b_stmt)).scalar_one_or_none()
        
        if not branch:
            logger.warning(f"Skipping user_branch mapping, branch not found for user ({user_cis_id}): {item}")
            continue
            
        ub_stmt = select(UserBranch).where(UserBranch.user_id == user.id, UserBranch.branch_id == branch.id)
        ub = (await db.execute(ub_stmt)).scalar_one_or_none()
        
        try:
            status_val = int(status)
        except (ValueError, TypeError):
            status_val = 1
            
        if not ub:
            ub = UserBranch(user_id=user.id, branch_id=branch.id, status=status_val)
            if status_val == 0:
                ub.deleted_at = datetime.now(timezone.utc)
            db.add(ub)
        else:
            ub.status = status_val
            if status_val == 0:
                ub.deleted_at = datetime.now(timezone.utc)
            else:
                ub.deleted_at = None
                
    await db.flush()

async def delete_doctor_payload(db: AsyncSession, cis_id: Any):
    """Soft delete a doctor record."""
    doctor_cis_id = int(cis_id)
    stmt = select(User).where(User.cis_id == doctor_cis_id, User.type == UserType.DOCTOR)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user:
        user.deleted_at = datetime.now(timezone.utc)
        await db.flush()

async def bulk_sync_payload(db: AsyncSession, data: Dict[str, Any]):
    """Process a full bulk sync payload containing branches, users, and user_branches lists."""
    branches_data = data.get("branches", [])
    doctors_data = data.get("users", [])
    user_branches_data = data.get("user_branches", [])
    
    pulled_branch_keys = set()
    for b_data in branches_data:
        branch = await upsert_branch_payload(db, b_data)
        if branch.external_id is not None:
            pulled_branch_keys.add((branch.ecosystem.lower(), branch.external_id))
        
    # Soft delete local branches omitted from full sync
    all_b_stmt = select(Branch).where(Branch.deleted_at.is_(None))
    all_branches = (await db.execute(all_b_stmt)).scalars().all()
    for b in all_branches:
        if b.external_id is not None and (b.ecosystem.lower(), b.external_id) not in pulled_branch_keys:
            b.deleted_at = datetime.now(timezone.utc)
            
    pulled_doc_cis_ids = set()
    for d_data in doctors_data:
        doctor = await upsert_doctor_payload(db, d_data)
        if doctor.cis_id is not None:
            pulled_doc_cis_ids.add(doctor.cis_id)
        
    # Soft delete local doctors omitted from full sync
    all_d_stmt = select(User).where(User.type == UserType.DOCTOR, User.deleted_at.is_(None))
    all_doctors = (await db.execute(all_d_stmt)).scalars().all()
    for d in all_doctors:
        if d.cis_id is not None and d.cis_id not in pulled_doc_cis_ids:
            d.deleted_at = datetime.now(timezone.utc)
            
    await db.flush()
    
    if user_branches_data:
        await upsert_user_branch_payload(db, user_branches_data)
