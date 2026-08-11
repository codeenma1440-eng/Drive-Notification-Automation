import os
import json
import requests
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ═══════════════════════════════════════════════════════════════════
# CONFIGURATION — Only edit this section
# ═══════════════════════════════════════════════════════════════════

WATCHED_FOLDERS = {
    'VORMS':                   '1-7b6q7t6gvkAtE0xAlpCvxmbB4FRoVYD',
    'Repati Kosam':            '1NhK3dPc_y7HKGpOiTbQod-KMkaNSBo3Z',
    '3rdYr_CSC_2026-27':       '1v4qVS-_WBi1B-Qm2bj-SasZNfuBfYq1j',
    # 'Drive 4': '',
    # 'Drive 5': '',
}

MANIFEST_FILE = 'manifest.json'   # snapshot of everything seen last run

# ═══════════════════════════════════════════════════════════════════
# DO NOT EDIT BELOW THIS LINE
# ═══════════════════════════════════════════════════════════════════

token_data       = json.loads(os.environ['GDRIVE_TOKEN'])
client_data      = json.loads(os.environ['GDRIVE_CLIENT_SECRET'])
TELEGRAM_TOKEN   = os.environ['TELEGRAM_BOT_TOKEN']
TELEGRAM_CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

ACTIVE = {name: fid.strip() for name, fid in WATCHED_FOLDERS.items() if fid.strip()}
if not ACTIVE:
    print("No drives configured.")
    exit(0)

print(f"Watching {len(ACTIVE)} drive(s): {', '.join(ACTIVE.keys())}")

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
            print("Telegram sent OK.")
    except Exception as e:
        print(f"Telegram exception: {e}")

# ── Formatting helpers ─────────────────────────────────────────────
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
    except Exception:
        return 'Unknown'

def format_path(path_names, new_name=None, is_new_folder=False):
    lines = []
    for i, part in enumerate(path_names):
        indent = '  ' * i
        lines.append(f"📂 {part}" if i == 0 else f"{indent}↳ {part}")
    if new_name:
        indent = '  ' * len(path_names)
        marker = f"📂 {new_name} *(New)*" if is_new_folder else new_name
        lines.append(f"{indent}↳ {marker}")
    return '\n'.join(lines)

# ── Manifest (previous snapshot) ──────────────────────────────────
if os.path.exists(MANIFEST_FILE):
    with open(MANIFEST_FILE) as f:
        try:
            manifest = json.load(f)
        except Exception:
            manifest = {}
else:
    manifest = {}

first_run_drives = [name for name in ACTIVE if name not in manifest]

new_manifest = {}
total_scanned_folders = 0
total_scanned_items = 0
total_notified = 0

FIELDS = 'nextPageToken, files(id,name,mimeType,createdTime,modifiedTime,parents)'

def list_children(folder_id):
    """List immediate children (files+folders) of a folder."""
    items, page_token = [], None
    while True:
        resp = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields=FIELDS,
            pageSize=200,
            pageToken=page_token,
        ).execute()
        items.extend(resp.get('files', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return items

def walk_folder(folder_id, path_names, drive_name, seen):
    """Recursively walk a folder tree, filling `seen` with {id: item_info}."""
    global total_scanned_folders, total_scanned_items
    total_scanned_folders += 1
    print(f"  Scanning: {' > '.join(path_names)}")
    children = list_children(folder_id)
    for item in children:
        total_scanned_items += 1
        item_id = item['id']
        is_folder = item['mimeType'] == 'application/vnd.google-apps.folder'
        seen[item_id] = {
            'name': item['name'],
            'mime': item['mimeType'],
            'created': item.get('createdTime', ''),
            'modified': item.get('modifiedTime', ''),
            'is_folder': is_folder,
            'path': path_names,       # parent path (not including itself)
            'drive': drive_name,
        }
        if is_folder:
            walk_folder(item_id, path_names + [item['name']], drive_name, seen)

# ── Scan each watched drive ────────────────────────────────────────
notifications = []

for drive_name, root_id in ACTIVE.items():
    print(f"\n=== Drive: {drive_name} ===")
    seen = {}
    walk_folder(root_id, [drive_name], drive_name, seen)
    new_manifest[drive_name] = seen

    old_seen = manifest.get(drive_name, {})

    if drive_name in first_run_drives:
        print(f"  First run for '{drive_name}' — baseline saved ({len(seen)} items), no notifications sent.")
        continue

    for item_id, info in seen.items():
        old_info = old_seen.get(item_id)
        if old_info is None:
            # brand new item
            if info['is_folder']:
                notifications.append({
                    'kind': 'folder',
                    'drive': drive_name,
                    'path': info['path'],
                    'name': info['name'],
                    'time': info['created'],
                })
            else:
                notifications.append({
                    'kind': 'new_file',
                    'drive': drive_name,
                    'path': info['path'],
                    'name': info['name'],
                    'mime': info['mime'],
                    'time': info['created'],
                })
        else:
            if (not info['is_folder']) and info['modified'] != old_info.get('modified'):
                notifications.append({
                    'kind': 'modified',
                    'drive': drive_name,
                    'path': info['path'],
                    'name': info['name'],
                    'mime': info['mime'],
                    'time': info['modified'],
                })

# ── Send notifications ─────────────────────────────────────────────
for n in notifications:
    if n['kind'] == 'folder':
        vertical = format_path(n['path'], new_name=n['name'], is_new_folder=True)
        msg = (
            f"📁 *Drive Notifier* — _{n['drive']}_\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📂 *New Folder Created*\n\n"
            f"{vertical}\n\n"
            f"🕐 {fmt_time(n['time'])}"
        )
    elif n['kind'] == 'new_file':
        vertical = format_path(n['path'])
        msg = (
            f"📁 *Drive Notifier* — _{n['drive']}_\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🆕 *New File Uploaded*\n\n"
            f"{vertical}\n\n"
            f"📄 `{n['name']}`\n"
            f"🗂 {fmt_type(n['mime'], n['name'])}\n"
            f"🕐 {fmt_time(n['time'])}"
        )
    else:  # modified
        vertical = format_path(n['path'])
        msg = (
            f"📁 *Drive Notifier* — _{n['drive']}_\n"
            f"━━━━━━━━━━━━━━━\n"
            f"✏️ *File Modified*\n\n"
            f"{vertical}\n\n"
            f"📄 `{n['name']}`\n"
            f"🗂 {fmt_type(n['mime'], n['name'])}\n"
            f"🕐 {fmt_time(n['time'])}"
        )
    send_telegram(msg)
    total_notified += 1
    print(f"Notified [{n['kind']}]: {n['name']}")

# ── Save manifest ──────────────────────────────────────────────────
with open(MANIFEST_FILE, 'w') as f:
    json.dump(new_manifest, f)

# ── Scan summary (always sent, so you know it's alive) ─────────────
summary_lines = [
    "📁 *Drive Notifier — Scan Complete*",
    "━━━━━━━━━━━━━━━",
]
for drive_name in ACTIVE:
    count = len(new_manifest.get(drive_name, {}))
    tag = " (baseline)" if drive_name in first_run_drives else ""
    summary_lines.append(f"📂 {drive_name}: {count} items{tag}")
summary_lines.append(f"\n🔎 Folders scanned: {total_scanned_folders}")
summary_lines.append(f"📄 Items checked: {total_scanned_items}")
summary_lines.append(f"🔔 Notifications sent: {total_notified}")
if total_notified == 0:
    summary_lines.append("\n_No new or modified files this scan._")

send_telegram('\n'.join(summary_lines))

print(f"\nDone. Folders scanned: {total_scanned_folders} | Items checked: {total_scanned_items} | Notified: {total_notified}")
