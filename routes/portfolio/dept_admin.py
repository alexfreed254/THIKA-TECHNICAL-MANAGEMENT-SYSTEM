"""E-Portfolio - Department Admin routes."""

from flask import render_template, request, redirect, url_for, flash

from auth_utils import login_required, role_required, current_user, write_audit_log
from db import get_service_client

from routes.portfolio import portfolio_bp


def _dept_admin_profile():
    return current_user()


@portfolio_bp.route("/portfolio/dept-admin/dashboard")
@login_required
@role_required("dept_admin")
def portfolio_dept_admin_dashboard():
    db = get_service_client()
    user = _dept_admin_profile()

    dept_id = user.get("dept_id") or user.get("department_id")
    if not dept_id:
        flash("Department not assigned.", "error")
        return redirect(url_for("dept_admin.dashboard"))

    # Department scope: filter by class.department_id (via classes table join is DB-specific)
    # For MVP integration we keep it simple: fetch assessments for classes in dept.
    class_ids = (db.table("classes")
                   .select("id")
                   .eq("department_id", dept_id)
                   .execute().data or [])
    class_id_list = [c["id"] for c in class_ids if c.get("id")]

    q = db.table("assessments").select("*, units(name, code), classes(name)")
    if class_id_list:
        q = q.in_("class_id", class_id_list)

    assessments = q.order("uploaded_at", desc=True).execute().data or []

    return render_template("portfolio/dept_admin/dashboard.html", assessments=assessments)

