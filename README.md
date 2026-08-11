# BarcodeMakerPro Windows Clone

This repository contains a Windows-friendly copy of the AAMVA PDF417 barcode generator.

## Requirements

- Python 3.9+ or newer
- `tkinter` installed
- `Pillow`
- `pdf417`

Install dependencies:

```powershell
pip install -r requirements.txt
```

## Run GUI

```powershell
python windows_barcode_app.py --gui
```

or use the launcher:

```powershell
run_windows.bat
```

## Quick Install (Windows)

Run the installer script once to install Python requirements and create shortcuts on the Desktop and Start Menu:

```powershell
install_windows.bat
```

If shortcut creation fails, the app will still work via `run_windows.bat`.

## CLI

Generate image from the default profile:

```powershell
python windows_barcode_app.py --out barcode.png
```

Validate only:

```powershell
python windows_barcode_app.py --validate-only
```

Parse raw AAMVA data:

```powershell
python windows_barcode_app.py --parse-aamva raw_aamva.dat
```

## AddressKit (optional)

This project supports integrating with AddressKit (an open-source Australian address validation API) for the `Verify Address` button. To run AddressKit locally using Docker Compose:

1. Create a `docker-compose.yml` with `opensearch` and `api` services (see AddressKit README).
2. Start the services:

```bash
docker compose up -d
```

3. By default the API listens on port `7234`. In the app, set the Address API URL to `http://localhost:7234` via the `Profile -> Set Address API...` menu.

Note: AddressKit loads G-NAF data and requires additional memory for some Australian states. See the upstream README for detailed instructions: https://github.com/bradleyhodges/addresskit
