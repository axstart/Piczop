# Piczop

Portable Windows photo organizer for a USB stick. Plug in the drive, run `Piczop.exe`, click **Back up now**. Photos and videos are copied onto the stick. Exact copies already on the stick are skipped. Similar photos are **queued for you to review** — nothing is merged or deleted until you confirm. Originals stay on the computer. No account and no cloud.

## Download (Windows)

Get builds from GitHub Releases (not from Vercel — the app is too large for static hosting):

- **Installer:** https://github.com/axstart/Piczop/releases/latest/download/Piczop-Setup.exe  
  Normal Windows install (Start Menu, optional desktop icon, uninstall entry).
- **Portable zip:** https://github.com/axstart/Piczop/releases/latest/download/Piczop-Windows.zip  
  Unzip, run `Piczop.exe`, then copy the whole folder to a USB stick if you want.

After using the installer, you can still copy the installed `Piczop` folder onto a USB stick and run it from there.

## Windows app

Piczop is a native-feeling Windows desktop app (PySide6). Use **Piczop.exe** for daily use; use Python only when developing.

### Run from source

Requires Python 3.11+.

```powershell
cd D:\Piczop
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.main
```

`python -m app` also starts the same window.

### Build Piczop.exe

```powershell
cd D:\Piczop
powershell -ExecutionPolicy Bypass -File .\scripts\build-windows.ps1
```

That script creates `.venv` if needed, installs dependencies, writes `assets\piczop.ico`, and runs PyInstaller (`piczop.spec`: windowed, onedir, version info, icon).

**Exe location:** `dist\Piczop\Piczop.exe`  
Copy the **entire** `dist\Piczop` folder (not just the exe). Supporting DLLs live next to it (typically in `_internal`).

### Portable (USB or copy)

Copy `dist\Piczop` onto a USB stick or any folder. Double-click `Piczop.exe`. No installer required.

On first run, when the app folder is writable, Piczop creates `PiczopLibrary\` next to `Piczop.exe` (photos, videos, review, trash, thumbs, catalog). That folder is never stored inside the PyInstaller unpack directory.

### Library path (installer vs portable)

- **Portable / USB / any writable folder:** `PiczopLibrary` next to `Piczop.exe` (stays on the stick).
- **Program Files (or other read-only install dir):** `%LOCALAPPDATA%\Piczop\PiczopLibrary` so backups work without admin write access.

### Graceful degradation (disk / USB)

| Condition | Behavior |
| --- | --- |
| Library folder not writable next to the exe (e.g. Program Files) | Fall back to `%LOCALAPPDATA%\Piczop\PiczopLibrary` |
| Free space under ~500 MB | Home shows a low-space warning; **Back up now** asks before starting (you can cancel) |
| Free space under ~50 MB, or estimated found-file sizes exceed free space | Backup is blocked with a clear message (after scan when sizes are known) |
| Drive full or USB removed mid-copy | Backup cancels immediately with one message — it does not spam hundreds of per-file errors |

Pause / cancel still work as usual. Near-duplicate review stays human-in-the-loop.

### Local logs (privacy)

Diagnostics stay on disk only: `PiczopLibrary\logs\piczop.log` (rotated / size-capped). Piczop does **not** phone home — no network logging or telemetry.

### Windows installer

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-installer.ps1
```

That script builds `dist\Piczop` if needed, finds or installs [Inno Setup](https://jrsoftware.org/isinfo.php) 6 (`ISCC.exe`), and writes `dist\Piczop-Setup.exe`. Default install directory is `{autopf}\Piczop`. Start Menu shortcut; optional desktop icon; uninstall entry.

## Put it on a USB stick

After a successful build, copy `dist\Piczop` onto the flash drive. On another Windows PC, open the drive and run `Piczop.exe`.

Layout on the stick:

- `Piczop.exe` and supporting files
- `PiczopLibrary\photos\YYYY\MM\`
- `PiczopLibrary\videos\YYYY\MM\`
- `PiczopLibrary\review\` (similar photos held until you decide, if that setting is on)
- `PiczopLibrary\trash\` (stick copies removed after you confirm merge/delete; restore from Review)
- `PiczopLibrary\catalog.db`
- `PiczopLibrary\thumbs\`
- `PiczopLibrary\settings.json`
- `PiczopLibrary\logs\piczop.log` (local diagnostics only)

## How duplicates work (human in the loop)

- **Exact copies** (same bytes) are skipped using SHA-256. A fast size + first-1MB check avoids hashing files that already match. Skipping an identical file that is already on the stick is not a merge or delete.
- **Near-duplicates** (same photo, different size or JPEG compression) use a 64-bit difference hash (dHash) from Pillow. Two photos are similar if Hamming distance is 8 or less. These are **proposals only**. Piczop does not skip, merge, or delete them without your review.
- PC originals are **never deleted**. Stick files are never deleted until you confirm; confirmed removals move to `PiczopLibrary\trash\` first (restore from the Review page).

### Review flow

1. Back up. Home and the summary show **N duplicate groups need your review**.
2. Open **Review**. Groups appear with thumbnails side by side. Click the photo you want to keep as primary.
3. Choose:
   - **Keep all** — keep every copy; mark the group dismissed.
   - **Keep this as primary** — mark the others as duplicates; files stay on the stick.
   - **Merge** — keep the primary on the stick, then **Confirm** to move extra stick copies to trash.
   - **Delete extras** — same as merge: **Confirm** with a filename list, then extras go to trash.
4. Merge/delete buttons stay disabled until you select a photo. Confirm is required before anything is moved to trash.

Catalog statuses: `pending_review`, `confirmed_duplicate`, `dismissed`, `merged`.

### Settings

- **Copy all, I'll review later** (default) — similar photos are copied into the library and flagged for Review.
- **Don't copy similar photos until I review** — similar photos are copied into `PiczopLibrary\review\` instead of the dated photos folders. After you keep them, they are moved into the library. Merge/delete still need your confirm.

There is no auto “skip near-duplicates” that drops similar photos without review.

### Review place is saved

The catalog (`PiczopLibrary\catalog.db`) stores a small `ui_state` table: current page, gallery filter, current review group id, and selected primary photo. Switching to Gallery or quitting the app does not lose your review place.

Review shows **one group at a time** (Previous / Next). Pending vs done is the existing group status (`pending_review` vs dismissed/confirmed/merged).

### Gallery

Filters: **Date** (timeline headers by month), **People**, **Places**, **Screenshots**, **Review pending**, **Videos**.

**Screenshots** is a dedicated collection. WhatsApp/Telegram paths are treated as downloads, not screenshots. Camera make/model or GPS means camera roll, not a screenshot. Face clustering never runs on screenshots.

### Organize (suggestions, human in the loop)

Open **Organize**, optionally **Scan library**, then **Apply…** with a confirm dialog. Apply only **moves files on the stick** into folders. Nothing is auto-applied. PC originals are never deleted.

- **By date** — `photos/YYYY/MM/` from EXIF `DateTimeOriginal` / created time.
- **Screenshots** — `photos/Screenshots/YYYY/MM/` (never mixed with People).
- **By person** — EXIF/XMP people tags when present. Optional local OpenCV Haar faces (`pip install opencv-python-headless`); otherwise unnamed clusters are skipped and you still get tags + “scan later”. Rename Person 1, Person 2… then Apply. Stored as `person_id` / `person_label` on files.
- **By location** — EXIF GPS only. No Nominatim, no paid APIs. Groups by rounded lat/lon (~1 km) or Has location / No location. Folder `photos/YYYY/loc_<lat,lon>/` when you apply a GPS cluster.

People limits: this is not Google Photos identity. Haar + crop hashes are best-effort and will mix lookalikes. No cloud.

## Smart names and folders

Destination names look like `2024-06-15_143022_Camera_a1b2c3d4.jpg` (or `_Screenshot` / `_Download` from path hints: Screenshots, DCIM, Camera Roll, WhatsApp, Downloads). The original filename is stored in the catalog. Date comes from EXIF `DateTimeOriginal` when present.

## What it scans

Pictures, Videos, Desktop, Downloads (optional Documents), Camera Roll, and `DCIM` on attached drives. Extra folders can be added in Settings.

Pause / cancel a backup; later runs only copy new files.

Windows autorun is not used (blocked on modern Windows). Double-click `Piczop.exe` on the stick.
