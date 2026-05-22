"""E-Portfolio - Super Admin routes."""

from flask import render_template

from auth_utils import login_required, super_admin_required
from db import get_service_client

from routes.portfolio import portfolio_bp


@portfolio_bp.route("/portfolio/super-admin/dashboard")
@login_required
@super_admin_required
def portfolio_super_admin_dashboard():
    db = get_service_client()

    assessments = (db.table("assessments")
                     .select("*, units(name, code), classes(name)")
                     .order("uploaded_at", desc=True)
                     .limit(500)
                     .execute().data or [])

    return render_template("portfolio/super_admin/dashboard.html", assessments=assessments)

