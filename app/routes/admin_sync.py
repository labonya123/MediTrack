from flask import Blueprint, render_template, jsonify, flash, redirect, url_for, request, session
from functools import wraps
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from app.services import sync_service, auth_service
from app.database.local_db import execute_query

admin_sync_bp = Blueprint('admin_sync', __name__, url_prefix='/admin/sync')


def admin_required(f):
    """Decorator: Ensure user is logged in as admin"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash('Access denied. Admin privileges required.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


@admin_sync_bp.route('/dashboard')
@admin_required
def dashboard():
    """
    Sync monitoring dashboard page.
    Shows real-time status, pending records, and sync history.
    """
    sync_status = sync_service.get_sync_status()
    
    sync_history = execute_query(
        """SELECT * FROM audit_log 
           WHERE action IN ('SYNC_SUCCESS', 'SYNC_FAILURE', 'AUTO_SYNC', 'MANUAL_SYNC_TRIGGERED')
           ORDER BY timestamp DESC LIMIT 50""",
        fetch=True
    ) or []
    
    pending_details = []
    for table, count in sync_status.get('pending_by_table', {}).items():
        pending_details.append({
            'table': table,
            'count': count,
            'percentage': round((count / sync_status['pending_count']) * 100, 1) if sync_status['pending_count'] > 0 else 0
        })
    
    pending_details.sort(key=lambda x: x['count'], reverse=True)
    
    from config import USE_CLOUD, SUPABASE_URL
    cloud_config = {
        'enabled': USE_CLOUD,
        'url': SUPABASE_URL if SUPABASE_URL else 'Not configured',
        'has_credentials': bool(SUPABASE_URL and sync_service.get_supabase_client())
    }
    
    return render_template(
        'admin/sync_dashboard.html',
        sync_status=sync_status,
        pending_details=pending_details,
        sync_history=sync_history,
        cloud_config=cloud_config
    )


@admin_sync_bp.route('/api/status')
@admin_required
def api_status():
    """
    JSON endpoint for real-time sync status polling.
    Used by JavaScript to update dashboard every 10 seconds.
    """
    status = sync_service.get_sync_status()
    return jsonify(status)


@admin_sync_bp.route('/history')
@admin_required
def sync_history():
    """
    Detailed sync history page with filtering and pagination.
    """
    page = request.args.get('page', 1, type=int)
    per_page = 100
    offset = (page - 1) * per_page
    
    history = execute_query(
        """SELECT al.*, u.username 
           FROM audit_log al
           LEFT JOIN users u ON al.user_id = u.user_id
           WHERE al.action IN ('SYNC_SUCCESS', 'SYNC_FAILURE', 'AUTO_SYNC', 'MANUAL_SYNC_TRIGGERED')
           ORDER BY al.timestamp DESC
           LIMIT ? OFFSET ?""",
        (per_page, offset),
        fetch=True
    ) or []
   
    total = execute_query(
        """SELECT COUNT(*) as cnt FROM audit_log 
           WHERE action IN ('SYNC_SUCCESS', 'SYNC_FAILURE', 'AUTO_SYNC', 'MANUAL_SYNC_TRIGGERED')""",
        fetchone=True
    )
    total_count = total['cnt'] if total else 0
    
    total_pages = (total_count + per_page - 1) // per_page
    
    return render_template(
        'admin/sync_history.html',
        history=history,
        page=page,
        total_pages=total_pages,
        total_count=total_count
    )


@admin_sync_bp.route('/reset-status', methods=['POST'])
@admin_required
def reset_sync_status():
    """
    TESTING ONLY: Resets all records to sync_status = 'pending'.
    Useful for testing sync functionality.
    Should be removed or protected in production.
    """
    user_id = session.get('user_id')
    
    from config import DEBUG
    if not DEBUG:
        flash('This function is disabled in production.', 'danger')
        return redirect(url_for('admin_sync.dashboard'))
    
    sync_service.reset_sync_status()
    
    auth_service.log_audit(
        user_id=user_id,
        user_role='admin',
        action='SYNC_STATUS_RESET',
        target_patient_id=None,
        details='Admin reset all records to pending (TESTING)',
        ip_address=request.remote_addr
    )
    
    flash('⚠️ All records reset to pending status (testing mode)', 'warning')
    return redirect(url_for('admin_sync.dashboard'))