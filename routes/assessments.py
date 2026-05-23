"""
routes/assessments.py — Assessment and Evidence Management Module

This module handles:
- Trainee assessment submissions
- Evidence file uploads
- Trainer approval workflow
- Assessment viewing and management
"""

from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, abort
from auth_utils import login_required, current_user, write_audit_log
from db import get_service_client, get_anon_client
import uuid
from datetime import datetime

assessments_bp = Blueprint("assessments", __name__)


def _svc():
    return get_service_client()


@assessments_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload_assessment():
    """Trainee upload assessment and evidence files"""
    user = current_user()
    if user.get("role") != "student":
        abort(403)
    
    db = _svc()
    error = None
    success = None
    
    # Get student record
    student = db.table("students").select("*").eq("user_id", user["id"]).limit(1).execute().data
    if not student:
        error = "Student record not found."
    else:
        student = student[0]
        
        # Get available units for the student's class
        units = db.table("class_units") \
            .select("*, units(code, name, department_id)") \
            .eq("class_id", student["class_id"]) \
            .execute().data or []
    
    if request.method == "POST":
        unit_id = request.form.get("unit_id", type=int)
        assessment_type = request.form.get("assessment_type")
        year = request.form.get("year", type=int, default=datetime.now().year)
        term = request.form.get("term", type=int, default=1)
        cycle = request.form.get("cycle", type=int)
        
        if not unit_id or not assessment_type:
            error = "Unit and assessment type are required."
        else:
            try:
                # Get trainer assignment for this unit
                class_unit = db.table("class_units") \
                    .select("trainer_id") \
                    .eq("unit_id", unit_id) \
                    .eq("class_id", student["class_id"]) \
                    .limit(1) \
                    .execute().data
                
                if not class_unit:
                    error = "No trainer assigned to this unit for your class."
                else:
                    trainer_id = class_unit[0]["trainer_id"]
                    
                    # Create assessment record
                    assessment = db.table("assessments").insert({
                        "trainee_id": student["id"],
                        "unit_id": unit_id,
                        "trainer_id": trainer_id,
                        "class_id": student["class_id"],
                        "year": year,
                        "term": term,
                        "cycle": cycle,
                        "assessment_type": assessment_type,
                        "status": "pending",
                    }).execute()
                    
                    assessment_id = assessment.data[0]["id"]
                    
                    # Handle file uploads (evidence)
                    files = request.files.getlist("evidence_files")
                    for file in files:
                        if file and file.filename:
                            # TODO: Upload to Supabase Storage
                            # For now, just record the file metadata
                            file_url = f"/storage/evidence/{uuid.uuid4()}_{file.filename}"
                            db.table("evidence").insert({
                                "assessment_id": assessment_id,
                                "file_url": file_url,
                                "file_name": file.filename,
                                "file_type": _determine_file_type(file.filename),
                                "file_size": len(file.read()) if file else 0,
                                "uploaded_at": datetime.now().isoformat(),
                            }).execute()
                    
                    write_audit_log("upload_assessment", target=str(assessment_id))
                    success = "Assessment uploaded successfully. Waiting for trainer approval."
                    
            except Exception as exc:
                error = f"Error uploading assessment: {exc}"
    
    return render_template("assessments/upload.html",
                           error=error, success=success,
                           units=units, student=student)


def _determine_file_type(filename):
    """Determine file type based on extension"""
    ext = filename.lower().split('.')[-1] if '.' in filename else ''
    if ext in ['pdf']:
        return 'pdf'
    elif ext in ['jpg', 'jpeg', 'png', 'gif']:
        return 'image'
    elif ext in ['mp4', 'mov', 'avi']:
        return 'video'
    else:
        return 'document'


@assessments_bp.route("/my-assessments")
@login_required
def my_assessments():
    """Trainee view their own assessments"""
    user = current_user()
    if user.get("role") != "student":
        abort(403)
    
    db = _svc()
    
    # Get student record
    student = db.table("students").select("*").eq("user_id", user["id"]).limit(1).execute().data
    if not student:
        return render_template("assessments/my_assessments.html", assessments=[], error="Student record not found.")
    
    student = student[0]
    
    # Get student's assessments
    assessments = db.table("assessments") \
        .select("*, units(code, name), trainers(name)") \
        .eq("trainee_id", student["id"]) \
        .order("submitted_at", desc=True) \
        .execute().data or []
    
    return render_template("assessments/my_assessments.html", assessments=assessments)


@assessments_bp.route("/pending-approvals")
@login_required
def pending_approvals():
    """Trainer view pending assessments for approval"""
    user = current_user()
    if user.get("role") != "trainer":
        abort(403)
    
    db = _svc()
    
    # Get trainer record
    trainer = db.table("trainers").select("*").eq("user_id", user["id"]).limit(1).execute().data
    if not trainer:
        return render_template("assessments/pending_approvals.html", assessments=[], error="Trainer record not found.")
    
    trainer = trainer[0]
    
    # Get pending assessments for this trainer
    assessments = db.table("assessments") \
        .select("*, students(full_name, admission_number), units(code, name), classes(name)") \
        .eq("trainer_id", trainer["id"]) \
        .eq("status", "pending") \
        .order("submitted_at", desc=True) \
        .execute().data or []
    
    return render_template("assessments/pending_approvals.html", assessments=assessments)


@assessments_bp.route("/approve/<int:assessment_id>", methods=["POST"])
@login_required
def approve_assessment(assessment_id):
    """Trainer approve or reject assessment"""
    user = current_user()
    if user.get("role") != "trainer":
        abort(403)
    
    db = _svc()
    
    action = request.form.get("action")  # approve or reject
    feedback = request.form.get("feedback", "")
    
    if action not in ["approve", "reject"]:
        return jsonify({"error": "Invalid action"}), 400
    
    try:
        # Get trainer record
        trainer = db.table("trainers").select("*").eq("user_id", user["id"]).limit(1).execute().data
        if not trainer:
            return jsonify({"error": "Trainer record not found"}), 400
        
        trainer = trainer[0]
        trainer_name = trainer["name"]
        
        # Verify this assessment belongs to this trainer
        assessment = db.table("assessments").select("*").eq("id", assessment_id).limit(1).execute().data
        if not assessment or assessment[0]["trainer_id"] != trainer["id"]:
            return jsonify({"error": "Assessment not found or not assigned to you"}), 403
        
        # Update assessment status
        status = "approved" if action == "approve" else "rejected"
        reviewed_at = datetime.now().isoformat()
        
        db.table("assessments").update({
            "status": status,
            "feedback": feedback,
            "reviewed_at": reviewed_at,
        }).eq("id", assessment_id).execute()
        
        # If approved, rename evidence files with trainer name and date
        if action == "approve":
            evidence = db.table("evidence").select("*").eq("assessment_id", assessment_id).execute().data or []
            approval_date = datetime.now().strftime("%Y%m%d")
            
            for e in evidence:
                # Extract original filename and extension
                original_name = e["file_name"]
                name_parts = original_name.rsplit('.', 1)
                base_name = name_parts[0] if len(name_parts) > 1 else original_name
                extension = f".{name_parts[1]}" if len(name_parts) > 1 else ""
                
                # Create new filename with trainer name and approval date
                # Format: original_filename_trainername_YYYYMMDD.ext
                trainer_name_clean = trainer_name.replace(" ", "_").lower()
                new_filename = f"{base_name}_{trainer_name_clean}_{approval_date}{extension}"
                
                # Update the file_name in the database
                # Note: In production, you would also rename the actual file in Supabase Storage
                db.table("evidence").update({
                    "file_name": new_filename
                }).eq("id", e["id"]).execute()
        
        write_audit_log(f"assessment_{action}", target=str(assessment_id))
        
        return jsonify({"success": True, "status": status})
    
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@assessments_bp.route("/view/<int:assessment_id>")
@login_required
def view_assessment(assessment_id):
    """View assessment details and evidence"""
    db = _svc()
    user = current_user()
    
    # Get assessment
    assessment = db.table("assessments") \
        .select("*, students(full_name, admission_number), units(code, name), trainers(name), classes(name)") \
        .eq("id", assessment_id) \
        .limit(1) \
        .execute().data
    
    if not assessment:
        abort(404)
    
    assessment = assessment[0]
    
    # Check access permissions
    if user.get("role") == "student":
        # Students can only view their own assessments
        student = db.table("students").select("id").eq("user_id", user["id"]).limit(1).execute().data
        if not student or student[0]["id"] != assessment["trainee_id"]:
            abort(403)
    elif user.get("role") == "trainer":
        # Trainers can only view assessments assigned to them
        trainer = db.table("trainers").select("id").eq("user_id", user["id"]).limit(1).execute().data
        if not trainer or trainer[0]["id"] != assessment["trainer_id"]:
            abort(403)
    
    # Get evidence files
    evidence = db.table("evidence").select("*").eq("assessment_id", assessment_id).execute().data or []
    
    # Log file view
    write_audit_log("view_assessment", target=str(assessment_id))
    
    return render_template("assessments/view.html", assessment=assessment, evidence=evidence)
