"""
routes/exam_booking.py — Examination Booking Module (Module 5)
CDACC-style assessment registration with HOD → Registrar approval workflow.
"""

import io
import base64
from flask import (Blueprint, render_template, request,
                   redirect, url_for, flash, abort, jsonify, session)
from auth_utils import login_required, current_user, write_audit_log
from db import get_service_client
from notify import send_notification, send_to_role

exam_bp = Blueprint("exam", __name__)


def _db():
    return get_service_client()


def _student_row(user_id):
    rows = (_db().table("students").select("*, classes(name, department_id, departments(name))")
            .eq("user_id", user_id).limit(1).execute().data or [])
    return rows[0] if rows else None


def _generate_qr(data: str) -> str:
    """Generate QR code and return as base64 PNG data URI."""
    try:
        import qrcode
        qr = qrcode.QRCode(version=1, box_size=6, border=2)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/png;base64,{b64}"
    except Exception:
        return ""


# ── Student: My Bookings ──────────────────────────────────────────────────────

@exam_bp.route("/my-bookings")
@login_required
def my_bookings():
    user = current_user()
    db = _db()
    student = _student_row(user["id"])
    if not student:
        flash("Student profile not found.", "error")
        return redirect(url_for("student.dashboard"))

    bookings = (db.table("exam_bookings")
                  .select("*, exam_series(name), assessment_centers(name)")
                  .eq("student_id", student["id"])
                  .order("created_at", desc=True)
                  .execute().data or [])
    return render_template("exam/my_bookings.html", student=student, bookings=bookings)


# ── Student: New Booking ──────────────────────────────────────────────────────

@exam_bp.route("/book", methods=["GET", "POST"])
@login_required
def book_exam():
    user = current_user()
    db = _db()
    student = _student_row(user["id"])
    if not student:
        abort(403)

    error = None
    series_list = db.table("exam_series").select("*").eq("is_active", True).order("year", desc=True).execute().data or []
    centers = db.table("assessment_centers").select("*").eq("is_active", True).order("name").execute().data or []
    dept_id = (student.get("classes") or {}).get("department_id")
    units = []
    if dept_id:
        units = db.table("units").select("*").eq("department_id", dept_id).order("code").execute().data or []

    if request.method == "POST":
        series_id = request.form.get("exam_series_id", type=int)
        center_id = request.form.get("assessment_center_id", type=int)
        unit_ids  = request.form.getlist("unit_ids")
        unit_types = {uid: request.form.get(f"unit_type_{uid}", "Core") for uid in unit_ids}
        unit_costs = {uid: float(request.form.get(f"unit_cost_{uid}", 0) or 0) for uid in unit_ids}

        if not series_id or not unit_ids:
            error = "Please select an exam series and at least one unit."
        else:
            total = sum(unit_costs.values())
            # Generate QR data
            qr_data = f"TTTTI-EXAM-{student['admission_number']}-{series_id}"
            qr_img  = _generate_qr(qr_data)

            booking = db.table("exam_bookings").insert({
                "student_id":           student["id"],
                "exam_series_id":       series_id,
                "assessment_center_id": center_id,
                "full_name":            student["full_name"],
                "admission_number":     student["admission_number"],
                "gender":               request.form.get("gender", ""),
                "date_of_birth":        request.form.get("date_of_birth") or None,
                "mobile_number":        request.form.get("mobile_number", ""),
                "email":                student.get("email", ""),
                "national_id":          request.form.get("national_id", ""),
                "course_code":          request.form.get("course_code", ""),
                "course_name":          request.form.get("course_name", ""),
                "module_level":         request.form.get("module_level", ""),
                "pwd_status":           request.form.get("pwd_status", "None"),
                "department_id":        dept_id,
                "status":               "submitted",
                "qr_code":              qr_img,
                "total_cost":           total,
            }).execute().data[0]

            booking_id = booking["id"]

            # Insert booked units
            for uid in unit_ids:
                unit_row = next((u for u in units if str(u["id"]) == uid), {})
                db.table("exam_booking_units").insert({
                    "booking_id": booking_id,
                    "unit_id":    int(uid),
                    "unit_name":  unit_row.get("name", ""),
                    "unit_type":  unit_types.get(uid, "Core"),
                    "unit_cost":  unit_costs.get(uid, 0),
                }).execute()

            # Handle document uploads (URLs from form)
            for doc_type in ["national_id_doc", "kcse_cert", "result_slip", "supporting_doc"]:
                url = request.form.get(f"doc_{doc_type}", "").strip()
                if url:
                    db.table("exam_booking_documents").insert({
                        "booking_id": booking_id,
                        "doc_type":   doc_type,
                        "file_url":   url,
                        "file_name":  doc_type,
                    }).execute()

            # Notify HODs in this department
            send_to_role("hod", "New Exam Booking Submitted",
                         f"{student['full_name']} ({student['admission_number']}) has submitted an exam booking for approval.",
                         notif_type="approval", module="exam", reference_id=booking_id,
                         department_id=dept_id)

            write_audit_log("exam_booking_submit", target=student["admission_number"],
                            detail={"booking_id": booking_id})
            flash("Exam booking submitted successfully. Awaiting HOD approval.", "success")
            return redirect(url_for("exam.my_bookings"))

    return render_template("exam/book_exam.html",
                           student=student, series_list=series_list,
                           centers=centers, units=units, error=error)


# ── Student: View Booking / Exam Card ────────────────────────────────────────

@exam_bp.route("/booking/<int:booking_id>")
@login_required
def view_booking(booking_id):
    user = current_user()
    db = _db()
    student = _student_row(user["id"])

    booking = (db.table("exam_bookings")
                 .select("*, exam_series(name,year), assessment_centers(name,location)")
                 .eq("id", booking_id).limit(1).execute().data or [None])[0]
    if not booking:
        abort(404)

    # Allow student to see own, or admin/hod/registrar
    role = user.get("role", "")
    if role == "student" and (not student or booking["student_id"] != student["id"]):
        abort(403)

    booked_units = (db.table("exam_booking_units")
                      .select("*, units(code)")
                      .eq("booking_id", booking_id)
                      .execute().data or [])
    documents = (db.table("exam_booking_documents")
                   .select("*").eq("booking_id", booking_id).execute().data or [])

    return render_template("exam/view_booking.html",
                           booking=booking, booked_units=booked_units,
                           documents=documents, student=student)


# ── HOD: Approve/Reject Bookings ─────────────────────────────────────────────

@exam_bp.route("/hod-review")
@login_required
def hod_review():
    user = current_user()
    if user.get("role") not in ("hod", "dept_admin", "super_admin", "deputy_principal"):
        abort(403)
    db = _db()
    dept_id = user.get("dept_id")

    query = (db.table("exam_bookings")
               .select("*, exam_series(name), assessment_centers(name), students(full_name,admission_number)")
               .eq("status", "submitted")
               .order("created_at", desc=True))
    if dept_id and user.get("role") not in ("super_admin", "deputy_principal"):
        query = query.eq("department_id", dept_id)
    bookings = query.execute().data or []

    return render_template("exam/hod_review.html", bookings=bookings, user=user)


@exam_bp.route("/hod-action/<int:booking_id>", methods=["POST"])
@login_required
def hod_action(booking_id):
    user = current_user()
    if user.get("role") not in ("hod", "dept_admin", "super_admin", "deputy_principal"):
        abort(403)
    db = _db()
    action  = request.form.get("action")
    comment = request.form.get("comment", "").strip()

    booking = (db.table("exam_bookings").select("*").eq("id", booking_id).limit(1).execute().data or [None])[0]
    if not booking:
        abort(404)

    from utils import now_eat
    if action == "approve":
        db.table("exam_bookings").update({
            "status":           "hod_approved",
            "hod_approved_by":  user["id"],
            "hod_approved_at":  now_eat().isoformat(),
            "hod_comment":      comment,
        }).eq("id", booking_id).execute()
        # Notify registrar
        send_to_role("registrar", "Exam Booking Awaiting Registrar Approval",
                     f"Booking #{booking_id} for {booking['full_name']} has been HOD-approved.",
                     notif_type="approval", module="exam", reference_id=booking_id)
        # Notify student
        student_user = (db.table("students").select("user_id").eq("id", booking["student_id"]).limit(1).execute().data or [{}])[0]
        if student_user.get("user_id"):
            send_notification(student_user["user_id"], "Exam Booking HOD Approved",
                              "Your exam booking has been approved by the HOD and forwarded to the Registrar.",
                              notif_type="success", module="exam", reference_id=booking_id)
        flash("Booking approved and forwarded to Registrar.", "success")
    else:
        db.table("exam_bookings").update({
            "status":           "hod_rejected",
            "hod_approved_by":  user["id"],
            "hod_approved_at":  now_eat().isoformat(),
            "hod_comment":      comment,
        }).eq("id", booking_id).execute()
        student_user = (db.table("students").select("user_id").eq("id", booking["student_id"]).limit(1).execute().data or [{}])[0]
        if student_user.get("user_id"):
            send_notification(student_user["user_id"], "Exam Booking Rejected by HOD",
                              f"Your exam booking was rejected. Reason: {comment}",
                              notif_type="rejection", module="exam", reference_id=booking_id)
        flash("Booking rejected.", "error")

    write_audit_log(f"exam_hod_{action}", target=str(booking_id))
    return redirect(url_for("exam.hod_review"))


# ── Registrar: Approve/Reject ─────────────────────────────────────────────────

@exam_bp.route("/registrar-review")
@login_required
def registrar_review():
    user = current_user()
    if user.get("role") not in ("registrar", "super_admin", "deputy_principal"):
        abort(403)
    db = _db()
    bookings = (db.table("exam_bookings")
                  .select("*, exam_series(name), assessment_centers(name), students(full_name,admission_number)")
                  .eq("status", "hod_approved")
                  .order("created_at", desc=True)
                  .execute().data or [])
    return render_template("exam/registrar_review.html", bookings=bookings, user=user)


@exam_bp.route("/registrar-action/<int:booking_id>", methods=["POST"])
@login_required
def registrar_action(booking_id):
    user = current_user()
    if user.get("role") not in ("registrar", "super_admin", "deputy_principal"):
        abort(403)
    db = _db()
    action  = request.form.get("action")
    comment = request.form.get("comment", "").strip()

    booking = (db.table("exam_bookings").select("*").eq("id", booking_id).limit(1).execute().data or [None])[0]
    if not booking:
        abort(404)

    from utils import now_eat
    new_status = "registrar_approved" if action == "approve" else "registrar_rejected"
    db.table("exam_bookings").update({
        "status":                 new_status,
        "registrar_approved_by":  user["id"],
        "registrar_approved_at":  now_eat().isoformat(),
        "registrar_comment":      comment,
    }).eq("id", booking_id).execute()

    student_user = (db.table("students").select("user_id").eq("id", booking["student_id"]).limit(1).execute().data or [{}])[0]
    if student_user.get("user_id"):
        msg = "Your exam booking has been fully approved. You can now download your exam card." if action == "approve" \
              else f"Your exam booking was rejected by the Registrar. Reason: {comment}"
        send_notification(student_user["user_id"],
                          "Exam Booking " + ("Approved" if action == "approve" else "Rejected"),
                          msg, notif_type="success" if action == "approve" else "rejection",
                          module="exam", reference_id=booking_id)

    write_audit_log(f"exam_registrar_{action}", target=str(booking_id))
    flash(f"Booking {action}d.", "success" if action == "approve" else "error")
    return redirect(url_for("exam.registrar_review"))


# ── Exam Card PDF ─────────────────────────────────────────────────────────────

@exam_bp.route("/exam-card/<int:booking_id>")
@login_required
def exam_card(booking_id):
    user = current_user()
    db = _db()
    student = _student_row(user["id"])

    booking = (db.table("exam_bookings")
                 .select("*, exam_series(name,year,start_date,end_date), assessment_centers(name,location)")
                 .eq("id", booking_id).limit(1).execute().data or [None])[0]
    if not booking:
        abort(404)

    role = user.get("role", "")
    if role == "student" and (not student or booking["student_id"] != student["id"]):
        abort(403)
    if booking["status"] not in ("registrar_approved", "confirmed"):
        if role == "student":
            flash("Exam card is only available after Registrar approval.", "error")
            return redirect(url_for("exam.my_bookings"))

    booked_units = (db.table("exam_booking_units")
                      .select("*, units(code)")
                      .eq("booking_id", booking_id)
                      .execute().data or [])

    from utils import now_eat
    return render_template("exam/exam_card_pdf.html",
                           booking=booking, booked_units=booked_units,
                           generated=now_eat().strftime("%d %b %Y %H:%M"))


# ── Admin: Manage Series & Centers ───────────────────────────────────────────

@exam_bp.route("/admin/series", methods=["GET", "POST"])
@login_required
def manage_series():
    user = current_user()
    if user.get("role") not in ("super_admin", "registrar", "deputy_principal"):
        abort(403)
    db = _db()
    error = None

    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            name = request.form.get("name", "").strip()
            year = request.form.get("year", type=int)
            start = request.form.get("start_date") or None
            end   = request.form.get("end_date") or None
            if not name or not year:
                error = "Name and year are required."
            else:
                db.table("exam_series").insert({"name": name, "year": year,
                                                "start_date": start, "end_date": end}).execute()
                flash("Exam series created.", "success")
                return redirect(url_for("exam.manage_series"))
        elif action == "delete":
            sid = request.form.get("series_id", type=int)
            db.table("exam_series").delete().eq("id", sid).execute()
            flash("Series deleted.", "success")
            return redirect(url_for("exam.manage_series"))

    series = db.table("exam_series").select("*").order("year", desc=True).execute().data or []
    return render_template("exam/manage_series.html", series=series, error=error, user=user)


@exam_bp.route("/admin/centers", methods=["GET", "POST"])
@login_required
def manage_centers():
    user = current_user()
    if user.get("role") not in ("super_admin", "registrar", "deputy_principal"):
        abort(403)
    db = _db()
    error = None

    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            name     = request.form.get("name", "").strip()
            location = request.form.get("location", "").strip()
            capacity = request.form.get("capacity", 0, type=int)
            if not name:
                error = "Center name is required."
            else:
                db.table("assessment_centers").insert({
                    "name": name, "location": location, "capacity": capacity
                }).execute()
                flash("Assessment center added.", "success")
                return redirect(url_for("exam.manage_centers"))
        elif action == "delete":
            cid = request.form.get("center_id", type=int)
            db.table("assessment_centers").delete().eq("id", cid).execute()
            flash("Center deleted.", "success")
            return redirect(url_for("exam.manage_centers"))

    centers = db.table("assessment_centers").select("*").order("name").execute().data or []
    return render_template("exam/manage_centers.html", centers=centers, error=error, user=user)


# ── All Bookings (Admin view) ─────────────────────────────────────────────────

@exam_bp.route("/admin/all-bookings")
@login_required
def all_bookings():
    user = current_user()
    if user.get("role") not in ("super_admin", "registrar", "deputy_principal", "hod", "dept_admin"):
        abort(403)
    db = _db()
    status_filter = request.args.get("status", "")
    dept_filter   = request.args.get("dept_id", type=int)

    query = (db.table("exam_bookings")
               .select("*, exam_series(name), assessment_centers(name), students(full_name,admission_number)")
               .order("created_at", desc=True).limit(200))
    if status_filter:
        query = query.eq("status", status_filter)
    if dept_filter:
        query = query.eq("department_id", dept_filter)
    elif user.get("role") in ("hod", "dept_admin") and user.get("dept_id"):
        query = query.eq("department_id", user["dept_id"])

    bookings = query.execute().data or []
    depts = db.table("departments").select("*").order("name").execute().data or []
    return render_template("exam/all_bookings.html",
                           bookings=bookings, depts=depts,
                           status_filter=status_filter, dept_filter=dept_filter, user=user)
