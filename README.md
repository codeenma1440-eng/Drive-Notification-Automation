# Drive-Notification-Automation

One workflow per drive, each with its own schedule, manifest and concurrency group.

| Drive | Workflow | Cron | Manifest |
|---|---|---|---|
| 3rdYr CSC | `watch_3rdyr.yml` | every 10 min | `manifests/3rdyr.json` |
| Repati Kosam | `watch_repati.yml` | every 25 min (0/25/50) | `manifests/repati.json` |
| VORMS | `watch_vorms.yml` | every 30 min | `manifests/vorms.json` |

Delete a manifest file to re-baseline that drive (next run sends no notifications).
Add a drive: new entry in `DRIVES` in `check_drive.py` + copy a workflow file.
