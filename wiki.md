# SVG Live Viewer

Desktop SVG inspection tool for local project folders.

## Repo-native behavior

- App-level config lives beside the script in `config.json`
- Recent project directories are stored in app config
- Project-level state lives in `<ProjectDir>/svg_live_viewer.json`
- The most recent project auto-loads on startup when available
- The selected SVG is stored relative to the project directory

## Folder contents

- `svg_live_viewer.py`: main app entrypoint
- `requirements.txt`: runtime dependency list
- `setup.py`: local dependency bootstrapper
- `config.json`: app-level state, including recent projects

## Project behavior

Select a project directory first. The app scans that folder recursively for `.svg` files, lets you choose which SVG to watch, and persists view/render settings into the project config file.
