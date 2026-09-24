"""add comprehensive performance composite indexes for all tables and foreign keys

Revision ID: a9b8c7d6e5f4
Revises: f8b9c0d1e2f3
Create Date: 2026-09-23 17:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a9b8c7d6e5f4'
down_revision: Union[str, None] = 'f8b9c0d1e2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------
    # 1. Chat Subsystem Indexes
    # -------------------------------------------------------------
    op.create_index(
        'ix_chat_messages_session_created',
        'chat_messages',
        ['session_id', 'created_at'],
        unique=False
    )
    op.create_index(
        'ix_chat_session_user_status',
        'chat_session',
        ['user_id', 'status'],
        unique=False
    )
    op.create_index(
        'ix_chat_session_branch_id',
        'chat_session',
        ['branch_id'],
        unique=False
    )
    op.create_index(
        'ix_chat_session_feedback_issue',
        'chat_session',
        ['has_data_issue', 'session_type'],
        unique=False
    )
    op.create_index(
        'ix_chat_session_updated_at',
        'chat_session',
        ['updated_at'],
        unique=False
    )

    # -------------------------------------------------------------
    # 2. User & Branch Subsystem Indexes
    # -------------------------------------------------------------
    op.create_index(
        'ix_user_branch_branch_status',
        'user_branch',
        ['branch_id', 'status'],
        unique=False
    )
    op.create_index(
        'ix_user_branch_user_status',
        'user_branch',
        ['user_id', 'status'],
        unique=False
    )
    op.create_index(
        'ix_branches_code',
        'branches',
        ['code'],
        unique=False
    )
    op.create_index(
        'ix_branches_ecosystem',
        'branches',
        ['ecosystem'],
        unique=False
    )
    op.create_index(
        'ix_users_type_deleted',
        'users',
        ['type', 'deleted_at'],
        unique=False
    )
    op.create_index(
        'ix_users_dr_type',
        'users',
        ['dr_type'],
        unique=False
    )
    op.create_index(
        'ix_users_ecosystem',
        'users',
        ['ecosystem'],
        unique=False
    )
    op.create_index(
        'ix_user_token_usage_user_ym',
        'user_token_usage',
        ['user_id', 'year_month'],
        unique=False
    )
    op.create_index(
        'ix_user_token_usage_branch_ym',
        'user_token_usage',
        ['branch_id', 'year_month'],
        unique=False
    )

    # -------------------------------------------------------------
    # 3. RBAC & Exclusion Junction Table Foreign Key Indexes
    # -------------------------------------------------------------
    op.create_index(
        'ix_role_access_access_id',
        'role_access',
        ['access_id'],
        unique=False
    )
    op.create_index(
        'ix_user_access_access_id',
        'user_access',
        ['access_id'],
        unique=False
    )
    op.create_index(
        'ix_user_role_role_id',
        'user_role',
        ['role_id'],
        unique=False
    )
    op.create_index(
        'ix_user_category_exclusion_cat_id',
        'user_category_exclusion',
        ['category_id'],
        unique=False
    )

    # -------------------------------------------------------------
    # 4. Knowledge & Project Subsystem Indexes
    # -------------------------------------------------------------
    op.create_index(
        'ix_knowledge_status_deleted',
        'knowledge',
        ['status', 'deleted_at'],
        unique=False
    )
    op.create_index(
        'ix_knowledge_uploaded_by',
        'knowledge',
        ['uploaded_by'],
        unique=False
    )
    op.create_index(
        'ix_knowledge_approved_by',
        'knowledge',
        ['approved_by'],
        unique=False
    )
    op.create_index(
        'ix_knowledge_category_cat_id',
        'knowledge_category',
        ['category_id'],
        unique=False
    )
    op.create_index(
        'ix_pending_operations_user_status',
        'pending_operations',
        ['user_id', 'status'],
        unique=False
    )
    op.create_index(
        'ix_projects_created_by',
        'projects',
        ['created_by'],
        unique=False
    )


def downgrade() -> None:
    # 4. Knowledge & Project
    op.drop_index('ix_projects_created_by', table_name='projects')
    op.drop_index('ix_pending_operations_user_status', table_name='pending_operations')
    op.drop_index('ix_knowledge_category_cat_id', table_name='knowledge_category')
    op.drop_index('ix_knowledge_approved_by', table_name='knowledge')
    op.drop_index('ix_knowledge_uploaded_by', table_name='knowledge')
    op.drop_index('ix_knowledge_status_deleted', table_name='knowledge')

    # 3. RBAC & Exclusion Junctions
    op.drop_index('ix_user_category_exclusion_cat_id', table_name='user_category_exclusion')
    op.drop_index('ix_user_role_role_id', table_name='user_role')
    op.drop_index('ix_user_access_access_id', table_name='user_access')
    op.drop_index('ix_role_access_access_id', table_name='role_access')

    # 2. User & Branch
    op.drop_index('ix_user_token_usage_branch_ym', table_name='user_token_usage')
    op.drop_index('ix_user_token_usage_user_ym', table_name='user_token_usage')
    op.drop_index('ix_users_ecosystem', table_name='users')
    op.drop_index('ix_users_dr_type', table_name='users')
    op.drop_index('ix_users_type_deleted', table_name='users')
    op.drop_index('ix_branches_ecosystem', table_name='branches')
    op.drop_index('ix_branches_code', table_name='branches')
    op.drop_index('ix_user_branch_user_status', table_name='user_branch')
    op.drop_index('ix_user_branch_branch_status', table_name='user_branch')

    # 1. Chat
    op.drop_index('ix_chat_session_updated_at', table_name='chat_session')
    op.drop_index('ix_chat_session_feedback_issue', table_name='chat_session')
    op.drop_index('ix_chat_session_branch_id', table_name='chat_session')
    op.drop_index('ix_chat_session_user_status', table_name='chat_session')
    op.drop_index('ix_chat_messages_session_created', table_name='chat_messages')


