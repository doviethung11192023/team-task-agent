from config import config
import slack_sdk


def send_slack_notification(message: str) -> bool:
    """Gửi thông báo qua Slack."""
    try:
        if not config.SLACK_BOT_TOKEN or not config.SLACK_CHANNEL_ID:
            return False

        client = slack_sdk.WebClient(token=config.SLACK_BOT_TOKEN)
        client.chat_postMessage(
            channel=config.SLACK_CHANNEL_ID,
            text=message
        )
        return True
    except Exception as e:
        print(f"Slack notification error: {e}")
        return False