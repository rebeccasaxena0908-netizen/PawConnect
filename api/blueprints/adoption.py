"""Animals in the adoption catalogue, applications and admin review."""
from flask import g
from flask_smorest import Blueprint

from api.schemas import AnimalIn, AnimalQuery, ApplicationIn, ReviewIn
from api.security import ApiError, require_auth, require_permission
from api.util import records
from core import workflows as wf
from core.models import QUESTIONNAIRE

animals = Blueprint("animals", __name__, url_prefix="/animals", description="Adoption catalogue")
blp = Blueprint("adoption", __name__, url_prefix="/adoption", description="Adoption applications")


@animals.route("", methods=["GET"])
@animals.arguments(AnimalQuery, location="query")
@animals.response(200)
@require_auth
def list_animals(query):
    """All animals, or only those still available (?available=true)."""
    return records(wf.list_animals(only_available=query["available"]))


@animals.route("", methods=["POST"])
@animals.arguments(AnimalIn)
@animals.response(201)
@require_permission("manage_animals")
def add_animal(body):
    return wf.add_animal(g.user, **body).to_dict()


@blp.route("/questionnaire", methods=["GET"])
@blp.response(200)
@require_auth
def questionnaire():
    """The screening questions and the points each answer is worth."""
    return QUESTIONNAIRE


@blp.route("/applications", methods=["POST"])
@blp.arguments(ApplicationIn)
@blp.response(201)
@require_permission("apply_adoption")
def apply(body):
    """Apply to adopt. Scored out of 100; 65+ is pre-approved automatically."""
    return wf.submit_application(g.user, body["animal_id"], body["answers"], body["reason"]).to_dict()


@blp.route("/applications", methods=["GET"])
@blp.response(200)
@require_auth
def list_applications():
    """Admins see every application, everyone else their own."""
    if g.user.can("review_applications"):
        return records(wf.list_applications())
    if not g.user.can("apply_adoption"):
        raise ApiError(403, f"{g.user.role}s don't have adoption applications.")
    return records(wf.list_applications(g.user))


@blp.route("/applications/<application_id>/review", methods=["POST"])
@blp.arguments(ReviewIn)
@blp.response(200)
@require_permission("review_applications")
def review(body, application_id):
    """Approve or reject. Approving marks the animal Adopted and closes the other applications."""
    return wf.review_application(g.user, application_id, body["decision"]).to_dict()
