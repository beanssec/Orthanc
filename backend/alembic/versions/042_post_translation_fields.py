"""Add translation fields to posts table."""
from alembic import op
import sqlalchemy as sa

revision = "042_post_translation"
down_revision = "041_evidence_classification"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("posts", sa.Column("detected_language", sa.String(10), nullable=True))
    op.add_column("posts", sa.Column("translated_content", sa.Text(), nullable=True))
    op.add_column("posts", sa.Column("translation_model", sa.String(100), nullable=True))

def downgrade() -> None:
    op.drop_column("posts", "translation_model")
    op.drop_column("posts", "translated_content")
    op.drop_column("posts", "detected_language")
