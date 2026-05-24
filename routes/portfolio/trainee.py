"""E-Portfolio - Trainee routes.

Integrated into the existing Attendance system auth/session model:
- Uses session-based RBAC from auth_utils.py
- Uses Supabase via db.get_service_client() (server-side admin)
- Uses Supabase Storage for file uploads

This file adds functionality under /portfolio/* without changing
existing Attendance routes.
"""

from datetime import datetime
import os
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from auth_utils import login_required, student_required, current_user, write_audit_log
from db import get_service_client
from werkzeug.utils import secure_filename

from utils import now_eat_naive

# E-Portfolio BP shares the module package BP
from routes.portfolio import portfolio_bp

# Use a dedicated name to keep endpoints unique.
portfolio_trainee_bp = portfolio_bp

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "mp4", "webm"}

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_pdf(file) -> bool:
    """Basic PDF validation - check magic bytes."""
    if not file or file.filename == '':
        return False
    file.seek(0)
    header = file.read(5)
    file.seek(0)
    return header == b'%PDF-'

def generate_storage_path(user_id: str, class_id: str, unit_id: str, filename: str) -> str:
    """
    Generate a structured path for Supabase Storage.
    Format: {class_id}/{unit_id}/{user_id}/{timestamp}_{uuid}_{secure_filename}
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    unique_id = str(uuid.uuid4())[:8]
    secure_name = secure_filename(filename)
    return f"{class_id}/{unit_id}/{user_id}/{timestamp}_{unique_id}_{secure_name}"

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


def _student_row():
    user = current_user()
    if not user:
        flash("Please log in.", "warning")
        return None

    db = get_service_client()
    rows = (db.table("students")
              .select("*")
              .eq("user_id", user["id"])
              .limit(1)
              .execute().data or [])
    return rows[0] if rows else None


@portfolio_trainee_bp.route("/portfolio/dashboard")
@login_required
@student_required
def portfolio_trainee_dashboard():
    """Show trainee submissions (assessments)."""
    db = get_service_client()
    student = _student_row()
    if not student:
        flash("Student profile missing.", "error")
        return redirect(url_for("student.dashboard"))

    trainee_id = student.get("user_id") or student.get("id")
    assessments = (db.table("assessments")
                     .select("*, units(name, code), classes(name)")
                     .eq("trainee_id", trainee_id)
                     .order("uploaded_at", desc=True)
                     .execute().data or [])

    return render_template("portfolio/trainee/dashboard.html", assessments=assessments)


@portfolio_trainee_bp.route("/portfolio/upload", methods=["GET", "POST"])
@login_required
@student_required
def portfolio_upload():
    """Upload script + evidence and create assessment record."""
    db = get_service_client()
    student = _student_row()
    if not student:
        flash("Student profile missing.", "error")
        return redirect(url_for("student.dashboard"))

    if request.method == "POST":
        unit_id = request.form.get("unit_id", type=int)
        class_id = request.form.get("class_id", type=int)
        assessment_type = request.form.get("assessment_type", "").strip()
        title = request.form.get("title", "").strip()
        cycle = request.form.get("cycle", "").strip()
        year = request.form.get("year", type=int)
        term = request.form.get("term", type=int)
        assessment_number = request.form.get("assessment_number", "").strip().upper()

        if not unit_id or not class_id or not assessment_type or not title or not assessment_number:
            flash("Missing required fields.", "error")
            return redirect(url_for("portfolio.portfolio_upload"))

        script = request.files.get("script")
        if not script or not script.filename or not allowed_file(script.filename) or not validate_pdf(script):
            flash("Please upload a valid PDF script file.", "error")
            return redirect(url_for("portfolio.portfolio_upload"))

        # Generate storage path & upload PDF to Supabase Storage
        trainee_id = student.get("user_id") or student.get("id")
        script_path = generate_storage_path(trainee_id, str(class_id), str(unit_id), script.filename)
        
        bucket_scripts = current_app.config.get("BUCKET_SCRIPTS", "assessment-scripts")
        bucket_evidence = current_app.config.get("BUCKET_EVIDENCE", "assessment-evidence")
        
        try:
            script_url = upload_to_supabase(db, bucket_scripts, script, script_path)
        except Exception as e:
            flash(f'Upload failed: {str(e)}', 'error')
            return redirect(url_for("portfolio.portfolio_upload"))

        # Handle optional evidence files
        evidence_paths = []
        evidence_files = request.files.getlist("evidence") if "evidence" in request.files else []
        for ev in evidence_files:
            if not ev or not ev.filename:
                continue
            if not allowed_file(ev.filename):
                flash(f"Unsupported evidence file type: {ev.filename}", "error")
                return redirect(url_for("portfolio.portfolio_upload"))
            
            evidence_path = generate_storage_path(trainee_id, str(class_id), str(unit_id), ev.filename)
            try:
                upload_to_supabase(db, bucket_evidence, ev, evidence_path)
                evidence_paths.append(evidence_path)
            except Exception as e:
                current_app.logger.warning(f"Evidence upload failed: {e}")
                flash(f"Warning: Evidence file '{ev.filename}' failed to upload.", 'warning')

        # Insert assessment record with storage paths
        ins = db.table("assessments").insert({
            "trainee_id": trainee_id,
            "unit_id": unit_id,
            "class_id": class_id,
            "assessment_type": assessment_type,
            "title": title,
            "assessment_number": assessment_number,
            "cycle": cycle or None,
            "year": year or now_eat_naive().year,
            "term": term or 1,
            "status": "submitted",
            "script_path": script_path,
            "script_file_name": secure_filename(script.filename),
            "evidence_paths": evidence_paths,
            "uploaded_at": now_eat_naive().isoformat(),
        }).execute()

        assessment_id = ins.data[0]["id"] if ins.data else None

        # Also insert evidence records for tracking
        for ev_path in evidence_paths:
            db.table("evidence").insert({
                "assessment_id": assessment_id,
                "file_path": ev_path,
                "file_name": ev_path.split('/')[-1],
                "uploaded_at": now_eat_naive().isoformat(),
            }).execute()

        write_audit_log("portfolio_upload", target=str(assessment_id), detail={
            "assessment_type": assessment_type,
            "unit_id": unit_id,
            "class_id": class_id,
            "assessment_number": assessment_number,
        })

        flash("Assessment submitted successfully! Awaiting review.", "success")
        return redirect(url_for("portfolio.portfolio_trainee_dashboard"))

    # GET: dropdowns
    units = db.table("units").select("id, code, name").execute().data or []
    classes = db.table("classes").select("id, name, year, term").execute().data or []

    return render_template(
        "portfolio/trainee/upload.html",
        units=units,
        classes=classes,
        current_year=datetime.now().year,
    )

