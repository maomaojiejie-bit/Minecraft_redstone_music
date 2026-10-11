"""Build a Minecraft resource pack from MuseScore Studio's MS Basic soundfont.

Usage (standalone):
    python -m studio.musescore_pack
    python studio/musescore_pack.py --out output/musescore_instrument_pack.zip
"""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import mido
import numpy as np
import soundfile as sf

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / "minecraft-redstone-music"
SRC_ZIP = SKILL_DIR / "assets" / "qzpno_mv.zip"
MAP_PATH = SKILL_DIR / "assets" / "redpiano_map_multi.json"

MUSESCORE_CANDIDATES = [
    Path(r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe"),
    Path(r"C:\Program Files\MuseScore 4\bin\mscore.exe"),
]

SR = 44100
SLOT = 4.0
NOTE_DUR = 2.8
DRUM_SLOT = 2.0
DRUM_DUR = 1.0

FAMILY_PROGRAM = {"pno": 0, "bass": 33, "lead": 29, "pad": 48}
FAMILY_CHANNEL = {"pno": 0, "bass": 1, "lead": 2, "pad": 3}
FAMILY_VELOCITY = {"pno": 0, "bass": 90, "lead": 90, "pad": 90}
LAYER_VELOCITY = {"p": 55, "mf": 85, "f": 115, "x": 90}
LAYER_ORDER = {"p": 0, "mf": 1, "f": 2, "x": 0}

DRUM_NOTES = {"kick": 36, "snare": 38, "hihat_closed": 42, "tom": 45, "crash": 49}
DRUM_VELOCITY = {"kick": 110, "snare": 105, "hihat_closed": 85, "tom": 100, "crash": 95}
DRUM_MAX = {"kick": 0.6, "snare": 0.5, "hihat_closed": 0.3, "tom": 0.6, "crash": 1.5}
DRUM_ORDER = {"kick": 0, "snare": 1, "hihat_closed": 2, "tom": 3, "crash": 4}

CREDITS = """McMusicMaker MuseScore MS Basic instrument pack - credits
================================================================

This resource pack was rendered from MuseScore Studio 4's built-in
MS Basic soundfont (MS Basic.sf3), using the same 103 sample names and
instrument mapping as the qzpno_mv pack so it can be dropped into the
RedPiano mod / datapack without rebuilding the machine.

MuseScore Studio is developed by MuseScore BVBA and contributors.
MS Basic is the default GM soundfont shipped with MuseScore 4.
See https://musescore.org/ for license and attribution details.

Samples were rendered offline with MuseScore4 -o out.wav, sliced by
fixed time slots, trimmed, normalized to -1 dBFS peak, and encoded
as Ogg Vorbis.
"""


def find_musescore():
    for p in MUSESCORE_CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError(
        "MuseScore 4 not found. Expected: " + ", ".join(str(p) for p in MUSESCORE_CANDIDATES)
    )


def collect_records(map_path=MAP_PATH):
    mm = json.loads(Path(map_path).read_text(encoding="utf-8"))
    insts = mm["instruments"]
    records = []

    for key, event in insts["pno"]["sound"].items():
        band_s, layer = key.split("_")
        records.append({
            "family": "pno",
            "note": int(band_s),
            "layer": layer,
            "event": event,
            "name": event.split(":", 1)[1],
        })

    for fam in ("bass", "lead", "pad"):
        for key, event in insts[fam]["sound"].items():
            band_s, layer = key.split("_")
            records.append({
                "family": fam,
                "note": int(band_s),
                "layer": layer,
                "event": event,
                "name": event.split(":", 1)[1],
            })

    for key, event in insts["drum"]["sound"].items():
        drum_type = key.split(":", 1)[1]
        records.append({
            "family": "drum",
            "drum_type": drum_type,
            "note": None,
            "layer": "x",
            "event": event,
            "name": event.split(":", 1)[1],
        })
    return records


def _sort_key(rec):
    if rec["family"] == "drum":
        return (DRUM_ORDER.get(rec["drum_type"], 99), 0)
    return (rec["note"], LAYER_ORDER.get(rec["layer"], 0))


def build_midi(records, mid_path):
    mid = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0))

    family = records[0]["family"]
    channel = 9 if family == "drum" else FAMILY_CHANNEL[family]
    if family != "drum":
        track.append(mido.Message("program_change", program=FAMILY_PROGRAM[family], channel=channel, time=0))

    sec_per_tick = 0.5 / mid.ticks_per_beat
    events = []
    for i, rec in enumerate(records):
        slot = DRUM_SLOT if family == "drum" else SLOT
        dur = DRUM_DUR if family == "drum" else NOTE_DUR
        start_tick = int(round(i * slot / sec_per_tick))
        end_tick = int(round((i * slot + dur) / sec_per_tick))
        if family == "drum":
            note = DRUM_NOTES[rec["drum_type"]]
            vel = DRUM_VELOCITY[rec["drum_type"]]
        else:
            note = rec["note"]
            vel = LAYER_VELOCITY[rec["layer"]] if family == "pno" else FAMILY_VELOCITY[family]
        events.append((start_tick, 1, note, vel, channel))
        events.append((end_tick, 0, note, 0, channel))

    events.sort(key=lambda e: (e[0], e[1]))
    last_tick = 0
    for tick, kind, note, vel, ch in events:
        delta = tick - last_tick
        last_tick = tick
        if kind:
            track.append(mido.Message("note_on", note=note, velocity=vel, channel=ch, time=delta))
        else:
            track.append(mido.Message("note_off", note=note, velocity=0, channel=ch, time=delta))
    mid.save(str(mid_path))


def render_with_musescore(exe, mid_path, wav_path, timeout=600):
    cmd = [str(exe), "-o", str(wav_path), str(mid_path)]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if not wav_path.exists():
        raise RuntimeError("MuseScore did not produce " + str(wav_path))
    return wav_path


def slice_family(wav_path, records, out_dir, family, progress=None, src_zip=None):
    data, sr = sf.read(str(wav_path), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    slot = DRUM_SLOT if family == "drum" else SLOT
    written = []

    orig_peaks = {}
    if src_zip is not None:
        with zipfile.ZipFile(src_zip) as zsrc:
            for rec in records:
                try:
                    raw = zsrc.read("assets/qzpno/sounds/" + rec["name"] + ".ogg")
                    o, _ = sf.read(io.BytesIO(raw), dtype="float32")
                    if o.ndim > 1:
                        o = o.mean(axis=1)
                    orig_peaks[rec["name"]] = float(np.max(np.abs(o)))
                except Exception:
                    orig_peaks[rec["name"]] = 0.0

    for i, rec in enumerate(records):
        if family == "drum":
            max_dur = DRUM_MAX.get(rec["drum_type"], DRUM_DUR)
        else:
            max_dur = NOTE_DUR
        start = int(round(i * slot * sr))
        end = min(len(mono), int(round((i * slot + slot - 0.05) * sr)))
        seg = mono[start:end]
        if seg.size == 0:
            continue

        peak = float(np.max(np.abs(seg)))
        if peak < 1e-6:
            continue
        thr = max(1e-4, peak * 0.002)
        nz = np.nonzero(np.abs(seg) > thr)[0]
        if nz.size == 0:
            continue
        seg = seg[nz[0] : nz[-1] + 1]

        max_len = int(round(max_dur * sr))
        if seg.size > max_len:
            seg = seg[:max_len]

        p = float(np.max(np.abs(seg)))
        if p > 0:
            target = orig_peaks.get(rec["name"], 0.9) if orig_peaks else 0.9
            if target > 0:
                seg = seg * (target / p)

        fade = min(int(0.02 * sr), seg.size)
        if fade > 0:
            seg[-fade:] *= np.linspace(1.0, 0.0, fade, dtype="float32")

        out_path = Path(out_dir) / (rec["name"] + ".ogg")
        sf.write(str(out_path), seg, sr, format="OGG", subtype="VORBIS")
        written.append(out_path)
        if progress:
            progress(f"{family} {i + 1}/{len(records)} {rec['name']}")
    return written


def build_musescore_pack(out_zip="output/musescore_instrument_pack.zip", work_dir=None, log=print):
    exe = find_musescore()
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
        base = REPO_ROOT / "output" / "_musescore_work"
        base.mkdir(parents=True, exist_ok=True)
    try:
        out_dir = base / "samples"
        out_dir.mkdir(parents=True, exist_ok=True)
        all_files = []
        for fam in ("pno", "bass", "lead", "pad", "drum"):
            recs = groups.get(fam, [])
            if not recs:
                continue
            log(f"rendering {fam}: {len(recs)} samples")
            mid_path = base / f"{fam}.mid"
            wav_path = base / f"{fam}.wav"
            build_midi(recs, mid_path)
            render_with_musescore(exe, mid_path, wav_path)
            files = slice_family(wav_path, recs, out_dir, fam, progress=None, src_zip=SRC_ZIP)
            all_files.extend(files)
            log(f"  {len(files)} samples written")

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
                            "description": "MuseScore MS Basic instrument pack for RedPiano",
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
        log(f"pack written: {out_zip} ({len(all_files)} samples)")
        return out_zip
    finally:
        if own_tmp:
            shutil.rmtree(base, ignore_errors=True)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    out = "output/musescore_instrument_pack.zip"
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
    build_musescore_pack(out_zip=out, log=print)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
