"""
routes/dual_training.py — Dual Training Management (Module 10)
Industry allocation, employer assignment, competency tracking, workplace attendance.
"""

from flask import (Blueprint, render_template, request,
                   redirect, url_for, flash, abort, jsonify)
from auth_utils import login_required, current_user, write_audit_log
from db import get_service_client
from notify import send_notification, send_to_role

dual_bp = Blueprint("dual", __name__)


def _db():
    return get_service_client()


# ── Admin: Manage Employers ───────────────────────────────────────────────────

@dual_bp.route("/employers", methods=["GET", "POST"])
@login_required
def employers():
    user = current_user()
    if user.get("role") not in ("super_admin", "dept_admin", "hod", "deputy_principal"):
        abort(403)
    db = _db()
    error = None

    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            company  = request.form.get("company_name", "").strip()
            contact  = request.form.get("contact_person", "").strip()
            email    = request.form.get("email", "").strip().lower()
            phone    = request.form.get("phone", "").strip()
            address  = request.form.get("address", "").strip()
            sector   = request.form.get("industry_sector", "").strip()
            if not company:
                error = "Company name is required."
            else:
                db.table("employers").insert({
                    "company_name": company, "contact_person": contact,
                    "email": email, "phone": phone,
                    "address": address, "industry_sector": sector,
                }).execute()
                write_audit_log("create_employer", target=company)
                flash("Employer added.", "success")
                return redirect(url_for("dual.employers"))
        elif action == "delete":
            eid = request.form.get("employer_id", type=int)
            db.table("employers").delete().eq("id", eid).execute()
            flash("Employer deleted.", "success")
            return redirect(url_for("dual.employers"))

    employers_list = db.table("employers").select("*").order("company_name").execute().data or []
    return render_template("dual/employers.html",
                           employers=employers_list, error=error, user=user)


# ── Admin: Allocate Student to Industry ──────────────────────────────────────

@dual_bp.route("/allocations", methods=["GET", "POST"])
@login_required
def allocations():
    user = current_user()
    if user.get("role") not in ("super_admin", "dept_admin", "hod", "deputy_principal"):
        abort(403)
    db = _db()
    error = None
    dept_id = user.get("dept_id")

    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            student_id   = request.form.get("student_id", type=int)
            employer_id  = request.form.get("employer_id", type=int)
            supervisor_id = request.form.get("supervisor_id") or None
            start_date   = request.form.get("start_date") or None
            end_date     = request.form.get("end_date") or None

            if not student_id or not employer_id:
                error = "Student and employer are required."
            else:
                alloc = db.table("dual_training_allocations").insert({
                    "student_id":    student_id,
                    "employer_id":   employer_id,
                    "supervisor_id": supervisor_id,
                    "start_date":    start_date,
                    "end_date":      end_date,
                    "department_id": dept_id,
                    "status":        "active",
                }).execute().data[0]

                # Notify student
                student_row = (db.table("students").select("user_id,full_name").eq("id", student_id).limit(1).execute().data or [{}])[0]
                if student_row.get("user_id"):
                    employer_row = (db.table("employers").select("company_name").eq("id", employer_id).limit(1).execute().data or [{}])[0]
                    send_notification(student_row["user_id"],
                                      "Dual Training Allocation",
                                      f"You have been allocated to {employer_row.get('company_name', 'an employer')} for dual training.",
                                      notif_type="info", module="dual_training", reference_id=alloc["id"])

                write_audit_log("create_dual_allocation", target=str(student_id))
                flash("Student allocated to industry.", "success")
                return redirect(url_for("dual.allocations"))

    # Get students in dept
    dept_class_ids = []
    if dept_id:
        dept_class_ids = [c["id"] for c in db.table("classes").select("id").eq("department_id", dept_id).execute().data or []]

    students = []
    if dept_class_ids:
        students = db.table("students").select("id,full_name,admission_number").in_("class_id", dept_class_ids).order("full_name").execute().data or []
    elif user.get("role") in ("super_admin", "deputy_principal"):
        students = db.table("students").select("id,full_name,admission_number").order("full_name").limit(500).execute().data or []

    employers_list = db.table("employers").select("*").eq("is_active", True).order("company_name").execute().data or []

    # Existing allocations
    query = db.table("dual_training_allocations").select("*, students(full_name,admission_number), employers(company_name)").order("created_at", desc=True)
    if dept_id and user.get("role") not in ("super_admin", "deputy_principal"):
        query = query.eq("department_id", dept_id)
    allocs = query.execute().data or []

    return render_template("dual/allocations.html",
                           students=students, employers=employers_list,
                           allocs=allocs, error=error, user=user)


# ── Employer: Dashboard ───────────────────────────────────────────────────────

@dual_bp.route("/employer-dashboard")
@login_required
def employer_dashboard():
    user = current_user()
    if user.get("role") not in ("employer", "super_admin"):
        abort(403)
    db = _db()

    employer_row = (db.table("employers").select("*").eq("user_id", user["id"]).limit(1).execute().data or [None])[0]
    if not employer_row and user.get("role") != "super_admin":
        abort(403)

    allocs = []
    if employer_row:
        allocs = (db.table("dual_training_allocations")
                    .select("*, students(full_name,admission_number,classes(name))")
                    .eq("employer_id", employer_row["id"])
                    .eq("status", "active")
                    .execute().data or [])

    return render_template("dual/employer_dashboard.html",
                           employer=employer_row, allocs=allocs, user=user)


# ── Employer: Submit Weekly Feedback ─────────────────────────────────────────

@dual_bp.route("/feedback/<int:allocation_id>", methods=["GET", "POST"])
@login_required
def submit_feedback(allocation_id):
    user = current_user()
    if user.get("role") not in ("employer", "industry_supervisor", "super_admin"):
        abort(403)
    db = _db()

    alloc = (db.table("dual_training_allocations")
               .select("*, students(full_name,admission_number), employers(company_name)")
               .eq("id", allocation_id).limit(1).execute().data or [None])[0]
    if not alloc:
        abort(404)

    error = None
    if request.method == "POST":
        week      = request.form.get("week_number", type=int)
        punct     = request.form.get("punctuality", type=int)
        tech      = request.form.get("technical_skills", type=int)
        disc      = request.form.get("discipline", type=int)
        comm      = request.form.get("communication", type=int)
        safety    = request.form.get("safety_awareness", type=int)
        team      = request.form.get("teamwork", type=int)
        init      = request.form.get("initiative", type=int)
        comment   = request.form.get("overall_comment", "").strip()
        signature = request.form.get("digital_signature", "").strip()

        if not week:
            error = "Week number is required."
        else:
            from utils import now_eat
            employer_row = (db.table("employers").select("id").eq("user_id", user["id"]).limit(1).execute().data or [{}])[0]
            db.table("employer_feedback").insert({
                "allocation_id":   allocation_id,
                "employer_id":     employer_row.get("id"),
                "week_number":     week,
                "punctuality":     punct,
                "technical_skills": tech,
                "discipline":      disc,
                "communication":   comm,
                "safety_awareness": safety,
                "teamwork":        team,
                "initiative":      init,
                "overall_comment": comment,
                "digital_signature": signature,
                "signed_at":       now_eat().isoformat() if signature else None,
            }).execute()

            # Notify trainer/dept admin
            send_to_role("dept_admin", "Employer Feedback Submitted",
                         f"Employer submitted weekly feedback for {(alloc.get('students') or {}).get('full_name', 'a student')}.",
                         notif_type="info", module="dual_training", reference_id=allocation_id)

            write_audit_log("employer_feedback_submit", target=str(allocation_id))
            flash("Feedback submitted.", "success")
            return redirect(url_for("dual.employer_dashboard"))

    # Previous feedback
    feedbacks = (db.table("employer_feedback")
                   .select("*").eq("allocation_id", allocation_id)
                   .order("week_number").execute().data or [])

    return render_template("dual/submit_feedback.html",
                           alloc=alloc, feedbacks=feedbacks, error=error, user=user)


# ── Workplace Attendance ──────────────────────────────────────────────────────

@dual_bp.route("/workplace-attendance/<int:allocation_id>", methods=["GET", "POST"])
@login_required
def workplace_attendance(allocation_id):
    user = current_user()
    if user.get("role") not in ("employer", "industry_supervisor", "dept_admin", "super_admin", "hod"):
        abort(403)
    db = _db()

    alloc = (db.table("dual_training_allocations")
               .select("*, students(full_name,admission_number)")
               .eq("id", allocation_id).limit(1).execute().data or [None])[0]
    if not alloc:
        abort(404)

    error = None
    if request.method == "POST":
        date       = request.form.get("date")
        check_in   = request.form.get("check_in") or None
        check_out  = request.form.get("check_out") or None
        hours      = request.form.get("hours_worked", type=float)
        status     = request.form.get("status", "present")
        note       = request.form.get("supervisor_note", "").strip()

        if not date:
            error = "Date is required."
        else:
            db.table("dual_training_attendance").insert({
                "allocation_id": allocation_id,
                "date":          date,
                "check_in":      check_in,
                "check_out":     check_out,
                "hours_worked":  hours,
                "status":        status,
                "supervisor_note": note,
            }).execute()
            flash("Attendance recorded.", "success")
            return redirect(url_for("dual.workplace_attendance", allocation_id=allocation_id))

    records = (db.table("dual_training_attendance")
                 .select("*").eq("allocation_id", allocation_id)
                 .order("date", desc=True).execute().data or [])

    total_hours = sum(r.get("hours_worked") or 0 for r in records)
    return render_template("dual/workplace_attendance.html",
                           alloc=alloc, records=records,
                           total_hours=total_hours, error=error, user=user)


# ── Competency Tracking ───────────────────────────────────────────────────────

@dual_bp.route("/competencies/<int:allocation_id>", methods=["GET", "POST"])
@login_required
def competencies(allocation_id):
    user = current_user()
    if user.get("role") not in ("employer", "industry_supervisor", "dept_admin", "super_admin", "hod", "trainer"):
        abort(403)
    db = _db()

    alloc = (db.table("dual_training_allocations")
               .select("*, students(full_name,admission_number), employers(company_name)")
               .eq("id", allocation_id).limit(1).execute().data or [None])[0]
    if not alloc:
        abort(404)

    error = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            unit_id   = request.form.get("unit_id", type=int)
            comp_name = request.form.get("competency_name", "").strip()
            target_h  = request.form.get("target_hours", 0, type=int)
            if not comp_name:
                error = "Competency name is required."
            else:
                db.table("dual_training_competencies").insert({
                    "allocation_id":   allocation_id,
                    "unit_id":         unit_id,
                    "competency_name": comp_name,
                    "target_hours":    target_h,
                    "status":          "not_started",
                }).execute()
                flash("Competency added.", "success")
                return redirect(url_for("dual.competencies", allocation_id=allocation_id))
        elif action == "update":
            comp_id  = request.form.get("comp_id", type=int)
            achieved = request.form.get("achieved_hours", 0, type=int)
            status   = request.form.get("status", "in_progress")
            from utils import now_eat
            db.table("dual_training_competencies").update({
                "achieved_hours": achieved,
                "status":         status,
                "assessed_by":    user["id"],
                "assessed_at":    now_eat().isoformat(),
            }).eq("id", comp_id).execute()
            flash("Competency updated.", "success")
            return redirect(url_for("dual.competencies", allocation_id=allocation_id))

    comps = (db.table("dual_training_competencies")
               .select("*, units(code,name)")
               .eq("allocation_id", allocation_id)
               .execute().data or [])

    dept_id = alloc.get("department_id")
    units = db.table("units").select("*").eq("department_id", dept_id).order("code").execute().data or [] if dept_id else []

    return render_template("dual/competencies.html",
                           alloc=alloc, comps=comps, units=units,
                           error=error, user=user)


# ── Monitoring Dashboard (M&E / Trainer) ─────────────────────────────────────

@dual_bp.route("/monitoring")
@login_required
def monitoring():
    user = current_user()
    if user.get("role") not in ("monitoring_evaluation", "super_admin", "deputy_principal",
                                 "dept_admin", "hod", "trainer"):
        abort(403)
    db = _db()
    dept_id = user.get("dept_id")

    query = (db.table("dual_training_allocations")
               .select("*, students(full_name,admission_number,classes(name)), employers(company_name)")
               .order("created_at", desc=True))
    if dept_id and user.get("role") not in ("super_admin", "deputy_principal", "monitoring_evaluation"):
        query = query.eq("department_id", dept_id)

    allocs = query.execute().data or []

    # Enrich with hours and feedback count
    for a in allocs:
        att = db.table("dual_training_attendance").select("hours_worked").eq("allocation_id", a["id"]).execute().data or []
        a["total_hours"] = sum(r.get("hours_worked") or 0 for r in att)
        fb = db.table("employer_feedback").select("id", count="exact").eq("allocation_id", a["id"]).execute()
        a["feedback_count"] = fb.count or 0

    return render_template("dual/monitoring.html", allocs=allocs, user=user)
