"""
routes/results.py — Results/Marksheet Upload Module
Supports Excel bulk upload and manual entry. Trainer/HOD/Admin access.
"""

from flask import (Blueprint, render_template, request,
                   redirect, url_for, flash, abort, jsonify)
from auth_utils import login_required, current_user, write_audit_log
from db import get_service_client
from notify import send_notification, send_to_role

results_bp = Blueprint("results", __name__)


def _db():
    return get_service_client()


# ── View Results (Student) ────────────────────────────────────────────────────

@results_bp.route("/my-results")
@login_required
def my_results():
    user = current_user()
    if user.get("role") != "student":
        abort(403)
    db = _db()

    student_rows = db.table("students").select("id,full_name,admission_number").eq("user_id", user["id"]).limit(1).execute().data or []
    if not student_rows:
        abort(403)
    student = student_rows[0]

    results = (db.table("result_sheets")
                 .select("*, units(code,name), exam_series(name)")
                 .eq("student_id", student["id"])
                 .order("year", desc=True).order("term")
                 .execute().data or [])

    # Group by year/term
    from collections import defaultdict
    grouped = defaultdict(list)
    for r in results:
        key = f"{r['year']} Term {r['term']}"
        grouped[key].append(r)

    return render_template("results/my_results.html",
                           student=student, grouped=dict(grouped), user=user)


# ── Trainer/Admin: Enter Results Manually ────────────────────────────────────

@results_bp.route("/enter", methods=["GET", "POST"])
@login_required
def enter_results():
    user = current_user()
    if user.get("role") not in ("trainer", "dept_admin", "hod", "super_admin", "deputy_principal"):
        abort(403)
    db = _db()
    error = None
    dept_id = user.get("dept_id")

    classes = db.table("classes").select("*").eq("department_id", dept_id).order("name").execute().data or [] if dept_id else \
              db.table("classes").select("*").order("name").execute().data or []
    units   = db.table("units").select("*").eq("department_id", dept_id).order("code").execute().data or [] if dept_id else \
              db.table("units").select("*").order("code").execute().data or []
    series  = db.table("exam_series").select("*").order("year", desc=True).execute().data or []

    class_id = request.args.get("class_id", type=int)
    unit_id  = request.args.get("unit_id", type=int)
    year     = request.args.get("year", 2026, type=int)
    term     = request.args.get("term", 1, type=int)

    students = []
    existing_map = {}
    if class_id and unit_id:
        students = (db.table("students")
                      .select("id,full_name,admission_number")
                      .eq("class_id", class_id)
                      .order("admission_number")
                      .execute().data or [])
        existing = (db.table("result_sheets")
                      .select("*")
                      .eq("unit_id", unit_id)
                      .eq("year", year).eq("term", term)
                      .in_("student_id", [s["id"] for s in students] or [-1])
                      .execute().data or [])
        existing_map = {r["student_id"]: r for r in existing}

    if request.method == "POST":
        class_id  = request.form.get("class_id", type=int)
        unit_id   = request.form.get("unit_id", type=int)
        year      = request.form.get("year", type=int)
        term      = request.form.get("term", type=int)
        series_id = request.form.get("exam_series_id", type=int) or None
        student_ids = request.form.getlist("student_ids")

        saved = 0
        for sid_str in student_ids:
            sid = int(sid_str)
            oral    = request.form.get(f"oral_{sid}", type=float)
            theory  = request.form.get(f"theory_{sid}", type=float)
            practical = request.form.get(f"practical_{sid}", type=float)
            
            # Validate scores are within valid range (0-100)
            for score_name, score_val in [("Formative Oral", oral), ("Formative Theory", theory), ("Formative Practical", practical)]:
                if score_val is not None and (score_val < 0 or score_val > 100):
                    error = f"Invalid {score_name} score for student {sid}: must be between 0 and 100"
                    break
            
            if error:
                break
            
            total  = round(sum(filter(None, [oral, theory, practical])), 2)
            grade  = _compute_grade(total)
            remark = _compute_remark(grade)

            try:
                db.table("result_sheets").upsert({
                    "student_id":     sid,
                    "unit_id":        unit_id,
                    "class_id":       class_id,
                    "department_id":  dept_id,
                    "exam_series_id": series_id,
                    "year":           year,
                    "term":           term,
                    "formative_oral_score": oral,
                    "formative_theory_score": theory,
                    "formative_practical_score": practical,
                    "total_score":    total,
                    "grade":          grade,
                    "remarks":        remark,
                    "uploaded_by":    user["id"],
                    "upload_method":  "manual",
                }, on_conflict="student_id,unit_id,year,term").execute()
                saved += 1
            except Exception as exc:
                error = f"Error saving results: {exc}"
                break

        if not error:
            write_audit_log("enter_results", detail={"class_id": class_id, "unit_id": unit_id, "count": saved})
            flash(f"{saved} result(s) saved.", "success")
            return redirect(url_for("results.enter_results",
                                    class_id=class_id, unit_id=unit_id, year=year, term=term))

    return render_template("results/enter_results.html",
                           classes=classes, units=units, series=series,
                           class_id=class_id, unit_id=unit_id,
                           year=year, term=term,
                           students=students, existing_map=existing_map,
                           error=error, user=user)


# ── Excel Upload ──────────────────────────────────────────────────────────────

@results_bp.route("/upload-excel", methods=["GET", "POST"])
@login_required
def upload_excel():
    user = current_user()
    if user.get("role") not in ("trainer", "dept_admin", "hod", "super_admin", "deputy_principal"):
        abort(403)
    db = _db()
    error = None
    result = None
    dept_id = user.get("dept_id")

    units  = db.table("units").select("*").eq("department_id", dept_id).order("code").execute().data or [] if dept_id else \
             db.table("units").select("*").order("code").execute().data or []
    series = db.table("exam_series").select("*").order("year", desc=True).execute().data or []

    if request.method == "POST":
        file      = request.files.get("file")
        unit_id   = request.form.get("unit_id", type=int)
        year      = request.form.get("year", type=int)
        term      = request.form.get("term", type=int)
        series_id = request.form.get("exam_series_id", type=int) or None

        if not file or not file.filename.endswith((".xlsx", ".xls")):
            error = "Please upload a valid Excel file."
        elif not unit_id or not year or not term:
            error = "Unit, year and term are required."
        else:
            try:
                import openpyxl
                wb = openpyxl.load_workbook(file, data_only=True)
                ws = wb.active
                rows = list(ws.iter_rows(min_row=2, values_only=True))

                success = 0
                errors  = []
                for r in rows:
                    if not r or not r[0]:
                        continue
                    try:
                        adm_no = str(r[0]).strip()
                        oral    = float(r[1]) if r[1] is not None else None
                        theory   = float(r[2]) if r[2] is not None else None
                        practical = float(r[3]) if r[3] is not None else None
                        
                        # Validate scores are within valid range (0-100)
                        for score_name, score_val in [("Formative Oral", oral), ("Formative Theory", theory), ("Formative Practical", practical)]:
                            if score_val is not None and (score_val < 0 or score_val > 100):
                                errors.append(f"{adm_no}: Invalid {score_name} score - must be between 0 and 100")
                                break
                        
                        total  = round(sum(filter(None, [oral, theory, practical])), 2)
                        grade  = _compute_grade(total)
                        remark = _compute_remark(grade)

                        # Find student
                        s_rows = db.table("students").select("id,class_id").eq("admission_number", adm_no).limit(1).execute().data or []
                        if not s_rows:
                            errors.append(f"{adm_no}: student not found")
                            continue
                        sid = s_rows[0]["id"]
                        cid = s_rows[0]["class_id"]

                        db.table("result_sheets").upsert({
                            "student_id":     sid,
                            "unit_id":        unit_id,
                            "class_id":       cid,
                            "department_id":  dept_id,
                            "exam_series_id": series_id,
                            "year":           year,
                            "term":           term,
                            "formative_oral_score": oral,
                            "formative_theory_score": theory,
                            "formative_practical_score": practical,
                            "total_score":    total,
                            "grade":          grade,
                            "remarks":        remark,
                            "uploaded_by":    user["id"],
                            "upload_method":  "excel",
                        }, on_conflict="student_id,unit_id,year,term").execute()
                        success += 1
                    except Exception as exc:
                        errors.append(f"Row {r[0]}: {exc}")

                result = {"success": success, "errors": errors[:10]}
                write_audit_log("upload_results_excel", detail={"unit_id": unit_id, "count": success})
                flash(f"{success} result(s) uploaded from Excel.", "success")
            except Exception as exc:
                error = f"Upload failed: {exc}"

    return render_template("results/upload_excel.html",
                           units=units, series=series,
                           result=result, error=error, user=user)


# ── View Results (Admin/Trainer) ──────────────────────────────────────────────

@results_bp.route("/view")
@login_required
def view_results():
    user = current_user()
    if user.get("role") not in ("trainer", "dept_admin", "hod", "super_admin",
                                 "deputy_principal", "monitoring_evaluation"):
        abort(403)
    db = _db()
    dept_id = user.get("dept_id")

    class_id  = request.args.get("class_id", type=int)
    unit_id   = request.args.get("unit_id", type=int)
    year      = request.args.get("year", 2026, type=int)
    term      = request.args.get("term", 1, type=int)

    classes = db.table("classes").select("*").eq("department_id", dept_id).order("name").execute().data or [] if dept_id else \
              db.table("classes").select("*").order("name").execute().data or []
    units   = db.table("units").select("*").eq("department_id", dept_id).order("code").execute().data or [] if dept_id else \
              db.table("units").select("*").order("code").execute().data or []

    results = []
    if class_id and unit_id:
        students = db.table("students").select("id").eq("class_id", class_id).execute().data or []
        sids = [s["id"] for s in students]
        if sids:
            results = (db.table("result_sheets")
                         .select("*, students(full_name,admission_number), units(code,name)")
                         .in_("student_id", sids)
                         .eq("unit_id", unit_id)
                         .eq("year", year).eq("term", term)
                         .order("students(admission_number)")
                         .execute().data or [])

    return render_template("results/view_results.html",
                           classes=classes, units=units,
                           class_id=class_id, unit_id=unit_id,
                           year=year, term=term,
                           results=results, user=user)


# ── Grade helpers ─────────────────────────────────────────────────────────────

def _compute_grade(total: float) -> str:
    if total is None:
        return "—"
    if total >= 70:
        return "A"
    elif total >= 60:
        return "B"
    elif total >= 50:
        return "C"
    elif total >= 40:
        return "D"
    else:
        return "E"


def _compute_remark(grade: str) -> str:
    return {
        "A": "Distinction",
        "B": "Credit",
        "C": "Pass",
        "D": "Supplementary",
        "E": "Fail",
    }.get(grade, "—")
