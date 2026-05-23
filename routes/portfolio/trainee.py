"""E-Portfolio - Trainee routes.

Integrated into the existing Attendance system auth/session model:
- Uses session-based RBAC from auth_utils.py
- Uses Supabase via db.get_service_client() (server-side admin)

This file adds functionality under /portfolio/* without changing
existing Attendance routes.
"""

from datetime import datetime
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

        if not unit_id or not class_id or not assessment_type or not title:
            flash("Missing required fields.", "error")
            return redirect(url_for("portfolio.portfolio_upload"))

        script = request.files.get("script")
        if not script or not script.filename or not allowed_file(script.filename):
            flash("Please upload a valid script file.", "error")
            return redirect(url_for("portfolio.portfolio_upload"))

        # For MVP integration with your existing schema, we store only file names.
        # Your current attendance system already supports evidence via other modules.
        # Here we keep it minimal and non-destructive.
        script_filename = secure_filename(script.filename)

        # Insert assessment record
        trainee_id = student.get("user_id") or student.get("id")
        ins = db.table("assessments").insert({
            "trainee_id": trainee_id,
            "unit_id": unit_id,
            "class_id": class_id,
            "assessment_type": assessment_type,
            "title": title,
            "cycle": cycle or None,
            "year": year or now_eat_naive().year,
            "term": term or 1,
            "status": "submitted",
            "script_file_name": script_filename,
            "uploaded_at": now_eat_naive().isoformat(),
        }).execute()

        assessment_id = ins.data[0]["id"] if ins.data else None

        # Evidence files (optional) — supports multi-select for images/videos/files
        evidence_files = request.files.getlist("evidence") if "evidence" in request.files else []
        for ev in evidence_files:
            if not ev or not ev.filename:
                continue
            # Enforce allowed extensions for safety
            if not allowed_file(ev.filename):
                flash(f"Unsupported evidence file type: {ev.filename}", "error")
                return redirect(url_for("portfolio.portfolio_upload"))

            # MVP integration with your existing DB schema:
            # store evidence file name only (uploading to Supabase Storage is handled by other modules in your system).
            ev_name = secure_filename(ev.filename)
            db.table("evidence").insert({
                "assessment_id": assessment_id,
                "file_name": ev_name,
                "uploaded_at": now_eat_naive().isoformat(),
            }).execute()


        write_audit_log("portfolio_upload", target=str(assessment_id), detail={
            "assessment_type": assessment_type,
            "unit_id": unit_id,
            "class_id": class_id,
        })

        flash("Assessment submitted successfully!", "success")
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

