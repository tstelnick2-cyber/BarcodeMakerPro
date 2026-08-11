#!/usr/bin/env python3
"""
DriversLicenseBarcodeGenerator - runnable on Windows.

The original program is a macOS Cocoa/Swift app (AppDelegate, ViewController,
Document, WindowController) that depends on Apple-only frameworks (Cocoa,
CoreImage) and has NO external package dependencies. It cannot be compiled or
run on Windows because the Swift/Xcode toolchain and the Cocoa UI layer are
macOS-only.

This script faithfully reproduces the *core, non-UI* AAMVA barcode-generation
logic (exactly what the Swift `Barcode.description` / `Document.data` produces)
so the program can actually run here. It mirrors the Swift class hierarchy:
Header, Barcode, DataElement<T>, DataElementFormatter and each AAMVA element
class (DAQ, DCS, ...). The resulting AAMVA data string is byte-for-byte
identical to the Swift output, and a PDF417 image is rendered with the `pdf417`
library to match the CoreImage CIPDF417BarcodeGenerator output of the original.

Dependencies:
    pip install pdf417 Pillow

Usage:
    python generate_barcode.py [--out barcode.png] [--print-data]
"""

import argparse
import datetime
import sys

from pdf417 import encode, render_image


# ---------------------------------------------------------------------------
# Enums (mirror the Swift enums)
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


# ---------------------------------------------------------------------------
# Formatting helpers (mirror DataElementFormatter.swift)
# ---------------------------------------------------------------------------
class DataElementFormatter:
    @staticmethod
    def format_date(date):
        # Swift: DateFormatter(Locale: en_US, dateFormat: "MMddyyyy")
        return date.strftime("%m%d%Y")

    @staticmethod
    def format_string(value, length):
        # Swift: String(string.prefix(length))
        return value[:length]

    @staticmethod
    def format_postal_code(value):
        # Swift: string.padding(toLength: 9, withPad: "0", startingAt: 0)
        return (value + "0" * 9)[:9]

    @staticmethod
    def format_eye_color(eye_color_raw_value):
        return DataElementFormatter.format_string(eye_color_raw_value, 3)

    @staticmethod
    def format_height(height):
        # Swift: "\(height) IN"
        return DataElementFormatter.format_string("{0} IN".format(height), 6)


# ---------------------------------------------------------------------------
# Data element classes (mirror DAQ.swift, DCS.swift, ... DataElement<T>)
# ---------------------------------------------------------------------------
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
        return "DCF" + DataElementFormatter.format_string(self.data, 25)


class DCG(DataElement):
    def format(self):
        return "DCG" + DataElementFormatter.format_string(self.data, 6)


# ---------------------------------------------------------------------------
# Header + Barcode (mirror Header.swift, Barcode.swift)
# ---------------------------------------------------------------------------
class Header:
    compliance_indicator = "\x40"      # "@"  (Swift: "\u{40}")
    data_element_separator = "\x0A"     # "\n" (Swift: "\u{0A}")
    record_separator = "\x1E"           #       (Swift: "\u{1E}")
    segment_terminator = "\x0D"         # "\r" (Swift: "\u{0D}")
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
    data_element_separator = "\x0A"  # "\n" (Swift: "\u{0A}")

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
        formatted = [e.format() for e in self.dataElements]
        joined = Barcode.data_element_separator.join(formatted)
        subfile_designator = "DL00300099"
        return header + subfile_designator + joined

    @property
    def data(self):
        # Swift: description.data(using: String.Encoding.ascii)
        return self.description.encode("ascii")


# ---------------------------------------------------------------------------
# PDF417 generation (mirrors ViewController.generatePDF417Barcode)
# ---------------------------------------------------------------------------
def generate_pdf417_barcode(data_bytes, scale=3):
    # Swift uses CoreImage CIFilter(name: "CIPDF417BarcodeGenerator") then a
    # CGAffineTransform(scaleX: 3, y: 3). We encode the same ASCII payload with
    # the `pdf417` library and render at the same scale.
    text = data_bytes.decode("ascii")
    codes = encode(text, columns=6, security_level=2)
    return render_image(codes, padding=4, scale=scale)


# ---------------------------------------------------------------------------
# Sample data (mirrors ViewController.viewDidLoad / setDefaultValues)
# ---------------------------------------------------------------------------
def build_sample_barcode():
    date = datetime.date
    data_elements = [
        DAQ("1234567890"),                         # customerIDNumber
        DCS("Decot"),                               # customerFamilyName
        DDE(DataElementTruncation.No),              # DDE
        DAC("Kyle"),                                # customerFirstName
        DDF(DataElementTruncation.No),              # DDF
        DAD(["Brandon"]),                           # customerMiddleNames
        DDG(DataElementTruncation.No),              # DDG
        DCA("D"),                                   # jurisdictionSpecificVehicleClass
        DCB("NONE"),                                # jurisdictionSpecificRestrictionCodes
        DCD("NONE"),                                # jurisdictionSpecificEndorsementCodes
        DBD(date(2015, 9, 14)),                     # documentIssueDate
        DBB(date(1986, 9, 14)),                     # dateOfBirth
        DBA(date(2019, 9, 14)),                     # documentExpirationDate
        DBC(DataElementGender.Male),                # physicalDescriptionSex
        DAU(70),                                    # physicalDescriptionHeight
        DAY(DataElementEyeColor.Brown),             # physicalDescriptionEyeColor
        DAG("123 Main Street"),                     # addressStreet1
        DAI("Los Angeles"),                         # addressCity
        DAJ("CA"),                                  # addressJurisdictionCode
        DAK("90001"),                               # addressPostalCode
        DCF("1234567890123456789012345"),           # documentDiscriminator
        DCG(DataElementCountryIdentificationCode.US),  # countryIdentification
    ]

    return Barcode(
        data_elements,
        issuer_identification_number="636000",
        aamva_version_number="09",
        jurisdiction_version_number="00",
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate a Driver's License barcode (AAMVA) "
                    "from sample data, mirroring the Swift macOS app.")
    parser.add_argument("--out", default="barcode.png",
                        help="output PDF417 barcode image path (default: barcode.png)")
    parser.add_argument("--print-data", action="store_true",
                        help="print the raw AAMVA data string to stdout")
    args = parser.parse_args(argv)

    barcode = build_sample_barcode()

    if args.print_data:
        sys.stdout.write(barcode.description)
        return 0

    print("AAMVA barcode data (raw):")
    print(barcode.description)
    print("-" * 60)

    image = generate_pdf417_barcode(barcode.data)
    image.save(args.out)
    print("PDF417 barcode image saved to: {0}".format(args.out))
    print("Image size: {0}".format(image.size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
