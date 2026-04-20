"""initial_tables

Revision ID: 6be8710c5d03
Revises:
Create Date: 2026-04-01 08:14:35.684621

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '6be8710c5d03'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- users ---
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('external_id', sa.String(255), unique=True, nullable=False, index=True),
        sa.Column('preferences', postgresql.JSONB, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- conversations ---
    op.create_table(
        'conversations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('status', sa.Enum('active', 'completed', 'expired', name='conversationstatus'), nullable=False, server_default='active'),
        sa.Column('state', postgresql.JSONB, server_default='{}'),
        sa.Column('language', sa.String(10), server_default='en'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    )

    # --- messages ---
    op.create_table(
        'messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('conversations.id'), nullable=False, index=True),
        sa.Column('role', sa.Enum('user', 'assistant', 'system', 'tool', name='messagerole'), nullable=False),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('tool_calls', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- bookings ---
    op.create_table(
        'bookings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('conversations.id'), nullable=False),
        sa.Column('juniper_booking_id', sa.String(255), nullable=True),
        sa.Column('idempotency_key', sa.String(255), unique=True, nullable=False, index=True),
        sa.Column('status', sa.Enum('pending', 'confirmed', 'cancelled', 'modified', name='bookingstatus'), nullable=False, server_default='pending'),
        sa.Column('hotel_name', sa.String(500), nullable=True),
        sa.Column('check_in', sa.String(10), nullable=True),
        sa.Column('check_out', sa.String(10), nullable=True),
        sa.Column('total_price', sa.String(50), nullable=True),
        sa.Column('currency', sa.String(10), nullable=True),
        sa.Column('booking_details', postgresql.JSONB, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- webhook_subscriptions ---
    op.create_table(
        'webhook_subscriptions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('url', sa.String(2048), nullable=False),
        sa.Column('events', postgresql.ARRAY(sa.String), server_default='{}'),
        sa.Column('secret', sa.String(255), nullable=False),
        sa.Column('active', sa.Boolean, server_default='true'),
        sa.Column('failure_count', sa.Integer, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('webhook_subscriptions')
    op.drop_table('bookings')
    op.drop_table('messages')
    op.drop_table('conversations')
    op.drop_table('users')

    # Drop enum types
    sa.Enum(name='bookingstatus').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='messagerole').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='conversationstatus').drop(op.get_bind(), checkfirst=True)
