from slack_sdk import WebClient
from dotenv import load_dotenv
import os

load_dotenv()

client = WebClient(
    token=os.getenv("SLACK_BOT_TOKEN")
)

response = client.chat_postMessage(
    channel=os.getenv("SLACK_CHANNEL_ID"),
    text="🚀 Slack bot connected successfully!"
)

print(response["ok"])