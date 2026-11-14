"""Drive watcher — one drive per run.

Usage:  python check_drive.py <drive1|drive2|drive3>

Each drive has its own workflow, its own schedule, its own manifest file
(manifests/<name>.json) and its own concurrency group, so drives never
interfere with each other. All of them post to the same Telegram chat.
"""
import os
import sys
import json
import time
import threading
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ═══════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════

DRIVES = {
    'drive1': {'name': '3rdYr_CSC_2026-27', 'id': '1-7b6q7t6gvkAtE0xAlpCvxmbB4FRoVYD', 'manifest': '3rdyr'},
    'drive2': {'name': 'Repati Kosam',      'id': '1NhK3dPc_y7HKGpOiTbQod-KMkaNSBo3Z', 'manifest': 'repati'},
    'drive3': {'name': 'VORMS',             'id': '1v4qVS-_WBi1B-Qm2bj-SasZNfuBfYq1j', 'manifest': 'vorms'},
}

# Folder IDs to completely skip — not scanned, not reported, not recursed into.
SKIP_FOLDERS = {
    '1-pKjtGbx9mnEeRkVqHovCXpGaSbhi9IK',  # 1stYr folder
    '1vPMXSB0_Vvy1JGCFij25gq1kBtx00gaZ',  # 2ndYr folder
    '1FjW39Bjw5HokWUtENI2RyMQbTdCwFzAA',  # FSD - 11 PROGRAM MORE LIBRARIES
}

SCAN_WORKERS = 8          # parallel Drive API requests inside one scan
TELEGRAM_GAP = 1.1        # seconds between messages (Telegram: ~1 msg/s per chat)
FOLDER_MIME = 'application/vnd.google-apps.folder'

# ═══════════════════════════════════════════════════════════════════
# SETUP
# ═══════════════════════════════════════════════════════════════════

# Drive key comes from the command line (python check_drive.py drive1)
# or from the DRIVE_KEY environment variable.
KEY = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('DRIVE_KEY', '')
if KEY not in DRIVES:
    sys.exit(f"Unknown drive '{KEY}'. Use one of: {', '.join(DRIVES)}")

DRIVE_NAME = DRIVES[KEY]['name']
ROOT_ID    = DRIVES[KEY]['id']
MANIFEST_FILE = os.path.join('manifests', DRIVES[KEY]['manifest'] + '.json')

token_data       = json.loads(os.environ['GDRIVE_TOKEN'])
client_data      = json.loads(os.environ['GDRIVE_CLIENT_SECRET'])
TELEGRAM_TOKEN   = os.environ['TELEGRAM_BOT_TOKEN']
TELEGRAM_CHAT_ID = os.environ['TELEGRAM_CHAT_ID']

creds = Credentials(
    token=token_data.get('token'),
    refresh_token=token_data.get('refresh_token'),
    token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
    client_id=client_data['installed']['client_id'],
    client_secret=client_data['installed']['client_secret'],
    scopes=token_data.get('scopes'),
)
if creds.expired or not creds.token:
    creds.refresh(Request())

_local = threading.local()
def get_service():
    """httplib2 is not thread-safe: one Drive client per worker thread."""
    if not hasattr(_local, 'svc'):
        _local.svc = build('drive', 'v3', credentials=creds, cache_discovery=False)
    return _local.svc

# ── Escape special chars for MarkdownV2 ───────────────────────────
def esc(s):
    """Escape all MarkdownV2 special characters in dynamic text."""
    for ch in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
        s = s.replace(ch, '\\' + ch)
    return s

# ── Telegram (retries on 429 / network errors; returns True only if delivered) ──
def send_telegram(msg):
    for attempt in range(5):
        try:
            r = requests.post(
                f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
                json={
                    'chat_id': TELEGRAM_CHAT_ID,
                    'text': msg,
                    'parse_mode': 'MarkdownV2',
                    'disable_web_page_preview': True,
                },
                timeout=20,
            )
            if r.status_code == 200:
                return True
            if r.status_code == 429:
                wait = r.json().get('parameters', {}).get('retry_after', 5)
                print(f"Telegram 429, waiting {wait}s")
                time.sleep(wait + 1)
                continue
            if 400 <= r.status_code < 500:
                print(f"Telegram rejected message ({r.status_code}): {r.text}")
                return False
            print(f"Telegram {r.status_code}, retrying")
        except requests.RequestException as e:
            print(f"Telegram exception: {e}")
        time.sleep(2 * (attempt + 1))
    return False

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
        prefix = '📂' if i == 0 else '↳'
        lines.append(f"{indent}{prefix} {esc(part)}")
    if new_name:
        indent = '  ' * len(path_names)
        if is_new_folder:
            lines.append(f"{indent}↳ 📂 {esc(new_name)} _\\(New\\)_")
        else:
            lines.append(f"{indent}↳ {esc(new_name)}")
    return '\n'.join(lines)

# ── Manifest: {file_id: modifiedTime}. Missing file = first run (baseline only) ──
first_run = not os.path.exists(MANIFEST_FILE)
old = {}
if not first_run:
    with open(MANIFEST_FILE) as f:
        old = json.load(f)          # corrupt manifest -> crash loudly, never silently reset

# ── Scan (parallel, level by level) ───────────────────────────────
FIELDS = 'nextPageToken, files(id,name,mimeType,createdTime,modifiedTime)'

def list_children(folder_id):
    svc, items, page_token = get_service(), [], None
    while True:
        resp = svc.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields=FIELDS, pageSize=1000, pageToken=page_token,
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute(num_retries=5)
        items.extend(resp.get('files', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            return items

def scan():
    seen = {}                                   # id -> info
    frontier = [(ROOT_ID, [DRIVE_NAME])]
    folders = 0
    with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
        while frontier:
            folders += len(frontier)
            results = list(pool.map(lambda fp: list_children(fp[0]), frontier))
            nxt = []
            for (fid, path), children in zip(frontier, results):
                print(f"  Scanning: {' > '.join(path)}  ({len(children)} items)", flush=True)
                for it in children:
                    is_folder = it['mimeType'] == FOLDER_MIME
                    if is_folder and it['id'] in SKIP_FOLDERS:
                        print(f"  Skipping (excluded): {' > '.join(path + [it['name']])}")
                        continue
                    seen[it['id']] = {
                        'name': it['name'], 'mime': it['mimeType'],
                        'created': it.get('createdTime', ''),
                        'modified': it.get('modifiedTime', ''),
                        'is_folder': is_folder, 'path': path,
                    }
                    if is_folder:
                        nxt.append((it['id'], path + [it['name']]))
            frontier = nxt
    return seen, folders

t0 = time.time()
print(f"=== {DRIVE_NAME} ({KEY}) ===")
print("Run started (IST):", (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime('%d %b %Y, %I:%M:%S %p'))
print("Previous manifest:", "NONE (first run)" if first_run else f"{len(old)} items")
if ROOT_ID in SKIP_FOLDERS:
    sys.exit("Root folder is in SKIP_FOLDERS")
# Drive returns an EMPTY list (not an error) for folders it can't see, so verify access first.
try:
    root = get_service().files().get(
        fileId=ROOT_ID, fields='id,name,mimeType', supportsAllDrives=True).execute(num_retries=5)
except Exception as e:
    sys.exit(f"Cannot access root folder {ROOT_ID} for '{KEY}': {e}\n"
             f"Check the folder ID and that the token's account has access to it.")
if root['mimeType'] != FOLDER_MIME:
    sys.exit(f"{ROOT_ID} is not a folder (it is {root['mimeType']}).")
print(f"Root OK: '{root['name']}'")
seen, n_folders = scan()      # any API failure raises -> nothing saved, retried next run
print(f"Scanned {n_folders} folders / {len(seen)} items in {time.time()-t0:.0f}s")

if not seen and first_run:
    sys.exit(f"'{KEY}' scan returned 0 items on first run — not saving an empty baseline. "
             f"Folder may be empty, or the account may lack access to its contents.")

# ── Diff ───────────────────────────────────────────────────────────
new_manifest = {i: v['modified'] for i, v in seen.items()}
if first_run:
    print("First run — baseline saved, no notifications.")
    notifications = []
else:
    notifications = []
    for item_id, info in seen.items():
        base = {'id': item_id, 'path': info['path'], 'name': info['name'], 'mime': info['mime']}
        if item_id not in old:
            if info['is_folder']:
                notifications.append({**base, 'kind': 'folder', 'time': info['created']})
            else:
                notifications.append({**base, 'kind': 'new_file', 'time': info['created']})
        elif not info['is_folder'] and info['modified'] != old[item_id]:
            notifications.append({**base, 'kind': 'modified', 'time': info['modified']})

print(f"Changes found: {sum(n['kind']=='new_file' for n in notifications)} new files, "
      f"{sum(n['kind']=='folder' for n in notifications)} new folders, "
      f"{sum(n['kind']=='modified' for n in notifications)} modified")

# ── Notify (oldest first) ──────────────────────────────────────────
notifications.sort(key=lambda n: n['time'])
drive_esc = esc(DRIVE_NAME)
sent = failed = 0
for n in notifications:
    time_esc = esc(fmt_time(n['time']))
    head = f"📁 *Drive Notifier* — _{drive_esc}_\n━━━━━━━━━━━━━━━\n"
    if n['kind'] == 'folder':
        msg = head + f"📂 *New Folder Created*\n\n{format_path(n['path'], new_name=n['name'], is_new_folder=True)}\n\n🕐 {time_esc}"
    else:
        title = '🆕 *New File Uploaded*' if n['kind'] == 'new_file' else '✏️ *File Modified*'
        msg = (head + f"{title}\n\n{format_path(n['path'])}\n\n"
               f"📄 `{esc(n['name'])}`\n🗂 {esc(fmt_type(n['mime'], n['name']))}\n🕐 {time_esc}")
    if send_telegram(msg):
        sent += 1
        print(f"Notified [{n['kind']}]: {n['name']}")
        time.sleep(TELEGRAM_GAP)
    else:
        failed += 1
        print(f"FAILED [{n['kind']}]: {n['name']} — will retry next run")
        # leave the item in its OLD state so the next run detects it again
        if n['id'] in old:
            new_manifest[n['id']] = old[n['id']]
        else:
            new_manifest.pop(n['id'], None)

# ── Save manifest (atomic) ─────────────────────────────────────────
os.makedirs('manifests', exist_ok=True)
tmp = MANIFEST_FILE + '.tmp'
with open(tmp, 'w') as f:
    json.dump(new_manifest, f, separators=(',', ':'), sort_keys=True)
os.replace(tmp, MANIFEST_FILE)
print(f"Done in {time.time()-t0:.0f}s | notified {sent} | failed {failed}")
