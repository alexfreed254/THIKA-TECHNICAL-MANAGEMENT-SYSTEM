"""
routes/verification.py — Internal (Module 8) & External (Module 9) Verification
"""

from flask import (Blueprint, render_template, request,
                   redirect, url_for, flash, abort, jsonify)
from auth_utils import login_required, current_user, write_audit_log
from db import get_service_client
from notify import send_notification, send_to_role

verif_bp = Blueprint("verif", __name__)


def _db():
    return get_service_client()


# ════════════════════════════════════════════════════════════
# MODULE 8: INTERNAL VERIFICATION
# ════════════════════════════════════════════════════════════

# ── Trainer: Submit Assessment for IV ────────────────────────────────────────

@verif_bp.route("/internal/submit", methods=["GET", "POST"])
@login_required
def iv_submit():
    user = current_user()
    if user.get("role") not in ("trainer", "dept_admin", "super_admin"):
        abort(403)
    db = _db()
    error = None

    dept_id = user.get("dept_id")
    units   = db.table("units").select("*").eq("department_id", dept_id).order("code").execute().data or [] if dept_id else []
    classes = db.table("classes").select("*").eq("department_id", dept_id).order("name").execute().data or [] if dept_id else []

    if request.method == "POST":
        unit_id     = request.form.get("unit_id", type=int)
        class_id    = request.form.get("class_id", type=int)
        assess_type = request.form.get("assessment_type", "").strip()
        assess_date = request.form.get("assessment_date") or None
        evidence    = request.form.get("evidence_description", "").strip()
        file_urls   = request.form.getlist("evidence_file_urls")

        # Get trainer row
        trainer_rows = db.table("trainers").select("id").eq("user_id", user["id"]).limit(1).execute().data or []
        trainer_id = trainer_rows[0]["id"] if trainer_rows else None

        if not unit_id or not assess_type:
            error = "Unit and assessment type are required."
        else:
            iv = db.table("internal_verifications").insert({
                "trainer_id":            trainer_id,
                "unit_id":               unit_id,
                "class_id":              class_id,
                "department_id":         dept_id,
                "assessment_type":       assess_type,
                "assessment_date":       assess_date,
                "evidence_description":  evidence,
                "status":                "pending",
            }).execute().data[0]

            iv_id = iv["id"]
            for url in file_urls:
                if url.strip():
                    db.table("iv_evidence_files").insert({
                        "verification_id": iv_id,
                        "file_url":        url.strip(),
                        "file_name":       url.strip().split("/")[-1],
                        "uploaded_by":     user["id"],
                    }).execute()

            # Notify internal verifiers / HOD
            send_to_role("hod", "New Assessment Submitted for Internal Verification",
                         f"A new assessment has been submitted for internal verification by trainer.",
                         notif_type="info", module="internal_verif", reference_id=iv_id,
                         department_id=dept_id)

            write_audit_log("iv_submit", target=str(iv_id))
            flash("Assessment submitted for internal verification.", "success")
            return redirect(url_for("verif.iv_my_submissions"))

    return render_template("verif/iv_submit.html",
                           units=units, classes=classes, error=error, user=user)


# ── Trainer: My Submissions ───────────────────────────────────────────────────

@verif_bp.route("/internal/my-submissions")
@login_required
def iv_my_submissions():
    user = current_user()
    db = _db()
    trainer_rows = db.table("trainers").select("id").eq("user_id", user["id"]).limit(1).execute().data or []
    trainer_id = trainer_rows[0]["id"] if trainer_rows else None

    ivs = []
    if trainer_id:
        ivs = (db.table("internal_verifications")
                 .select("*, units(code,name), classes(name)")
                 .eq("trainer_id", trainer_id)
                 .order("created_at", desc=True)
                 .execute().data or [])
    return render_template("verif/iv_my_submissions.html", ivs=ivs, user=user)


# ── HOD/Verifier: Review Queue ────────────────────────────────────────────────

@verif_bp.route("/internal/review-queue")
@login_required
def iv_review_queue():
    user = current_user()
    if user.get("role") not in ("hod", "dept_admin", "super_admin", "deputy_principal", "monitoring_evaluation"):
        abort(403)
    db = _db()
    dept_id = user.get("dept_id")

    query = (db.table("internal_verifications")
               .select("*, units(code,name), classes(name), trainers(name)")
               .order("created_at", desc=True))
    if dept_id and user.get("role") not in ("super_admin", "deputy_principal", "monitoring_evaluation"):
        query = query.eq("department_id", dept_id)

    status_filter = request.args.get("status", "pending")
    if status_filter:
        query = query.eq("status", status_filter)

    ivs = query.execute().data or []
    return render_template("verif/iv_review_queue.html", ivs=ivs, user=user,
                           status_filter=status_filter)


# ── HOD/Verifier: Review Single ───────────────────────────────────────────────

@verif_bp.route("/internal/review/<int:iv_id>", methods=["GET", "POST"])
@login_required
def iv_review(iv_id):
    user = current_user()
    if user.get("role") not in ("hod", "dept_admin", "super_admin", "deputy_principal", "monitoring_evaluation"):
        abort(403)
    db = _db()

    iv = (db.table("internal_verifications")
            .select("*, units(code,name), classes(name), trainers(name,user_id)")
            .eq("id", iv_id).limit(1).execute().data or [None])[0]
    if not iv:
        abort(404)

    files = db.table("iv_evidence_files").select("*").eq("verification_id", iv_id).execute().data or []
    error = None

    if request.method == "POST":
        action     = request.form.get("action")
        comment    = request.form.get("verifier_comment", "").strip()
        score      = request.form.get("compliance_score", type=int)
        recommend  = request.form.get("recommendations", "").strip()
        signature  = request.form.get("verifier_signature", "").strip()

        from utils import now_eat
        status_map = {
            "approve":  "approved",
            "reject":   "rejected",
            "revision": "revision_required",
        }
        new_status = status_map.get(action, "under_review")

        db.table("internal_verifications").update({
            "status":             new_status,
            "verifier_id":        user["id"],
            "verifier_comment":   comment,
            "verifier_signature": signature,
            "verified_at":        now_eat().isoformat(),
            "compliance_score":   score,
            "recommendations":    recommend,
            "version":            (iv.get("version") or 1) + 1,
        }).eq("id", iv_id).execute()

        # Notify trainer
        trainer_user_id = (iv.get("trainers") or {}).get("user_id")
        if trainer_user_id:
            send_notification(trainer_user_id,
                              f"Internal Verification {new_status.replace('_', ' ').title()}",
                              f"Your assessment (IV #{iv_id}) has been {new_status.replace('_', ' ')}. {comment}",
                              notif_type="success" if action == "approve" else "warning",
                              module="internal_verif", reference_id=iv_id)

        write_audit_log(f"iv_{action}", target=str(iv_id))
        flash(f"Assessment marked as {new_status.replace('_', ' ')}.", "success")
        return redirect(url_for("verif.iv_review_queue"))

    return render_template("verif/iv_review.html", iv=iv, files=files, error=error, user=user)


# ════════════════════════════════════════════════════════════
# MODULE 9: EXTERNAL VERIFICATION
# ════════════════════════════════════════════════════════════

# ── External Verifier: Dashboard ─────────────────────────────────────────────

@verif_bp.route("/external/dashboard")
@login_required
def ev_dashboard():
    user = current_user()
    if user.get("role") not in ("external_verifier", "super_admin", "deputy_principal"):
        abort(403)
    db = _db()

    my_reports = (db.table("external_verifications")
                    .select("*, departments(name)")
                    .eq("verifier_id", user["id"])
                    .order("created_at", desc=True)
                    .execute().data or [])

    # Stats
    total    = len(my_reports)
    approved = sum(1 for r in my_reports if r["status"] == "approved")
    pending  = sum(1 for r in my_reports if r["status"] in ("draft", "submitted"))
    avg_score = round(sum(r.get("compliance_score") or 0 for r in my_reports) / total, 1) if total else 0

    depts = db.table("departments").select("*").order("name").execute().data or []
    return render_template("verif/ev_dashboard.html",
                           my_reports=my_reports, total=total,
                           approved=approved, pending=pending,
                           avg_score=avg_score, depts=depts, user=user)


# ── External Verifier: Create Report ─────────────────────────────────────────

@verif_bp.route("/external/create-report", methods=["GET", "POST"])
@login_required
def ev_create_report():
    user = current_user()
    if user.get("role") not in ("external_verifier", "super_admin"):
        abort(403)
    db = _db()
    error = None
    depts = db.table("departments").select("*").order("name").execute().data or []

    if request.method == "POST":
        dept_id     = request.form.get("department_id", type=int)
        visit_date  = request.form.get("visit_date") or None
        title       = request.form.get("report_title", "").strip()
        score       = request.form.get("compliance_score", type=int)
        findings    = request.form.get("findings", "").strip()
        recommend   = request.form.get("recommendations", "").strip()
        report_url  = request.form.get("report_file_url", "").strip()
        signature   = request.form.get("digital_signature", "").strip()
        action      = request.form.get("action", "draft")

        if not title or not dept_id:
            error = "Title and department are required."
        else:
            from utils import now_eat
            ev = db.table("external_verifications").insert({
                "department_id":    dept_id,
                "verifier_id":      user["id"],
                "visit_date":       visit_date,
                "report_title":     title,
                "compliance_score": score,
                "findings":         findings,
                "recommendations":  recommend,
                "status":           "submitted" if action == "submit" else "draft",
                "digital_signature": signature,
                "signed_at":        now_eat().isoformat() if signature else None,
                "report_file_url":  report_url,
            }).execute().data[0]

            ev_id = ev["id"]
            db.table("ev_audit_history").insert({
                "ev_id":    ev_id,
                "action":   "created",
                "actor_id": user["id"],
                "detail":   f"Report created with status: {ev['status']}",
            }).execute()

            if action == "submit":
                send_to_role("super_admin", "New External Verification Report Submitted",
                             f"External verifier submitted report: {title}",
                             notif_type="info", module="external_verif", reference_id=ev_id)
                send_to_role("deputy_principal", "New External Verification Report",
                             f"External verifier submitted report: {title}",
                             notif_type="info", module="external_verif", reference_id=ev_id)

            write_audit_log("ev_create_report", target=str(ev_id))
            flash("Report saved.", "success")
            return redirect(url_for("verif.ev_dashboard"))

    return render_template("verif/ev_create_report.html", depts=depts, error=error, user=user)


# ── Admin: All External Reports ───────────────────────────────────────────────

@verif_bp.route("/external/all-reports")
@login_required
def ev_all_reports():
    user = current_user()
    if user.get("role") not in ("super_admin", "deputy_principal", "monitoring_evaluation"):
        abort(403)
    db = _db()
    dept_filter = request.args.get("dept_id", type=int)

    query = (db.table("external_verifications")
               .select("*, departments(name)")
               .order("created_at", desc=True))
    if dept_filter:
        query = query.eq("department_id", dept_filter)

    reports = query.execute().data or []
    depts   = db.table("departments").select("*").order("name").execute().data or []

    # Stats
    total     = len(reports)
    avg_score = round(sum(r.get("compliance_score") or 0 for r in reports) / total, 1) if total else 0

    return render_template("verif/ev_all_reports.html",
                           reports=reports, depts=depts,
                           dept_filter=dept_filter, total=total,
                           avg_score=avg_score, user=user)


# ── Admin: Approve/Reject External Report ────────────────────────────────────

@verif_bp.route("/external/action/<int:ev_id>", methods=["POST"])
@login_required
def ev_action(ev_id):
    user = current_user()
    if user.get("role") not in ("super_admin", "deputy_principal"):
        abort(403)
    db = _db()
    action  = request.form.get("action")
    comment = request.form.get("comment", "").strip()

    new_status = "approved" if action == "approve" else "rejected"
    db.table("external_verifications").update({"status": new_status}).eq("id", ev_id).execute()
    db.table("ev_audit_history").insert({
        "ev_id":    ev_id,
        "action":   new_status,
        "actor_id": user["id"],
        "detail":   comment,
    }).execute()

    # Notify the verifier
    ev = (db.table("external_verifications").select("verifier_id").eq("id", ev_id).limit(1).execute().data or [{}])[0]
    if ev.get("verifier_id"):
        send_notification(ev["verifier_id"],
                          f"External Verification Report {new_status.title()}",
                          f"Your report #{ev_id} has been {new_status}. {comment}",
                          notif_type="success" if action == "approve" else "rejection",
                          module="external_verif", reference_id=ev_id)

    write_audit_log(f"ev_{action}", target=str(ev_id))
    flash(f"Report {new_status}.", "success" if action == "approve" else "error")
    return redirect(url_for("verif.ev_all_reports"))


# ── View Single External Report ───────────────────────────────────────────────

@verif_bp.route("/external/report/<int:ev_id>")
@login_required
def ev_view_report(ev_id):
    user = current_user()
    db = _db()
    report = (db.table("external_verifications")
                .select("*, departments(name)")
                .eq("id", ev_id).limit(1).execute().data or [None])[0]
    if not report:
        abort(404)

    # Access: own report or admin
    if user.get("role") == "external_verifier" and report.get("verifier_id") != user["id"]:
        abort(403)

    history = (db.table("ev_audit_history")
                 .select("*").eq("ev_id", ev_id)
                 .order("created_at").execute().data or [])

    # Institution summary for this dept
    dept_id = report.get("department_id")
    dept_reports = []
    if dept_id:
        dept_reports = (db.table("external_verifications")
                          .select("compliance_score,visit_date,status")
                          .eq("department_id", dept_id)
                          .order("visit_date", desc=True)
                          .limit(10).execute().data or [])

    return render_template("verif/ev_view_report.html",
                           report=report, history=history,
                           dept_reports=dept_reports, user=user)
