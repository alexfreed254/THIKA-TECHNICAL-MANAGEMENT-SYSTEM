"""E-Portfolio - Trainer routes.

Provides review workflow endpoints under /portfolio/*.
Integrated with existing auth/session model.
Includes file renaming on review and CSV export functionality.
"""

from datetime import datetime
import os
import csv
import io
from flask import render_template, request, redirect, url_for, flash, current_app, send_file

from auth_utils import login_required, trainer_required, current_user, write_audit_log
from db import get_service_client
from werkzeug.utils import secure_filename

from routes.portfolio import portfolio_bp
from utils import now_eat


def _trainer_row():
    user = current_user()
    db = get_service_client()
    rows = (db.table("trainers").select("*").eq("user_id", user["id"]).limit(1).execute().data or [])
    return rows[0] if rows else None


def rename_assessment_file(supabase, bucket: str, old_path: str, trainee_name: str, status: str) -> str:
    """
    Rename file on review: {original}_{trainee_name}_{status}
    Returns new path.
    """
    try:
        # Parse original filename
        original_name = old_path.split('/')[-1]
        name_parts = os.path.splitext(original_name)
        new_filename = f"{name_parts[0]}_{secure_filename(trainee_name)}_{status}{name_parts[1]}"
        new_path = '/'.join(old_path.split('/')[:-1] + [new_filename])
        
        # Supabase Storage doesn't have direct rename, so copy + delete
        supabase.storage.from_(bucket).copy(old_path, new_path)
        supabase.storage.from_(bucket).remove([old_path])
        return new_path
    except Exception as e:
        current_app.logger.error(f"Rename failed: {str(e)}")
        return old_path  # Return original on failure


def export_assessments_to_csv(supabase, unit_id: str, class_id: str = None, year: int = None):
    """
    Export assessments for a unit to CSV format.
    Returns (filename, csv_content) for download.
    """
    query = supabase.table('assessments').select('''
        id,
        uploaded_at,
        status,
        assessment_number,
        term,
        cycle,
        year,
        reviewer_comments,
        reviewed_at,
        students!assessments_trainee_id_fkey(full_name, admission_number),
        classes!assessments_class_id_fkey(name as class_name),
        units!assessments_unit_id_fkey(name as unit_name, code as unit_code)
    ''').eq('unit_id', unit_id)
    
    if class_id:
        query = query.eq('class_id', class_id)
    if year:
        query = query.eq('year', year)
    
    response = query.order('uploaded_at', desc=True).execute()
    assessments = response.data
    
    # Build CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Admission No', 'Trainee Name', 'Class', 'Unit Code', 'Unit Name',
        'Assessment #', 'Type', 'Term', 'Cycle', 'Year', 'Submitted',
        'Status', 'Reviewed At', 'Notes', 'Script URL'
    ])
    
    for a in assessments:
        trainee = a.get('students', {})
        unit = a.get('units', {})
        class_obj = a.get('classes', {})
        
        writer.writerow([
            trainee.get('admission_number', 'N/A'),
            trainee.get('full_name', 'N/A'),
            class_obj.get('class_name', 'N/A'),
            unit.get('unit_code', 'N/A'),
            unit.get('unit_name', 'N/A'),
            a.get('assessment_number'),
            a.get('assessment_type'),
            a.get('term'),
            a.get('cycle'),
            a.get('year'),
            a.get('uploaded_at', '')[:19].replace('T', ' ') if a.get('uploaded_at') else '',
            a.get('status', 'pending'),
            a.get('reviewed_at', '')[:19].replace('T', ' ') if a.get('reviewed_at') else '',
            a.get('reviewer_comments', ''),
            a.get('script_path', '')
        ])
    
    filename = f"assessments_{unit_id}_{datetime.now().strftime('%Y%m%d')}.csv"
    return filename, output.getvalue()


@portfolio_bp.route("/portfolio/trainer/dashboard")
@login_required
@trainer_required
def portfolio_trainer_dashboard():
    """Trainer dashboard: show assessments relevant to assigned units."""
    db = get_service_client()
    trainer = _trainer_row()
    if not trainer:
        flash("Trainer profile missing.", "error")
        return redirect(url_for("lecturer.dashboard"))

    trainer_id = trainer.get("user_id") or trainer.get("id")
    assignments = (db.table("trainer_assignments")
                    .select("unit_id, class_id")
                    .eq("trainer_id", trainer_id) 
                    .execute().data or [])

    unit_ids = list({a["unit_id"] for a in assignments if a.get("unit_id")})
    class_ids = list({a["class_id"] for a in assignments if a.get("class_id")})

    assessments = []
    if unit_ids and class_ids:
        assessments = (db.table("assessments")
                        .select("*, units(name, code), classes(name)")
                        .in_("unit_id", unit_ids)
                        .in_("class_id", class_ids)
                        .order("uploaded_at", desc=True)
                        .execute().data or [])

    return render_template("portfolio/trainer/dashboard.html", assessments=assessments)


@portfolio_bp.route("/portfolio/review/<int:assessment_id>", methods=["GET", "POST"])
@login_required
@trainer_required
def portfolio_review(assessment_id: int):
    db = get_service_client()
    trainer = _trainer_row()
    if not trainer:
        flash("Trainer profile missing.", "error")
        return redirect(url_for("lecturer.dashboard"))

    assessment = (db.table("assessments")
                     .select("*, units(name, code), classes(name)")
                     .eq("id", assessment_id)
                     .limit(1)
                     .execute().data or [])
    if not assessment:
        flash("Assessment not found.", "error")
        return redirect(url_for("portfolio.portfolio_trainer_dashboard"))

    a = assessment[0]

    # Enforce that this trainer is assigned to the assessment's unit.
    # (Dept Admin/HOD assign the unit in class_units; prevents trainers reviewing others.)
    trainer_id = trainer.get("user_id") or trainer.get("id")
    assignments_check = (db.table("class_units")
                             .select("id")
                             .eq("trainer_id", trainer_id)
                             .eq("unit_id", a.get("unit_id"))
                             .limit(1)
                             .execute().data or [])
    if not assignments_check:
        flash("Access denied: this unit is not assigned to your trainer profile.", "error")
        return redirect(url_for("portfolio.portfolio_trainer_dashboard"))

    if request.method == "POST":
        action = request.form.get("action")
        comments = request.form.get("comments", "").strip()

        if action not in ("approve", "reject", "revision"):
            flash("Invalid action.", "error")
            return redirect(url_for("portfolio.portfolio_review", assessment_id=assessment_id))

        status_map = {
            "approve": "approved",
            "reject": "rejected",
            "revision": "revision_required",
        }
        new_status = status_map[action]

        # Get trainee name for file renaming
        trainee_data = (db.table("students")
                       .select("full_name")
                       .eq("user_id", a.get("trainee_id"))
                       .limit(1)
                       .execute().data or [])
        trainee_name = trainee_data[0].get("full_name", "unknown") if trainee_data else "unknown"

        # Rename file in Supabase Storage if script_path exists
        if a.get("script_path"):
            bucket_scripts = current_app.config.get("BUCKET_SCRIPTS", "assessment-scripts")
            new_path = rename_assessment_file(db, bucket_scripts, a["script_path"], trainee_name, new_status)
            
            # Update assessment with new path and reviewed filename
            db.table("assessments").update({
                "status": new_status,
                "reviewed_at": now_eat().isoformat(),
                "reviewer_comments": comments or None,
                "script_path": new_path,
                "reviewed_filename": new_path.split('/')[-1]
            }).eq("id", assessment_id).execute()
        else:
            # No file to rename, just update status
            db.table("assessments").update({
                "status": new_status,
                "reviewed_at": now_eat().isoformat(),
                "reviewer_comments": comments or None,
            }).eq("id", assessment_id).execute()

        write_audit_log("portfolio_review", target=str(assessment_id), detail={
            "action": action,
            "status": new_status,
            "trainee_name": trainee_name,
        })

        flash(f"Assessment {action}d successfully.", "success")
        return redirect(url_for("portfolio.portfolio_trainer_dashboard"))

    evidence = (db.table("evidence")
                   .select("*")
                   .eq("assessment_id", assessment_id)
                   .execute().data or [])

    return render_template("portfolio/trainer/review.html", assessment=a, evidence=evidence)


@portfolio_bp.route("/portfolio/export/<int:unit_id>")
@login_required
@trainer_required
def portfolio_export(unit_id: int):
    """Export assessments for a unit to CSV."""
    db = get_service_client()
    trainer = _trainer_row()
    if not trainer:
        flash("Trainer profile missing.", "error")
        return redirect(url_for("lecturer.dashboard"))

    # Verify trainer is assigned to this unit
    trainer_id = trainer.get("user_id") or trainer.get("id")
    assignments_check = (db.table("class_units")
                         .select("id")
                         .eq("trainer_id", trainer_id)
                         .eq("unit_id", unit_id)
                         .limit(1)
                         .execute().data or [])
    if not assignments_check:
        flash("Access denied: this unit is not assigned to your trainer profile.", "error")
        return redirect(url_for("portfolio.portfolio_trainer_dashboard"))

    # Get optional filters
    class_id = request.args.get("class_id", type=int)
    year = request.args.get("year", type=int)

    try:
        filename, csv_content = export_assessments_to_csv(db, str(unit_id), class_id, year)
        
        # Create a file-like object from the string
        output = io.BytesIO(csv_content.encode('utf-8'))
        output.seek(0)
        
        return send_file(
            output,
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        current_app.logger.error(f"CSV export failed: {str(e)}")
        flash(f"Export failed: {str(e)}", "error")
        return redirect(url_for("portfolio.portfolio_trainer_dashboard"))

