# SVG Live Viewer Wiki

SVG Live Viewer is a desktop tool for inspecting SVG files inside a selected project directory.

## Quick Start

```bash
python setup.py --venv
python svg_live_viewer.py
```

Manual install:

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python svg_live_viewer.py
```

On Linux or macOS, use `source .venv/bin/activate`.

## Project Workflow

1. Select a project directory.
2. Choose an SVG discovered under that directory.
3. Inspect the render and adjust view settings.

## State Files

- App config: `config.json` beside `svg_live_viewer.py`
- Project config: `svg_live_viewer.json` in the selected project directory
- Log file: `svg_live_viewer.log`

These files are runtime state and are ignored by Git.
