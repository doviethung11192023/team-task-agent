# app/utils/helpers.py
from app.database.supabase_client import db
from datetime import datetime
from app.utils.logger import get_logger, log_event


logger = get_logger("app.utils.helpers")

def log_audit(action: str, entity_type: str, entity_id: str, performed_by: str, details: dict):
    """Ghi log hành động vào Audit Log"""
    try:
        log_event(
            logger,
            "audit.write.enter",
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            performed_by=performed_by,
        )
        db.log_audit(action, entity_type, entity_id, performed_by, details or {})
        log_event(
            logger,
            "audit.write.exit",
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            performed_by=performed_by,
        )
    except Exception as e:
        log_event(
            logger,
            "audit.write.exception",
            level="error",
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            performed_by=performed_by,
            error_type=type(e).__name__,
            error=str(e),
        )

def build_graph_config(thread_id: str):
    return {
        "configurable": {
            "thread_id": thread_id
        }
    }
def format_response(message: str, **kwargs):
    """Format response chung"""
    return {
        "message": message,
        "timestamp": datetime.now().isoformat(),
        **kwargs
    }