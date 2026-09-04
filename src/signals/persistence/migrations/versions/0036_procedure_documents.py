"""Capture précoce des dossiers de procédure.

Revision ID: 0036_procedure_documents
Revises: 0035_landing_signal
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036_procedure_documents"
down_revision = "0035_landing_signal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("source_event") as batch_op:
        batch_op.add_column(
            sa.Column("source_notice_links", sa.JSON, nullable=False, server_default="[]")
        )
    op.create_table(
        "procedure_documents",
        sa.Column("procedure_document_key", sa.String(64), primary_key=True),
        sa.Column("source_system", sa.String(32), nullable=False),
        sa.Column("source_notice_id", sa.String(256), nullable=False),
        sa.Column("source_procedure_id", sa.String(256)),
        sa.Column("buyer_fingerprint", sa.String(64)),
        sa.Column("object_normalized", sa.Text),
        sa.Column("cpv_main", sa.String(8)),
        sa.Column("submission_deadline", sa.DateTime(timezone=True)),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("access_status", sa.String(32), nullable=False),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("media_type", sa.String(255)),
        sa.Column("byte_size", sa.BigInteger, nullable=False),
        sa.Column("archive_content", sa.LargeBinary),
        sa.Column("blocks", sa.JSON, nullable=False),
        sa.Column("join_status", sa.String(32), nullable=False),
        sa.Column("linked_award_key", sa.String(64)),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "source_system", "source_notice_id", "source_url", "content_hash",
            name="uq_procedure_documents_source_version",
        ),
    )
    for name, columns in (
        ("ix_procedure_documents_source_system", ["source_system"]),
        ("ix_procedure_documents_source_notice_id", ["source_notice_id"]),
        ("ix_procedure_documents_source_procedure_id", ["source_procedure_id"]),
        ("ix_procedure_documents_buyer_fingerprint", ["buyer_fingerprint"]),
        ("ix_procedure_documents_cpv_main", ["cpv_main"]),
        ("ix_procedure_documents_submission_deadline", ["submission_deadline"]),
        ("ix_procedure_documents_host", ["host"]),
        ("ix_procedure_documents_access_status", ["access_status"]),
        ("ix_procedure_documents_join_status", ["join_status"]),
        ("ix_procedure_documents_linked_award_key", ["linked_award_key"]),
        ("ix_procedure_documents_expires_at", ["expires_at"]),
    ):
        op.create_index(name, "procedure_documents", columns)


def downgrade() -> None:
    op.drop_table("procedure_documents")
    with op.batch_alter_table("source_event") as batch_op:
        batch_op.drop_column("source_notice_links")
