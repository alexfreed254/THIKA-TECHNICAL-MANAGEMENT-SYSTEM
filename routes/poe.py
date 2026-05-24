"""
routes/poe.py — Portfolio of Evidence (POE) for Trainers and Trainees
Trainers upload professional teaching and validation documents.
Trainees upload assessment evidence and portfolio components.
"""

from flask import (Blueprint, render_template, request,
                   redirect, url_for, flash, abort, jsonify)
from auth_utils import login_required, current_user, write_audit_log
from db import get_service_client
from notify import send_notification
from werkzeug.utils import secure_filename
import os
import uuid
from datetime import datetime

poe_bp = Blueprint("poe", __name__)

TRAINER_POE_CATEGORIES = [
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

TRAINEE_POE_CATEGORIES = [
    "Assessment Scripts",
    "Practical Evidence",
    "Project Work",
    "Industrial Attachment",
    "Case Studies",
    "Presentations",
    "Certificates",
    "Achievements",
    "Other",
]


def _db():
    return get_service_client()


def _trainer_row(user_id):
    rows = _db().table("trainers").select("*, departments(name)").eq("user_id", user_id).limit(1).execute().data or []
    return rows[0] if rows else None


def _student_row(user_id):
    rows = _db().table("students").select("*").eq("user_id", user_id).limit(1).execute().data or []
    return rows[0] if rows else None


def allowed_file(filename: str) -> bool:
    """Check if file extension is allowed."""
    allowed_exts = {'.pdf', '.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp4', '.mov', '.avi', '.mkv', '.doc', '.docx', '.ppt', '.pptx'}
    return any(filename.lower().endswith(ext) for ext in allowed_exts)


def generate_storage_path(user_id: str, category: str, filename: str) -> str:
    """
    Generate a structured path for Supabase Storage.
    Format: {category}/{user_id}/{timestamp}_{uuid}_{secure_filename}
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    unique_id = str(uuid.uuid4())[:8]
    secure_name = secure_filename(filename)
    return f"{category}/{user_id}/{timestamp}_{unique_id}_{secure_name}"


def upload_to_supabase(supabase, bucket: str, file, path: str) -> str:
    """
    Upload file to Supabase Storage bucket.
    Returns the public URL or raises exception on failure.
    """
    try:
        file.seek(0)
        supabase.storage.from_(bucket).upload(
            path=path,
            file=file.read(),
            file_options={"content-type": file.content_type, "upsert": "false"}
        )
        # Get public URL (bucket must be public)
        public_url = supabase.storage.from_(bucket).get_public_url(path)
        return public_url
    except Exception as e:
        current_app.logger.error(f"Upload failed to {bucket}/{path}: {str(e)}")
        raise


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
                           categories=TRAINER_POE_CATEGORIES, user=user)


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
                           trainer=trainer, categories=TRAINER_POE_CATEGORIES,
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
                           categories=TRAINER_POE_CATEGORIES, user=user)


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


# ── Trainee: My POE ───────────────────────────────────────────────────────────

@poe_bp.route("/trainee/my-poe")
@login_required
def trainee_my_poe():
    user = current_user()
    if user.get("role") != "student":
        abort(403)
    db = _db()
    student = _student_row(user["id"])
    if not student:
        abort(403)

    trainee_id = student["id"]
    
    # Get trainee's POE components
    docs = (db.table("trainee_poe_components")
              .select("*")
              .eq("trainee_id", trainee_id)
              .order("created_at", desc=True)
              .execute().data or [])

    # Group by category
    from collections import defaultdict
    grouped = defaultdict(list)
    for d in docs:
        grouped[d["component_category"]].append(d)

    return render_template("poe/trainee_my_poe.html",
                           student=student, docs=docs,
                           grouped=dict(grouped),
                           categories=TRAINEE_POE_CATEGORIES, user=user)


# ── Trainee: Upload POE Component ──────────────────────────────────────────────

@poe_bp.route("/trainee/upload", methods=["GET", "POST"])
@login_required
def trainee_upload_poe():
    user = current_user()
    if user.get("role") != "student":
        abort(403)
    db = _db()
    student = _student_row(user["id"])
    if not student:
        abort(403)

    error = None
    if request.method == "POST":
        category = request.form.get("component_category", "").strip()
        title = request.form.get("component_title", "").strip()
        description = request.form.get("description", "").strip()
        
        file = request.files.get("file")
        
        if not category or not title:
            error = "Category and title are required."
        elif not file or not file.filename or not allowed_file(file.filename):
            error = "Please upload a valid file."
        else:
            try:
                from flask import current_app
                trainee_id = student["id"]
                
                # Generate storage path and upload to Supabase
                file_path = generate_storage_path(str(trainee_id), category, file.filename)
                bucket_poe = current_app.config.get("BUCKET_POE", "poe-components")
                
                file_url = upload_to_supabase(db, bucket_poe, file, file_path)
                
                # Determine file type
                ext = file.filename.split(".")[-1].lower() if "." in file.filename else ""
                ftype = "photo" if ext in ("jpg","jpeg","png","gif","webp") \
                       else "video" if ext in ("mp4","mov","avi","mkv") \
                       else "pdf" if ext == "pdf" else "document"

                db.table("trainee_poe_components").insert({
                    "trainee_id": trainee_id,
                    "component_category": category,
                    "component_title": title,
                    "description": description,
                    "file_path": file_path,
                    "file_name": secure_filename(file.filename),
                    "file_type": ftype,
                    "file_url": file_url,
                }).execute()

                write_audit_log("trainee_poe_upload", target=title)
                flash("POE component uploaded successfully.", "success")
                return redirect(url_for("poe.trainee_my_poe"))
            except Exception as e:
                error = f"Upload failed: {str(e)}"

    return render_template("poe/trainee_upload_poe.html",
                           student=student, categories=TRAINEE_POE_CATEGORIES,
                           error=error, user=user)


# ── Trainee: Delete POE Component ──────────────────────────────────────────────

@poe_bp.route("/trainee/delete/<int:component_id>", methods=["POST"])
@login_required
def trainee_delete_poe(component_id):
    user = current_user()
    db = _db()
    student = _student_row(user["id"])

    component = (db.table("trainee_poe_components").select("trainee_id,file_path").eq("id", component_id).limit(1).execute().data or [None])[0]
    if not component:
        abort(404)

    # Only own trainee can delete
    if not student or component["trainee_id"] != student["id"]:
        abort(403)

    # Delete from Supabase Storage if file exists
    if component.get("file_path"):
        try:
            from flask import current_app
            bucket_poe = current_app.config.get("BUCKET_POE", "poe-components")
            db.storage.from_(bucket_poe).remove([component["file_path"]])
        except Exception:
            pass  # Continue even if storage deletion fails

    db.table("trainee_poe_components").delete().eq("id", component_id).execute()
    write_audit_log("trainee_poe_delete", target=str(component_id))
    flash("POE component deleted.", "success")
    return redirect(url_for("poe.trainee_my_poe"))


# ── Trainer/Admin: Review Trainee POE ───────────────────────────────────────────

@poe_bp.route("/trainee/review/<int:trainee_id>")
@login_required
def review_trainee_poe(trainee_id):
    user = current_user()
    if user.get("role") not in ("trainer", "dept_admin", "super_admin", "hod"):
        abort(403)
    db = _db()

    student = (db.table("students").select("*, departments(name)").eq("id", trainee_id).limit(1).execute().data or [None])[0]
    if not student:
        abort(404)

    docs = (db.table("trainee_poe_components")
              .select("*")
              .eq("trainee_id", trainee_id)
              .order("component_category").order("created_at", desc=True)
              .execute().data or [])

    from collections import defaultdict
    grouped = defaultdict(list)
    for d in docs:
        grouped[d["component_category"]].append(d)

    return render_template("poe/review_trainee_poe.html",
                           student=student, docs=docs,
                           grouped=dict(grouped),
                           categories=TRAINEE_POE_CATEGORIES, user=user)


# ── Trainer/Admin: Verify Trainee POE Component ──────────────────────────────────

@poe_bp.route("/trainee/verify/<int:component_id>", methods=["POST"])
@login_required
def verify_trainee_poe_component(component_id):
    user = current_user()
    if user.get("role") not in ("trainer", "dept_admin", "super_admin", "hod"):
        abort(403)
    db = _db()

    from utils import now_eat
    db.table("trainee_poe_components").update({
        "is_verified": True,
        "verified_by": user["id"],
        "verified_at": now_eat().isoformat(),
    }).eq("id", component_id).execute()

    # Notify trainee
    component = (db.table("trainee_poe_components").select("trainee_id,component_title").eq("id", component_id).limit(1).execute().data or [{}])[0]
    student_row = (db.table("students").select("user_id").eq("id", component.get("trainee_id")).limit(1).execute().data or [{}])[0]
    if student_row.get("user_id"):
        send_notification(student_row["user_id"], "POE Component Verified",
                          f"Your POE component '{component.get('component_title')}' has been verified.",
                          notif_type="success", module="poe", reference_id=component_id)

    write_audit_log("trainee_poe_verify", target=str(component_id))
    flash("POE component verified.", "success")
    return redirect(request.referrer or url_for("poe.trainee_my_poe"))
