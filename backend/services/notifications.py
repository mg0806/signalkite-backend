import httpx

from config import settings


def configured_channels() -> dict[str, bool]:
    return {
        "browser": True,
        "push": bool(settings.fcm_server_key),
        "whatsapp": bool(settings.whatsapp_webhook_url),
        "telegram": bool(settings.telegram_bot_token and settings.telegram_chat_id),
        "email": bool(settings.email_webhook_url and settings.alert_email_to),
        "sms": bool((settings.sms_webhook_url or settings.textlocal_api_key) and settings.alert_phone_to),
    }


def send_notification(channels: list[str], title: str, message: str) -> list[dict]:
    status = configured_channels()
    results = []
    for channel in channels:
        channel = channel.lower()
        if not status.get(channel, False):
            results.append({"channel": channel, "status": "not_configured"})
            continue
        try:
            if channel == "telegram":
                url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
                response = httpx.post(url, json={"chat_id": settings.telegram_chat_id, "text": f"{title}\n{message}"}, timeout=10)
                response.raise_for_status()
            elif channel == "sms" and settings.textlocal_api_key:
                response = httpx.post(
                    "https://api.textlocal.in/send/",
                    data={
                        "apikey": settings.textlocal_api_key,
                        "numbers": settings.alert_phone_to,
                        "sender": settings.textlocal_sender,
                        "message": message,
                    },
                    timeout=10,
                )
                response.raise_for_status()
            elif channel in {"whatsapp", "email", "sms"}:
                url = getattr(settings, f"{channel}_webhook_url")
                payload = {"title": title, "message": message}
                if channel == "email":
                    payload["to"] = settings.alert_email_to
                if channel == "sms":
                    payload["to"] = settings.alert_phone_to
                response = httpx.post(url, json=payload, timeout=10)
                response.raise_for_status()
            results.append({"channel": channel, "status": "queued"})
        except Exception as exc:
            results.append({"channel": channel, "status": "failed", "error": str(exc)})
    return results
