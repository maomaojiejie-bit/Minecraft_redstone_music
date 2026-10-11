"""Build a Minecraft resource pack from FL Studio's default instrument samples.

Usage:
    python -m studio.flstudio_pack
    python studio/flstudio_pack.py --out output/flstudio_instrument_pack.zip
"""
from __future__ import annotations

import io
import json
import shutil
import struct
import sys
import zipfile
from fractions import Fraction
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from studio.musescore_pack import (
    SRC_ZIP,
    collect_records,
    _sort_key,
    NOTE_DUR,
    DRUM_MAX,
    DRUM_DUR,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SR = 44100

FL_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Image-Line\FL Studio 2026"),
    Path(r"C:\Program Files (x86)\Image-Line\FL Studio 20"),
]

# source instrument definitions (relative to FL Studio root)
PNO_FOLDER = "Data/Patches/Packs/Instruments/Keyboard/Close Grand"
PNO_PATTERN = "Close Grand {}.wav"
PNO_ROOTS = {i: 21 + (i - 1) for i in range(1, 89)}  # A0..C8

LEAD_FOLDER = "Data/Patches/Packs/Instruments/Guitar/Jazz"
LEAD_PATTERN = "Jazz Guitar ({}).wav"
LEAD_ROOTS = [40, 43, 47, 51, 55, 59, 63, 67, 71, 75, 80, 84]

PAD_FOLDER = "Data/Patches/Packs/Instruments/Orchestral/Strings Section"
PAD_FILES = {
    "OSTR C1.wav": 24, "OSTR C2.wav": 36, "OSTR C3.wav": 48,
    "OSTR C4.wav": 60, "OSTR C5.wav": 72, "OSTR C6.wav": 84,
    "OSTR F1.wav": 29, "OSTR F2.wav": 41, "OSTR F3.wav": 53,
    "OSTR F4.wav": 65, "OSTR F5.wav": 77,
}

BASS_FOLDER = "Data/Patches/Packs/Instruments/Bass/Acoustic"
BASS_PATTERN = "Acoustic Bass ({}).wav"
BASS_ROOTS = [28, 32, 35, 40, 44, 47, 51, 55, 60, 64]

DRUM_FILES = {
    "kick": "Data/Patches/Packs/Drums/Kicks/909 Kick.wav",
    "snare": "Data/Patches/Packs/Drums/Snares/909 Snare.wav",
    "hihat_closed": "Data/Patches/Packs/Drums/Hats/909 CH 1.wav",
    "tom": "Data/Patches/Packs/Drums/Toms/909 Tom.wav",
    "crash": "Data/Patches/Packs/Drums/Cymbals/909 Crash.wav",
}

CREDITS = """McMusicMaker FL Studio default instrument pack - credits
================================================================

This resource pack was built from FL Studio's bundled default
instrument samples (Close Grand piano, Jazz Guitar, Acoustic Bass,
Strings Section, and the 909 drum kit) using the same 103 sample names
and instrument mapping as the qzpno_mv pack, so it can be dropped into
the RedPiano mod / datapack without rebuilding the machine.

FL Studio and its bundled content are developed by Image-Line.
See https://www.image-line.com/ for license and attribution details.

Samples were decoded from FL Studio's RIFF-wrapped Ogg Vorbis files,
pitch-shifted where necessary, trimmed, normalized, and encoded as
Ogg Vorbis.
"""


def find_fl_root():
    for p in FL_CANDIDATES:
        if (p / PNO_FOLDER).exists():
            return p
    raise FileNotFoundError(
        "FL Studio sample folder not found. Expected one of: "
        + ", ".join(str(p) for p in FL_CANDIDATES)
    )


def _extract_ogg(path):
    data = Path(path).read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not RIFF/WAVE: " + str(path))
    pos = 12
    while pos + 8 <= len(data):
        cid = data[pos:pos+4]
        size = struct.unpack_from("<I", data, pos+4)[0]
        body = pos + 8
        if cid == b"data":
            return data[body:body+size]
        pos = body + size + (size & 1)
    raise ValueError("no data chunk: " + str(path))


def read_fl_sample(path):
    try:
        y, sr = sf.read(str(path), dtype="float32", always_2d=False)
    except Exception:
        ogg = _extract_ogg(path)
        y, sr = sf.read(io.BytesIO(ogg), dtype="float32", always_2d=False)
    if y.ndim > 1:
        y = y.mean(axis=1)
    return y, sr


def pitch_shift(y, sr, semitones, target_dur):
    if abs(semitones) < 1e-6:
        out = y.copy()
    else:
        k = 2.0 ** (semitones / 12.0)
        frac = Fraction(k).limit_denominator(1000)
        out = resample_poly(y, frac.numerator, frac.denominator)
    target_len = int(round(target_dur * sr))
    if out.size > target_len:
        out = out[:target_len]
    elif out.size < target_len:
        out = np.pad(out, (0, target_len - out.size))
    return out


def load_sources(family, fl_root):
    sources = []
    if family == "pno":
        for i, root in PNO_ROOTS.items():
            p = fl_root / PNO_FOLDER / PNO_PATTERN.format(i)
            if p.exists():
                y, sr = read_fl_sample(p)
                sources.append((root, y, sr))
    elif family == "lead":
        for i, root in enumerate(LEAD_ROOTS, start=1):
            p = fl_root / LEAD_FOLDER / LEAD_PATTERN.format(i)
            if p.exists():
                y, sr = read_fl_sample(p)
                sources.append((root, y, sr))
    elif family == "pad":
        for name, root in PAD_FILES.items():
            p = fl_root / PAD_FOLDER / name
            if p.exists():
                y, sr = read_fl_sample(p)
                sources.append((root, y, sr))
    elif family == "bass":
        for i, root in enumerate(BASS_ROOTS, start=1):
            p = fl_root / BASS_FOLDER / BASS_PATTERN.format(i)
            if p.exists():
                y, sr = read_fl_sample(p)
                sources.append((root, y, sr))
    return sources


def render_family(family, records, out_dir, fl_root, log=print):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sources = [] if family == "drum" else load_sources(family, fl_root)
    if family != "drum" and not sources:
        raise RuntimeError("no source samples for " + family)

    # original qzpno peaks for volume matching
    orig_peaks = {}
    with zipfile.ZipFile(SRC_ZIP) as zsrc:
        for rec in records:
            try:
                raw = zsrc.read("assets/qzpno/sounds/" + rec["name"] + ".ogg")
                o, _ = sf.read(io.BytesIO(raw), dtype="float32")
                if o.ndim > 1:
                    o = o.mean(axis=1)
                orig_peaks[rec["name"]] = float(np.max(np.abs(o)))
            except Exception:
                orig_peaks[rec["name"]] = 0.9

    written = []
    for rec in records:
        if family == "drum":
            path = fl_root / DRUM_FILES[rec["drum_type"]]
            y, sr = read_fl_sample(path)
            target_dur = DRUM_MAX.get(rec["drum_type"], DRUM_DUR)
            seg = pitch_shift(y, sr, 0.0, target_dur)
        else:
            target_note = int(rec["note"])
            root, y, sr = min(sources, key=lambda s: abs(s[0] - target_note))
            semis = target_note - root
            seg = pitch_shift(y, sr, semis, NOTE_DUR)

        peak = float(np.max(np.abs(seg)))
        if peak > 0:
            target = orig_peaks.get(rec["name"], 0.9)
            if target > 0:
                seg = seg * (target / peak)

        fade = min(int(0.02 * sr), seg.size)
        if fade > 0:
            seg[-fade:] *= np.linspace(1.0, 0.0, fade, dtype="float32")

        out_path = out_dir / (rec["name"] + ".ogg")
        sf.write(str(out_path), seg, sr, format="OGG", subtype="VORBIS")
        written.append(out_path)
        log("  " + rec["name"])
    return written


def build_flstudio_pack(out_zip="output/flstudio_instrument_pack.zip", work_dir=None, log=print):
    fl_root = find_fl_root()
    records = collect_records()
    groups = {}
    for rec in records:
        groups.setdefault(rec["family"], []).append(rec)
    for fam in groups:
        groups[fam].sort(key=_sort_key)

    own_tmp = work_dir is None
    if work_dir:
        base = Path(work_dir)
    else:
        base = REPO_ROOT / "output" / "_flstudio_work"
        base.mkdir(parents=True, exist_ok=True)
    try:
        out_dir = base / "samples"
        out_dir.mkdir(parents=True, exist_ok=True)
        all_files = []
        for fam in ("pno", "bass", "lead", "pad", "drum"):
            recs = groups.get(fam, [])
            if not recs:
                continue
            log("rendering " + fam + ": " + str(len(recs)) + " samples")
            files = render_family(fam, recs, out_dir, fl_root, log=log)
            all_files.extend(files)
            log("  " + str(len(files)) + " samples written")

        out_zip = Path(out_zip)
        if not out_zip.is_absolute():
            out_zip = REPO_ROOT / out_zip
        out_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(
                "pack.mcmeta",
                json.dumps(
                    {
                        "pack": {
                            "pack_format": 64,
                            "description": "FL Studio default instrument pack for RedPiano",
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            z.writestr("CREDITS.txt", CREDITS)
            with zipfile.ZipFile(SRC_ZIP) as src:
                z.writestr("assets/qzpno/sounds.json", src.read("assets/qzpno/sounds.json"))
            for f in all_files:
                z.write(str(f), "assets/qzpno/sounds/" + f.name)
        log("pack written: " + str(out_zip) + " (" + str(len(all_files)) + " samples)")
        return out_zip
    finally:
        if own_tmp:
            shutil.rmtree(base, ignore_errors=True)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    out = "output/flstudio_instrument_pack.zip"
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
    build_flstudio_pack(out_zip=out, log=print)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


