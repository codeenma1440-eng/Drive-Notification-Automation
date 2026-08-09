import os
import json
import requests
from datetime import datetime, timedelta, timezone
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ═══════════════════════════════════════════════════════════════════
# CONFIGURATION — Only edit this section
# ═══════════════════════════════════════════════════════════════════

WATCHED_FOLDERS = [
    '1-7b6q7t6gvkAtE0xAlpCvxmbB4FRoVYD',  # Drive 1: 3rdYr CSC
    '1NhK3dPc_y7HKGpOiTbQod-KMkaNSBo3Z',  # Drive 2: Repati Kosam
    '1v4qVS-_WBi1B-Qm2bj-SasZNfuBfYq1j',  # Drive 3
    '',  # Drive 4: Add folder ID here when needed
    '',  # Drive 5: Add folder ID here when needed
]

SKIP_FOLDERS = {
    '1-pKjtGbx9mnEeRkVqHovCXpGaSbhi9IK',  # 1stYr folder
    '1vPMXSB0_Vvy1JGCFij25gq1kBtx00gaZ',  # 2ndYr folder
}

AUTH_EMAIL             = 'codeenma1440@gmail.com'
PAGE_TOKEN_FILE        = 'page_token.txt'
NEW_FILE_THRESHOLD_SEC = 60

# ═══════════════════════════════════════════════════════════════════
# DO NOT EDIT BELOW THIS LINE
# ═══════════════════════════════════════════════════════════════════

token_data       = json.loads(os.environ['GDRIVE_TOKEN'])
client_data      = json.loads(os.environ['GDRIVE_CLIENT_SECRET'])
TELEGRAM_TOKEN   = os.environ['TELEGRAM_BOT_TOKEN']
TELEGRAM_CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

ACTIVE_FOLDERS = [f.strip() for f in WATCHED_FOLDERS if f.strip()]

if not ACTIVE_FOLDERS:
    print("No drives configured.")
    exit(0)

print(f"Watching {len(ACTIVE_FOLDERS)} drive(s).")

# ── Auth ───────────────────────────────────────────────────────────
creds = Credentials(
    token=token_data.get('token'),
    refresh_token=token_data.get('refresh_token'),
    token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
    client_id=client_data['installed']['client_id'],
    client_secret=client_data['installed']['client_secret'],
    scopes=token_data.get('scopes'),
)
if creds.expired and creds.refresh_token:
    creds.refresh(Request())

service = build('drive', 'v3', credentials=creds)

# ── Cache ──────────────────────────────────────────────────────────
_cache = {}

def get_info(fid):
    if fid in _cache:
        return _cache[fid]
    try:
        result = service.files().get(
            fileId=fid,
            fields='id,name,mimeType,parents'
        ).execute()
        _cache[fid] = result
        return result
    except Exception as e:
        print(f"Warning: Cannot get info for {fid}: {e}")
        _cache[fid] = None
        return None

def get_ancestor_ids(fid):
    ids = []
    current = fid
    visited = set()
    while current and current not in visited:
        visited.add(current)
        ids.append(current)
        info = get_info(current)
        if not info:
            break
        parents = info.get('parents', [])
        current = parents[0] if parents else None
    return ids

def find_watched_root(fid):
    ancestors = get_ancestor_ids(fid)
    for anc in ancestors:
        if anc in SKIP_FOLDERS:
            return None
    for anc in ancestors:
        if anc in ACTIVE_FOLDERS:
            return anc
    return None

def build_path(fid, root_id):
    parts = []
    current = fid
    visited = set()
    while current and current not in visited:
        visited.add(current)
        info = get_info(current)
        if not info:
            break
        parts.insert(0, info.get('name', '?'))
        if current == root_id:
            break
        parents = info.get('parents', [])
        current = parents[0] if parents else None
    return parts

def format_path(parts, new_folder_name=None):
    """Format path vertically. If new_folder_name given, append it marked as New."""
    if not parts:
        return '📂 Unknown'
    lines = []
    for i, part in enumerate(parts):
        indent = '  ' * i
        if i == 0:
            lines.append(f"📂 {part}")
        else:
            lines.append(f"{indent}↳ {part}")
    if new_folder_name:
        indent = '  ' * len(parts)
        lines.append(f"{indent}↳ 📂 {new_folder_name} *(New)*")
    return '\n'.join(lines)

# ── Formatting ─────────────────────────────────────────────────────
MIME_LABELS = {
    'application/pdf': 'PDF',
    'application/vnd.google-apps.document': 'Google Doc',
    'application/vnd.google-apps.spreadsheet': 'Google Sheet',
    'application/vnd.google-apps.presentation': 'Google Slides',
    'application/vnd.google-apps.folder': 'Folder',
    'application/vnd.google-apps.form': 'Google Form',
    'image/jpeg': 'JPEG',
    'image/png': 'PNG',
    'image/gif': 'GIF',
    'video/mp4': 'MP4',
    'video/x-matroska': 'MKV',
    'audio/mpeg': 'MP3',
    'application/zip': 'ZIP',
    'application/x-rar-compressed': 'RAR',
    'application/x-7z-compressed': '7Z',
    'text/plain': 'TXT',
    'text/html': 'HTML',
    'text/css': 'CSS',
    'text/x-python': 'Python',
    'application/json': 'JSON',
    'application/javascript': 'JavaScript',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'Word',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'Excel',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'PowerPoint',
    'application/x-msdownload': 'EXE',
    'application/octet-stream': 'Binary',
}

def fmt_type(mime, name):
    if mime in MIME_LABELS:
        return MIME_LABELS[mime]
    if name and '.' in name:
        return name.rsplit('.', 1)[-1].upper()
    return 'File'

def fmt_time(t):
    if not t:
        return 'Unknown'
    try:
        dt  = datetime.fromisoformat(t.replace('Z', '+00:00'))
        ist = dt + timedelta(hours=5, minutes=30)
        return ist.strftime('%d %b %Y, %I:%M %p')
    except:
        return 'Unknown'

def is_new_file(created, modified):
    if not created or not modified:
        return True
    try:
        created_dt  = datetime.fromisoformat(created.replace('Z', '+00:00'))
        modified_dt = datetime.fromisoformat(modified.replace('Z', '+00:00'))
        diff = abs((modified_dt - created_dt).total_seconds())
        return diff < NEW_FILE_THRESHOLD_SEC
    except:
        return True

# ── Telegram ───────────────────────────────────────────────────────
def send_telegram(msg):
    try:
        r = requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={
                'chat_id': TELEGRAM_CHAT_ID,
                'text': msg,
                'parse_mode': 'Markdown',
                'disable_web_page_preview': True,
            },
            timeout=15
        )
        if r.status_code != 200:
            print(f"Telegram error {r.status_code}: {r.text}")
        else:
            print(f"Telegram sent OK.")
    except Exception as e:
        print(f"Telegram exception: {e}")

# ── Page token ─────────────────────────────────────────────────────
if os.path.exists(PAGE_TOKEN_FILE):
    with open(PAGE_TOKEN_FILE) as f:
        page_token = f.read().strip()
    if not page_token or not page_token.isdigit():
        print("Invalid token — resetting.")
        r = service.changes().getStartPageToken().execute()
        page_token = r['startPageToken']
        with open(PAGE_TOKEN_FILE, 'w') as f:
            f.write(page_token)
        print(f"Fresh token: {page_token}. Waiting for next run.")
        exit(0)
    print(f"Resuming from token: {page_token}")
else:
    r = service.changes().getStartPageToken().execute()
    page_token = r['startPageToken']
    with open(PAGE_TOKEN_FILE, 'w') as f:
        f.write(page_token)
    print(f"First run — token saved: {page_token}. Waiting for next run.")
    exit(0)

# ── Scan changes ───────────────────────────────────────────────────
new_token    = page_token
notified     = 0
checked      = 0
notified_ids = set()

while True:
    try:
        resp = service.changes().list(
            pageToken=page_token,
            fields='nextPageToken,newStartPageToken,'
                   'changes(changeType,removed,'
                   'file(id,name,mimeType,size,createdTime,modifiedTime,parents,webViewLink))',
            includeRemoved=False,
            spaces='drive',
            pageSize=100,
        ).execute()
    except Exception as e:
        print(f"Error fetching changes: {e}")
        break

    for change in resp.get('changes', []):
        if change.get('removed'):
            continue

        f = change.get('file', {})
        if not f:
            continue

        checked  += 1
        file_id   = f.get('id', '')
        name      = f.get('name', 'Unknown')
        mime      = f.get('mimeType', '')
        parents   = f.get('parents', [])
        created   = f.get('createdTime', '')
        modified  = f.get('modifiedTime', '')

        if not parents:
            continue

        parent_id = parents[0]

        if file_id in notified_ids:
            continue

        is_folder = mime == 'application/vnd.google-apps.folder'
        check_id  = file_id if is_folder else parent_id

        root_id = find_watched_root(check_id)
        if not root_id:
            print(f"Skipped (outside watched): {name}")
            continue

        file_is_new = is_new_file(created, modified)

        if is_folder:
            # Path = parent path, new folder name shown separately
            parent_path_parts = build_path(parent_id, root_id)
            vertical = format_path(parent_path_parts, new_folder_name=name)
            msg = (
                f"📁 *Drive Notifier*\n"
                f"━━━━━━━━━━━━━━━\n"
                f"📂 *New Folder Created*\n\n"
                f"{vertical}\n\n"
                f"🕐 {fmt_time(created)}"
            )
        elif file_is_new:
            path_parts = build_path(parent_id, root_id)
            vertical   = format_path(path_parts)
            msg = (
                f"📁 *Drive Notifier*\n"
                f"━━━━━━━━━━━━━━━\n"
                f"🆕 *New File Uploaded*\n\n"
                f"{vertical}\n\n"
                f"📄 `{name}`\n"
                f"🗂 {fmt_type(mime, name)}\n"
                f"🕐 {fmt_time(created)}"
            )
        else:
            path_parts = build_path(parent_id, root_id)
            vertical   = format_path(path_parts)
            msg = (
                f"📁 *Drive Notifier*\n"
                f"━━━━━━━━━━━━━━━\n"
                f"✏️ *File Modified*\n\n"
                f"{vertical}\n\n"
                f"📄 `{name}`\n"
                f"🗂 {fmt_type(mime, name)}\n"
                f"🕐 {fmt_time(modified)}"
            )

        send_telegram(msg)
        notified_ids.add(file_id)
        notified += 1
        kind = 'folder' if is_folder else ('new' if file_is_new else 'modified')
        print(f"Notified [{kind}]: {name}")

    if 'newStartPageToken' in resp:
        new_token = resp['newStartPageToken']
        break
    elif 'nextPageToken' in resp:
        page_token = resp['nextPageToken']
    else:
        break

with open(PAGE_TOKEN_FILE, 'w') as f:
    f.write(new_token)

print(f"\nDone. Checked: {checked} | Notified: {notified} | Token: {new_token}")
