# BarcodeMakerPro

BarcodeMakerPro provides Linux and Windows-friendly clones of the AAMVA PDF417 barcode generator.

## Requirements

- Python 3.9+ or newer
- `Pillow`
- `pdf417`
- `tkinter` (platform-provided; install `python3-tk` on Linux if needed)

Install dependencies:

```powershell
pip install -r requirements.txt
```

## GUI Usage

Linux:

```bash
python linux_barcode_app.py --gui
```

Windows:

```powershell
python windows_barcode_app.py --gui
```

Windows launcher:

```powershell
run_windows.bat
```

## CLI Usage

Generate a barcode image from the built-in profile:

```bash
python linux_barcode_app.py --out barcode.png
python windows_barcode_app.py --out barcode.png
```

Generate at a fixed width and let height scale naturally:

```bash
python windows_barcode_app.py --out barcode.png --dpi 200
```

Force a specific output size:

```bash
python windows_barcode_app.py --out barcode.png --width 400 --height 100
```

Validate profile only:

```bash
python windows_barcode_app.py --validate-only
```

Parse raw AAMVA data:

```bash
python windows_barcode_app.py --parse-aamva raw_aamva.dat
```

## CLI Options

- `--dpi`: Render image DPI for default width output
- `--width`: Optional output width in pixels
- `--height`: Optional output height in pixels
- `--scale`: PDF417 scale factor
- `--columns`: PDF417 column count
- `--ratio`: PDF417 module aspect ratio

## Quick Install (Windows)

Run the installer script once to install Python requirements and create shortcuts on the Desktop and Start Menu:

```powershell
install_windows.bat
```

If shortcut creation fails, the app still works via `run_windows.bat`.

## AddressKit (optional)

This project supports integrating with AddressKit (an open-source Australian address validation API) for the `Verify Address` button. To run AddressKit locally using Docker Compose:

1. Create a `docker-compose.yml` with `opensearch` and `api` services (see AddressKit README).
2. Start the services:

```bash
docker compose up -d
```

3. By default the API listens on port `7234`. In the app, set the Address API URL to `http://localhost:7234` via the `Profile -> Set Address API...` menu.

Note: AddressKit loads G-NAF data and requires additional memory for some Australian states. See the upstream README for detailed instructions: https://github.com/bradleyhodges/addresskit

## AddressKit (optional)

This project supports integrating with AddressKit (an open-source Australian address validation API) for the `Verify Address` button. To run AddressKit locally using Docker Compose:

1. Create a `docker-compose.yml` with `opensearch` and `api` services (see AddressKit README).
2. Start the services:

```bash
docker compose up -d
```

3. By default the API listens on port `7234`. In the app, set the Address API URL to `http://localhost:7234` via the `Profile -> Set Address API...` menu.

Note: AddressKit loads G-NAF data and requires additional memory for some Australian states. See the upstream README for detailed instructions: https://github.com/bradleyhodges/addresskit
