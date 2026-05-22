"""
routes/poe.py — Portfolio of Evidence (POE) for Trainers
Trainers upload professional teaching and validation documents.
"""

from flask import (Blueprint, render_template, request,
                   redirect, url_for, flash, abort, jsonify)
from auth_utils import login_required, current_user, write_audit_log
from db import get_service_client
from notify import send_notification

poe_bp = Blueprint("poe", __name__)

POE_CATEGORIES = [
    "Lesson Plans",
    "Scheme of Work",
    "Assessment Tools",
    "Student Work Samples",
    "Trainer Qualifications",
    "Professional Development",
    "Industry Experience",
    "Research & Publications",
    "Observation Reports",
    "Moderation Records",
    "Other",
]


def _db():
    return get_service_client()


def _trainer_row(user_id):
    rows = _db().table("trainers").select("*, departments(name)").eq("user_id", user_id).limit(1).execute().data or []
    return rows[0] if rows else None


# ── Trainer: My POE ───────────────────────────────────────────────────────────

@poe_bp.route("/my-poe")
@login_required
def my_poe():
    user = current_user()
    if user.get("role") not in ("trainer", "dept_admin", "super_admin"):
        abort(403)
    db = _db()
    trainer = _trainer_row(user["id"])
    if not trainer and user.get("role") == "trainer":
        abort(403)

    trainer_id = trainer["id"] if trainer else request.args.get("trainer_id", type=int)
    if not trainer_id:
        abort(400)

    docs = (db.table("poe_documents")
              .select("*")
              .eq("trainer_id", trainer_id)
              .order("created_at", desc=True)
              .execute().data or [])

    # Group by category
    from collections import defaultdict
    grouped = defaultdict(list)
    for d in docs:
        grouped[d["doc_category"]].append(d)

    return render_template("poe/my_poe.html",
                           trainer=trainer, docs=docs,
                           grouped=dict(grouped),
                           categories=POE_CATEGORIES, user=user)


# ── Trainer: Upload Document ──────────────────────────────────────────────────

@poe_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload_doc():
    user = current_user()
    if user.get("role") not in ("trainer", "dept_admin", "super_admin"):
        abort(403)
    db = _db()
    trainer = _trainer_row(user["id"])
    if not trainer and user.get("role") == "trainer":
        abort(403)

    error = None
    if request.method == "POST":
        trainer_id  = trainer["id"] if trainer else request.form.get("trainer_id", type=int)
        category    = request.form.get("doc_category", "").strip()
        title       = request.form.get("doc_title", "").strip()
        description = request.form.get("description", "").strip()
        file_url    = request.form.get("file_url", "").strip()
        gdrive_id   = request.form.get("google_drive_id", "").strip()

        if not category or not title or not file_url:
            error = "Category, title and file URL are required."
        else:
            ext = file_url.split(".")[-1].lower() if "." in file_url else ""
            ftype = "photo" if ext in ("jpg","jpeg","png","gif","webp") \
                   else "video" if ext in ("mp4","mov","avi","mkv") \
                   else "pdf" if ext == "pdf" else "document"

            db.table("poe_documents").insert({
                "trainer_id":     trainer_id,
                "doc_category":   category,
                "doc_title":      title,
                "description":    description,
                "file_url":       file_url,
                "file_name":      file_url.split("/")[-1],
                "file_type":      ftype,
                "google_drive_id": gdrive_id or None,
            }).execute()

            write_audit_log("poe_upload", target=title)
            flash("Document uploaded to POE.", "success")
            return redirect(url_for("poe.my_poe"))

    return render_template("poe/upload_doc.html",
                           trainer=trainer, categories=POE_CATEGORIES,
                           error=error, user=user)


# ── Trainer: Delete Document ──────────────────────────────────────────────────

@poe_bp.route("/delete/<int:doc_id>", methods=["POST"])
@login_required
def delete_doc(doc_id):
    user = current_user()
    db = _db()
    trainer = _trainer_row(user["id"])

    doc = (db.table("poe_documents").select("trainer_id").eq("id", doc_id).limit(1).execute().data or [None])[0]
    if not doc:
        abort(404)

    # Only own trainer or admin can delete
    if user.get("role") == "trainer" and (not trainer or doc["trainer_id"] != trainer["id"]):
        abort(403)

    db.table("poe_documents").delete().eq("id", doc_id).execute()
    write_audit_log("poe_delete", target=str(doc_id))
    flash("Document deleted.", "success")
    return redirect(url_for("poe.my_poe"))


# ── HOD/Admin: Review Trainer POE ────────────────────────────────────────────

@poe_bp.route("/review/<int:trainer_id>")
@login_required
def review_poe(trainer_id):
    user = current_user()
    if user.get("role") not in ("hod", "dept_admin", "super_admin", "deputy_principal", "external_verifier"):
        abort(403)
    db = _db()

    trainer = (db.table("trainers").select("*, departments(name)").eq("id", trainer_id).limit(1).execute().data or [None])[0]
    if not trainer:
        abort(404)

    docs = (db.table("poe_documents")
              .select("*")
              .eq("trainer_id", trainer_id)
              .order("doc_category").order("created_at", desc=True)
              .execute().data or [])

    from collections import defaultdict
    grouped = defaultdict(list)
    for d in docs:
        grouped[d["doc_category"]].append(d)

    return render_template("poe/review_poe.html",
                           trainer=trainer, docs=docs,
                           grouped=dict(grouped),
                           categories=POE_CATEGORIES, user=user)


# ── HOD/Admin: Verify Document ────────────────────────────────────────────────

@poe_bp.route("/verify/<int:doc_id>", methods=["POST"])
@login_required
def verify_doc(doc_id):
    user = current_user()
    if user.get("role") not in ("hod", "dept_admin", "super_admin", "deputy_principal", "external_verifier"):
        abort(403)
    db = _db()

    from utils import now_eat
    db.table("poe_documents").update({
        "is_verified":  True,
        "verified_by":  user["id"],
        "verified_at":  now_eat().isoformat(),
    }).eq("id", doc_id).execute()

    # Notify trainer
    doc = (db.table("poe_documents").select("trainer_id,doc_title").eq("id", doc_id).limit(1).execute().data or [{}])[0]
    trainer_row = (db.table("trainers").select("user_id").eq("id", doc.get("trainer_id")).limit(1).execute().data or [{}])[0]
    if trainer_row.get("user_id"):
        send_notification(trainer_row["user_id"], "POE Document Verified",
                          f"Your document '{doc.get('doc_title')}' has been verified.",
                          notif_type="success", module="poe", reference_id=doc_id)

    write_audit_log("poe_verify", target=str(doc_id))
    flash("Document verified.", "success")
    return redirect(request.referrer or url_for("poe.my_poe"))


# ── Admin: All Trainers POE Overview ─────────────────────────────────────────

@poe_bp.route("/admin/overview")
@login_required
def admin_overview():
    user = current_user()
    if user.get("role") not in ("hod", "dept_admin", "super_admin", "deputy_principal", "external_verifier"):
        abort(403)
    db = _db()
    dept_id = user.get("dept_id")

    query = db.table("trainers").select("*, departments(name)")
    if dept_id and user.get("role") not in ("super_admin", "deputy_principal", "external_verifier"):
        query = query.eq("department_id", dept_id)
    trainers = query.order("name").execute().data or []

    # Enrich with doc counts
    for t in trainers:
        docs = db.table("poe_documents").select("id,is_verified", count="exact").eq("trainer_id", t["id"]).execute()
        t["doc_count"]      = docs.count or 0
        t["verified_count"] = sum(1 for d in (docs.data or []) if d.get("is_verified"))

    return render_template("poe/admin_overview.html",
                           trainers=trainers, user=user)
