# Drive-Notification-Automation

One workflow per drive, each with its own schedule, manifest and concurrency group.

| Drive | Workflow | Run At   |
|---|---|---|---|
| Drive 01 | `watch_3rdyr.yml` | every 10 min | 
| Drive 02 | `watch_repati.yml` | every 30 min) | 
| Drive 03 | `watch_vorms.yml` | every 30 min |

Delete a manifest file to re-baseline that drive (next run sends no notifications).
Add a drive: new entry in `DRIVES` in `check_drive.py` + copy a workflow file.
