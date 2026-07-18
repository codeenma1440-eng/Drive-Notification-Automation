import os
import json
import requests
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ═══════════════════════════════════════════════════
# CONFIGURATION — Only edit this section
# ═══════════════════════════════════════════════════

# Add/remove drive folder IDs below
# Leave empty string '' to skip that slot
WATCHED_FOLDERS = [
    '1-7b6q7t6gvkAtE0xAlpCvxmbB4FRoVYD',  # Drive 1: 3rdYr CSC
    '1NhK3dPc_y7HKGpOiTbQod-KMkaNSBo3Z',  # Drive 2: Repati Kosam
    '1v4qVS-_WBi1B-Qm2bj-SasZNfuBfYq1j',  # Drive 3
    '',  # Drive 4: empty — add ID here when needed
    '',  # Drive 5: empty — add ID here when needed
]

# Folders to completely skip (and everything inside them)
SKIP_FOLDERS = {
    '1-pKjtGbx9mnEeRkVqHovCXpGaSbhi9IK',  # 1stYr folder
    '1vPMXSB0_Vvy1JGCFij25gq1kBtx00gaZ',  # 2ndYr folder
}

AUTH_EMAIL      = 'codeenma1440@gmail.com'
PAGE_TOKEN_FILE = 'page_token.txt'

# ═══════════════════════════════════════════════════
# DO NOT EDIT BELOW THIS LINE
# ═══════════════════════════════════════════════════

token_data       = json.loads(os.environ['GDRIVE_TOKEN'])
client_data      = json.loads(os.environ['GDRIVE_CLIENT_SECRET'])
TELEGRAM_TOKEN   = os.environ['TELEGRAM_BOT_TOKEN']
TELEGRAM_CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

# Filter out empty drive slots
ACTIVE_FOLDERS = [f.strip() for f in WATCHED_FOLDERS if f.strip()]

if not ACTIVE_FOLDERS:
    print("No drives configured. Add folder IDs to WATCHED_FOLDERS.")
    exit(0)

print(f"Watching {len(ACTIVE_FOLDERS)} drive(s).")

# ── Auth ───────────────────────────────────────────
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

# ── Folder cache ───────────────────────────────────
_cache = {}

def get_info(fid):
    if fid in _cache:
        return _cache[fid]
    try:
        f = service.files().get(
            fileId=fid,
            fields='id,name,mimeType,parents'
        ).execute()
        _cache[fid] = f
        return f
    except Exception as e:
        print(f"Warning: could not get info for {fid}: {e}")
        _cache[fid] = None
        return None

def get_ancestor_ids(fid):
    """Walk up parent chain and return all ancestor IDs."""
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
    """
    Returns the watched root folder ID if fid is inside
    one of our watched folders and NOT inside a skip folder.
    Returns None otherwise.
    """
    ancestors = get_ancestor_ids(fid)
    # Check skip folders first
    for anc in ancestors:
        if anc in SKIP_FOLDERS:
            return None
    # Check watched folders
    for anc in ancestors:
        if anc in ACTIVE_FOLDERS:
            return anc
    return None

def build_path(fid, root_id):
    """Build path from root_id down to fid as list of names."""
    parts = []
    current = fid
    visited = set()
    while current and current not in visited:
        visited.add(current)
        info = get_info(current)
        if not info:
            break
        parts.insert(0, info.get('name', ''))
        if current == root_id:
            break
        parents = info.get('parents', [])
        current = parents[0] if parents else None
    return parts

def shorten_path(parts, levels=3):
    if len(parts) <= levels:
        return ' › '.join(parts)
    return '...› ' + ' › '.join(parts[-levels:])

# ── Formatting ─────────────────────────────────────
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
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'Word',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'Excel',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'PPT',
    'text/html': 'HTML',
    'application/x-msdownload': 'EXE',
}

def fmt_type(mime, name):
    if mime in MIME_LABELS:
        return MIME_LABELS[mime]
    if name and '.' in name:
        return name.rsplit('.', 1)[-1].upper()
    return 'File'

def fmt_size(s):
    if not s:
        return 'N/A'
    s = int(s)
    if s < 1024:        return f"{s} B"
    if s < 1024**2:     return f"{s/1024:.1f} KB"
    if s < 1024**3:     return f"{s/1024**2:.1f} MB"
    return f"{s/1024**3:.1f} GB"

def fmt_time(t):
    if not t:
        return 'Unknown'
    dt = datetime.fromisoformat(t.replace('Z', '+00:00'))
    ist = dt + timedelta(hours=5, minutes=30)
    return ist.strftime('%d %b %Y, %I:%M %p')

# ── Telegram ───────────────────────────────────────
def send(msg):
    try:
        r = requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={
                'chat_id': TELEGRAM_CHAT_ID,
                'text': msg,
                'parse_mode': 'Markdown',
                'disable_web_page_preview': True,
            },
            timeout=10
        )
        if r.status_code != 200:
            print(f"Telegram error: {r.text}")
    except Exception as e:
        print(f"Telegram exception: {e}")

# ── Page token ─────────────────────────────────────
if os.path.exists(PAGE_TOKEN_FILE):
    with open(PAGE_TOKEN_FILE) as f:
        page_token = f.read().strip()
    print(f"Resuming from token: {page_token}")
else:
    r = service.changes().getStartPageToken().execute()
    page_token = r['startPageToken']
    with open(PAGE_TOKEN_FILE, 'w') as f:
        f.write(page_token)
    print("First run — token initialized. Waiting for next run.")
    exit(0)

# ── Scan changes ───────────────────────────────────
new_token = page_token
notified  = 0
checked   = 0

while True:
    resp = service.changes().list(
        pageToken=page_token,
        fields='nextPageToken,newStartPageToken,'
               'changes(changeType,removed,'
               'file(id,name,mimeType,size,createdTime,parents,webViewLink))',
        includeRemoved=False,
        spaces='drive',
        pageSize=100,
    ).execute()

    for change in resp.get('changes', []):
        if change.get('removed'):
            continue

        f = change.get('file', {})
        if not f:
            continue

        checked += 1
        file_id = f.get('id', '')
        name    = f.get('name', 'Unknown')
        mime    = f.get('mimeType', '')
        parents = f.get('parents', [])
        parent_id = parents[0] if parents else None

        if not parent_id:
            continue

        is_folder = mime == 'application/vnd.google-apps.folder'
        check_id  = file_id if is_folder else parent_id

        root_id = find_watched_root(check_id)
        if not root_id:
            continue

        # Build path
        if is_folder:
            path_parts = build_path(parent_id, root_id)
            path_parts.append(name)
        else:
            path_parts = build_path(parent_id, root_id)

        short_path = shorten_path(path_parts)
        link = f"{f.get('webViewLink', '#')}?authuser={AUTH_EMAIL}"

        if is_folder:
            msg = (
                f"📁 *Drive Notifier*\n\n"
                f"📂 *New Folder Created!*\n"
                f"*Path:* `{short_path}`\n"
                f"*Created:* {fmt_time(f.get('createdTime'))}\n"
                f"🔗 [Open Folder]({link})"
            )
        else:
            msg = (
                f"📁 *Drive Notifier*\n\n"
                f"*Path:* `{short_path}`\n"
                f"*File:* {name}\n"
                f"*Type:* {fmt_type(mime, name)}\n"
                f"*Size:* {fmt_size(f.get('size'))}\n"
                f"*Uploaded:* {fmt_time(f.get('createdTime'))}\n"
                f"🔗 [Open File]({link})"
            )

        send(msg)
        print(f"Notified: {name}")
        notified += 1

    if 'newStartPageToken' in resp:
        new_token = resp['newStartPageToken']
        break
    page_token = resp.get('nextPageToken', page_token)

with open(PAGE_TOKEN_FILE, 'w') as f:
    f.write(new_token)

print(f"Done. Checked: {checked} changes. Notified: {notified}. Token: {new_token}")
