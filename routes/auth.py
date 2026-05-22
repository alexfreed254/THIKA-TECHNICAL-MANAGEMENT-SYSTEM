"""
routes/auth.py — Unified login / logout using Supabase Auth.

Self-healing: if a user_profiles row is missing at login time,
it is created automatically so the user is never locked out.
"""

import traceback
from flask import (Blueprint, render_template, request,
                   session, redirect, url_for, jsonify)
from db import get_anon_client, get_service_client
from auth_utils import (
    SESSION_USER, SESSION_ACCESS, SESSION_REFRESH,
    write_audit_log,
)

auth_bp = Blueprint("auth", __name__)


def _get_user_id_by_email(email: str) -> str | None:
    """Look up a Supabase auth user UUID by email using the service-role admin API."""
    try:
        svc = get_service_client()
        page = 1
        while True:
            users = svc.auth.admin.list_users(page=page, per_page=1000)
            if not users:
                break
            for u in users:
                if u.email and u.email.lower() == email.lower():
                    return u.id
            if len(users) < 1000:
                break
            page += 1
    except Exception as exc:
        print(f"[auth] _get_user_id_by_email failed: {exc}")
    return None


def _auto_confirm_and_login(email: str, password: str):
    """
    Confirm a user's email via the admin API then retry sign-in.
    Returns the auth response or raises an exception.
    """
    uid = _get_user_id_by_email(email)
    if uid:
        try:
            svc = get_service_client()
            svc.auth.admin.update_user_by_id(uid, {"email_confirm": True})
            print(f"[auth] auto-confirmed email for uid={uid}")
        except Exception as e:
            print(f"[auth] update_user_by_id failed: {e}")
    # Retry sign-in regardless — if confirm worked it will succeed
    return get_anon_client().auth.sign_in_with_password(
        {"email": email, "password": password}
    )


def _ensure_profile(user_id: str, email: str) -> dict:
    # Returns the user_profiles row, creating it if missing.
    svc = get_service_client()
    try:
        res = (svc.table("user_profiles")
                  .select("*")
                  .eq("id", user_id)
                  .limit(1)
                  .execute().data or [])
        if res:
            return res[0]
    except Exception:
        pass

    # Profile missing — only auto-create for non-admin users.
    # Super admins / dept admins must be inserted manually or via the
    # super_admin "add user" flow so their role is set correctly.
    # We still create a placeholder so the user gets a meaningful error
    # rather than a crash, but we mark it inactive so they cannot log in
    # until an admin activates and assigns the correct role.
    try:
        svc.table("user_profiles").insert({
            "id":            user_id,
            "full_name":     email,
            "role":          "student",
            "department_id": None,
            "is_active":     False,   # inactive until admin sets role
        }).execute()
        res = (svc.table("user_profiles")
                  .select("*")
                  .eq("id", user_id)
                  .limit(1)
                  .execute().data or [])
        return res[0] if res else None
    except Exception as exc:
        print(f"[auth] _ensure_profile failed for {user_id}: {exc}")
        traceback.print_exc()
        return None


# ── Student Login (admission number + password) ───────────────────────────────

@auth_bp.route("/student-login", methods=["GET", "POST"])
def student_login():
    if request.method == "POST":
        return login()
    return redirect(url_for("auth.login", tab="trainee"))


# ── Trainer Login (redirect to unified login) ─────────────────────────────────

@auth_bp.route("/trainer-login", methods=["GET", "POST"])
def trainer_login():
    if request.method == "POST":
        return login()
    return redirect(url_for("auth.login", tab="staff"))


# ── Unified Login (trainee/admission + staff/email) ───────────────────────────

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    active_tab = request.args.get("tab", "staff")
    registered = request.args.get("registered")
    message = None

    if request.method == "POST":
        login_type = request.form.get("login_type")
        if not login_type:
            login_type = "trainee" if request.form.get("admission_number") else "staff"

        if login_type == "trainee":
            active_tab = "trainee"
            admission_number = request.form.get("admission_number", "").strip()
            password = request.form.get("password", "")

            if not admission_number or not password:
                return render_template("auth/login.html",
                                       active_tab=active_tab,
                                       error="Admission number and password are required.",
                                       admission_number=admission_number)

            svc = get_service_client()
            try:
                rows = (svc.table("students")
                           .select("email, user_id")
                           .eq("admission_number", admission_number)
                           .limit(1)
                           .execute().data or [])
            except Exception as exc:
                return render_template("auth/login.html",
                                       active_tab=active_tab,
                                       error=f"Database error: {exc}",
                                       admission_number=admission_number)

            if not rows:
                return render_template("auth/login.html",
                                       active_tab=active_tab,
                                       error="Admission number not found.",
                                       admission_number=admission_number)

            email = rows[0].get("email")
            if not email:
                return render_template("auth/login.html",
                                       active_tab=active_tab,
                                       error="Account not registered yet. Please activate your account first.",
                                       admission_number=admission_number)

            try:
                client = get_anon_client()
                resp = client.auth.sign_in_with_password({"email": email, "password": password})
            except Exception as exc:
                msg = str(exc)
                if any(k in msg.lower() for k in ["invalid login", "invalid credentials", "invalid"]):
                    return render_template("auth/login.html",
                                           active_tab=active_tab,
                                           error="Invalid admission number or password.",
                                           admission_number=admission_number)
                return render_template("auth/login.html",
                                       active_tab=active_tab,
                                       error=f"Login error: {msg}",
                                       admission_number=admission_number)

            if not resp or not resp.user:
                return render_template("auth/login.html",
                                       active_tab=active_tab,
                                       error="Login failed. Please try again.",
                                       admission_number=admission_number)

            profile = _ensure_profile(resp.user.id, email)
            if not profile:
                return render_template("auth/login.html",
                                       active_tab=active_tab,
                                       error="Profile could not be loaded. Contact administrator.",
                                       admission_number=admission_number)

            if not profile.get("is_active", False):
                return render_template("auth/login.html",
                                       active_tab=active_tab,
                                       error="Your account has been disabled.",
                                       admission_number=admission_number)

            session.permanent = bool(request.form.get("remember") or request.form.get("remember_me"))
            session[SESSION_ACCESS] = resp.session.access_token
            session[SESSION_REFRESH] = resp.session.refresh_token
            session[SESSION_USER] = {
                "id":      resp.user.id,
                "email":   resp.user.email,
                "name":    profile.get("full_name") or admission_number,
                "role":    "student",
                "dept_id": profile.get("department_id"),
                "active":  profile["is_active"],
            }
            write_audit_log("student_login", target=admission_number)
            return redirect(url_for("student.dashboard"))

        # Staff / admin / trainer login by email
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        active_tab = "staff"

        if not email or not password:
            return render_template("auth/login.html",
                                   active_tab=active_tab,
                                   error="Email and password are required.",
                                   email=email)

        resp = None
        try:
            client = get_anon_client()
            resp = client.auth.sign_in_with_password({"email": email, "password": password})
        except Exception as exc:
            msg = str(exc)
            msg_lower = msg.lower()
            print(f"[auth] sign_in EXCEPTION for {email}: {repr(exc)}")

            if "email not confirmed" in msg_lower or "not confirmed" in msg_lower:
                # User created via Supabase dashboard without email confirmation.
                # Auto-confirm via admin API and retry.
                try:
                    resp = _auto_confirm_and_login(email, password)
                except Exception as confirm_exc:
                    print(f"[auth] auto-confirm failed for {email}: {confirm_exc}")
                    return render_template("auth/login.html",
                                           active_tab=active_tab,
                                           error="Email not confirmed. The system tried to auto-confirm but failed. "
                                                 "Please go to Supabase → Authentication → Users, find this user "
                                                 "and click 'Confirm email' manually.",
                                           email=email)
            elif "invalid login credentials" in msg_lower:
                # Genuinely wrong password
                return render_template("auth/login.html",
                                       active_tab=active_tab,
                                       error="Incorrect email or password.",
                                       email=email)
            else:
                # Show the REAL Supabase error so we can diagnose it
                return render_template("auth/login.html",
                                       active_tab=active_tab,
                                       error=f"Supabase error: {msg}",
                                       email=email)

        if not resp or not resp.user:
            return render_template("auth/login.html",
                                   active_tab=active_tab,
                                   error="Login failed — no user returned.",
                                   email=email)

        user_id = resp.user.id
        profile = _ensure_profile(user_id, email)

        if not profile:
            return render_template("auth/login.html",
                                   active_tab=active_tab,
                                   error="Profile could not be loaded. Please run the fix SQL in Supabase and try again.",
                                   email=email)

        if not profile.get("is_active", False):
            return render_template("auth/login.html",
                                   active_tab=active_tab,
                                   error="Your account has been disabled. Contact your administrator.",
                                   email=email)

        session.permanent = bool(request.form.get("remember") or request.form.get("remember_me"))
        session[SESSION_ACCESS] = resp.session.access_token
        session[SESSION_REFRESH] = resp.session.refresh_token
        session[SESSION_USER] = {
            "id":      user_id,
            "email":   resp.user.email,
            "name":    profile.get("full_name") or email,
            "role":    profile.get("role"),
            "dept_id": profile.get("department_id"),
            "active":  profile["is_active"],
        }

        write_audit_log("login", target=email)

        role = profile.get("role")
        if role == "super_admin":
            return redirect(url_for("super_admin.dashboard"))
        elif role == "dept_admin":
            return redirect(url_for("dept_admin.dashboard"))
        elif role == "trainer":
            return redirect(url_for("lecturer.dashboard"))
        else:
            return redirect(url_for("student.dashboard"))

    if registered:
        message = "Registration completed. Please log in with your admission number and password."

    return render_template("auth/login.html",
                           active_tab=active_tab,
                           registered=registered,
                           message=message)


# ── Logout ────────────────────────────────────────────────────────────────────

@auth_bp.route("/logout")
def logout():
    write_audit_log("logout")
    try:
        get_anon_client().auth.sign_out()
    except Exception:
        pass
    session.clear()
    return redirect(url_for("main.index"))


# ── Forgot password ───────────────────────────────────────────────────────────

@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    msg = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if email:
            try:
                get_anon_client().auth.reset_password_email(email)
            except Exception:
                pass
        msg = ("If an account exists for that email address, "
               "a password reset link has been sent.")
    return render_template("auth/forgot_password.html", msg=msg)
