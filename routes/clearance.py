"""
routes/clearance.py — Student Clearance Module
Multi-department clearance workflow: Dept → Finance → Library → Registrar → Principal sign-off.
"""

from flask import (Blueprint, render_template, request,
                   redirect, url_for, flash, abort)
from auth_utils import login_required, current_user, write_audit_log
from db import get_service_client
from notify import send_notification, send_to_role

clearance_bp = Blueprint("clearance", __name__)


def _db():
    return get_service_client()


def _student_row(user_id):
    rows = (_db().table("students")
              .select("*, classes(name, department_id, departments(name))")
              .eq("user_id", user_id).limit(1).execute().data or [])
    return rows[0] if rows else None


# ── Student: Request Clearance ────────────────────────────────────────────────

@clearance_bp.route("/request")
@login_required
def request_clearance():
    user = current_user()
    if user.get("role") != "student":
        abort(403)
    db = _db()
    student = _student_row(user["id"])
    if not student:
        abort(403)

    # Check if already requested
    existing = (db.table("clearance_requests")
                  .select("*")
                  .eq("student_id", student["id"])
                  .limit(1).execute().data or [None])[0]

    if existing:
        return redirect(url_for("clearance.my_clearance"))

    dept_id = (student.get("classes") or {}).get("department_id")
    cr = db.table("clearance_requests").insert({
        "student_id":   student["id"],
        "department_id": dept_id,
        "status":       "pending",
    }).execute().data[0]

    # Notify dept admin / HOD
    send_to_role("dept_admin", "Clearance Request Submitted",
                 f"{student['full_name']} ({student['admission_number']}) has requested clearance.",
                 notif_type="info", module="clearance", reference_id=cr["id"],
                 department_id=dept_id)
    send_to_role("hod", "Clearance Request Submitted",
                 f"{student['full_name']} ({student['admission_number']}) has requested clearance.",
                 notif_type="info", module="clearance", reference_id=cr["id"],
                 department_id=dept_id)

    write_audit_log("clearance_request", target=student["admission_number"])
    flash("Clearance request submitted. You will be notified as each stage is cleared.", "success")
    return redirect(url_for("clearance.my_clearance"))


# ── Student: My Clearance Status ─────────────────────────────────────────────

@clearance_bp.route("/my-clearance")
@login_required
def my_clearance():
    user = current_user()
    if user.get("role") != "student":
        abort(403)
    db = _db()
    student = _student_row(user["id"])
    if not student:
        abort(403)

    cr = (db.table("clearance_requests")
            .select("*")
            .eq("student_id", student["id"])
            .limit(1).execute().data or [None])[0]

    return render_template("clearance/my_clearance.html",
                           student=student, cr=cr, user=user)


# ── Student: Download Clearance Certificate ───────────────────────────────────

@clearance_bp.route("/download/<int:cr_id>")
@login_required
def download_clearance(cr_id):
    user = current_user()
    db = _db()
    student = _student_row(user["id"])

    cr = (db.table("clearance_requests").select("*").eq("id", cr_id).limit(1).execute().data or [None])[0]
    if not cr:
        abort(404)

    # Only student (own) or admin can download
    role = user.get("role", "")
    if role == "student" and (not student or cr["student_id"] != student["id"]):
        abort(403)
    if cr["status"] != "completed":
        if role == "student":
            flash("Clearance certificate is only available after all stages are completed.", "error")
            return redirect(url_for("clearance.my_clearance"))

    # Get student details
    s_row = (db.table("students")
               .select("*, classes(name, departments(name))")
               .eq("id", cr["student_id"]).limit(1).execute().data or [{}])[0]

    from utils import now_eat
    return render_template("clearance/clearance_certificate.html",
                           cr=cr, student=s_row,
                           generated=now_eat().strftime("%d %b %Y %H:%M"))


# ── Dept Admin / HOD: Clear Department Stage ─────────────────────────────────

@clearance_bp.route("/dept-clear/<int:cr_id>", methods=["POST"])
@login_required
def dept_clear(cr_id):
    user = current_user()
    if user.get("role") not in ("dept_admin", "hod", "super_admin"):
        abort(403)
    db = _db()

    cr = (db.table("clearance_requests").select("*").eq("id", cr_id).limit(1).execute().data or [None])[0]
    if not cr:
        abort(404)

    comment = request.form.get("comment", "").strip()
    action  = request.form.get("action", "clear")

    from utils import now_eat
    if action == "clear":
        db.table("clearance_requests").update({
            "status":           "dept_cleared",
            "dept_cleared_by":  user["id"],
            "dept_cleared_at":  now_eat().isoformat(),
            "dept_comment":     comment,
        }).eq("id", cr_id).execute()

        # Notify finance
        send_to_role("finance", "Clearance Awaiting Finance Clearance",
                     f"Student clearance #{cr_id} has been cleared by the department.",
                     notif_type="info", module="clearance", reference_id=cr_id)

        # Notify student
        s_row = (db.table("students").select("user_id").eq("id", cr["student_id"]).limit(1).execute().data or [{}])[0]
        if s_row.get("user_id"):
            send_notification(s_row["user_id"], "Department Clearance Done",
                              "Your clearance has been approved by the department. Awaiting Finance clearance.",
                              notif_type="success", module="clearance", reference_id=cr_id)

        flash("Department clearance done.", "success")
    else:
        flash("Clearance rejected at department stage.", "error")

    write_audit_log("dept_clear", target=str(cr_id))
    return redirect(url_for("clearance.admin_clearances"))


# ── Finance: Clear Finance Stage ─────────────────────────────────────────────

@clearance_bp.route("/finance-clear/<int:cr_id>", methods=["POST"])
@login_required
def finance_clear(cr_id):
    user = current_user()
    if user.get("role") not in ("finance", "super_admin"):
        abort(403)
    db = _db()

    cr = (db.table("clearance_requests").select("*").eq("id", cr_id).limit(1).execute().data or [None])[0]
    if not cr:
        abort(404)

    comment = request.form.get("comment", "").strip()
    from utils import now_eat
    db.table("clearance_requests").update({
        "status":              "finance_cleared",
        "finance_cleared_by":  user["id"],
        "finance_cleared_at":  now_eat().isoformat(),
        "finance_comment":     comment,
    }).eq("id", cr_id).execute()

    # Notify registrar
    send_to_role("registrar", "Clearance Awaiting Registrar",
                 f"Student clearance #{cr_id} has been cleared by Finance.",
                 notif_type="info", module="clearance", reference_id=cr_id)

    s_row = (db.table("students").select("user_id").eq("id", cr["student_id"]).limit(1).execute().data or [{}])[0]
    if s_row.get("user_id"):
        send_notification(s_row["user_id"], "Finance Clearance Done",
                          "Your clearance has been approved by Finance. Awaiting Registrar clearance.",
                          notif_type="success", module="clearance", reference_id=cr_id)

    write_audit_log("finance_clear", target=str(cr_id))
    flash("Finance clearance done.", "success")
    return redirect(url_for("clearance.admin_clearances"))


# ── Registrar: Clear Registrar Stage ─────────────────────────────────────────

@clearance_bp.route("/registrar-clear/<int:cr_id>", methods=["POST"])
@login_required
def registrar_clear(cr_id):
    user = current_user()
    if user.get("role") not in ("registrar", "super_admin"):
        abort(403)
    db = _db()

    cr = (db.table("clearance_requests").select("*").eq("id", cr_id).limit(1).execute().data or [None])[0]
    if not cr:
        abort(404)

    comment = request.form.get("comment", "").strip()
    from utils import now_eat
    db.table("clearance_requests").update({
        "status":                "registrar_cleared",
        "registrar_cleared_by":  user["id"],
        "registrar_cleared_at":  now_eat().isoformat(),
        "registrar_comment":     comment,
    }).eq("id", cr_id).execute()

    # Notify deputy principal
    send_to_role("deputy_principal", "Clearance Awaiting Principal Sign-off",
                 f"Student clearance #{cr_id} is ready for Principal/Deputy Principal sign-off.",
                 notif_type="info", module="clearance", reference_id=cr_id)

    s_row = (db.table("students").select("user_id").eq("id", cr["student_id"]).limit(1).execute().data or [{}])[0]
    if s_row.get("user_id"):
        send_notification(s_row["user_id"], "Registrar Clearance Done",
                          "Your clearance has been approved by the Registrar. Awaiting Principal sign-off.",
                          notif_type="success", module="clearance", reference_id=cr_id)

    write_audit_log("registrar_clear", target=str(cr_id))
    flash("Registrar clearance done.", "success")
    return redirect(url_for("clearance.admin_clearances"))


# ── Deputy Principal / Principal: Final Sign-off ──────────────────────────────

@clearance_bp.route("/principal-sign/<int:cr_id>", methods=["POST"])
@login_required
def principal_sign(cr_id):
    user = current_user()
    if user.get("role") not in ("deputy_principal", "super_admin"):
        abort(403)
    db = _db()

    cr = (db.table("clearance_requests").select("*").eq("id", cr_id).limit(1).execute().data or [None])[0]
    if not cr:
        abort(404)

    principal_name = request.form.get("principal_name", "").strip()
    signature      = request.form.get("principal_signature", "").strip()
    stamp          = request.form.get("stamp_applied") == "on"

    if not principal_name:
        flash("Principal name is required.", "error")
        return redirect(url_for("clearance.admin_clearances"))

    from utils import now_eat
    db.table("clearance_requests").update({
        "status":               "completed",
        "principal_signed_by":  user["id"],
        "principal_signed_at":  now_eat().isoformat(),
        "principal_name":       principal_name,
        "principal_signature":  signature,
        "stamp_applied":        stamp,
        "completed_at":         now_eat().isoformat(),
    }).eq("id", cr_id).execute()

    s_row = (db.table("students").select("user_id,full_name").eq("id", cr["student_id"]).limit(1).execute().data or [{}])[0]
    if s_row.get("user_id"):
        send_notification(s_row["user_id"], "Clearance Complete — Download Your Certificate",
                          "Your clearance has been fully approved and signed. You can now download your clearance certificate.",
                          notif_type="success", module="clearance", reference_id=cr_id)

    write_audit_log("principal_sign_clearance", target=str(cr_id))
    flash("Clearance completed and signed.", "success")
    return redirect(url_for("clearance.admin_clearances"))


# ── Admin: All Clearances ─────────────────────────────────────────────────────

@clearance_bp.route("/admin/all")
@login_required
def admin_clearances():
    user = current_user()
    allowed = ("super_admin", "dept_admin", "hod", "finance", "registrar",
               "deputy_principal", "monitoring_evaluation")
    if user.get("role") not in allowed:
        abort(403)
    db = _db()

    status_filter = request.args.get("status", "")
    dept_filter   = request.args.get("dept_id", type=int)
    dept_id       = user.get("dept_id")

    query = (db.table("clearance_requests")
               .select("*, students(full_name,admission_number,classes(name,departments(name)))")
               .order("created_at", desc=True))

    if status_filter:
        query = query.eq("status", status_filter)
    if dept_filter:
        query = query.eq("department_id", dept_filter)
    elif dept_id and user.get("role") in ("dept_admin", "hod"):
        query = query.eq("department_id", dept_id)

    clearances = query.execute().data or []
    depts = db.table("departments").select("*").order("name").execute().data or []

    return render_template("clearance/admin_clearances.html",
                           clearances=clearances, depts=depts,
                           status_filter=status_filter,
                           dept_filter=dept_filter, user=user)
