"""E-Portfolio - Trainer routes.

Provides review workflow endpoints under /portfolio/*.
Integrated with existing auth/session model.
"""

from datetime import datetime
from flask import render_template, request, redirect, url_for, flash

from auth_utils import login_required, trainer_required, current_user, write_audit_log
from db import get_service_client

from routes.portfolio import portfolio_bp


def _trainer_row():
    user = current_user()
    db = get_service_client()
    rows = (db.table("trainers").select("*").eq("user_id", user["id"]).limit(1).execute().data or [])
    return rows[0] if rows else None


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

    assignments = (db.table("trainer_assignments")
                    .select("unit_id, class_id")
                    .eq("trainer_id", trainer["user_id"] if "user_id" in trainer else trainer["id"]) 
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
    # (Dept Admin/HOD assign the unit in trainer_assignments; prevents trainers reviewing others.)
    assignments_check = (db.table("trainer_assignments")
                             .select("id")
                             .eq("trainer_id", trainer.get("user_id") or trainer.get("id"))
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

        db.table("assessments").update({
            "status": new_status,
            "reviewed_at": datetime.utcnow().isoformat(),
            "reviewer_comments": comments or None,
        }).eq("id", assessment_id).execute()

        write_audit_log("portfolio_review", target=str(assessment_id), detail={
            "action": action,
            "status": new_status,
        })

        flash(f"Assessment {action}d successfully.", "success")
        return redirect(url_for("portfolio.portfolio_trainer_dashboard"))

    evidence = (db.table("evidence")
                   .select("*")
                   .eq("assessment_id", assessment_id)
                   .execute().data or [])

    return render_template("portfolio/trainer/review.html", assessment=a, evidence=evidence)

