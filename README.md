# SVG Live Viewer

Desktop SVG inspection tool for local project folders.

## Requirements

- Python 3.10+
- Dependencies from `requirements.txt`

## Install

```bash
python setup.py --venv
```

Or manually:

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On Linux or macOS, activate the virtual environment with `source .venv/bin/activate`.

## Run

```bash
python svg_live_viewer.py
```

## Behavior

Select a project directory, choose an SVG file, and inspect it in the viewer. The app stores recent projects in local runtime config and stores project-specific state in the selected project directory.

See `wiki.md` for more details.
