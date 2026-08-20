# PyInstaller build spec for PdfToMarkdown.
#
# Build with:
#     pyinstaller PdfToMarkdown.spec --noconfirm
#
# Two packages ship data files that PyInstaller cannot discover on its own,
# because neither has a built-in hook:
#
#   customtkinter  ships its themes, fonts and icons under assets/ and reads
#                  them relative to its own __file__ at runtime.
#   tkinterdnd2    ships the native tkdnd Tcl extension under tkdnd/<platform>
#                  and appends that directory to Tcl's auto_path (see
#                  TkinterDnD.py::_require). Only the host platform's build is
#                  bundled, which keeps roughly 1.3 MB of other-OS binaries out
#                  of the output.

import os
import platform
import sys

import customtkinter
import tkinterdnd2

# --------------------------------------------------------------------------
# Locate package data
# --------------------------------------------------------------------------

CTK_DIR = os.path.dirname(customtkinter.__file__)
DND_DIR = os.path.dirname(tkinterdnd2.__file__)


def _tkdnd_platform() -> str:
    """Mirror the folder-picking logic in tkinterdnd2.TkinterDnD._require."""
    system = platform.system()
    if system == "Windows":
        machine = os.environ.get("PROCESSOR_ARCHITECTURE", platform.machine())
    else:
        machine = platform.machine()

    table = {
        ("Darwin", "arm64"): "osx-arm64",
        ("Darwin", "x86_64"): "osx-x64",
        ("Linux", "aarch64"): "linux-arm64",
        ("Linux", "x86_64"): "linux-x64",
        ("Windows", "ARM64"): "win-arm64",
        ("Windows", "AMD64"): "win-x64",
        ("Windows", "x86"): "win-x86",
    }
    try:
        return table[(system, machine)]
    except KeyError:
        raise SystemExit(f"Unsupported build platform: {system} / {machine}")


TKDND_PLATFORM = _tkdnd_platform()

datas = [
    (os.path.join(CTK_DIR, "assets"), "customtkinter/assets"),
    (
        os.path.join(DND_DIR, "tkdnd", TKDND_PLATFORM),
        f"tkinterdnd2/tkdnd/{TKDND_PLATFORM}",
    ),
]

# --------------------------------------------------------------------------
# Windows version resource (shows in the file's Properties dialog)
# --------------------------------------------------------------------------

version_info = None
if sys.platform.startswith("win"):
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable,
        VarFileInfo, VarStruct, VSVersionInfo,
    )

    version_info = VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=(1, 0, 0, 0),
            prodvers=(1, 0, 0, 0),
            mask=0x3F,
            flags=0x0,
            OS=0x40004,
            fileType=0x1,
            subtype=0x0,
        ),
        kids=[
            StringFileInfo([
                StringTable("040904B0", [
                    StringStruct("CompanyName", "Kartik Dhiman"),
                    StringStruct("FileDescription", "PDF to Markdown converter"),
                    StringStruct("FileVersion", "1.0.0.0"),
                    StringStruct("InternalName", "PdfToMarkdown"),
                    StringStruct("LegalCopyright",
                                 "Copyright (c) 2026 Kartik Dhiman. MIT License."),
                    StringStruct("OriginalFilename", "PdfToMarkdown.exe"),
                    StringStruct("ProductName", "PdfToMarkdown"),
                    StringStruct("ProductVersion", "1.0.0.0"),
                ]),
            ]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )

# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

ICON = os.path.join(SPECPATH, "assets", "icon.ico")

a = Analysis(
    ["main.py"],
    pathex=[SPECPATH],
    binaries=[],
    datas=datas,
    hiddenimports=["tkinterdnd2", "customtkinter"],
    hookspath=[],
    runtime_hooks=[],
    # Trim large libraries that get pulled in transitively but are never used.
    #
    # pygame is reached only through pdfminer.ccitt, which imports it inside a
    # debug bitmap-viewer class in that module's main() demo path. pdfplumber
    # never touches it during normal decoding, so excluding it is safe and
    # saves a large amount of space.
    excludes=[
        "pygame",
        "numpy", "pandas", "matplotlib", "scipy",
        "PyQt5", "PyQt6", "PySide2", "PySide6",
        "pytest", "setuptools", "pip",
        "tkinter.test", "test", "unittest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PdfToMarkdown",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI app: no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON if os.path.exists(ICON) else None,
    version=version_info,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PdfToMarkdown",
)
