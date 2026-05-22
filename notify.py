"""
notify.py — In-app notification helper.
Sends notifications to users via the notifications table.
Never raises — notification failures must not break main flows.
"""

from db import get_service_client


def send_notification(
    recipient_id: str,
    title: str,
    message: str,
    notif_type: str = "info",
    module: str = None,
    reference_id: int = None,
    sender_id: str = None,
):
    """
    Insert a notification row for a user.
    notif_type: 'info' | 'success' | 'warning' | 'error' | 'approval' | 'rejection'
    """
    try:
        db = get_service_client()
        db.table("notifications").insert({
            "recipient_id": recipient_id,
            "sender_id":    sender_id,
            "title":        title,
            "message":      message,
            "type":         notif_type,
            "module":       module,
            "reference_id": reference_id,
        }).execute()
    except Exception as exc:
        print(f"[notify] send_notification failed: {exc}")


def send_to_role(
    role: str,
    title: str,
    message: str,
    notif_type: str = "info",
    module: str = None,
    reference_id: int = None,
    department_id: int = None,
    sender_id: str = None,
):
    """Send a notification to all active users with a given role (optionally filtered by dept)."""
    try:
        db = get_service_client()
        query = db.table("user_profiles").select("id").eq("role", role).eq("is_active", True)
        if department_id:
            query = query.eq("department_id", department_id)
        users = query.execute().data or []
        for u in users:
            send_notification(
                recipient_id=u["id"],
                title=title,
                message=message,
                notif_type=notif_type,
                module=module,
                reference_id=reference_id,
                sender_id=sender_id,
            )
    except Exception as exc:
        print(f"[notify] send_to_role failed: {exc}")


def get_unread_count(user_id: str) -> int:
    """Return unread notification count for a user."""
    try:
        db = get_service_client()
        result = (db.table("notifications")
                    .select("id", count="exact")
                    .eq("recipient_id", user_id)
                    .eq("is_read", False)
                    .execute())
        return result.count or 0
    except Exception:
        return 0


def get_notifications(user_id: str, limit: int = 20) -> list:
    """Return recent notifications for a user."""
    try:
        db = get_service_client()
        return (db.table("notifications")
                  .select("*")
                  .eq("recipient_id", user_id)
                  .order("created_at", desc=True)
                  .limit(limit)
                  .execute().data or [])
    except Exception:
        return []


def mark_read(notification_id: int, user_id: str):
    """Mark a notification as read."""
    try:
        from utils import now_eat
        db = get_service_client()
        db.table("notifications").update({
            "is_read": True,
            "read_at": now_eat().isoformat(),
        }).eq("id", notification_id).eq("recipient_id", user_id).execute()
    except Exception:
        pass


def mark_all_read(user_id: str):
    """Mark all notifications as read for a user."""
    try:
        from utils import now_eat
        db = get_service_client()
        db.table("notifications").update({
            "is_read": True,
            "read_at": now_eat().isoformat(),
        }).eq("recipient_id", user_id).eq("is_read", False).execute()
    except Exception:
        pass
