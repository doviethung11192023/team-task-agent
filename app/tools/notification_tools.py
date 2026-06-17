# app/tools/notification_tools.py
from app.utils.slack_client import send_slack_notification
from app.database.redis_client import redis_client
from datetime import datetime
import os


class NotificationTools:
    
    @staticmethod
    def send_notification(message: str, channel: str = None) -> bool:
        """Gửi thông báo qua Slack"""
        # During tests, avoid making external network calls to Slack.
        if os.getenv("PYTEST_CURRENT_TEST") is not None or os.getenv("ENV") == "test":
            success = False
        else:
            success = send_slack_notification(message)
        if success:
            # Lưu log vào Redis
            log = {
                "timestamp": datetime.now().isoformat(),
                "message": message,
                "channel": channel or "default"
            }
            redis_client.client.lpush("notification_logs", str(log))
            redis_client.client.ltrim("notification_logs", 0, 99)
        return success

    @classmethod
    def send_risk_alert(cls, project_name: str, risk_title: str, risk_score: int):
        """Gửi alert khi có rủi ro cao"""
        if risk_score >= 7:
            message = f"🚨 **RỦI RO CAO** - Project: {project_name}\n" \
                      f"• {risk_title}\n" \
                      f"• Score: {risk_score}/9"
            return cls.send_notification(message)
        return False

    @staticmethod
    def get_recent_notifications(limit: int = 10):
        """Lấy lịch sử thông báo gần đây"""
        try:
            logs = redis_client.client.lrange("notification_logs", 0, limit - 1)
            return [eval(log) for log in logs]  # convert string dict
        except:
            return []


# Instance
notification_tools = NotificationTools()