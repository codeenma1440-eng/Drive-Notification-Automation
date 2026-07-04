import os
import json
import requests
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ── Load credentials from GitHub Secrets ──────────────────────────
token_data       = json.loads(os.environ['GDRIVE_TOKEN'])
client_data      = json.loads(os.environ['GDRIVE_CLIENT_SECRET'])
TELEGRAM_TOKEN   = os.environ['TELEGRAM_BOT_TOKEN']
TELEGRAM_CHAT_ID = os.environ['TELEGRAM_CHAT_ID']
WATCHED_FOLDER   = '1-7b6q7t6gvkAtE0xAlpCvxmbB4FRoVYD'
PAGE_TOKEN_FILE  = 'page_token.txt'
AUTH_EMAIL       = 'codeenma1440@gmail.com'

# ── Rebuild credentials ────────────────────────────────────────────
creds = Credentials(
    token=token_data.get('token'),
    refresh_token=token_data.get('refresh_token'),
    token_uri=token_data.get('token_uri'),
    client_id=client_data['installed']['client_id'],
    client_secret=client_data['installed']['client_secret'],
    scopes=token_data.get('scopes'),
)
if creds.expired and creds.refresh_token:
    creds.refresh(Request())

service = build('drive', 'v3', credentials=creds)

# ── Folder path helpers ────────────────────────────────────────────
_folder_cache = {}

def get_folder_name(fid):
    if fid in _folder_cache:
        return _folder_cache[fid]
    try:
        f = service.files().get(fileId=fid, fields='name,parents').execute()
        _folder_cache[fid] = f
        return f
    except:
        return None

def build_path(folder_id):
    parts = []
    fid = folder_id
    visited = set()
    while fid and fid not in visited:
        visited.add(fid)
        info = get_folder_name(fid)
        if not info:
            break
        parts.insert(0, info.get('name', ''))
        parents = info.get('parents', [])
        fid = parents[0] if parents else None
    return parts

def shorten_path(parts, levels=3):
    if len(parts) <= levels:
        return ' › '.join(parts)
    return '...› ' + ' › '.join(parts[-levels:])

def is_under_watched(folder_id):
    fid = folder_id
    visited = set()
    while fid and fid not in visited:
        if fid == WATCHED_FOLDER:
            return True
        visited.add(fid)
        info = get_folder_name(fid)
        if not info:
            break
        parents = info.get('parents', [])
        fid = parents[0] if parents else None
    return False

# ── Formatting helpers ─────────────────────────────────────────────
MIME_LABELS = {
    'application/pdf': 'PDF',
    'application/vnd.google-apps.document': 'Google Doc',
    'application/vnd.google-apps.spreadsheet': 'Google Sheet',
    'application/vnd.google-apps.presentation': 'Google Slides',
    'application/vnd.google-apps.folder': 'Folder',
    'image/jpeg': 'JPEG',
    'image/png': 'PNG',
    'video/mp4': 'MP4',
    'audio/mpeg': 'MP3',
    'application/zip': 'ZIP',
    'text/plain': 'TXT',
}

def fmt_type(mime, name):
    if mime in MIME_LABELS:
        return MIME_LABELS[mime]
    if '.' in name:
        return name.rsplit('.', 1)[-1].upper()
    return 'File'

def fmt_size(s):
    if not s:
        return 'N/A'
    s = int(s)
    if s < 1024:       return f"{s} B"
    if s < 1024**2:    return f"{s/1024:.1f} KB"
    if s < 1024**3:    return f"{s/1024**2:.1f} MB"
    return f"{s/1024**3:.1f} GB"

def fmt_time(t):
    if not t:
        return 'Unknown'
    dt = datetime.fromisoformat(t.replace('Z', '+00:00'))
    ist = dt + timedelta(hours=5, minutes=30)   # convert UTC → IST
    return ist.strftime('%d %b %Y, %I:%M %p')

# ── Telegram sender ────────────────────────────────────────────────
def send(msg):
    requests.post(
        f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
        json={
            'chat_id': TELEGRAM_CHAT_ID,
            'text': msg,
            'parse_mode': 'Markdown',
            'disable_web_page_preview': True,
        }
    )

# ── Main: check changes ────────────────────────────────────────────
if os.path.exists(PAGE_TOKEN_FILE):
    with open(PAGE_TOKEN_FILE) as f:
        page_token = f.read().strip()
else:
    r = service.changes().getStartPageToken().execute()
    page_token = r['startPageToken']
    with open(PAGE_TOKEN_FILE, 'w') as f:
        f.write(page_token)
    print("First run — page token initialized. Waiting for next run to detect changes.")
    exit(0)

new_token = page_token
while True:
    resp = service.changes().list(
        pageToken=page_token,
        fields='nextPageToken,newStartPageToken,'
               'changes(changeType,file(id,name,mimeType,size,createdTime,parents,webViewLink))',
        includeRemoved=False,
        spaces='drive',
    ).execute()

    for change in resp.get('changes', []):
        f = change.get('file', {})
        if not f:
            continue
        if f.get('mimeType') == 'application/vnd.google-apps.folder':
            continue

        parents = f.get('parents', [])
        parent_id = parents[0] if parents else None
        if not parent_id or not is_under_watched(parent_id):
            continue

        path_parts = build_path(parent_id)
        short_path = shorten_path(path_parts)
        link = f"{f.get('webViewLink', '#')}?authuser={AUTH_EMAIL}"

        msg = (
            f"📁 *Drive Notifier*\n\n"
            f"*Path:* `{short_path}`\n"
            f"*File:* {f.get('name','Unknown')}\n"
            f"*Type:* {fmt_type(f.get('mimeType',''), f.get('name',''))}\n"
            f"*Size:* {fmt_size(f.get('size'))}\n"
            f"*Uploaded:* {fmt_time(f.get('createdTime'))}\n"
            f"🔗 [Open File]({link})"
        )
        send(msg)
        print(f"Notified: {f.get('name')}")

    if 'newStartPageToken' in resp:
        new_token = resp['newStartPageToken']
        break
    page_token = resp.get('nextPageToken', page_token)

with open(PAGE_TOKEN_FILE, 'w') as f:
    f.write(new_token)
print(f"Token updated: {new_token}")
