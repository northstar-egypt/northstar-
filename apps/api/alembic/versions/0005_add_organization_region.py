"""add organization.region

The governorate an Egyptian club or academy is in, as an ISO 3166-2:EG code (app/regions.py).
The federation's oversight screen draws coverage by governorate from it: players tracked per
million people, so a governorate the platform has not reached shows as the gap it is. Until
now Organization stored only a country, and that panel was always empty.

Nullable: an organization abroad, or a national body, has no governorate. Existing rows are
filled by the seed container (data/pipelines/synthetic/regions.py) for synthetic clubs; a real
deployment would have the federation set them.

Revision ID: 0005_add_organization_region
Revises: 0004_create_match_event
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_add_organization_region"
down_revision: str | None = "0004_create_match_event"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("organization", sa.Column("region", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("organization", "region")
