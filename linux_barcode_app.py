#!/usr/bin/env python3
"""
Linux barcode generator and GUI clone for the BarcodeMakerPro project.

This script reproduces the core AAMVA driver's license barcode payload logic from
the macOS Swift app and adds a Linux-friendly Tkinter GUI.

Features:
- CLI mode for headless barcode generation
- Tkinter GUI for interactive barcode creation
- Raw AAMVA data preview and copy-to-clipboard
- Save PNG barcode image and JSON profile files
- Input validation, presets, and sample defaults
- Optimized payload construction and PDF417 rendering

Dependencies:
    pip install -r requirements.txt

Usage:
    python linux_barcode_app.py --gui
    python linux_barcode_app.py --out barcode.png --print-data
    python linux_barcode_app.py --config profile.json --out barcode.png
"""

import argparse
import datetime
import json
import os
import random
import re
import sys

try:
    import tkinter as tk
    from tkinter import messagebox, filedialog, ttk
    from tkinter.scrolledtext import ScrolledText
    from PIL import Image, ImageTk
    from pdf417 import encode, render_image
except ImportError:
    tk = None
    Image = None
    ImageTk = None
    encode = None
    render_image = None

# Simple tooltip helper for Tkinter widgets. Safe no-op when Tk not available.
class ToolTip:
    def __init__(self, widget, text):
        if tk is None:
            return
        self.widget = widget
        self.text = text
        self.tipwindow = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, event=None):
        if getattr(self, 'tipwindow', None) or not getattr(self, 'text', None):
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = ttk.Label(tw, text=self.text, background="#ffffe0", relief="solid", borderwidth=1)
        label.pack()
        self.tipwindow = tw

    def hide(self, event=None):
        tw = getattr(self, 'tipwindow', None)
        self.tipwindow = None
        if tw:
            tw.destroy()


# ---------------------------------------------------------------------------
# Data model and formatting helpers
# ---------------------------------------------------------------------------
class DataElementTruncation:
    Yes = "T"
    No = "N"
    Unknown = "U"


class DataElementGender:
    Male = 1
    Female = 2
    NotSpecified = 3


class DataElementEyeColor:
    Black = "BLK"
    Blue = "BLU"
    Brown = "BRO"
    Dichromaic = "DIC"
    Gray = "GRY"
    Green = "GRN"
    Hazel = "HAZ"
    Maroon = "MAR"
    Pink = "PNK"
    Unknown = "UNK"


class DataElementCountryIdentificationCode:
    US = "USA"
    CA = "CAN"


class DataElementFormatter:
    @staticmethod
    def format_date(value):
        return value.strftime("%m%d%Y")

    @staticmethod
    def format_string(value, length):
        return str(value)[:length]

    @staticmethod
    def format_postal_code(value):
        return (str(value) + "0" * 9)[:9]

    @staticmethod
    def format_eye_color(value):
        return DataElementFormatter.format_string(value, 3)

    @staticmethod
    def format_height(value):
        return DataElementFormatter.format_string(f"{value} IN", 6)


class DataElement:
    def __init__(self, data):
        self.data = data


class DAQ(DataElement):
    def format(self):
        return "DAQ" + DataElementFormatter.format_string(self.data, 25)


class DCS(DataElement):
    def format(self):
        return "DCS" + DataElementFormatter.format_string(self.data, 6)


class DDE(DataElement):
    def format(self):
        return "DDE" + DataElementFormatter.format_string(self.data, 1)


class DAA(DataElement):
    def format(self):
        return "DAA" + DataElementFormatter.format_string(self.data, 40)


class DAC(DataElement):
    def format(self):
        return "DAC" + DataElementFormatter.format_string(self.data, 40)


class DDF(DataElement):
    def format(self):
        return "DDF" + DataElementFormatter.format_string(self.data, 6)


class DAD(DataElement):
    def format(self):
        joined = ",".join(self.data)
        return "DAD" + DataElementFormatter.format_string(joined, 40)


class DDG(DataElement):
    def format(self):
        return "DDG" + DataElementFormatter.format_string(self.data, 6)


class DCA(DataElement):
    def format(self):
        return "DCA" + DataElementFormatter.format_string(self.data, 6)


class DCB(DataElement):
    def format(self):
        return "DCB" + DataElementFormatter.format_string(self.data, 40)


class DCD(DataElement):
    def format(self):
        return "DCD" + DataElementFormatter.format_string(self.data, 5)


class DBD(DataElement):
    def format(self):
        return "DBD" + DataElementFormatter.format_date(self.data)


class DBB(DataElement):
    def format(self):
        return "DBB" + DataElementFormatter.format_date(self.data)


class DBA(DataElement):
    def format(self):
        return "DBA" + DataElementFormatter.format_date(self.data)


class DBC(DataElement):
    def format(self):
        return "DBC" + str(self.data)


class DAU(DataElement):
    def format(self):
        return "DAU" + DataElementFormatter.format_height(self.data)


class DAY(DataElement):
    def format(self):
        return "DAY" + DataElementFormatter.format_eye_color(self.data)


class DAZ(DataElement):
    def format(self):
        return "DAZ" + DataElementFormatter.format_string(self.data, 3)


class DAG(DataElement):
    def format(self):
        return "DAG" + DataElementFormatter.format_string(self.data, 35)


class DAI(DataElement):
    def format(self):
        return "DAI" + DataElementFormatter.format_string(self.data, 20)


class DAJ(DataElement):
    def format(self):
        return "DAJ" + DataElementFormatter.format_string(self.data, 2)


class DAK(DataElement):
    def format(self):
        return "DAK" + DataElementFormatter.format_postal_code(self.data)


class DCF(DataElement):
    def format(self):
        # Document Discriminator length can vary by jurisdiction; do not forcibly truncate here.
        return "DCF" + str(self.data)


class DCG(DataElement):
    def format(self):
        return "DCG" + DataElementFormatter.format_string(self.data, 6)


class Header:
    compliance_indicator = "\x40"
    data_element_separator = "\x0A"
    record_separator = "\x1E"
    segment_terminator = "\x0D"
    file_type = "ANSI "

    def __init__(self, issuer_identification_number, aamva_version_number,
                 jurisdiction_version_number, number_of_entries):
        self.issuerIdentificationNumber = issuer_identification_number
        self.AAMVAVersionNumber = aamva_version_number
        self.jurisdictionVersionNumber = jurisdiction_version_number
        self.numberOfEntries = number_of_entries

    def __str__(self):
        return "".join([
            Header.compliance_indicator,
            Header.data_element_separator,
            Header.record_separator,
            Header.segment_terminator,
            Header.file_type,
            self.issuerIdentificationNumber,
            self.AAMVAVersionNumber,
            self.jurisdictionVersionNumber,
            self.numberOfEntries,
        ])


class Barcode:
    data_element_separator = "\x0A"

    def __init__(self, data_elements, issuer_identification_number,
                 aamva_version_number, jurisdiction_version_number):
        self.dataElements = data_elements
        self.issuerIdentificationNumber = issuer_identification_number
        self.AAMVAVersionNumber = aamva_version_number
        self.jurisdictionVersionNumber = jurisdiction_version_number

    @property
    def description(self):
        header = str(Header(
            issuer_identification_number=self.issuerIdentificationNumber,
            aamva_version_number=self.AAMVAVersionNumber,
            jurisdiction_version_number=self.jurisdictionVersionNumber,
            number_of_entries=str(len(self.dataElements)),
        ))
        formatted_elements = [element.format() for element in self.dataElements]
        joined = Barcode.data_element_separator.join(formatted_elements)
        return header + "DL00300099" + joined

    @property
    def data(self):
        return self.description.encode("ascii")


def generate_pdf417_barcode(text, scale=3, columns=6, security_level=2, padding=4, target_size=(400, 100)):
    if encode is None or render_image is None:
        raise RuntimeError("pdf417 and Pillow must be installed to generate barcode images.")
    codes = encode(text, columns=columns, security_level=security_level)

    if target_size is not None:
        target_width, target_height = target_size
        base_image = render_image(codes, padding=padding, scale=scale).convert("RGB")
        if base_image.width < target_width or base_image.height < target_height:
            scale_w = max(1, target_width // base_image.width)
            scale_h = max(1, target_height // base_image.height)
            dynamic_scale = max(scale, min(scale_w, scale_h))
            barcode_image = render_image(codes, padding=padding, scale=dynamic_scale).convert("RGB")
        else:
            barcode_image = base_image
    else:
        barcode_image = render_image(codes, padding=padding, scale=scale).convert("RGB")

    if target_size is None:
        return barcode_image

    barcode_width, barcode_height = barcode_image.size
    scale_factor = min(target_width / barcode_width, target_height / barcode_height)
    resize_width = max(1, int(barcode_width * scale_factor))
    resize_height = max(1, int(barcode_height * scale_factor))
    if resize_width != barcode_width or resize_height != barcode_height:
        barcode_image = barcode_image.resize((resize_width, resize_height), Image.LANCZOS)

    padded = Image.new("RGB", (target_width, target_height), "white")
    offset_x = (target_width - barcode_image.width) // 2
    offset_y = (target_height - barcode_image.height) // 2
    padded.paste(barcode_image, (offset_x, offset_y))
    return padded


# ---------------------------------------------------------------------------
# Profile helpers and validation
# ---------------------------------------------------------------------------
STATE_CODES = [
    "AK", "AL", "AR", "AS", "AZ", "CA", "CO", "CT", "DC", "DE", "FL",
    "GA", "GU", "HI", "IA", "ID", "IL", "IN", "KS", "KY", "LA", "MA",
    "MD", "ME", "MI", "MN", "MO", "MS", "MT", "NC", "ND", "NE", "NH",
    "NJ", "NM", "NV", "NY", "OH", "OK", "OR", "PA", "PR", "RI", "SC",
    "SD", "TN", "TX", "UT", "VA", "VI", "VT", "WA", "WI", "WV", "WY",
]
DEFAULT_PROFILE = {
    "customer_id": "1234567890",
    "first_name": "Kyle",
    "middle_names": "Brandon",
    "last_name": "Decot",
    "address_line": "123 Main Street",
    "city": "Los Angeles",
    "state_code": "CA",
    "postal_code": "90001",
    "issue_date": "2015-09-14",
    "expiration_date": "2019-09-14",
    "date_of_birth": "1986-09-14",
    "sex": "1",
    "eye_color": "BRO",
    "hair_color": "BRO",
    "country_code": "USA",
    "vehicle_class": "D",
    "endorsement_codes": "NONE",
    "restriction_codes": "NONE",
    "height_in": "70",
    "document_discriminator": "1234567890123456789012345",
    "issuer_id": "636000",
    "aamva_version": "09",
    "jurisdiction_version": "00",
}
SEX_OPTIONS = ["1", "2", "3"]
EYE_COLOR_OPTIONS = [
    DataElementEyeColor.Black,
    DataElementEyeColor.Blue,
    DataElementEyeColor.Brown,
    DataElementEyeColor.Dichromaic,
    DataElementEyeColor.Gray,
    DataElementEyeColor.Green,
    DataElementEyeColor.Hazel,
    DataElementEyeColor.Maroon,
    DataElementEyeColor.Pink,
    DataElementEyeColor.Unknown,
]
COUNTRY_CODES = [DataElementCountryIdentificationCode.US, DataElementCountryIdentificationCode.CA]

HAIR_COLOR_OPTIONS = [
    "BLK",
    "BLN",
    "BRO",
    "GRY",
    "RED",
    "SDY",
    "WHI",
    "BAL",
    "UNK",
]

STATES_WITH_HAIR = {"CA", "NY", "TX", "FL", "WA", "NJ", "PA", "IL"}

STATE_DL_FORMAT_PATTERNS = {
    "AL": r"^\d{1,8}$",
    "AK": r"^\d{1,7}$",
    "AZ": r"^[A-Z]\d{8}$|^\d{9}$",
    "AR": r"^\d{4,9}$",
    "CA": r"^[A-Z]\d{7}$",
    "CO": r"^\d{9}$|^[A-Z]\d{3,6}$|^[A-Z]{2}\d{2,5}$",
    "CT": r"^\d{9}$",
    "DE": r"^\d{1,7}$",
    "DC": r"^\d{7}$|^\d{9}$",
    "FL": r"^[A-Z]\d{12}$",
    "GA": r"^\d{7,9}$",
    "HI": r"^[A-Z]\d{8}$|^\d{9}$",
    "ID": r"^[A-Z]{2}\d{6}[A-Z]$|^\d{9}$",
    "IL": r"^[A-Z]\d{11,12}$",
    "IN": r"^[A-Z]\d{9}$|^\d{9,10}$",
    "IA": r"^\d{9}$|^\d{3}[A-Z]{2}\d{4}$",
    "KS": r"^[A-Z]\d[A-Z]\d[A-Z]$|^[A-Z]\d{8}$|^\d{9}$",
    "KY": r"^[A-Z]\d{8,9}$|^\d{9}$",
    "LA": r"^\d{1,9}$",
    "ME": r"^\d{7}$|^\d{7}[A-Z]$|^\d{8}$",
    "MD": r"^[A-Z]\d{12}$",
    "MA": r"^[A-Z]\d{8}$|^\d{9}$",
    "MI": r"^[A-Z]\d{10}$|^[A-Z]\d{12}$",
    "MN": r"^[A-Z]\d{12}$",
    "MS": r"^\d{9}$",
    "MO": r"^\d{3}[A-Z]\d{6}$|^[A-Z]\d{5,9}$|^[A-Z]\d{6}R$|^\d{8}[A-Z]{2}$|^\d{9}[A-Z]$|^\d{9}$",
    "MT": r"^[A-Z]{3}\d{10}$|^[A-Z]\d{8}$|^\d{9}$|^\d{13,14}$",
    "NE": r"^[A-Z]\d{6,8}$",
    "NV": r"^\d{9,10}$|^\d{12}$|^X\d{8}$",
    "NH": r"^\d{2}[A-Z]{3}\d{5}$",
    "NJ": r"^[A-Z]\d{14}$",
    "NM": r"^\d{8,9}$",
    "NY": r"^[A-Z]\d{7}$|^[A-Z]\d{18}$|^\d{8,9}$|^\d{16}$|^[A-Z]{8}$",
    "NC": r"^\d{1,12}$",
    "ND": r"^[A-Z]{3}\d{6}$|^\d{9}$",
    "OH": r"^[A-Z]\d{4,8}$|^[A-Z]{2}\d{3,7}$|^\d{8}$",
    "OK": r"^[A-Z]\d{9}$|^\d{9}$",
    "OR": r"^\d{1,9}$",
    "PA": r"^\d{8}$",
    "RI": r"^\d{7}$|^[A-Z]\d{6}$",
    "SC": r"^\d{5,11}$",
    "SD": r"^\d{6,10}$|^\d{12}$",
    "TN": r"^\d{7,9}$",
    "TX": r"^\d{7,8}$",
    "UT": r"^\d{4,10}$",
    "VT": r"^\d{8}$|^\d{7}A$",
    "VA": r"^[A-Z]\d{8,11}$|^\d{9}$",
    "WA": r"^[A-Z0-9]{1,12}$",
    "WV": r"^\d{7}$|^[A-Z]{1,2}\d{5,6}$",
    "WI": r"^[A-Z]\d{13}$",
    "WY": r"^\d{9,10}$",
}

STATE_ISSUER_IDS = {
    "AL": "636000",
    "AK": "636001",
    "AZ": "636002",
    "AR": "636003",
    "CA": "636004",
    "CO": "636005",
    "CT": "636006",
    "DC": "636007",
    "DE": "636008",
    "FL": "636009",
    "GA": "636010",
    "GU": "636011",
    "HI": "636012",
    "IA": "636013",
    "ID": "636014",
    "IL": "636015",
    "IN": "636016",
    "KS": "636017",
    "KY": "636018",
    "LA": "636019",
    "MA": "636020",
    "MD": "636021",
    "ME": "636022",
    "MI": "636023",
    "MN": "636024",
    "MO": "636025",
    "MS": "636026",
    "MT": "636027",
    "NC": "636028",
    "ND": "636029",
    "NE": "636030",
    "NH": "636031",
    "NJ": "636032",
    "NM": "636033",
    "NV": "636034",
    "NY": "636035",
    "OH": "636036",
    "OK": "636037",
    "OR": "636038",
    "PA": "636039",
    "PR": "636040",
    "RI": "636041",
    "SC": "636042",
    "SD": "636043",
    "TN": "636044",
    "TX": "636045",
    "UT": "636046",
    "VA": "636047",
    "VT": "636048",
    "WA": "636049",
    "WI": "636050",
    "WV": "636051",
    "WY": "636052",
}

STATE_JURISDICTION_VERSION_DEFAULTS = {
    state: issuer_id[-2:]
    for state, issuer_id in STATE_ISSUER_IDS.items()
}

AAMVA_VERSION_BY_YEAR = [
    ((0, 2010), "06"),
    ((2011, 2012), "07"),
    ((2013, 2014), "08"),
    ((2015, 2016), "09"),
    ((2017, 2018), "10"),
    ((2019, 2020), "11"),
    ((2021, 2022), "12"),
    ((2023, 9999), "13"),
]

DOCUMENT_DISCRIMINATOR_LENGTH = 25

LICENSE_FORMAT_REFERENCE = """
State - License Format
Alabama - 1-8 Numeric
Alaska - 1-7 Numeric
Arizona - 1 Alpha + 8 Numeric, 9 Numeric
Arkansas - 4-9 Numeric
California - 1 Alpha + 7 Numeric
Colorado - 9 Numeric, 1 Alpha + 3-6 Numeric, 2 Alpha + 2-5 Numeric
Connecticut - 9 Numeric
Delaware - 1-7 Numeric
District of Columbia - 7 Numeric, 9 Numeric
Florida - 1 Alpha + 12 Numeric
Georgia - 7-9 Numeric
Hawaii - 1 Alpha + 8 Numeric, 9 Numeric
Idaho - 2 Alpha + 6 Numeric + 1 Alpha, 9 Numeric
Illinois - 1 Alpha + 11-12 Numeric
Indiana - 1 Alpha + 9 Numeric, 9-10 Numeric
Iowa - 9 Numeric, 3 Numeric + 2 Alpha + 4 Numeric
Kansas - 1 Alpha + 1 Numeric + 1 Alpha + 1 Numeric + 1 Alpha, 1 Alpha + 8 Numeric, 9 Numeric
Kentucky - 1 Alpha + 8 Numeric, 1 Alpha + 9 Numeric, 9 Numeric
Louisiana - 1-9 Numeric
Maine - 7 Numeric, 7 Numeric + 1 Alpha, 8 Numeric
Maryland - 1 Alpha + 12 Numeric
Massachusetts - 1 Alpha + 8 Numeric, 9 Numeric
Michigan - 1 Alpha + 10 Numeric, 1 Alpha + 12 Numeric
Minnesota - 1 Alpha + 12 Numeric
Mississippi - 9 Numeric
Missouri - 3 Numeric + 1 Alpha + 6 Numeric, 1 Alpha + 5-9 Numeric, 1 Alpha + 6 Numeric + R, 8 Numeric + 2 Alpha, 9 Numeric + 1 Alpha, 9 Numeric
Montana - 3 Alpha + 10 Numeric, 1 Alpha + 8 Numeric, 9 Numeric, 13-14 Numeric
Nebraska - 1 Alpha + 6-8 Numeric
Nevada - 9-10 Numeric, 12 Numeric, X + 8 Numeric
New Hampshire - 2 Numeric + 3 Alpha + 5 Numeric
New Jersey - 1 Alpha + 14 Numeric
New Mexico - 8-9 Numeric
New York - 1 Alpha + 7 Numeric, 1 Alpha + 18 Numeric, 8-9 Numeric, 16 Numeric, 8 Alpha
North Carolina - 1-12 Numeric
North Dakota - 3 Alpha + 6 Numeric, 9 Numeric
Ohio - 1 Alpha + 4-8 Numeric, 2 Alpha + 3-7 Numeric, 8 Numeric
Oklahoma - 1 Alpha + 9 Numeric, 9 Numeric
Oregon - 1-9 Numeric
Pennsylvania - 8 Numeric
Rhode Island - 7 Numeric, 1 Alpha + 6 Numeric
South Carolina - 5-11 Numeric
South Dakota - 6-10 Numeric, 12 Numeric
Tennessee - 7-9 Numeric
Texas - 7-8 Numeric
Utah - 4-10 Numeric
Vermont - 8 Numeric, 7 Numeric + A
Virginia - 1 Alpha + 8-11 Numeric, 9 Numeric
Washington - 1-7 Alpha + any combination of Alpha/Numeric for 12 characters
West Virginia - 7 Numeric, 1-2 Alpha + 5-6 Numeric
Wisconsin - 1 Alpha + 13 Numeric
Wyoming - 9-10 Numeric
"""

# Per-state document discriminator lengths. Default is 25 unless overridden here.
STATE_DD_LENGTHS = {
    "NV": 21,
    # add other states here if needed
}


def parse_date(value):
    value = str(value).strip()
    if not value:
        raise ValueError("Date is empty")
    for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"]:
        try:
            return datetime.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError("Unable to parse date '{}'. Use YYYY-MM-DD or MM/DD/YYYY.".format(value))


def determine_aamva_version(issue_date):
    year = issue_date.year
    for year_range, version in AAMVA_VERSION_BY_YEAR:
        start, end = year_range
        if start <= year <= end:
            return version
    return DEFAULT_PROFILE["aamva_version"]


def determine_jurisdiction_version(value, state_code=None):
    raw_value = str(value or "").strip()
    digits = re.findall(r"\d", raw_value)
    if len(digits) >= 2:
        return "".join(digits[:2])
    if state_code and state_code in STATE_JURISDICTION_VERSION_DEFAULTS:
        return STATE_JURISDICTION_VERSION_DEFAULTS[state_code]
    return DEFAULT_PROFILE["jurisdiction_version"]


def generate_document_discriminator(version):
    # This generator creates a discriminator prefixed with the two-digit version.
    # Caller may later adjust length depending on jurisdiction/state.
    length = DOCUMENT_DISCRIMINATOR_LENGTH
    prefix = version.zfill(2)
    random_digits = "".join(str(random.randint(0, 9)) for _ in range(max(0, length - len(prefix))))
    return prefix + random_digits


def uses_legacy_name_codes(version):
    try:
        return int(version) < 8
    except (TypeError, ValueError):
        return False


def parse_aamva_header(raw_data):
    if isinstance(raw_data, bytes):
        raw_data = raw_data.decode("ascii", errors="replace")
    if len(raw_data) < 20:
        raise ValueError("AAMVA data too short to contain a valid header.")
    if raw_data[0] != Header.compliance_indicator:
        raise ValueError("Unexpected compliance indicator.")

    file_type = raw_data[4:9]
    issuer_id = raw_data[9:15]
    aamva_version = raw_data[15:17]
    jurisdiction_version = raw_data[17:19]
    subfile_indicator = "DL00300099"
    subfile_pos = raw_data.find(subfile_indicator, 19)
    if subfile_pos < 0:
        raise ValueError("AAMVA subfile designator not found.")

    number_of_entries = raw_data[19:subfile_pos]
    payload = raw_data[subfile_pos + len(subfile_indicator):]
    return {
        "file_type": file_type,
        "issuer_id": issuer_id,
        "aamva_version": aamva_version,
        "jurisdiction_version": jurisdiction_version,
        "number_of_entries": number_of_entries,
        "payload": payload,
    }


def parse_legacy_name(daa_value):
    parts = daa_value.strip().split()
    if len(parts) == 0:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def parse_aamva_elements(payload, version):
    if isinstance(payload, bytes):
        payload = payload.decode("ascii", errors="replace")
    elements = [elem for elem in payload.split(Header.data_element_separator) if elem]
    profile = {}
    for element in elements:
        tag = element[:3]
        value = element[3:]
        if tag == "DAQ":
            profile["customer_id"] = value.strip()
        elif tag == "DCS":
            profile["last_name"] = value.strip()
        elif tag == "DAA" and uses_legacy_name_codes(version):
            first, middle = parse_legacy_name(value)
            profile["first_name"] = first
            profile["middle_names"] = middle
        elif tag == "DAC":
            profile["first_name"] = value.strip()
        elif tag == "DAD":
            profile["middle_names"] = value.strip()
        elif tag == "DBD":
            profile["issue_date"] = parse_date(value)
        elif tag == "DBB":
            profile["date_of_birth"] = parse_date(value)
        elif tag == "DBA":
            profile["expiration_date"] = parse_date(value)
        elif tag == "DBC":
            profile["sex"] = value.strip()
        elif tag == "DAU":
            profile["height_in"] = value.strip().replace(" IN", "")
        elif tag == "DAY":
            profile["eye_color"] = value.strip()
        elif tag == "DAZ":
            profile["hair_color"] = value.strip()
        elif tag == "DAG":
            profile["address_line"] = value.strip()
        elif tag == "DAI":
            profile["city"] = value.strip()
        elif tag == "DAJ":
            profile["state_code"] = value.strip()
        elif tag == "DAK":
            profile["postal_code"] = value.strip()
        elif tag == "DCF":
            profile["document_discriminator"] = value.strip()
        elif tag == "DCG":
            profile["country_code"] = value.strip()
        elif tag == "DCA":
            profile["vehicle_class"] = value.strip()
        elif tag == "DCB":
            profile["restriction_codes"] = value.strip()
        elif tag == "DCD":
            profile["endorsement_codes"] = value.strip()
    return profile


def parse_aamva_data(raw_data):
    header = parse_aamva_header(raw_data)
    version = header["aamva_version"]
    profile = parse_aamva_elements(header["payload"], version)
    profile["issuer_id"] = header["issuer_id"]
    profile["aamva_version"] = version
    profile["jurisdiction_version"] = header["jurisdiction_version"]
    return profile


def verify_address_with_api(profile, api_url, api_key=None, timeout=10):
    """Verify the address using a generic address verification API.

    The function expects an API that accepts JSON with fields: street, city, state, postal_code.
    It returns a dict with keys `success` (bool) and either `normalized` (dict) or `error`.
    """
    try:
        import requests
    except Exception as exc:
        return {"success": False, "error": f"requests not available: {exc}"}

    payload = {
        "street": profile.get("address_line", ""),
        "city": profile.get("city", ""),
        "state": profile.get("state_code", ""),
        "postal_code": profile.get("postal_code", ""),
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=timeout)
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    if resp.status_code != 200:
        return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text}"}
    try:
        data = resp.json()
    except Exception:
        return {"success": False, "error": "Invalid JSON response"}

    # Best-effort interpretation
    if data.get("valid") is True or data.get("is_valid") is True:
        normalized = data.get("normalized") or data.get("address") or payload
        return {"success": True, "normalized": normalized}
    if data.get("suggestions"):
        return {"success": True, "normalized": data.get("suggestions")[0]}
    return {"success": False, "error": data}


def addresskit_search(api_url, query, timeout=8):
    """Search AddressKit `/addresses?q=` endpoint and return suggestions list.

    Returns list of {'id': pid, 'sla': sla} entries.
    """
    try:
        import requests
    except Exception as exc:
        return {"success": False, "error": f"requests not available: {exc}", "results": []}

    base = api_url.rstrip("/")
    # If the user provided the full addresses endpoint, use it; otherwise append
    if "/addresses" in base:
        url = base
    else:
        url = f"{base}/addresses"
    params = {"q": query}
    headers = {"Accept": "application/vnd.api+json"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    except Exception as exc:
        return {"success": False, "error": str(exc), "results": []}
    if resp.status_code != 200:
        return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text}", "results": []}
    try:
        data = resp.json()
    except Exception as exc:
        return {"success": False, "error": f"Invalid JSON: {exc}", "results": []}
    results = []
    for item in data.get("data", []):
        attrs = item.get("attributes", {})
        sla = attrs.get("sla") or attrs.get("display") or attrs.get("ssla")
        results.append({"id": item.get("id"), "sla": sla})
    return {"success": True, "results": results}


def addresskit_get_details(api_url, pid, timeout=8):
    try:
        import requests
    except Exception as exc:
        return {"success": False, "error": f"requests not available: {exc}"}
    base = api_url.rstrip("/")
    if "/addresses/" in base:
        url = base
    else:
        url = f"{base}/addresses/{pid}"
    headers = {"Accept": "application/vnd.api+json"}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    if resp.status_code != 200:
        return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text}"}
    try:
        data = resp.json()
    except Exception as exc:
        return {"success": False, "error": f"Invalid JSON: {exc}"}
    return {"success": True, "data": data}


def build_barcode_profile(profile):
    elements = [
        DAQ(profile["customer_id"]),
        DCS(profile["last_name"]),
        DDE(DataElementTruncation.No),
    ]

    if uses_legacy_name_codes(profile.get("aamva_version", "00")):
        combined_name = " ".join([profile["first_name"].strip(), profile["middle_names"].strip()]).strip()
        elements.append(DAA(combined_name))
    else:
        elements.append(DAC(profile["first_name"]))
        middle_names = [name.strip() for name in profile["middle_names"].split(",") if name.strip()]
        if middle_names:
            elements.append(DAD(middle_names))

    elements.extend([
        DDF(DataElementTruncation.No),
        DDG(DataElementTruncation.No),
        DCA(profile["vehicle_class"]),
        DCB(profile["restriction_codes"]),
        DCD(profile["endorsement_codes"]),
        DBD(parse_date(profile["issue_date"])),
        DBB(parse_date(profile["date_of_birth"])),
        DBA(parse_date(profile["expiration_date"])),
        DBC(int(profile["sex"])),
        DAU(int(profile["height_in"])),
        DAY(profile["eye_color"]),
    ])
    hair_color = profile.get("hair_color", "").strip()
    if hair_color:
        elements.append(DAZ(hair_color))
    elements.extend([
        DAG(profile["address_line"]),
        DAI(profile["city"]),
        DAJ(profile["state_code"]),
        DAK(profile["postal_code"]),
        DCF(profile["document_discriminator"]),
        DCG(profile["country_code"]),
    ])

    return Barcode(elements,
       issuer_identification_number=profile["issuer_id"],
       aamva_version_number=profile["aamva_version"],
       jurisdiction_version_number=profile["jurisdiction_version"])


def validate_profile(profile):
    errors = []
    if not profile["customer_id"].strip():
        errors.append("Customer ID cannot be empty.")
    if not profile["last_name"].strip():
        errors.append("Last name cannot be empty.")
    if not profile["first_name"].strip():
        errors.append("First name cannot be empty.")
    try:
        issue_date = parse_date(profile["issue_date"])
    except ValueError as exc:
        errors.append(str(exc))
        issue_date = None
    try:
        expiration_date = parse_date(profile["expiration_date"])
    except ValueError as exc:
        errors.append(str(exc))
        expiration_date = None
    try:
        date_of_birth = parse_date(profile["date_of_birth"])
    except ValueError as exc:
        errors.append(str(exc))
        date_of_birth = None
    if issue_date and expiration_date and expiration_date <= issue_date:
        errors.append("Expiration date must be after issue date.")
    if date_of_birth and issue_date and date_of_birth >= issue_date:
        errors.append("Date of birth must be before issue date.")
    if profile["state_code"] not in STATE_CODES:
        errors.append("State code must be one of: {}".format(", ".join(STATE_CODES)))
    if profile["sex"] not in SEX_OPTIONS:
        errors.append("Sex must be 1, 2, or 3.")
    if profile["eye_color"] not in EYE_COLOR_OPTIONS:
        errors.append("Eye color must be one of: {}".format(", ".join(EYE_COLOR_OPTIONS)))
    hair_color = profile.get("hair_color", "").strip()
    if hair_color and hair_color not in HAIR_COLOR_OPTIONS:
        errors.append("Hair color must be one of: {}".format(", ".join(HAIR_COLOR_OPTIONS)))
    if profile["country_code"] not in COUNTRY_CODES:
        errors.append("Country code must be one of: {}".format(", ".join(COUNTRY_CODES)))
    try:
        height = int(profile["height_in"])
        if height <= 0:
            raise ValueError()
    except ValueError:
        errors.append("Height must be a positive integer.")
    if not profile["issuer_id"].strip():
        errors.append("Issuer ID cannot be empty.")
    if not re.fullmatch(r"\d{2}", profile["aamva_version"].strip()):
        errors.append("AAMVA version must be a two-digit number.")
    if not re.fullmatch(r"\d{2}", profile["jurisdiction_version"].strip()):
        errors.append("Jurisdiction version must be a two-digit number.")
    dd = profile["document_discriminator"].strip()
    expected_dd_len = STATE_DD_LENGTHS.get(profile.get("state_code"), DOCUMENT_DISCRIMINATOR_LENGTH)
    if not dd:
        errors.append("Document discriminator cannot be empty.")
    elif not re.fullmatch(r"[A-Za-z0-9]{%d}" % expected_dd_len, dd):
        errors.append(f"Document discriminator must be {expected_dd_len} alphanumeric characters for state {profile.get('state_code')}")
    if profile["state_code"] in STATE_DL_FORMAT_PATTERNS:
        pattern = STATE_DL_FORMAT_PATTERNS[profile["state_code"]]
        if not re.fullmatch(pattern, profile["customer_id"].strip()):
            errors.append(f"Customer ID does not match {profile['state_code']} format.")

    if issue_date and re.fullmatch(r"\d{2}", profile["aamva_version"].strip()):
        expected_version = determine_aamva_version(issue_date)
        if profile["aamva_version"].strip() != expected_version:
            errors.append(
                f"AAMVA version {profile['aamva_version']} does not match expected version {expected_version} for issue year {issue_date.year}."
            )

    if not re.fullmatch(r"\d{2}", profile["jurisdiction_version"].strip()):
        errors.append("Jurisdiction version must be a two-digit number.")
    return errors


def load_profile(path):
    with open(path, "r", encoding="utf-8") as handle:
        profile = json.load(handle)
    data = DEFAULT_PROFILE.copy()
    data.update(profile)
    return data


def save_profile(path, profile):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(profile, handle, indent=2)


# ---------------------------------------------------------------------------
# GUI implementation
# ---------------------------------------------------------------------------
class BarcodeApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Linux AAMVA Barcode Generator")
        self.resizable(True, True)
        self.profile = DEFAULT_PROFILE.copy()
        self.photo = None
        self.state_code_previous = None
        self.jurisdiction_locked = False
        self._build_ui()
        self._populate_fields()
        self.state_code_previous = self.fields.get("state_code").variable.get().strip() if isinstance(self.fields.get("state_code"), ttk.OptionMenu) else None
        self._generate_barcode_preview()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        left_frame = ttk.Frame(self, padding=(10, 10))
        left_frame.grid(row=0, column=0, sticky="nsew")
        right_frame = ttk.Frame(self, padding=(10, 10))
        right_frame.grid(row=0, column=1, sticky="nsew")

        field_spec = [
            ("Customer ID", "customer_id"),
            ("First Name", "first_name"),
            ("Middle Names", "middle_names"),
            ("Last Name", "last_name"),
            ("Address", "address_line"),
            ("City", "city"),
            ("State", "state_code", STATE_CODES),
            ("Postal Code", "postal_code"),
            ("Issue Date", "issue_date"),
            ("Expiration Date", "expiration_date"),
            ("Date of Birth", "date_of_birth"),
            ("Sex", "sex", SEX_OPTIONS),
            ("Eye Color", "eye_color", EYE_COLOR_OPTIONS),
            ("Hair Color", "hair_color", HAIR_COLOR_OPTIONS),
            ("Country", "country_code", COUNTRY_CODES),
            ("Vehicle Class", "vehicle_class"),
            ("Restriction Codes", "restriction_codes"),
            ("Endorsement Codes", "endorsement_codes"),
            ("Height (in)", "height_in"),
            ("Document Discriminator", "document_discriminator"),
            ("Issuer ID", "issuer_id"),
            ("AAMVA Version", "aamva_version"),
            ("Jurisdiction Version", "jurisdiction_version"),
        ]

        self.fields = {}
        for index, spec in enumerate(field_spec):
            label_text = spec[0]
            key = spec[1]
            widget = self._create_field_widget(left_frame, index, label_text, key, spec[2] if len(spec) > 2 else None)
            self.fields[key] = widget
            if key == "state_code" and isinstance(widget, ttk.OptionMenu):
                widget.variable.trace_add("write", lambda *args, var=widget.variable: self.on_state_code_changed(var))
            if key == "jurisdiction_version" and isinstance(widget, ttk.Entry):
                self.jurisdiction_widget = widget
                # small status label next to the jurisdiction field to show auto-fill/lock
                try:
                    self.jurisdiction_note = ttk.Label(left_frame, text="", foreground="blue")
                    self.jurisdiction_note.grid(row=index, column=2, sticky="w", padx=(6, 0))
                    self.jurisdiction_lock_button = ttk.Button(left_frame, text="Unlock", width=7, command=self._toggle_jurisdiction_lock)
                    self.jurisdiction_lock_button.grid(row=index, column=3, sticky="w", padx=(6, 0))
                    # tooltip for clarity
                    try:
                        ToolTip(self.jurisdiction_lock_button, "Toggle jurisdiction version lock")
                    except Exception:
                        pass
                except Exception:
                    self.jurisdiction_note = None
                    self.jurisdiction_lock_button = None

        issue_widget = self.fields.get("issue_date")
        if isinstance(issue_widget, ttk.Entry):
            issue_widget.bind("<FocusOut>", lambda event: self.on_issue_date_changed())
            issue_widget.bind("<Return>", lambda event: self.on_issue_date_changed())

        button_frame = ttk.Frame(left_frame)
        button_frame.grid(row=len(field_spec), column=0, columnspan=2, pady=(10, 0), sticky="ew")
        button_frame.columnconfigure((0, 1, 2, 3, 4, 5, 6), weight=1)

        generate_button = ttk.Button(button_frame, text="Generate", command=self.on_generate_clicked)
        generate_button.grid(row=0, column=0, sticky="ew", padx=2)
        save_button = ttk.Button(button_frame, text="Save Image", command=self.on_save_image_clicked)
        save_button.grid(row=0, column=1, sticky="ew", padx=2)
        copy_button = ttk.Button(button_frame, text="Copy Raw", command=self.on_copy_raw_data)
        copy_button.grid(row=0, column=2, sticky="ew", padx=2)
        validate_button = ttk.Button(button_frame, text="Validate", command=self.on_validate_clicked)
        validate_button.grid(row=0, column=3, sticky="ew", padx=2)
        verify_addr_button = ttk.Button(button_frame, text="Verify Address", command=self.on_verify_address_clicked)
        verify_addr_button.grid(row=0, column=4, sticky="ew", padx=2)
        profile_button = ttk.Button(button_frame, text="Profile", command=self.on_profile_menu)
        profile_button.grid(row=0, column=4, sticky="ew", padx=2)
        generate_dd_button = ttk.Button(button_frame, text="Generate DD", command=self.on_generate_dd_clicked)
        generate_dd_button.grid(row=0, column=5, sticky="ew", padx=2)
        self.reference_button = ttk.Button(button_frame, text="Show Format Tip", command=self.toggle_reference)
        self.reference_button.grid(row=0, column=6, sticky="ew", padx=2)

        self.reference_frame = ttk.Frame(left_frame)
        self.reference_frame.grid(row=len(field_spec) + 1, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        self.reference_frame.columnconfigure(0, weight=1)
        self.reference_frame.rowconfigure(2, weight=1)

        search_frame = ttk.Frame(self.reference_frame)
        search_frame.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        search_frame.columnconfigure(1, weight=1)

        ttk.Label(search_frame, text="Search state:").grid(row=0, column=0, sticky="w")
        self.reference_search_var = tk.StringVar()
        self.reference_search_entry = ttk.Entry(search_frame, textvariable=self.reference_search_var)
        self.reference_search_entry.grid(row=0, column=1, sticky="ew", padx=(4, 4))
        self.reference_search_entry.bind("<Return>", lambda event: self._search_reference())
        search_button = ttk.Button(search_frame, text="Find", command=self._search_reference)
        search_button.grid(row=0, column=2, sticky="e")

        self.reference_text = ScrolledText(self.reference_frame, wrap="word", height=12)
        self.reference_text.grid(row=2, column=0, sticky="nsew")
        self.reference_text.insert(tk.END, LICENSE_FORMAT_REFERENCE)
        self.reference_text.configure(state="disabled")
        self.reference_text.tag_configure("highlight", background="#ffff99")
        self.reference_frame.grid_remove()

        self.status_label = ttk.Label(left_frame, text="Ready to generate barcode.")
        self.status_label.grid(row=len(field_spec) + 2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.uppercase_label = ttk.Label(left_frame, text="(All fields UPPERCASE)", foreground="gray")
        self.uppercase_label.grid(row=len(field_spec) + 2, column=2, columnspan=2, sticky="w", pady=(6, 0))

        image_frame = ttk.LabelFrame(right_frame, text="PDF417 Preview")
        image_frame.grid(row=0, column=0, sticky="nsew")
        image_frame.columnconfigure(0, weight=1)
        image_frame.rowconfigure(0, weight=1)

        self.image_label = ttk.Label(image_frame)
        self.image_label.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        data_frame = ttk.LabelFrame(right_frame, text="Raw AAMVA Data")
        data_frame.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        data_frame.columnconfigure(0, weight=1)
        data_frame.rowconfigure(0, weight=1)

        self.raw_data_text = ScrolledText(data_frame, wrap="none", height=12)
        self.raw_data_text.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self.raw_data_text.configure(state="disabled")

    def _create_field_widget(self, parent, row, label_text, field_key, options=None):
        label = ttk.Label(parent, text=label_text)
        label.grid(row=row, column=0, sticky="w", pady=2)
        if options is not None:
            variable = tk.StringVar(value=options[0])
            widget = ttk.OptionMenu(parent, variable, options[0], *options)
            widget.variable = variable
            # ensure option selections are uppercase
            try:
                variable.trace_add("write", lambda *args, var=variable: var.set(var.get().upper()) if var.get() != var.get().upper() else None)
            except Exception:
                pass
            widget.grid(row=row, column=1, sticky="ew", pady=2)
            widget._label = label
        else:
            entry = ttk.Entry(parent)
            entry.grid(row=row, column=1, sticky="ew", pady=2)
            # enforce uppercase while typing and on focus out, preserving cursor
            def _enforce(e, w=entry):
                try:
                    s = w.get()
                except Exception:
                    return
                ns = s.upper()
                if s != ns:
                    try:
                        pos = w.index(tk.INSERT)
                    except Exception:
                        pos = None
                    w.delete(0, tk.END)
                    w.insert(0, ns)
                    if pos is not None:
                        try:
                            w.icursor(pos)
                        except Exception:
                            pass
            try:
                entry.bind("<KeyRelease>", _enforce)
                entry.bind("<FocusOut>", _enforce)
            except Exception:
                pass
            widget = entry
            widget._label = label
        parent.columnconfigure(1, weight=1)
        return widget

    def _populate_fields(self):
        for key, widget in self.fields.items():
            value = self.profile.get(key, "")
            # normalize to string and uppercase for display consistency
            value = str(value).upper()
            if isinstance(widget, ttk.OptionMenu):
                try:
                    widget.variable.set(value)
                except Exception:
                    pass
            else:
                try:
                    widget.delete(0, tk.END)
                    widget.insert(0, value)
                except Exception:
                    pass
        self.on_issue_date_changed()

    def _collect_profile(self):
        profile = {}
        for key, widget in self.fields.items():
            if isinstance(widget, ttk.OptionMenu):
                try:
                    profile[key] = widget.variable.get().strip().upper()
                except Exception:
                    profile[key] = str(widget.variable.get()).strip().upper()
            else:
                try:
                    profile[key] = widget.get().strip().upper()
                except Exception:
                    profile[key] = str(widget.get()).strip().upper()
        return profile

    def _set_jurisdiction_editable(self, editable):
        widget = getattr(self, "jurisdiction_widget", None)
        if widget is None:
            return
        widget.configure(state="normal" if editable else "disabled")
        self.jurisdiction_locked = not editable
        # update small UI note if present
        note = getattr(self, "jurisdiction_note", None)
        if note is not None:
            try:
                note.configure(text="" if editable else "(auto-filled)")
            except Exception:
                pass
        # update lock button label
        lock_btn = getattr(self, "jurisdiction_lock_button", None)
        if lock_btn is not None:
            try:
                lock_btn.configure(text=("Lock" if editable else "Unlock"))
            except Exception:
                pass

    def _toggle_jurisdiction_lock(self):
        # toggle between editable and locked
        # call with current locked state to flip (if locked -> make editable True)
        self._set_jurisdiction_editable(self.jurisdiction_locked)

    def on_state_code_changed(self, variable=None):
        state_code = None
        if variable is not None:
            state_code = variable.get().strip()
        else:
            state_widget = self.fields.get("state_code")
            if isinstance(state_widget, ttk.OptionMenu):
                state_code = state_widget.variable.get().strip()
        if not state_code:
            return

        issuer_widget = self.fields.get("issuer_id")
        if not isinstance(issuer_widget, ttk.Entry):
            return

        expected_issuer = STATE_ISSUER_IDS.get(state_code)
        if not expected_issuer:
            self.state_code_previous = state_code
            return

        current_issuer = issuer_widget.get().strip()
        previous_issuer = STATE_ISSUER_IDS.get(self.state_code_previous, "")
        if not current_issuer or current_issuer == previous_issuer or current_issuer == DEFAULT_PROFILE["issuer_id"]:
            issuer_widget.delete(0, tk.END)
            issuer_widget.insert(0, expected_issuer)
            self._set_status(f"Issuer ID auto-filled for {state_code}.")

        self.state_code_previous = state_code
        # show/hide hair color depending on state
        hair_widget = self.fields.get("hair_color")
        if hair_widget is not None:
            show = state_code in STATES_WITH_HAIR
            # widget may be OptionMenu with associated label stored in _label
            lbl = getattr(hair_widget, "_label", None)
            if lbl:
                if show:
                    lbl.grid()
                else:
                    lbl.grid_remove()
            try:
                if show:
                    hair_widget.grid()
                else:
                    hair_widget.grid_remove()
            except Exception:
                pass

    def on_generate_clicked(self):
        self._generate_barcode_preview()

    def on_save_image_clicked(self):
        profile = self._collect_profile()
        errors = validate_profile(profile)
        if errors:
            self._set_status("Validation failed: {}".format(errors[0]), error=True)
            return

        barcode = build_barcode_profile(profile)
        text = barcode.description
        try:
            image = generate_pdf417_barcode(text, target_size=(400, 100))
        except Exception as exc:
            messagebox.showerror("Barcode Generation Error", str(exc))
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG Image", "*.png")],
            title="Save PDF417 Barcode Image",
        )
        if not path:
            return
        image.save(path)
        self._set_status(f"Image saved to {path}")

    def on_copy_raw_data(self):
        profile = self._collect_profile()
        errors = validate_profile(profile)
        if errors:
            self._set_status("Validation failed: {}".format(errors[0]), error=True)
            return
        barcode = build_barcode_profile(profile)
        raw_text = barcode.description
        self.clipboard_clear()
        self.clipboard_append(raw_text)
        self._set_status("Raw data copied to clipboard.")

    def on_profile_menu(self):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Load Profile", command=self._load_profile_dialog)
        menu.add_command(label="Save Profile", command=self._save_profile_dialog)
        menu.add_command(label="Set Address API...", command=self._set_address_api_dialog)
        menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())

    def _load_profile_dialog(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
            title="Load Profile",
        )
        if not path:
            return
        try:
            profile = load_profile(path)
            self.profile = profile
            self._populate_fields()
            self._generate_barcode_preview()
            self._set_status(f"Profile loaded from {path}")
        except Exception as exc:
            messagebox.showerror("Load Error", str(exc))

    def _save_profile_dialog(self):
        profile = self._collect_profile()
        errors = validate_profile(profile)
        if errors:
            self._set_status("Validation failed: {}".format(errors[0]), error=True)
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json")],
            title="Save Profile",
        )
        if not path:
            return
        try:
            save_profile(path, profile)
            self._set_status(f"Profile saved to {path}")
        except Exception as exc:
            messagebox.showerror("Save Error", str(exc))

    def _set_address_api_dialog(self):
        def on_ok():
            url = url_entry.get().strip()
            key = key_entry.get().strip()
            if not url:
                messagebox.showerror("Invalid", "API URL is required")
                return
            self.profile["address_api_url"] = url
            self.profile["address_api_key"] = key
            dlg.destroy()
            self._set_status("Address API set.")

        dlg = tk.Toplevel(self)
        dlg.title("Set Address API")
        ttk.Label(dlg, text="API URL:").grid(row=0, column=0, sticky="w")
        url_entry = ttk.Entry(dlg, width=60)
        url_entry.grid(row=0, column=1, sticky="ew")
        ttk.Label(dlg, text="API Key (optional):").grid(row=1, column=0, sticky="w")
        key_entry = ttk.Entry(dlg, width=60)
        key_entry.grid(row=1, column=1, sticky="ew")
        ok = ttk.Button(dlg, text="OK", command=on_ok)
        ok.grid(row=2, column=0, columnspan=2)
        dlg.transient(self)
        dlg.grab_set()
        self.wait_window(dlg)

    def _generate_barcode_preview(self):
        profile = self._collect_profile()
        errors = validate_profile(profile)
        if errors:
            self._set_status("Validation failed: {}".format(errors[0]), error=True)
            return
        try:
            barcode = build_barcode_profile(profile)
            image = generate_pdf417_barcode(barcode.description, target_size=(400, 100))
            self._render_image(image)
            self._set_status("Barcode generated successfully.")
            self._set_raw_text(barcode.description)
        except Exception as exc:
            self._set_status(f"Generate failed: {exc}", error=True)

    def on_generate_dd_clicked(self):
        version_widget = self.fields.get("aamva_version")
        discriminator_widget = self.fields.get("document_discriminator")
        if not isinstance(discriminator_widget, ttk.Entry):
            return
        version = "00"
        if isinstance(version_widget, ttk.Entry):
            version = version_widget.get().strip() or version
        # Determine expected length for the selected state
        state_code = None
        state_widget = self.fields.get("state_code")
        if isinstance(state_widget, ttk.OptionMenu):
            state_code = state_widget.variable.get().strip()
        expected_len = STATE_DD_LENGTHS.get(state_code, DOCUMENT_DISCRIMINATOR_LENGTH)
        base = generate_document_discriminator(version)
        # If base is shorter than expected, pad random digits; if longer, truncate
        if len(base) < expected_len:
            extra = "".join(str(random.randint(0, 9)) for _ in range(expected_len - len(base)))
            generated = base + extra
        else:
            generated = base[:expected_len]
        discriminator_widget.delete(0, tk.END)
        discriminator_widget.insert(0, generated)
        self._set_status("Generated document discriminator for version {}.".format(version))

    def on_validate_clicked(self):
        profile = self._collect_profile()
        errors = validate_profile(profile)
        if errors:
            messagebox.showerror("Validation Errors", "\n".join(errors))
            self._set_status("Validation failed.", error=True)
        else:
            self._set_status("Validation passed.")
            messagebox.showinfo("Validation Passed", "Profile is valid for AAMVA formatting.")

    def on_verify_address_clicked(self):
        profile = self._collect_profile()
        api_url = self.profile.get("address_api_url") or profile.get("address_api_url")
        api_key = self.profile.get("address_api_key") or profile.get("address_api_key")
        if not api_url:
            if messagebox.askyesno("Address API not configured", "No address API configured. Would you like to set one now?"):
                self._set_address_api_dialog()
                api_url = self.profile.get("address_api_url")
        if not api_url:
            self._set_status("Address API not configured.", error=True)
            return

        # For AddressKit (Australian) use the autocomplete endpoint
        query = " ".join(filter(None, [profile.get("address_line", ""), profile.get("city", ""), profile.get("state_code", ""), profile.get("postal_code", "")]))
        if not query.strip():
            messagebox.showerror("No address", "Please enter at least an address line, city, state or postal code to search.")
            return

        if "addresskit" in api_url or "/addresses" in api_url:
            res = addresskit_search(api_url, query)
            if not res.get("success"):
                messagebox.showerror("Address Search Failed", str(res.get("error")))
                self._set_status("Address search failed.", error=True)
                return
            results = res.get("results", [])
            if not results:
                messagebox.showinfo("No Results", "No address suggestions found.")
                self._set_status("No suggestions found.")
                return
            first = results[0]
            sla = first.get("sla") or ""
            if not sla:
                messagebox.showinfo("Suggestion Found", "Found suggestions but no display address available.")
                self._set_status("Suggestion found but no display address.")
                return
            use = messagebox.askyesno("Use suggestion?", f"Use suggested address:\n\n{sla}\n\nAccept suggestion and populate fields?")
            if not use:
                self._set_status("User declined suggestion.")
                return
            # fetch details and populate
            pid = first.get("id")
            details = addresskit_get_details(api_url, pid)
            if not details.get("success"):
                messagebox.showerror("Details Failed", str(details.get("error")))
                self._set_status("Failed to fetch address details.", error=True)
                return
            data = details.get("data", {})
            attrs = data.get("data", {}).get("attributes", {}) if isinstance(data, dict) else {}
            structured = attrs.get("structured", {}) if isinstance(attrs, dict) else {}
            # Friendly mapping back to fields
            new_address = attrs.get("ssla") or attrs.get("sla") or profile.get("address_line")
            new_city = None
            new_state = None
            new_postal = None
            if structured:
                new_city = structured.get("locality", {}).get("name") if structured.get("locality") else None
                state_obj = structured.get("state") or {}
                new_state = state_obj.get("abbreviation") or state_obj.get("name")
                new_postal = structured.get("postcode") or structured.get("postcodes") and structured.get("postcodes")[0]
            # Apply normalized values to widgets
            try:
                if new_address:
                    widget = self.fields.get("address_line")
                    if widget and isinstance(widget, ttk.Entry):
                        widget.delete(0, tk.END)
                        widget.insert(0, str(new_address).upper())
                if new_city:
                    widget = self.fields.get("city")
                    if widget and isinstance(widget, ttk.Entry):
                        widget.delete(0, tk.END)
                        widget.insert(0, str(new_city).upper())
                if new_state:
                    widget = self.fields.get("state_code")
                    if widget and isinstance(widget, ttk.OptionMenu):
                        try:
                            widget.variable.set(str(new_state).upper())
                        except Exception:
                            pass
                if new_postal:
                    widget = self.fields.get("postal_code")
                    if widget and isinstance(widget, ttk.Entry):
                        widget.delete(0, tk.END)
                        widget.insert(0, str(new_postal).upper())
            except Exception:
                pass
            self._set_status("Address suggestion applied.")
            return

        # Generic API fallback
        res = verify_address_with_api(profile, api_url, api_key)
        if not res.get("success"):
            messagebox.showerror("Address Verify Failed", str(res.get("error")))
            self._set_status("Address verification failed.", error=True)
            return
        norm = res.get("normalized")
        if not norm:
            messagebox.showinfo("No normalization", "Address service did not return normalized address.")
            return
        use = messagebox.askyesno("Use normalized address?", json.dumps(norm, indent=2))
        if not use:
            self._set_status("User declined normalized address.")
            return
        try:
            if norm.get("street"):
                widget = self.fields.get("address_line")
                if widget and isinstance(widget, ttk.Entry):
                    widget.delete(0, tk.END)
                    widget.insert(0, str(norm.get("street")).upper())
            if norm.get("city"):
                widget = self.fields.get("city")
                if widget and isinstance(widget, ttk.Entry):
                    widget.delete(0, tk.END)
                    widget.insert(0, str(norm.get("city")).upper())
            if norm.get("state"):
                widget = self.fields.get("state_code")
                if widget and isinstance(widget, ttk.OptionMenu):
                    try:
                        widget.variable.set(str(norm.get("state")).upper())
                    except Exception:
                        pass
            if norm.get("postal_code"):
                widget = self.fields.get("postal_code")
                if widget and isinstance(widget, ttk.Entry):
                    widget.delete(0, tk.END)
                    widget.insert(0, str(norm.get("postal_code")).upper())
        except Exception:
            pass
        self._set_status("Address verification applied.")

    def _render_image(self, image):
        resized = image.resize((min(image.width, 500), min(image.height, 200)))
        self.photo = ImageTk.PhotoImage(resized)
        self.image_label.configure(image=self.photo)

    def toggle_reference(self):
        if self.reference_frame.winfo_viewable():
            self.reference_frame.grid_remove()
            self.reference_button.configure(text="Show Format Tip")
        else:
            self.reference_frame.grid()
            self.reference_button.configure(text="Hide Format Tip")

    def _search_reference(self):
        query = self.reference_search_var.get().strip()
        self.reference_text.configure(state="normal")
        self.reference_text.tag_remove("highlight", "1.0", tk.END)
        if query:
            query_lower = query.lower()
            lines = self.reference_text.get("1.0", tk.END).splitlines()
            found = False
            for index, line in enumerate(lines):
                if line.lower().startswith(query_lower):
                    start = f"{index + 1}.0"
                    end = f"{index + 1}.end"
                    self.reference_text.tag_add("highlight", start, end)
                    if not found:
                        self.reference_text.see(start)
                        found = True
            if found:
                self._set_status(f"Found state '{query}' in reference.")
            else:
                self._set_status(f"No matching state name for '{query}'.", error=True)
        else:
            self._set_status("Cleared reference search.")
        self.reference_text.configure(state="disabled")

    def on_issue_date_changed(self):
        issue_widget = self.fields.get("issue_date")
        version_widget = self.fields.get("aamva_version")
        jurisdiction_widget = self.fields.get("jurisdiction_version")
        state_widget = self.fields.get("state_code")
        state_code = None
        if isinstance(state_widget, ttk.OptionMenu):
            state_code = state_widget.variable.get().strip()

        if not issue_widget or not isinstance(issue_widget, ttk.Entry):
            return
        issue_value = issue_widget.get().strip()
        if not issue_value:
            return
        try:
            issue_date = parse_date(issue_value)
        except ValueError:
            return

        version = determine_aamva_version(issue_date)
        if isinstance(version_widget, ttk.Entry):
            current_value = version_widget.get().strip()
            if current_value != version:
                version_widget.delete(0, tk.END)
                version_widget.insert(0, version)
                self._set_status(f"AAMVA version auto-filled: {version}")

        if isinstance(jurisdiction_widget, ttk.Entry):
            current_value = jurisdiction_widget.get().strip()
            preferred = determine_jurisdiction_version(current_value, state_code)
            if current_value != preferred:
                if self.jurisdiction_locked:
                    self._set_jurisdiction_editable(True)
                jurisdiction_widget.delete(0, tk.END)
                jurisdiction_widget.insert(0, preferred)
                self._set_status(f"Jurisdiction version auto-filled: {preferred}")
                self._set_jurisdiction_editable(False)

    def _set_raw_text(self, text):
        self.raw_data_text.configure(state="normal")
        self.raw_data_text.delete("1.0", tk.END)
        self.raw_data_text.insert(tk.END, text)
        self.raw_data_text.configure(state="disabled")

    def _set_status(self, message, error=False):
        self.status_label.configure(text=message, foreground="red" if error else "black")


def run_gui():
    if tk is None or ImageTk is None or encode is None:
        raise RuntimeError("Missing GUI dependencies: install pdf417, Pillow, and tkinter.")
    app = BarcodeApp()
    app.mainloop()


# ---------------------------------------------------------------------------
# CLI implementation
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(description="Linux AAMVA barcode generator clone")
    parser.add_argument("--gui", action="store_true", help="Launch the Tkinter GUI")
    parser.add_argument("--out", default="barcode.png", help="Output PNG image path")
    parser.add_argument("--print-data", action="store_true", help="Print raw AAMVA data string")
    parser.add_argument("--config", help="Load profile from JSON file")
    parser.add_argument("--save-profile", help="Write the active profile to a JSON file")
    parser.add_argument("--validate-only", action="store_true", help="Validate profile only and exit")
    parser.add_argument("--dpi", type=int, default=200, help="Render image at this DPI for 2x0.5 inch output")
    parser.add_argument("--scale", type=int, default=3, help="PDF417 scale factor")
    parser.add_argument("--columns", type=int, default=6, help="PDF417 column count")
    parser.add_argument("--security-level", type=int, default=2, help="PDF417 security level")
    parser.add_argument("--parse-aamva", help="Parse raw AAMVA data from a file and print the resulting profile")
    args = parser.parse_args(argv)

    if args.gui:
        run_gui()
        return 0

    if args.parse_aamva:
        with open(args.parse_aamva, "rb") as handle:
            raw_data = handle.read()
        profile = parse_aamva_data(raw_data)
        formatted = {}
        for key, value in profile.items():
            formatted[key] = value.strftime("%Y-%m-%d") if isinstance(value, datetime.date) else value
        print(json.dumps(formatted, indent=2))
        return 0

    profile = DEFAULT_PROFILE.copy()
    if args.config:
        profile = load_profile(args.config)

    errors = validate_profile(profile)
    if errors:
        print("Profile validation failed:")
        for error in errors:
            print("  -", error)
        return 2

    if args.validate_only:
        print("Profile validation passed.")
        return 0

    barcode = build_barcode_profile(profile)
    if args.print_data:
        sys.stdout.write(barcode.description)

    target_size = (int(2 * args.dpi), int(0.5 * args.dpi))
    image = generate_pdf417_barcode(barcode.description, scale=args.scale,
                                    columns=args.columns,
                                    security_level=args.security_level,
                                    target_size=target_size)
    image.save(args.out, dpi=(args.dpi, args.dpi))
    print(f"Saved barcode image to {args.out} at {args.dpi} DPI ({target_size[0]}x{target_size[1]} pixels)")
    if args.save_profile:
        save_profile(args.save_profile, profile)
        print(f"Saved profile to {args.save_profile}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
