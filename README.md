```markdown
# RBV Downloader

Automated RBV image fetcher with resume capability.

This repository contains `rbvscrapperv2.py` — a script that downloads image pages from the RBV (pustaka.ut.ac.id) reader service, tracks progress with a manifest file, supports resuming interrupted downloads, and can combine downloaded images into a single PDF.

> IMPORTANT: The script requires valid session cookies from the site (stored in the Config.COOKIES dictionary). The server may return HTML (login/error) if cookies expire — the script detects this and prompts you to update the cookies.

## Requirements

- Python 3.8+
- A working internet connection
- Access (login) to https://pustaka.ut.ac.id to obtain valid cookies

Install dependencies:

```bash
git clone https://github.com/priawan-ut-044681976/rbv_downloader.git
cd rbv_downloader

# create and activate virtual environment (example using python -m venv)
python -m venv .venv
# on Windows
.venv\Scripts\activate
# on macOS/Linux
source .venv/bin/activate

# install requirements
pip install -r requirements.txt
```

## Configure cookies

Before running the script, open `rbvscrapperv2.py` and update the `Config.COOKIES` dictionary with your current session cookies from your browser. The script uses these cookies to authenticate requests to the RBV reader service.

How to extract cookies (brief):
1. Log in to https://pustaka.ut.ac.id using your browser.
2. Use browser devtools -> Network -> select a request to `pustaka.ut.ac.id` -> request headers -> find the `Cookie` header.
3. Copy relevant cookie key/value pairs (e.g., `PHPSESSID=...`) and paste them into `Config.COOKIES` in `rbvscrapperv2.py` as a Python dict.

Note: If the server returns HTML or an error instead of an image, the script will detect that and inform you the cookies likely expired.

## Usage

Run the script:

```bash
python rbvscrapperv2.py
```

The script is interactive:
1. Enter the module name (e.g., `MSIM4408`).
2. If a folder for that module already exists, the script attempts to load a manifest and offers options to resume, re-download format-mismatched files, or start a new download.
3. For new downloads you will be prompted for the number of submodules and pages per submodule.
4. Confirm to start downloads. The script will:
   - Create a folder named after the module.
   - Create a manifest file `<module>/<module>.manifest.json` to track per-file status.
   - Download files, pause randomly between requests (to mimic human-like behavior).
   - Detect text/HTML responses (invalid cookies) and format mismatches.
   - Save progress to the manifest so you can resume later.

Resume behavior:
- If interrupted, re-run the script and enter the same module name. The script will detect the manifest and offer to resume.
- The manifest keeps per-file status (pending, downloading, completed, failed, format_mismatch), attempts and sizes.

Combine images into PDF:
- After download completes, the script offers to combine the images into a single PDF.
- You can also choose this option when a module is already complete.
- The script uses Pillow to assemble images into `<module>/<module>.pdf`.

Example workflow:
1. Set cookies in `rbvscrapperv2.py`.
2. Run the script and follow prompts to create a new download.
3. If interrupted, re-run and choose the resume option.
4. When complete, choose to combine images into a PDF.

Troubleshooting
- "Received text/HTML instead of image": your cookies likely expired. Update `Config.COOKIES` with fresh cookies and resume.
- Format mismatches: the script expects images in the format set by `Config.IMAGE_FORMAT` (default `jpg`). If the server serves a different format (png, webp, etc.) the manifest will mark those files as `format_mismatch`. You can choose to re-download or skip them.
- Permissions: ensure the process has permission to create files and directories in the working directory.
- Pillow not installed: the script will prompt to install Pillow if you try to create a PDF without it.

Advanced / Notes
- Adjust delays in `Config.MIN_DELAY` / `Config.MAX_DELAY` to tune wait time between requests.
- The manifest file is located at `<module>/<module>.manifest.json`. Keep it if you plan to resume large downloads.
- This script is intended for personal/authorized use only. Respect the site's terms of service.

License
- No license file is included here — add one if you intend to make this public with explicit licensing.

If you'd like, I can:
- Add a small helper to extract cookies from a browser export,
- Convert the interactive flow to support a CLI via argparse,
- Or add a GitHub Actions workflow for automated checks.

```
