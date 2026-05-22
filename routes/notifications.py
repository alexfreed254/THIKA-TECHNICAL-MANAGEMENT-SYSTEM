"""
routes/notifications.py — In-app notification endpoints
"""

from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from auth_utils import login_required, current_user
from notify import get_notifications, get_unread_count, mark_read, mark_all_read

notif_bp = Blueprint("notif", __name__)


@notif_bp.route("/")
@login_required
def all_notifications():
    user = current_user()
    notifs = get_notifications(user["id"], limit=50)
    return render_template("notifications/all.html", notifs=notifs, user=user)


@notif_bp.route("/mark-read/<int:notif_id>", methods=["POST"])
@login_required
def mark_one_read(notif_id):
    user = current_user()
    mark_read(notif_id, user["id"])
    return jsonify(success=True)


@notif_bp.route("/mark-all-read", methods=["POST"])
@login_required
def mark_all():
    user = current_user()
    mark_all_read(user["id"])
    return jsonify(success=True)


@notif_bp.route("/api/unread-count")
@login_required
def unread_count():
    user = current_user()
    count = get_unread_count(user["id"])
    return jsonify(count=count)


@notif_bp.route("/api/recent")
@login_required
def recent():
    user = current_user()
    notifs = get_notifications(user["id"], limit=10)
    return jsonify(notifs)
