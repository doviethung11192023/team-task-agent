# app/database/redis_client.py
import redis
import json
from typing import Any, Optional
from config import config
from app.utils.logger import get_logger, log_event
from app.utils.serialization import serialize_for_json


logger = get_logger("app.database.redis_client")

class RedisClient:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._connect()
        return cls._instance

    def _connect(self):
        """Kết nối Redis sử dụng config từ biến môi trường"""
        try:
            # Ưu tiên dùng REDIS_URL nếu có (dùng cho Railway, Upstash...)
            if hasattr(config, 'REDIS_URL') and config.REDIS_URL:
                self.client = redis.from_url(config.REDIS_URL, decode_responses=True)
            else:
                # Kết nối theo host/port/password (dùng cho Docker local)
                self.client = redis.Redis(
                    host=config.REDIS_HOST,
                    port=config.REDIS_PORT,
                    password=config.REDIS_PASSWORD,
                    decode_responses=True,
                    socket_timeout=5,
                    socket_connect_timeout=5
                )
            
            # Test kết nối
            self.client.ping()
            log_event(logger, "redis.connect.success")
            
        except Exception as e:
            log_event(logger, "redis.connect.failure", level="error", error_type=type(e).__name__, error=str(e))
            self.client = None

    def set(self, key: str, value: Any, expire: int = 3600) -> bool:
        """Lưu dữ liệu vào Redis với thời hạn (expire tính bằng giây)"""
        if not self.client:
            log_event(logger, "redis.set.skip", level="debug", key=key, reason="client_unavailable")
            return False
        try:
            self.client.set(key, json.dumps(serialize_for_json(value), ensure_ascii=False), ex=expire)
            log_event(logger, "redis.set.success", level="debug", key=key, expire=expire)
            return True
        except Exception as e:
            log_event(logger, "redis.set.failure", level="error", key=key, error_type=type(e).__name__, error=str(e))
            return False

    def get(self, key: str) -> Optional[Any]:
        """Lấy dữ liệu từ Redis"""
        if not self.client:
            log_event(logger, "redis.get.skip", level="debug", key=key, reason="client_unavailable")
            return None
        try:
            data = self.client.get(key)
            log_event(logger, "redis.get.hit" if data else "redis.get.miss", level="debug", key=key)
            return json.loads(data) if data else None
        except Exception as e:
            log_event(logger, "redis.get.failure", level="error", key=key, error_type=type(e).__name__, error=str(e))
            return None

    def delete(self, key: str) -> bool:
        """Xóa một key"""
        if not self.client:
            return False
        try:
            self.client.delete(key)
            return True
        except:
            return False

    def clear_cache(self) -> bool:
        """Xóa toàn bộ cache (cẩn thận khi dùng)"""
        if not self.client:
            return False
        try:
            self.client.flushall()
            log_event(logger, "redis.clear_cache.success")
            return True
        except:
            return False

    def delete_pattern(self, pattern: str) -> int:
        """Xóa tất cả keys matching pattern (dùng scan để không block Redis)"""
        if not self.client:
            log_event(logger, "redis.delete_pattern.skip", level="debug", pattern=pattern, reason="client_unavailable")
            return 0
        try:
            cursor = 0
            deleted_count = 0
            while True:
                cursor, keys = self.client.scan(cursor=cursor, match=pattern, count=100)
                if keys:
                    self.client.delete(*keys)
                    deleted_count += len(keys)
                if cursor == 0:
                    break
            if deleted_count > 0:
                log_event(logger, "redis.delete_pattern.success", pattern=pattern, deleted_count=deleted_count)
            return deleted_count
        except Exception as e:
            log_event(logger, "redis.delete_pattern.failure", level="error", pattern=pattern, error_type=type(e).__name__, error=str(e))
            return 0

    def get_reminder_logs(self, limit: int = 20) -> list:
        """Lấy lịch sử reminder logs"""
        if not self.client:
            return []
        try:
            logs = self.client.lrange("reminder_logs", 0, limit - 1)
            return [json.loads(log) for log in logs]
        except:
            return []


# Singleton instance
redis_client = RedisClient()