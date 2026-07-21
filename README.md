# PFX Unpacker for PC

Unpacks Atari ST executables packed with PFX / PFXPAK (Markus Fritze / Thomas Quester). Produces the same result as using PFXPAK [Uncompress] on a real ST — a standard, runnable TOS executable.

## Requirements

- Python 3.10+
- Optional: PySimpleGUI (`pip install PySimpleGUI`) — enables GUI mode

## Usage

**Windows:** Double-click `start_app.bat` — it creates a local `.venv` and installs dependencies from `requirements.txt`, then launches the app. If `.venv` isn't set up yet, `start_app.bat` automatically triggers `install.bat` first; you can also run `install.bat` directly ahead of time if you just want dependencies installed without launching the app. Command-line arguments are passed through, e.g. `start_app.bat packed.prg --identify`.

**Manual (any platform):**

```
python pfx_unpacker.py packed.prg
python pfx_unpacker.py packed.prg -o output.prg
python pfx_unpacker.py packed.prg --identify

GUI: run with no arguments (requires PySimpleGUI)
     Note: Output files are created in the same directory as the input file
```

## Examples

```
python pfx_unpacker.py {filename}.prg
    -> writes {filename}_unpacked.prg

python pfx_unpacker.py {filename}.prg --identify
    -> PFX version : x.xxP
       Stub size   : xxx bytes
       Packed size : xxx,xxx bytes
```

## Supported Packers

- PFX 1.13P (most common — used by many demos and utilities)
- PFX 2.1P

**Not supported:** ICE, Synergy, UPX, or other non-PFX packers.  
**Not supported:** generic LHA archives (use lhasa for those).

## How It Works

1. Locates the -lz5- block in the data segment
2. Reads the original file size from the block header
3. Runs the LZSS decompressor (translated from XPFX.S by Ulf Ronald Andersson)
4. Writes the decompressed content — which is already a complete TOS file (header + text + data + relocation table) — directly to disk

## Notes

- Keep the original packed .prg to run on real hardware; some programs check their own filename or file size at startup.
- Tested with: PFXPAK.TTP, SYNC7.PRG, HDFORMAT.PRG, MSA_II_3.PRG, SOLITAR.PRG
