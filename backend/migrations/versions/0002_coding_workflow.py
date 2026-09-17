"""Coding workflow schema.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

from app.database import Base
from app.models import *  # noqa: F403

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    for table_name in (
        "evaluation_metrics",
        "evaluation_runs",
        "gold_encounters",
        "review_changes",
        "reviews",
        "rule_decisions",
        "coding_lines",
        "coding_results",
        "model_runs",
        "candidate_codes",
        "clinical_facts",
        "evidence_spans",
        "encounters",
        "chart_pages",
        "charts",
    ):
        op.drop_table(table_name)
