#!/usr/bin/env python3
"""Unpack PFX / PFXPAK compressed Atari ST executables.

Based on the XPFX.S decompressor source (LBCC subroutine) by Ulf Ronald Andersson.

How it works:
  The packed file contains a tiny 68K decompressor stub as its text segment
  and an LHarc-compatible -lz5- block as its data segment.  The stub runs
  the LZSS decompressor in memory and then jumps into the result.

  Decompressed layout:
    raw[0..4077]   = ring-buffer prefill (4078 x 0x20, never written to disk)
    raw[4078..]    = original TOS executable (header + text + data + reloc)

  archive_output_size (LE uint32 at data_seg[11]) = bytes to decompress =
  length of the original TOS file content in raw[4078:].

  We write raw[4078:4078+archive_output_size] directly as the output file.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

try:
    import PySimpleGUI as sg
    HAS_GUI = True
except ImportError:
    HAS_GUI = False

RING_PREFILL = 4078          # LZSS ring-buffer prefix: 4078 spaces
RING_SIZE    = 4096          # ring modulus (12-bit address space)
MIN_MATCH    = 3             # minimum back-reference copy length
PFX_BANNER_RE = re.compile(rb"LArc's PFX ([0-9.]+[A-Z]?)")


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def identify_pfx(packed: bytes) -> dict:
    if packed[:2] != b"\x60\x1a":
        raise ValueError("Not a TOS executable ($601A missing)")
    text_len = struct.unpack_from(">I", packed, 2)[0]
    stub = packed[28:28 + text_len]
    m = PFX_BANNER_RE.search(stub)
    if m is None:
        raise ValueError("Not a PFX-packed program (banner not found in stub)")
    data_len = struct.unpack_from(">I", packed, 6)[0]
    data_seg = packed[28 + text_len:28 + text_len + data_len]
    if b"-lz5-" not in data_seg[:10]:
        raise ValueError("Not a PFX-packed program (-lz5- not at start of data segment)")
    return {
        "version": m.group(1).decode("ascii", errors="replace"),
        "stub_size": text_len,
    }


# ---------------------------------------------------------------------------
# Decompressor  (XPFX.S  LBCC subroutine, direct translation)
# ---------------------------------------------------------------------------

def _sx16(v: int) -> int:
    """Sign-extend 16-bit to Python int."""
    return v if v < 0x8000 else v - 0x10000


def _decompress(bitstream: bytes, d4: int) -> bytearray:
    """LZSS decompressor from XPFX LBCC.

    d4  = number of bytes to output (archive_output_size).
    Returns 4078-byte prefill + d4 decompressed bytes.
    """
    out = bytearray(b"\x20" * RING_PREFILL)   # ring prefill
    d5  = RING_PREFILL - 1                     # ring position counter (0x0FED)
    src = 0
    d6  = 0
    d7  = -1                                   # bit counter; -1 = need new control byte

    while d4 > 0 and src < len(bitstream):
        if d7 < 0:
            d6 = bitstream[src]; src += 1; d7 = 7
        bit = d6 & 1; d6 >>= 1; d7 -= 1

        if bit:
            # Literal byte
            out.append(bitstream[src]); src += 1
            d5 += 1; d4 -= 1
        else:
            # Back reference: 2 input bytes consumed, peek 1 extra (not consumed)
            if src + 1 >= len(bitstream):
                break
            b0 = bitstream[src]
            b1 = bitstream[src + 1]
            b3 = bitstream[src + 3] if src + 3 < len(bitstream) else 0

            # Decode ring position (movep.w 1(a4); lsr.w #4; move.b (a4)+)
            d0  = ((b1 << 8) | b3) >> 4
            d0  = (d0 & 0xFF00) | (b0 & 0xFF)   # replace low byte with b0
            d0  = (d0 - d5) & 0xFFFF
            d0  = (-_sx16(d0)) & 0xFFFF
            d0 &= 0x0FFF
            d0  = (-_sx16(d0)) & 0xFFFF
            pos  = len(out) + _sx16(d0) - 1

            length = (b1 & 0x0F) + MIN_MATCH    # and.b (a4)+; addq #2
            src += 2

            for _ in range(length):
                if d4 <= 0:
                    break
                byte = out[pos] if 0 <= pos < len(out) else 0x20
                out.append(byte); pos += 1
                d5 += 1; d4 -= 1

    if d4 != 0:
        raise ValueError(
            f"Decompressor finished with d4={d4} (expected 0); "
            "compressed data may be truncated or format not recognised"
        )
    return out


# ---------------------------------------------------------------------------
# Main unpack logic
# ---------------------------------------------------------------------------

def unpack_pfx(packed: bytes) -> bytes:
    """Decompress a PFX-packed TOS executable.

    Returns the raw original TOS file bytes (header + text + data + reloc).
    """
    info = identify_pfx(packed)
    text_len = info["stub_size"]
    data_len  = struct.unpack_from(">I", packed, 6)[0]
    data_seg  = packed[28 + text_len:28 + text_len + data_len]

    # LHarc block header is at data_seg[0]:
    #   data_seg[0]      = header_size_byte  (varies: 22 for no filename, more with name)
    #   data_seg[2..6]   = "-lz5-"
    #   data_seg[11..14] = archive_output_size (LE) = bytes to decompress
    header_size         = data_seg[0]
    archive_output_size = struct.unpack_from("<I", data_seg, 11)[0]

    # Bitstream: stub does  moveq #2,d0; add.b (a4),d0; adda d0,a4
    # i.e. a4 advances by  header_size + 2
    bitstream_start = header_size + 2
    if bitstream_start >= len(data_seg):
        raise ValueError("Bitstream start is past end of data segment")
    bitstream = data_seg[bitstream_start:]

    raw = _decompress(bitstream, archive_output_size)

    # Original TOS file starts at raw[RING_PREFILL:]
    tos_file = bytes(raw[RING_PREFILL:RING_PREFILL + archive_output_size])
    if len(tos_file) != archive_output_size:
        raise ValueError(
            f"Expected {archive_output_size} bytes of TOS content, "
            f"got {len(tos_file)}"
        )
    # Sanity check: should start with $601A
    if tos_file[:2] != b"\x60\x1a":
        raise ValueError(
            f"Decompressed content does not start with $601A "
            f"(got {tos_file[:2].hex()}); decompression may be wrong"
        )
    return tos_file


def unpack_file(src: Path, dest: Path) -> tuple[int, int, dict]:
    packed = src.read_bytes()
    info   = identify_pfx(packed)
    result = unpack_pfx(packed)
    dest.write_bytes(result)
    return len(packed), len(result), info


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Unpack PFX / PFXPAK Atari ST executables"
    )
    parser.add_argument("input", type=Path, nargs="?",
                        help="Packed .prg / .tos / .ttp")
    parser.add_argument("-o", "--output", type=Path,
                        help="Output file (default: <name>_unpacked.prg)")
    parser.add_argument("--identify", action="store_true",
                        help="Show PFX version and exit")
    args = parser.parse_args(argv)

    if not args.input:
        parser.print_help()
        return 1

    packed = args.input.read_bytes()

    if args.identify:
        info = identify_pfx(packed)
        print(f"PFX version : {info['version']}")
        print(f"Stub size   : {info['stub_size']} bytes")
        print(f"Packed size : {len(packed):,} bytes")
        return 0

    output = args.output or args.input.with_name(args.input.stem + "_unpacked.prg")
    src_size, dest_size, info = unpack_file(args.input, output)
    print(f"PFX version : {info['version']}")
    print(f"Packed      : {args.input} ({src_size:,} bytes)")
    print(f"Unpacked    : {output} ({dest_size:,} bytes)")
    return 0


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

def run_gui() -> None:
    if not HAS_GUI:
        raise SystemExit("PySimpleGUI not installed; use CLI mode.")

    layout = [
        [sg.Text("PFX Unpacker", font=("Helvetica", 16, "bold"))],
        [sg.Text("Decompress Atari ST executables packed with PFX/PFXPAK", font=("Helvetica", 10), text_color="lightblue")],
        [sg.Text("")],  # Spacing
        [
            sg.Text("Source:", size=(8, 1)),
            sg.Input(key="-SRC-", enable_events=True, size=(45, 1)),
            sg.FileBrowse(file_types=(("Atari executables", "*.prg;*.tos;*.ttp"),)),
        ],
        [sg.Text("PFX:"), sg.Text("-", key="-INFO-", size=(50, 1))],
        [
            sg.Text("Output:", size=(8, 1)),
            sg.Input(key="-DEST-", size=(45, 1), readonly=True),
            sg.Button("Unpack", key="-UNPACK-", disabled=True),
        ],
        [sg.Text("", key="-STATUS-", size=(60, 1))],
        [sg.Text("")],  # Spacing
        [sg.Button("Exit"), sg.Push(), sg.Text("by Jeff Molofee (NeHe)", font=("Helvetica", 8), text_color="lightgray")],
    ]
    window = sg.Window("PFX Unpacker", layout, finalize=True)
    src_full_path = None  # Store full path internally
    dest_full_path = None

    while True:
        event, values = window.read()
        if event in (sg.WIN_CLOSED, "Exit"):
            break

        if event == "-SRC-" and values["-SRC-"]:
            src_full_path = Path(values["-SRC-"])
            try:
                info = identify_pfx(src_full_path.read_bytes())
                dest_full_path = src_full_path.with_name(src_full_path.stem + "_unpacked.prg")
                window["-SRC-"].update(src_full_path.name)
                window["-INFO-"].update(
                    f"PFX {info['version']}  |  {src_full_path.stat().st_size:,} bytes packed"
                )
                window["-DEST-"].update(dest_full_path.name)
                window["-UNPACK-"].update(disabled=False)
                window["-STATUS-"].update("")
            except Exception as exc:
                window["-INFO-"].update(f"Not PFX: {exc}")
                window["-UNPACK-"].update(disabled=True)

        if event == "-UNPACK-" and src_full_path and dest_full_path:
            try:
                _, dest_size, info = unpack_file(src_full_path, dest_full_path)
                window["-STATUS-"].update(
                    f"Done — {dest_size:,} bytes written to {dest_full_path.name}"
                )
            except Exception as exc:
                sg.popup_error(str(exc))

    window.close()


# ---------------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) > 1:
        return run_cli()
    if HAS_GUI:
        run_gui()
        return 0
    print(
        "Usage: pfx_unpacker.py packed.prg [-o out.prg] [--identify]",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
