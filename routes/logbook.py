"""
routes/logbook.py — Industrial Attachment & Digital Logbook (Module 11)
Trainee submissions every 2 hours, supervisor approval, trainer monitoring.
"""

from datetime import datetime, date, timedelta
from flask import (Blueprint, render_template, request,
                   redirect, url_for, flash, abort, jsonify)
from auth_utils import login_required, current_user, write_audit_log
from db import get_service_client
from notify import send_notification, send_to_role
import pytz

logbook_bp = Blueprint("logbook", __name__)

EAT = pytz.timezone("Africa/Nairobi")
SUBMISSION_SLOTS = ["07:00", "09:00", "11:00", "13:00", "15:00", "17:00", "19:00"]


def _db():
    return get_service_client()


def _now_eat():
    return datetime.now(EAT)


def _student_row(user_id):
    rows = (_db().table("students").select("*, classes(name, department_id, departments(name))")
            .eq("user_id", user_id).limit(1).execute().data or [])
    return rows[0] if rows else None


def _get_placement(student_id):
    rows = (_db().table("attachment_placements")
              .select("*, employers(company_name), industry_supervisors(full_name,user_id), trainers(name,user_id)")
              .eq("student_id", student_id).eq("status", "active")
              .limit(1).execute().data or [])
    return rows[0] if rows else None


# ── Student: Logbook Dashboard ────────────────────────────────────────────────

@logbook_bp.route("/dashboard")
@login_required
def student_dashboard():
    user = current_user()
    if user.get("role") != "student":
        abort(403)
    db = _db()
    student = _student_row(user["id"])
    if not student:
        abort(403)

    placement = _get_placement(student["id"])
    today = _now_eat().date()

    # Today's submissions
    today_entries = []
    if placement:
        today_entries = (db.table("logbook_entries")
                           .select("*")
                           .eq("placement_id", placement["id"])
                           .eq("submission_date", today.isoformat())
                           .order("submission_slot")
                           .execute().data or [])

    submitted_slots = {e["submission_slot"] for e in today_entries}
    now_time = _now_eat().strftime("%H:%M")

    # Available slots (not yet submitted, not in future)
    available_slots = []
    for slot in SUBMISSION_SLOTS:
        if slot not in submitted_slots and slot <= now_time:
            available_slots.append(slot)

    # Recent entries (last 7 days)
    week_ago = (today - timedelta(days=7)).isoformat()
    recent_entries = []
    if placement:
        recent_entries = (db.table("logbook_entries")
                            .select("*")
                            .eq("placement_id", placement["id"])
                            .gte("submission_date", week_ago)
                            .order("submission_date", desc=True)
                            .order("submission_slot", desc=True)
                            .limit(50)
                            .execute().data or [])

    # Stats
    total_entries  = len(recent_entries)
    approved_count = sum(1 for e in recent_entries if e["status"] == "approved")
    pending_count  = sum(1 for e in recent_entries if e["status"] == "pending")

    return render_template("logbook/student_dashboard.html",
                           student=student, placement=placement,
                           today_entries=today_entries,
                           available_slots=available_slots,
                           submitted_slots=submitted_slots,
                           recent_entries=recent_entries,
                           total_entries=total_entries,
                           approved_count=approved_count,
                           pending_count=pending_count,
                           today=today, now_time=now_time,
                           submission_slots=SUBMISSION_SLOTS,
                           user=user)


# ── Student: Submit Logbook Entry ─────────────────────────────────────────────

@logbook_bp.route("/submit", methods=["GET", "POST"])
@login_required
def submit_entry():
    user = current_user()
    if user.get("role") != "student":
        abort(403)
    db = _db()
    student = _student_row(user["id"])
    if not student:
        abort(403)

    placement = _get_placement(student["id"])
    if not placement:
        flash("No active industrial attachment found. Contact your trainer.", "error")
        return redirect(url_for("logbook.student_dashboard"))

    slot = request.args.get("slot", "")
    error = None
    now_eat = _now_eat()
    today = now_eat.date()

    if request.method == "POST":
        slot         = request.form.get("submission_slot", "")
        sub_date_str = request.form.get("submission_date", today.isoformat())
        title        = request.form.get("activity_title", "").strip()
        description  = request.form.get("description", "").strip()
        skills       = request.form.get("skills_gained", "").strip()
        tools        = request.form.get("tools_materials", "").strip()
        challenges   = request.form.get("challenges_faced", "").strip()
        time_spent   = request.form.get("time_spent", type=float)
        lat          = request.form.get("gps_latitude", type=float)
        lng          = request.form.get("gps_longitude", type=float)
        gps_name     = request.form.get("gps_location_name", "").strip()
        file_urls    = request.form.getlist("evidence_file_urls")

        # Backdate prevention: only allow today
        try:
            sub_date = date.fromisoformat(sub_date_str)
        except Exception:
            sub_date = today

        is_backdated = sub_date < today

        if not slot or slot not in SUBMISSION_SLOTS:
            error = "Please select a valid submission slot."
        elif not title:
            error = "Activity title is required."
        else:
            # Check duplicate
            existing = (db.table("logbook_entries")
                          .select("id", count="exact")
                          .eq("placement_id", placement["id"])
                          .eq("submission_date", sub_date.isoformat())
                          .eq("submission_slot", slot)
                          .execute())
            if (existing.count or 0) > 0:
                error = f"You have already submitted for the {slot} slot today."
            else:
                entry = db.table("logbook_entries").insert({
                    "placement_id":     placement["id"],
                    "student_id":       student["id"],
                    "submission_slot":  slot,
                    "submission_date":  sub_date.isoformat(),
                    "activity_title":   title,
                    "description":      description,
                    "skills_gained":    skills,
                    "tools_materials":  tools,
                    "challenges_faced": challenges,
                    "time_spent":       time_spent,
                    "gps_latitude":     lat,
                    "gps_longitude":    lng,
                    "gps_location_name": gps_name,
                    "status":           "pending",
                    "submitted_at":     now_eat.isoformat(),
                    "is_backdated":     is_backdated,
                }).execute().data[0]

                entry_id = entry["id"]

                # Save evidence files
                for url in file_urls:
                    if url.strip():
                        ext = url.strip().split(".")[-1].lower()
                        ftype = "photo" if ext in ("jpg","jpeg","png","gif","webp") \
                               else "video" if ext in ("mp4","mov","avi","mkv") \
                               else "pdf" if ext == "pdf" else "document"
                        db.table("logbook_evidence").insert({
                            "entry_id":  entry_id,
                            "file_url":  url.strip(),
                            "file_name": url.strip().split("/")[-1],
                            "file_type": ftype,
                        }).execute()

                # Notify supervisor
                sup = placement.get("industry_supervisors") or {}
                if sup.get("user_id"):
                    send_notification(sup["user_id"],
                                      "New Logbook Entry Submitted",
                                      f"{student['full_name']} submitted a logbook entry for {slot} slot.",
                                      notif_type="info", module="logbook", reference_id=entry_id)

                write_audit_log("logbook_submit", target=student["admission_number"],
                                detail={"slot": slot, "date": sub_date.isoformat()})
                flash(f"Logbook entry for {slot} submitted successfully.", "success")
                return redirect(url_for("logbook.student_dashboard"))

    return render_template("logbook/submit_entry.html",
                           student=student, placement=placement,
                           slot=slot, today=today,
                           submission_slots=SUBMISSION_SLOTS,
                           error=error, user=user)


# ── Student: View My Logbook ──────────────────────────────────────────────────

@logbook_bp.route("/my-logbook")
@login_required
def my_logbook():
    user = current_user()
    if user.get("role") != "student":
        abort(403)
    db = _db()
    student = _student_row(user["id"])
    if not student:
        abort(403)

    placement = _get_placement(student["id"])
    entries = []
    if placement:
        entries = (db.table("logbook_entries")
                     .select("*")
                     .eq("placement_id", placement["id"])
                     .order("submission_date", desc=True)
                     .order("submission_slot", desc=True)
                     .execute().data or [])

    # Group by date
    from collections import defaultdict
    grouped = defaultdict(list)
    for e in entries:
        grouped[e["submission_date"]].append(e)

    return render_template("logbook/my_logbook.html",
                           student=student, placement=placement,
                           grouped=dict(grouped), entries=entries,
                           user=user)


# ── Supervisor: Dashboard ─────────────────────────────────────────────────────

@logbook_bp.route("/supervisor/dashboard")
@login_required
def supervisor_dashboard():
    user = current_user()
    if user.get("role") not in ("industry_supervisor", "super_admin"):
        abort(403)
    db = _db()

    # Get supervisor row
    sup_row = (db.table("industry_supervisors").select("*").eq("user_id", user["id"]).limit(1).execute().data or [None])[0]

    placements = []
    if sup_row:
        placements = (db.table("attachment_placements")
                        .select("*, students(full_name,admission_number,classes(name))")
                        .eq("supervisor_id", sup_row["id"])
                        .eq("status", "active")
                        .execute().data or [])

    # Pending entries across all assigned trainees
    pending_entries = []
    for p in placements:
        entries = (db.table("logbook_entries")
                     .select("*, students(full_name,admission_number)")
                     .eq("placement_id", p["id"])
                     .eq("status", "pending")
                     .order("submission_date", desc=True)
                     .limit(20)
                     .execute().data or [])
        pending_entries.extend(entries)

    # Inactive trainees (no submission in last 2 days)
    today = _now_eat().date()
    two_days_ago = (today - timedelta(days=2)).isoformat()
    inactive = []
    for p in placements:
        recent = (db.table("logbook_entries")
                    .select("id", count="exact")
                    .eq("placement_id", p["id"])
                    .gte("submission_date", two_days_ago)
                    .execute())
        if (recent.count or 0) == 0:
            inactive.append(p)

    return render_template("logbook/supervisor_dashboard.html",
                           sup_row=sup_row, placements=placements,
                           pending_entries=pending_entries,
                           inactive=inactive, user=user)


# ── Supervisor: Review Entry ──────────────────────────────────────────────────

@logbook_bp.route("/supervisor/review/<int:entry_id>", methods=["GET", "POST"])
@login_required
def supervisor_review(entry_id):
    user = current_user()
    if user.get("role") not in ("industry_supervisor", "super_admin"):
        abort(403)
    db = _db()

    entry = (db.table("logbook_entries")
               .select("*, students(full_name,admission_number)")
               .eq("id", entry_id).limit(1).execute().data or [None])[0]
    if not entry:
        abort(404)

    evidence = db.table("logbook_evidence").select("*").eq("entry_id", entry_id).execute().data or []
    error = None

    if request.method == "POST":
        action  = request.form.get("action")
        comment = request.form.get("supervisor_comment", "").strip()

        from utils import now_eat
        new_status = "approved" if action == "approve" else "rejected"
        db.table("logbook_entries").update({
            "status":             new_status,
            "supervisor_comment": comment,
            "approved_by":        user["id"],
            "approved_at":        now_eat().isoformat(),
        }).eq("id", entry_id).execute()

        # Notify student
        student_row = (db.table("students").select("user_id").eq("id", entry["student_id"]).limit(1).execute().data or [{}])[0]
        if student_row.get("user_id"):
            send_notification(student_row["user_id"],
                              f"Logbook Entry {new_status.title()}",
                              f"Your logbook entry for {entry['submission_slot']} on {entry['submission_date']} has been {new_status}. {comment}",
                              notif_type="success" if action == "approve" else "rejection",
                              module="logbook", reference_id=entry_id)

        write_audit_log(f"logbook_{action}", target=str(entry_id))
        flash(f"Entry {new_status}.", "success" if action == "approve" else "error")
        return redirect(url_for("logbook.supervisor_dashboard"))

    return render_template("logbook/supervisor_review.html",
                           entry=entry, evidence=evidence, error=error, user=user)


# ── Supervisor: Evaluate Trainee ──────────────────────────────────────────────

@logbook_bp.route("/supervisor/evaluate/<int:placement_id>", methods=["GET", "POST"])
@login_required
def supervisor_evaluate(placement_id):
    user = current_user()
    if user.get("role") not in ("industry_supervisor", "super_admin"):
        abort(403)
    db = _db()

    placement = (db.table("attachment_placements")
                   .select("*, students(full_name,admission_number,user_id), industry_supervisors(id)")
                   .eq("id", placement_id).limit(1).execute().data or [None])[0]
    if not placement:
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
            sup_row = (db.table("industry_supervisors").select("id").eq("user_id", user["id"]).limit(1).execute().data or [{}])[0]
            db.table("supervisor_evaluations").insert({
                "placement_id":    placement_id,
                "supervisor_id":   sup_row.get("id"),
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

            # Notify student
            student_uid = (placement.get("students") or {}).get("user_id")
            if student_uid:
                send_notification(student_uid, "Weekly Evaluation Submitted",
                                  f"Your supervisor has submitted your week {week} evaluation.",
                                  notif_type="info", module="logbook", reference_id=placement_id)

            write_audit_log("supervisor_evaluate", target=str(placement_id))
            flash("Evaluation submitted.", "success")
            return redirect(url_for("logbook.supervisor_dashboard"))

    evaluations = (db.table("supervisor_evaluations")
                     .select("*").eq("placement_id", placement_id)
                     .order("week_number").execute().data or [])

    return render_template("logbook/supervisor_evaluate.html",
                           placement=placement, evaluations=evaluations,
                           error=error, user=user)


# ── Trainer: Monitoring Dashboard ────────────────────────────────────────────

@logbook_bp.route("/trainer/monitoring")
@login_required
def trainer_monitoring():
    user = current_user()
    if user.get("role") not in ("trainer", "dept_admin", "super_admin", "hod", "monitoring_evaluation"):
        abort(403)
    db = _db()

    trainer_row = (db.table("trainers").select("id,department_id").eq("user_id", user["id"]).limit(1).execute().data or [None])[0]
    dept_id = (trainer_row["department_id"] if trainer_row else None) or user.get("dept_id")

    # Placements in this dept
    query = db.table("attachment_placements").select("*, students(full_name,admission_number,classes(name)), employers(company_name), industry_supervisors(full_name)")
    if trainer_row:
        query = query.eq("trainer_id", trainer_row["id"])
    elif dept_id and user.get("role") not in ("super_admin", "monitoring_evaluation"):
        query = query.eq("department_id", dept_id)

    placements = query.order("created_at", desc=True).execute().data or []

    today = _now_eat().date()
    two_days_ago = (today - timedelta(days=2)).isoformat()

    for p in placements:
        # Total entries
        total = db.table("logbook_entries").select("id", count="exact").eq("placement_id", p["id"]).execute()
        p["total_entries"] = total.count or 0

        # Pending approvals
        pending = db.table("logbook_entries").select("id", count="exact").eq("placement_id", p["id"]).eq("status", "pending").execute()
        p["pending_count"] = pending.count or 0

        # Active today
        today_count = db.table("logbook_entries").select("id", count="exact").eq("placement_id", p["id"]).eq("submission_date", today.isoformat()).execute()
        p["today_count"] = today_count.count or 0

        # Inactive flag
        recent = db.table("logbook_entries").select("id", count="exact").eq("placement_id", p["id"]).gte("submission_date", two_days_ago).execute()
        p["is_inactive"] = (recent.count or 0) == 0

    return render_template("logbook/trainer_monitoring.html",
                           placements=placements, trainer_row=trainer_row,
                           today=today, user=user)


# ── Trainer: View Trainee Logbook ─────────────────────────────────────────────

@logbook_bp.route("/trainer/view-logbook/<int:placement_id>")
@login_required
def trainer_view_logbook(placement_id):
    user = current_user()
    if user.get("role") not in ("trainer", "dept_admin", "super_admin", "hod", "monitoring_evaluation"):
        abort(403)
    db = _db()

    placement = (db.table("attachment_placements")
                   .select("*, students(full_name,admission_number), employers(company_name), industry_supervisors(full_name)")
                   .eq("id", placement_id).limit(1).execute().data or [None])[0]
    if not placement:
        abort(404)

    entries = (db.table("logbook_entries")
                 .select("*")
                 .eq("placement_id", placement_id)
                 .order("submission_date", desc=True)
                 .order("submission_slot")
                 .execute().data or [])

    # Evaluations
    evaluations = (db.table("supervisor_evaluations")
                     .select("*").eq("placement_id", placement_id)
                     .order("week_number").execute().data or [])

    # Stats
    total    = len(entries)
    approved = sum(1 for e in entries if e["status"] == "approved")
    pending  = sum(1 for e in entries if e["status"] == "pending")
    rejected = sum(1 for e in entries if e["status"] == "rejected")

    from utils import now_eat
    return render_template("logbook/trainer_view_logbook.html",
                           placement=placement, entries=entries,
                           evaluations=evaluations,
                           total=total, approved=approved,
                           pending=pending, rejected=rejected,
                           generated=now_eat().strftime("%d %b %Y %H:%M"),
                           user=user)


# ── Admin: Manage Placements ──────────────────────────────────────────────────

@logbook_bp.route("/admin/placements", methods=["GET", "POST"])
@login_required
def admin_placements():
    user = current_user()
    if user.get("role") not in ("super_admin", "dept_admin", "hod", "deputy_principal"):
        abort(403)
    db = _db()
    error = None
    dept_id = user.get("dept_id")

    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            student_id  = request.form.get("student_id", type=int)
            employer_id = request.form.get("employer_id", type=int)
            sup_id      = request.form.get("supervisor_id", type=int) or None
            trainer_id  = request.form.get("trainer_id", type=int) or None
            start_date  = request.form.get("start_date") or None
            end_date    = request.form.get("end_date") or None

            if not student_id or not employer_id:
                error = "Student and employer are required."
            else:
                db.table("attachment_placements").insert({
                    "student_id":   student_id,
                    "employer_id":  employer_id,
                    "supervisor_id": sup_id,
                    "trainer_id":   trainer_id,
                    "start_date":   start_date,
                    "end_date":     end_date,
                    "department_id": dept_id,
                    "status":       "active",
                }).execute()

                # Notify student
                s_row = (db.table("students").select("user_id,full_name").eq("id", student_id).limit(1).execute().data or [{}])[0]
                if s_row.get("user_id"):
                    emp = (db.table("employers").select("company_name").eq("id", employer_id).limit(1).execute().data or [{}])[0]
                    send_notification(s_row["user_id"], "Industrial Attachment Assigned",
                                      f"You have been assigned to {emp.get('company_name','an employer')} for industrial attachment.",
                                      notif_type="info", module="logbook")

                write_audit_log("create_placement", target=str(student_id))
                flash("Placement created.", "success")
                return redirect(url_for("logbook.admin_placements"))

    # Data for form
    dept_class_ids = []
    if dept_id:
        dept_class_ids = [c["id"] for c in db.table("classes").select("id").eq("department_id", dept_id).execute().data or []]

    students = []
    if dept_class_ids:
        students = db.table("students").select("id,full_name,admission_number").in_("class_id", dept_class_ids).order("full_name").execute().data or []
    elif user.get("role") in ("super_admin", "deputy_principal"):
        students = db.table("students").select("id,full_name,admission_number").order("full_name").limit(500).execute().data or []

    employers_list = db.table("employers").select("*").eq("is_active", True).order("company_name").execute().data or []
    supervisors    = db.table("industry_supervisors").select("*").eq("is_active", True).order("full_name").execute().data or []
    trainers_list  = db.table("trainers").select("id,name").order("name").execute().data or []

    query = db.table("attachment_placements").select("*, students(full_name,admission_number), employers(company_name), industry_supervisors(full_name)")
    if dept_id and user.get("role") not in ("super_admin", "deputy_principal"):
        query = query.eq("department_id", dept_id)
    placements = query.order("created_at", desc=True).execute().data or []

    return render_template("logbook/admin_placements.html",
                           students=students, employers=employers_list,
                           supervisors=supervisors, trainers=trainers_list,
                           placements=placements, error=error, user=user)


# ── API: Get entry evidence ───────────────────────────────────────────────────

@logbook_bp.route("/api/entry-evidence/<int:entry_id>")
@login_required
def api_entry_evidence(entry_id):
    db = _db()
    evidence = db.table("logbook_evidence").select("*").eq("entry_id", entry_id).execute().data or []
    return jsonify(evidence)
