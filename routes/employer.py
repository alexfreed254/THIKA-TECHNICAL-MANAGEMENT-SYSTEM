"""
routes/employer.py — Employer Portal Module

This module handles:
- Employer read-only access to trainee portfolios
- Trainee search and viewing
- Recommendation submission
- All views are read-only (no POST/PUT/DELETE for data modification)
"""

from flask import Blueprint, render_template, request, redirect, url_for, session, abort
from auth_utils import login_required, current_user, write_audit_log
from db import get_service_client

employer_bp = Blueprint("employer", __name__)


def _svc():
    return get_service_client()


@employer_bp.route("/dashboard")
@login_required
def dashboard():
    """Employer dashboard - view trainees and portfolios"""
    user = current_user()
    if user.get("role") != "employer":
        abort(403)
    
    db = _svc()
    
    # Get employer user record
    employer = db.table("employer_users").select("*").eq("user_id", user["id"]).limit(1).execute().data
    if not employer:
        return render_template("employer/dashboard.html", error="Employer record not found.")
    
    employer = employer[0]
    
    # Get all trainees for viewing
    trainees = db.table("students") \
        .select("*, classes(name, department_id, departments(name))") \
        .order("full_name") \
        .execute().data or []
    
    # Get recommendations made by this employer
    recommendations = db.table("employer_recommendations") \
        .select("*, students(full_name, admission_number)") \
        .eq("employer_id", employer.get("employer_id")) \
        .order("created_at", desc=True) \
        .execute().data or []
    
    return render_template("employer/dashboard.html",
                           trainees=trainees,
                           recommendations=recommendations,
                           employer=employer)


@employer_bp.route("/trainee/<int:trainee_id>")
@login_required
def view_trainee(trainee_id):
    """View trainee portfolio (read-only)"""
    user = current_user()
    if user.get("role") != "employer":
        abort(403)
    
    db = _svc()
    
    # Get trainee details
    trainee = db.table("students") \
        .select("*, classes(name, department_id, departments(name))") \
        .eq("id", trainee_id) \
        .limit(1) \
        .execute().data
    
    if not trainee:
        abort(404)
    
    trainee = trainee[0]
    
    # Get trainee's assessments
    assessments = db.table("assessments") \
        .select("*, units(code, name), trainers(name)") \
        .eq("trainee_id", trainee_id) \
        .eq("status", "approved") \
        .order("submitted_at", desc=True) \
        .execute().data or []
    
    # Get evidence for approved assessments
    assessment_ids = [a["id"] for a in assessments]
    evidence = {}
    if assessment_ids:
        evidence_data = db.table("evidence") \
            .select("*") \
            .in_("assessment_id", assessment_ids) \
            .execute().data or []
        for e in evidence_data:
            if e["assessment_id"] not in evidence:
                evidence[e["assessment_id"]] = []
            evidence[e["assessment_id"]].append(e)
    
    # Get existing recommendation from this employer
    employer = db.table("employer_users").select("employer_id").eq("user_id", user["id"]).limit(1).execute().data
    existing_recommendation = None
    if employer:
        existing_recommendation = db.table("employer_recommendations") \
            .select("*") \
            .eq("trainee_id", trainee_id) \
            .eq("employer_id", employer[0]["employer_id"]) \
            .limit(1) \
            .execute().data or []
        if existing_recommendation:
            existing_recommendation = existing_recommendation[0]
    
    # Log portfolio view
    write_audit_log("view_trainee_portfolio", target=str(trainee_id))
    
    return render_template("employer/view_trainee.html",
                           trainee=trainee,
                           assessments=assessments,
                           evidence=evidence,
                           existing_recommendation=existing_recommendation)


@employer_bp.route("/recommend/<int:trainee_id>", methods=["POST"])
@login_required
def submit_recommendation(trainee_id):
    """Submit recommendation for trainee (POST allowed for recommendations)"""
    user = current_user()
    if user.get("role") != "employer":
        abort(403)
    
    db = _svc()
    
    # Get employer record
    employer = db.table("employer_users").select("employer_id").eq("user_id", user["id"]).limit(1).execute().data
    if not employer:
        return {"error": "Employer record not found"}, 400
    
    employer_id = employer[0]["employer_id"]
    
    content = request.form.get("content", "").strip()
    rating = request.form.get("rating", type=int)
    
    if not content:
        return {"error": "Recommendation content is required"}, 400
    
    if not rating or rating < 1 or rating > 5:
        return {"error": "Rating must be between 1 and 5"}, 400
    
    try:
        # Check if recommendation already exists
        existing = db.table("employer_recommendations") \
            .select("*") \
            .eq("trainee_id", trainee_id) \
            .eq("employer_id", employer_id) \
            .limit(1) \
            .execute().data
        
        if existing:
            # Update existing recommendation
            db.table("employer_recommendations").update({
                "content": content,
                "rating": rating,
            }).eq("id", existing[0]["id"]).execute()
        else:
            # Create new recommendation
            db.table("employer_recommendations").insert({
                "trainee_id": trainee_id,
                "employer_id": employer_id,
                "content": content,
                "rating": rating,
            }).execute()
        
        write_audit_log("submit_recommendation", target=str(trainee_id))
        
        return {"success": True}
    
    except Exception as exc:
        return {"error": str(exc)}, 500


@employer_bp.route("/search")
@login_required
def search_trainees():
    """Search trainees by name or admission number"""
    user = current_user()
    if user.get("role") != "employer":
        abort(403)
    
    db = _svc()
    
    query = request.args.get("q", "").strip()
    
    if not query:
        return redirect(url_for("employer.dashboard"))
    
    # Search trainees
    trainees = db.table("students") \
        .select("*, classes(name, department_id, departments(name))") \
        .or_(f"full_name.ilike.%{query}%,admission_number.ilike.%{query}%") \
        .order("full_name") \
        .execute().data or []
    
    return render_template("employer/search_results.html",
                           trainees=trainees,
                           query=query)
