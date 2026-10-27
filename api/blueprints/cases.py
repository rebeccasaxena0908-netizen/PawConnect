"""Rescue cases: SOS reports, the rescuer queue, status updates, notes and photos."""
import io

from flask import g, request, send_file
from flask_smorest import Blueprint

from api.schemas import AdvanceIn, AssignIn, CaseIn, NoteIn, StatusIn
from api.security import ApiError, require_auth, require_permission
from api.util import records
from core import workflows as wf

blp = Blueprint("cases", __name__, url_prefix="/cases", description="Rescue cases (SOS → recovery)")


def _visible(df):
    """Admins see every case, rescuers the open queue + their own, citizens their own reports."""
    user = g.user
    if user.can("assign_case"):
        return df
    if user.can("view_cases"):
        return df[(df["status"] == "Reported") | (df["rescuer_id"] == user.user_id)]
    if user.can("view_own_reports"):
        return df[df["reporter_id"] == user.user_id]
    raise ApiError(403, f"{user.role}s can't view rescue cases.")


def _visible_case(case_id: str):
    case = wf.load_case(case_id)                 # 404 if it doesn't exist
    df = wf.list_cases()
    if case_id not in set(_visible(df[df["case_id"] == case_id])["case_id"]):
        raise ApiError(403, "You can't see this case.")
    return case


def _uploaded_file(field: str):
    upload = request.files.get(field)
    if upload is None or not upload.filename:
        raise ApiError(400, f"Send the file as multipart/form-data in the field '{field}'.")
    return upload


@blp.route("", methods=["GET"])
@blp.response(200)
@require_auth
def list_cases():
    """Cases you are allowed to see, newest first (with the rescuer's name)."""
    df = _visible(wf.list_cases()).iloc[::-1]
    names = wf.list_users("Rescuer").set_index("user_id")["name"]
    return records(df.assign(rescuer_name=df["rescuer_id"].map(names).fillna("")))


@blp.route("", methods=["POST"])
@blp.arguments(CaseIn)
@blp.response(201)
@require_permission("report_sos")
def create_case(body):
    """Send an SOS. The pincode is turned into map coordinates."""
    case = wf.create_rescue_case(g.user, body["animal_type"], body["injury_level"], body["description"],
                                 body["pincode"], body["address"], use_network=body["use_network"])
    return case.to_dict()


@blp.route("/<case_id>", methods=["GET"])
@blp.response(200)
@require_auth
def get_case(case_id):
    return _visible_case(case_id).to_dict()


@blp.route("/<case_id>/accept", methods=["POST"])
@blp.response(200)
@require_permission("accept_case")
def accept(case_id):
    """Take an SOS. 409 if another rescuer accepted it first."""
    return wf.accept_case(case_id, g.user).to_dict()


@blp.route("/<case_id>/advance", methods=["POST"])
@blp.arguments(AdvanceIn)
@blp.response(200)
@require_permission("update_case")
def advance(body, case_id):
    """Move the case to its next stage (Assigned → In Transit → … → Recovered)."""
    return wf.advance_case(case_id, g.user, body["note"]).to_dict()


@blp.route("/<case_id>/notes", methods=["POST"])
@blp.arguments(NoteIn)
@blp.response(200)
@require_permission("update_case")
def add_note(body, case_id):
    """Add a medical / field note and optionally update the cost estimate."""
    return wf.add_case_note(case_id, g.user, body["note"], body["estimated_cost"]).to_dict()


@blp.route("/<case_id>/photo", methods=["POST"])
@blp.response(200)
@require_auth
def upload_photo(case_id):
    """Upload a photo (multipart/form-data, field name 'photo'; JPG, PNG or WEBP)."""
    upload = _uploaded_file("photo")
    return wf.attach_case_photo(case_id, g.user, upload.read(), upload.filename).to_dict()


@blp.route("/<case_id>/photo", methods=["GET"])
@require_auth
def get_photo(case_id):
    _visible_case(case_id)
    path = wf.case_photo_file(case_id)
    if path is None:
        raise ApiError(404, "This case has no photo.")
    return send_file(path)


@blp.route("/<case_id>/assign", methods=["POST"])
@blp.arguments(AssignIn)
@blp.response(200)
@require_permission("assign_case")
def assign(body, case_id):
    return wf.assign_case(case_id, body["rescuer_id"], g.user).to_dict()


@blp.route("/<case_id>/status", methods=["POST"])
@blp.arguments(StatusIn)
@blp.response(200)
@require_permission("assign_case")
def set_status(body, case_id):
    """Admin correction: set any stage directly."""
    return wf.set_case_status(case_id, body["status"], g.user).to_dict()


@blp.route("/import", methods=["POST"])
@blp.response(200)
@require_permission("assign_case")
def import_offline():
    """Import cases recorded offline (multipart field 'file', CSV)."""
    upload = _uploaded_file("file")
    imported, skipped = wf.import_offline_cases(g.user, io.BytesIO(upload.read()))
    return {"imported": imported, "skipped": skipped}
