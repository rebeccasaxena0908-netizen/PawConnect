"""initial schema – one table per old CSV file plus audit_events.

Money columns (amount, estimated_cost) are BIGINT holding whole paise; the
app converts them to rupees with db.tables.Money.

Revision ID: 0001
Revises: 
Create Date: 2026-10-27 19:26:31.825304
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Generated with `alembic revision --autogenerate`, then reviewed by hand.
    op.create_table('audit_events',
    sa.Column('event_id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('timestamp', sa.DateTime(), nullable=False),
    sa.Column('actor', sa.String(length=60), nullable=False),
    sa.Column('role', sa.String(length=10), nullable=False),
    sa.Column('action', sa.String(length=30), nullable=False),
    sa.Column('details', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('event_id', name=op.f('pk_audit_events'))
    )
    with op.batch_alter_table('audit_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_events_action'), ['action'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_events_timestamp'), ['timestamp'], unique=False)

    op.create_table('inventory',
    sa.Column('item_id', sa.String(length=10), nullable=False),
    sa.Column('item', sa.String(length=60), nullable=False),
    sa.Column('category', sa.String(length=30), nullable=True),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('unit', sa.String(length=20), nullable=True),
    sa.Column('reorder_level', sa.Integer(), server_default='0', nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('quantity >= 0', name=op.f('ck_inventory_quantity_not_negative')),
    sa.CheckConstraint('reorder_level >= 0', name=op.f('ck_inventory_reorder_not_negative')),
    sa.PrimaryKeyConstraint('item_id', name=op.f('pk_inventory'))
    )
    op.create_table('users',
    sa.Column('user_id', sa.String(length=10), nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('email', sa.String(length=120), nullable=False),
    sa.Column('mobile', sa.String(length=10), nullable=False),
    sa.Column('role', sa.String(length=10), nullable=False),
    sa.Column('pincode', sa.String(length=6), nullable=False),
    sa.Column('password_hash', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('verified', sa.String(length=3), server_default='yes', nullable=False),
    sa.CheckConstraint("role IN ('Citizen', 'Rescuer', 'Donor', 'Adopter', 'Admin')", name=op.f('ck_users_role')),
    sa.CheckConstraint("verified IN ('yes', 'no')", name=op.f('ck_users_verified')),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email')),
    sa.UniqueConstraint('mobile', name=op.f('uq_users_mobile'))
    )
    op.create_table('rescue_cases',
    sa.Column('case_id', sa.String(length=12), nullable=False),
    sa.Column('reporter_id', sa.String(length=10), nullable=False),
    sa.Column('animal_type', sa.String(length=10), nullable=False),
    sa.Column('injury_level', sa.String(length=10), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('pincode', sa.String(length=6), nullable=False),
    sa.Column('address', sa.String(length=150), nullable=True),
    sa.Column('latitude', sa.Float(), nullable=True),
    sa.Column('longitude', sa.Float(), nullable=True),
    sa.Column('location_source', sa.String(length=40), nullable=True),
    sa.Column('photo_path', sa.String(length=255), nullable=True),
    sa.Column('status', sa.String(length=25), server_default='Reported', nullable=False),
    sa.Column('rescuer_id', sa.String(length=10), nullable=True),
    sa.Column('reported_at', sa.DateTime(), nullable=False),
    sa.Column('assigned_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('medical_notes', sa.Text(), nullable=True),
    sa.Column('estimated_cost', sa.BigInteger(), nullable=True),
    sa.CheckConstraint("animal_type IN ('Dog', 'Cat', 'Cow', 'Bird', 'Monkey', 'Other')", name=op.f('ck_rescue_cases_animal_type')),
    sa.CheckConstraint("injury_level IN ('Low', 'Moderate', 'Critical')", name=op.f('ck_rescue_cases_injury_level')),
    sa.CheckConstraint("status = 'Reported' OR rescuer_id IS NOT NULL", name=op.f('ck_rescue_cases_rescuer_when_assigned')),
    sa.CheckConstraint("status IN ('Reported', 'Assigned', 'In Transit', 'Sheltered/In Treatment', 'Recovered')", name=op.f('ck_rescue_cases_status')),
    sa.CheckConstraint('estimated_cost IS NULL OR estimated_cost >= 0', name=op.f('ck_rescue_cases_cost_not_negative')),
    sa.ForeignKeyConstraint(['reporter_id'], ['users.user_id'], name=op.f('fk_rescue_cases_reporter_id_users')),
    sa.ForeignKeyConstraint(['rescuer_id'], ['users.user_id'], name=op.f('fk_rescue_cases_rescuer_id_users')),
    sa.PrimaryKeyConstraint('case_id', name=op.f('pk_rescue_cases'))
    )
    with op.batch_alter_table('rescue_cases', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_rescue_cases_pincode'), ['pincode'], unique=False)
        batch_op.create_index(batch_op.f('ix_rescue_cases_status'), ['status'], unique=False)
        batch_op.create_index('ix_rescue_cases_status_pincode', ['status', 'pincode'], unique=False)

    op.create_table('allocations',
    sa.Column('allocation_id', sa.String(length=12), nullable=False),
    sa.Column('case_id', sa.String(length=12), nullable=False),
    sa.Column('source_fund', sa.String(length=30), nullable=False),
    sa.Column('amount', sa.BigInteger(), nullable=False),
    sa.Column('purpose', sa.String(length=30), nullable=False),
    sa.Column('allocated_by', sa.String(length=10), nullable=False),
    sa.Column('allocated_at', sa.DateTime(), nullable=False),
    sa.Column('notes', sa.String(length=200), nullable=True),
    sa.CheckConstraint("purpose IN ('Surgery', 'Medicines', 'Vaccination', 'Food', 'Shelter maintenance', 'Transport')", name=op.f('ck_allocations_purpose')),
    sa.CheckConstraint("source_fund IN ('General Shelter Fund', 'Emergency Feed Fund')", name=op.f('ck_allocations_source_fund')),
    sa.CheckConstraint('amount > 0', name=op.f('ck_allocations_amount_positive')),
    sa.ForeignKeyConstraint(['allocated_by'], ['users.user_id'], name=op.f('fk_allocations_allocated_by_users')),
    sa.ForeignKeyConstraint(['case_id'], ['rescue_cases.case_id'], name=op.f('fk_allocations_case_id_rescue_cases')),
    sa.PrimaryKeyConstraint('allocation_id', name=op.f('pk_allocations'))
    )
    with op.batch_alter_table('allocations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_allocations_case_id'), ['case_id'], unique=False)

    op.create_table('animals',
    sa.Column('animal_id', sa.String(length=10), nullable=False),
    sa.Column('name', sa.String(length=40), nullable=False),
    sa.Column('species', sa.String(length=10), nullable=False),
    sa.Column('breed', sa.String(length=40), nullable=True),
    sa.Column('age_years', sa.Float(), nullable=True),
    sa.Column('gender', sa.String(length=10), nullable=True),
    sa.Column('vaccinated', sa.String(length=3), server_default='no', nullable=False),
    sa.Column('sterilized', sa.String(length=3), server_default='no', nullable=False),
    sa.Column('temperament', sa.String(length=60), nullable=True),
    sa.Column('description', sa.String(length=300), nullable=True),
    sa.Column('photo_path', sa.String(length=255), nullable=True),
    sa.Column('status', sa.String(length=10), server_default='Available', nullable=False),
    sa.Column('case_id', sa.String(length=12), nullable=True),
    sa.Column('added_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("species IN ('Dog', 'Cat', 'Cow', 'Bird', 'Monkey', 'Other')", name=op.f('ck_animals_species')),
    sa.CheckConstraint("status IN ('Available', 'Adopted')", name=op.f('ck_animals_status')),
    sa.CheckConstraint("sterilized IN ('yes', 'no')", name=op.f('ck_animals_sterilized')),
    sa.CheckConstraint("vaccinated IN ('yes', 'no')", name=op.f('ck_animals_vaccinated')),
    sa.CheckConstraint('age_years IS NULL OR (age_years >= 0 AND age_years <= 40)', name=op.f('ck_animals_age')),
    sa.ForeignKeyConstraint(['case_id'], ['rescue_cases.case_id'], name=op.f('fk_animals_case_id_rescue_cases')),
    sa.PrimaryKeyConstraint('animal_id', name=op.f('pk_animals'))
    )
    with op.batch_alter_table('animals', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_animals_status'), ['status'], unique=False)

    op.create_table('donations',
    sa.Column('transaction_id', sa.String(length=30), nullable=False),
    sa.Column('donor_id', sa.String(length=10), nullable=False),
    sa.Column('donor_name', sa.String(length=60), nullable=False),
    sa.Column('donor_email', sa.String(length=120), nullable=True),
    sa.Column('amount', sa.BigInteger(), nullable=False),
    sa.Column('contribution_type', sa.String(length=30), nullable=False),
    sa.Column('case_id', sa.String(length=12), nullable=True),
    sa.Column('method', sa.String(length=10), nullable=False),
    sa.Column('payment_ref', sa.String(length=60), nullable=True),
    sa.Column('masked_account', sa.String(length=60), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('timestamp', sa.DateTime(), nullable=False),
    sa.CheckConstraint("contribution_type <> 'Specific Medical Case' OR case_id IS NOT NULL", name=op.f('ck_donations_case_for_specific')),
    sa.CheckConstraint("contribution_type IN ('General Shelter Fund', 'Specific Medical Case', 'Emergency Feed Fund')", name=op.f('ck_donations_contribution_type')),
    sa.CheckConstraint("method IN ('UPI', 'Card', 'Razorpay')", name=op.f('ck_donations_method')),
    sa.CheckConstraint("status IN ('Pending', 'Success', 'Failed')", name=op.f('ck_donations_status')),
    sa.CheckConstraint('amount > 0', name=op.f('ck_donations_amount_positive')),
    sa.ForeignKeyConstraint(['case_id'], ['rescue_cases.case_id'], name=op.f('fk_donations_case_id_rescue_cases')),
    sa.ForeignKeyConstraint(['donor_id'], ['users.user_id'], name=op.f('fk_donations_donor_id_users')),
    sa.PrimaryKeyConstraint('transaction_id', name=op.f('pk_donations'))
    )
    with op.batch_alter_table('donations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_donations_donor_id'), ['donor_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_donations_payment_ref'), ['payment_ref'], unique=False)
        batch_op.create_index(batch_op.f('ix_donations_timestamp'), ['timestamp'], unique=False)

    op.create_table('adoption_applications',
    sa.Column('application_id', sa.String(length=12), nullable=False),
    sa.Column('applicant_id', sa.String(length=10), nullable=False),
    sa.Column('applicant_name', sa.String(length=60), nullable=False),
    sa.Column('animal_id', sa.String(length=10), nullable=False),
    sa.Column('housing', sa.String(length=60), nullable=False),
    sa.Column('experience', sa.String(length=60), nullable=False),
    sa.Column('hours_alone', sa.String(length=60), nullable=False),
    sa.Column('family', sa.String(length=60), nullable=False),
    sa.Column('budget', sa.String(length=60), nullable=False),
    sa.Column('reason', sa.String(length=400), nullable=True),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=15), nullable=False),
    sa.Column('submitted_at', sa.DateTime(), nullable=False),
    sa.Column('reviewed_by', sa.String(length=10), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(), nullable=True),
    sa.CheckConstraint("status IN ('Pre-Approved', 'Under Review', 'Approved', 'Rejected', 'Closed')", name=op.f('ck_adoption_applications_status')),
    sa.CheckConstraint('score BETWEEN 0 AND 100', name=op.f('ck_adoption_applications_score_range')),
    sa.ForeignKeyConstraint(['animal_id'], ['animals.animal_id'], name=op.f('fk_adoption_applications_animal_id_animals')),
    sa.ForeignKeyConstraint(['applicant_id'], ['users.user_id'], name=op.f('fk_adoption_applications_applicant_id_users')),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.user_id'], name=op.f('fk_adoption_applications_reviewed_by_users')),
    sa.PrimaryKeyConstraint('application_id', name=op.f('pk_adoption_applications'))
    )
    with op.batch_alter_table('adoption_applications', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_adoption_applications_animal_id'), ['animal_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_adoption_applications_applicant_id'), ['applicant_id'], unique=False)



def downgrade() -> None:
    # Generated with `alembic revision --autogenerate`, then reviewed by hand.
    with op.batch_alter_table('adoption_applications', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_adoption_applications_applicant_id'))
        batch_op.drop_index(batch_op.f('ix_adoption_applications_animal_id'))

    op.drop_table('adoption_applications')
    with op.batch_alter_table('donations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_donations_timestamp'))
        batch_op.drop_index(batch_op.f('ix_donations_payment_ref'))
        batch_op.drop_index(batch_op.f('ix_donations_donor_id'))

    op.drop_table('donations')
    with op.batch_alter_table('animals', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_animals_status'))

    op.drop_table('animals')
    with op.batch_alter_table('allocations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_allocations_case_id'))

    op.drop_table('allocations')
    with op.batch_alter_table('rescue_cases', schema=None) as batch_op:
        batch_op.drop_index('ix_rescue_cases_status_pincode')
        batch_op.drop_index(batch_op.f('ix_rescue_cases_status'))
        batch_op.drop_index(batch_op.f('ix_rescue_cases_pincode'))

    op.drop_table('rescue_cases')
    op.drop_table('users')
    op.drop_table('inventory')
    with op.batch_alter_table('audit_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_events_timestamp'))
        batch_op.drop_index(batch_op.f('ix_audit_events_action'))

    op.drop_table('audit_events')
