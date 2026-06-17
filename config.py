import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # LLM
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

    # Database - PostgreSQL Direct Connection
    DB_HOST = os.getenv("DB_HOST")
    DB_PORT = int(os.getenv("DB_PORT", 6543))
    DB_NAME = os.getenv("DB_NAME")
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_SSLMODE = os.getenv("DB_SSLMODE", "require")

    # # Supabase (giữ lại để linh hoạt)
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")

    # Slack
    SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
    SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID")

    # Redis
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
    REDIS_URL = os.getenv("REDIS_URL")

    # LangSmith
    LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")
    LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", "false").lower() == "true"
    LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "ai-team-task-agent")

    # App
    ENV = os.getenv("ENV", "development")
    DEBUG = os.getenv("DEBUG", "True").lower() == "true"


config = Config()
# cách sử dụng ở trong các module khác
# import psycopg2
# from config import config

# def get_db_connection():
#     return psycopg2.connect(
#         host=config.DB_HOST,
#         port=config.DB_PORT,
#         database=config.DB_NAME,
#         user=config.DB_USER,
#         password=config.DB_PASSWORD,
#         sslmode=config.DB_SSLMODE
#     )