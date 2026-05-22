"""
routes/main.py — Public landing page.
"""

import os
from flask import Blueprint, render_template, redirect, url_for, jsonify
from auth_utils import current_user, is_authenticated

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    # If already logged in, redirect to the correct dashboard
    if is_authenticated():
        user = current_user()
        role = user.get("role", "")
        if role == "super_admin":
            return redirect(url_for("super_admin.welcome"))
        elif role == "dept_admin":
            return redirect(url_for("dept_admin.welcome"))
        elif role == "trainer":
            return redirect(url_for("lecturer.dashboard"))
        elif role == "student":
            return redirect(url_for("student.dashboard"))
    # Not logged in — go straight to the unified login page
    return redirect(url_for("auth.login"))


@main_bp.route("/debug/env")
def debug_env():
    """Temporary: confirm which keys Render is actually using."""
    import base64, json
    def decode_ref(tok):
        try:
            payload = tok.split('.')[1] if tok else ''
            payload += '=' * (4 - len(payload) % 4)
            return json.loads(base64.b64decode(payload)).get('ref', 'decode-failed')
        except Exception as e:
            return f'error:{e}'

    anon = os.environ.get('SUPABASE_ANON_KEY', '')
    svc  = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
    url  = os.environ.get('SUPABASE_URL', '')

    return jsonify({
        'url':          url,
        'url_ref':      url.split('.')[0].replace('https://','') if url else '',
        'anon_ref':     decode_ref(anon),
        'anon_last10':  anon[-10:] if anon else '',
        'svc_ref':      decode_ref(svc),
        'svc_last10':   svc[-10:] if svc else '',
    })
