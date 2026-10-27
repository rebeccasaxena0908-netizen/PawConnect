"""Fund balances, allocation of money to cases, and per-case funding."""
from flask import g
from flask_smorest import Blueprint

from api.schemas import AllocateIn
from api.security import require_auth, require_permission
from api.util import records
from core import workflows as wf

blp = Blueprint("funds", __name__, url_prefix="/funds", description="Shelter funds and allocations")


@blp.route("/overview", methods=["GET"])
@blp.response(200)
@require_auth
def overview():
    """Raised, allocated and available money for each fund (transparency for everyone)."""
    return records(wf.funds_overview().reset_index())


@blp.route("/allocate", methods=["POST"])
@blp.arguments(AllocateIn)
@blp.response(201)
@require_permission("allocate_funds")
def allocate(body):
    """Move money from a fund to a case. 409 if the fund doesn't have enough (checked under a lock)."""
    allocation = wf.allocate_funds(g.user, body["case_id"], body["amount"], body["purpose"],
                                   body["source_fund"], body["notes"])
    return allocation.to_dict()


@blp.route("/allocations", methods=["GET"])
@blp.response(200)
@require_auth
def allocations():
    """Every allocation – shown to donors so they can see where money went."""
    return records(wf.list_allocations())


@blp.route("/case-funding", methods=["GET"])
@blp.response(200)
@require_auth
def case_funding():
    """Estimated cost, money given directly, money allocated and the gap, per case."""
    return records(wf.case_funding())
