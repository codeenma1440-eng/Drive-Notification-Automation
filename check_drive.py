import os
import requests

TELEGRAM_TOKEN   = os.environ['TELEGRAM_BOT_TOKEN']
TELEGRAM_CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

msg = (
    "📁 *Drive Notifier*\n"
    "━━━━━━━━━━━━━━━\n"
    "✅ *Test Message*\n\n"
    "If you can see this in your group, notifications are working perfectly\\!\n\n"
    "🚀 Drive monitoring is active\\."
)

r = requests.post(
    f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
    json={
        'chat_id': TELEGRAM_CHAT_ID,
        'text': msg,
        'parse_mode': 'MarkdownV2',
        'disable_web_page_preview': True,
    },
    timeout=15
)

if r.status_code == 200:
    print("SUCCESS! Message sent to group.")
else:
    print(f"FAILED: {r.status_code} — {r.text}")
