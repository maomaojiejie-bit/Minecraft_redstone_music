"""Online / local SoundFont search, preview and RedPiano resource-pack builder.

Uses only Python standard library + numpy/soundfile + the local sf2_synth.
Online search queries musical-artifacts.com; if the network is unavailable
the caller can still import a local .sf2 file or a direct URL.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import struct
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import soundfile as sf

from studio.musescore_pack import (
    SRC_ZIP,
    collect_records,
    _sort_key,
    NOTE_DUR,
    DRUM_MAX,
    DRUM_DUR,
    DRUM_NOTES,
    DRUM_VELOCITY,
    LAYER_VELOCITY,
)
from studio.sf2_synth import SoundFont, SR

REPO_ROOT = Path(__file__).resolve().parent.parent
SF2_DIR = REPO_ROOT / "output" / "soundfonts"
USER_AGENT = "McMusicMaker/1.0 (+https://github.com/)"

# A small built-in catalogue of free / redistributable SoundFonts.
CATALOG: list[dict] = [
    {
        "name": "GeneralUser GS",
        "tags": ["gm", "general midi", "piano", "guitar", "strings", "bass", "drums"],
        "description": "General MIDI SoundFont by S. Christian Collins (free for non-commercial use).",
        "url": "https://github.com/mrbumpy409/GeneralUser-GS/raw/master/GeneralUser-GS.sf2",
        "filename": "GeneralUser-GS.sf2",
        "license": "Free for non-commercial use",
    },
]


def _request_json(url: str, timeout: float = 15.0):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw.decode("utf-8", "replace"))


def _request_text(url: str, timeout: float = 15.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def search_catalog(query: str) -> list[dict]:
    q = (query or "").strip().lower()
    out = []
    for item in CATALOG:
        hay = " ".join([item.get("name", ""), item.get("description", ""), " ".join(item.get("tags", []))]).lower()
        if not q or q in hay:
            out.append(dict(item, source="内置目录"))
    return out


def search_online(query: str, limit: int = 30) -> list[dict]:
    """Search musical-artifacts.com. Returns entries with direct .sf2/.sf3 URLs when possible."""
    q = (query or "").strip()
    if not q:
        return []
    results: list[dict] = []
    # 1) JSON API: returns a list of artifact dicts
    try:
        url = "https://musical-artifacts.com/artifacts.json?" + urllib.parse.urlencode({"q": q})
        data = _request_json(url)
        if isinstance(data, dict):
            data = data.get("artifacts") or data.get("items") or []
        if isinstance(data, list):
            for item in data[:limit]:
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or item.get("title") or "artifact"
                desc = item.get("description") or ""
                page = item.get("url") or ("https://musical-artifacts.com/artifacts/" + str(item.get("id", "")))
                mirrors = item.get("mirrors") or []
                if isinstance(mirrors, str):
                    mirrors = [mirrors]
                direct = ""
                filename = ""
                for mu in mirrors:
                    if not isinstance(mu, str):
                        continue
                    low = mu.lower()
                    if ".sf2" in low or ".sf3" in low:
                        direct = mu
                        filename = urllib.parse.unquote(mu.rsplit("/", 1)[-1].split("?")[0])
                        break
                results.append({
                    "name": name,
                    "description": desc,
                    "url": direct,
                    "filename": filename,
                    "source": "musical-artifacts.com",
                    "page": page,
                })
                if len(results) >= limit:
                    return results
    except Exception:
        pass
    if results:
        return results
    # 2) HTML search fallback: collect artifact links and titles
    try:
        html = _request_text("https://musical-artifacts.com/artifacts?" + urllib.parse.urlencode({"q": q}))
        seen = set()
        for m in re.finditer(r'href="(/artifacts/\d+)"[^>]*>(.*?)</a>', html, re.S):
            href, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
            if href in seen or not title:
                continue
            seen.add(href)
            results.append({
                "name": title,
                "description": "",
                "url": "",
                "filename": "",
                "source": "musical-artifacts.com",
                "page": "https://musical-artifacts.com" + href,
            })
            if len(results) >= limit:
                break
    except Exception:
        pass
    return results

def search(query: str) -> list[dict]:
    out = search_catalog(query)
    try:
        out.extend(search_online(query))
    except Exception:
        pass
    return out


def download(url: str, dest: Path, progress=None) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if progress:
                progress(got, total)
    return dest


def list_local_soundfonts() -> list[Path]:
    """Scan common FL Studio / MuseScore locations for .sf2/.sf3 files."""
    roots = [
        Path(r"C:\Program Files (x86)\Image-Line\FL Studio 2026\Data\Patches\Packs\Instruments"),
        Path(r"C:\Program Files (x86)\Image-Line\FL Studio 2026\Data\Patches\Soundfonts"),
        Path(r"C:\Program Files (x86)\Image-Line\FL Studio 20\Data\Patches\Packs\Instruments"),
        Path(r"C:\Program Files (x86)\Image-Line\FL Studio 20\Data\Patches\Soundfonts"),
        Path(r"C:\Program Files\MuseScore 4\sound"),
        SF2_DIR,
    ]
    found: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        try:
            for p in root.rglob("*"):
                if p.suffix.lower() in (".sf2", ".sf3") and p not in found:
                    found.append(p)
        except Exception:
            continue
    found.sort(key=lambda p: (p.suffix.lower() != ".sf2", str(p).lower()))
    return found


def list_presets(sf2_path: str | Path) -> list[tuple[int, int, int, str]]:
    return SoundFont(sf2_path).list_presets()


def preview(sf2_path: str | Path, preset_index: int, note: int = 60,
            velocity: int = 100, duration: float = 2.0) -> np.ndarray:
    return SoundFont(sf2_path).render_note(preset_index, note, velocity, duration)


def _read_original_peaks(names: list[str]) -> dict[str, float]:
    peaks: dict[str, float] = {}
    with zipfile.ZipFile(SRC_ZIP) as z:
        for name in names:
            try:
                raw = z.read("assets/qzpno/sounds/" + name + ".ogg")
                y, sr = sf.read(io.BytesIO(raw))
                if y.ndim > 1:
                    y = y.mean(axis=1)
                peaks[name] = float(np.max(np.abs(y)))
            except Exception:
                peaks[name] = 0.9
    return peaks


def _write_ogg(path: Path, y: np.ndarray, sr: int = SR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), y.astype(np.float32), sr, format="OGG", subtype="VORBIS")


def build_pack(sf2_path: str | Path, mapping: dict, out_zip: str | Path = "output/online_instrument_pack.zip",
               log=print) -> Path:
    """Render the 103 RedPiano samples from a SoundFont.

    mapping = {
        "pno": preset_index, "lead": preset_index, "pad": preset_index, "bass": preset_index,
        "drum": preset_index,
        "drum_notes": {"kick": 36, ...},   # optional
    }
    """
    sf_path = Path(sf2_path)
    sfo = SoundFont(sf_path)
    records = collect_records()
    groups: dict[str, list[dict]] = {}
    for rec in records:
        groups.setdefault(rec["family"], []).append(rec)
    for fam in groups:
        groups[fam].sort(key=_sort_key)

    names = [rec["name"] for rec in records]
    orig_peaks = _read_original_peaks(names)

    out_zip = Path(out_zip)
    if not out_zip.is_absolute():
        out_zip = REPO_ROOT / out_zip
    out_zip.parent.mkdir(parents=True, exist_ok=True)

    work = REPO_ROOT / "output" / "_online_pack_work"
    work.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    try:
        for fam in ("pno", "bass", "lead", "pad", "drum"):
            recs = groups.get(fam, [])
            if not recs:
                continue
            preset = mapping.get(fam)
            if preset is None:
                log(f"skip {fam}: no preset selected")
                continue
            log(f"rendering {fam}: {len(recs)} samples")
            for rec in recs:
                if fam == "drum":
                    dtype = rec["drum_type"]
                    note = int(mapping.get("drum_notes", DRUM_NOTES).get(dtype, DRUM_NOTES[dtype]))
                    vel = DRUM_VELOCITY.get(dtype, 100)
                    dur = DRUM_MAX.get(dtype, DRUM_DUR)
                else:
                    note = int(rec["note"])
                    vel = LAYER_VELOCITY.get(rec["layer"], 90)
                    dur = NOTE_DUR
                y = sfo.render_note(int(preset), note, vel, dur)
                peak = float(np.max(np.abs(y)))
                if peak < 1e-9:
                    log(f"  warning: silent sample {rec['name']}")
                target = orig_peaks.get(rec["name"], 0.9)
                if peak > 1e-9:
                    y = y * (target / peak)
                # tiny fade-out to avoid clicks
                n = min(len(y), int(0.02 * SR))
                if n > 0:
                    y[-n:] *= np.linspace(1.0, 0.0, n, dtype=np.float32)
                p = work / (rec["name"] + ".ogg")
                _write_ogg(p, y)
                rendered.append(p)
            log(f"  {len(recs)} samples written")

        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(
                "pack.mcmeta",
                json.dumps(
                    {
                        "pack": {
                            "pack_format": 64,
                            "description": "Online SoundFont instrument pack for RedPiano",
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            z.writestr(
                "CREDITS.txt",
                "McMusicMaker online SoundFont pack\n"
                "==================================\n\n"
                "Source SoundFont: " + str(sf_path) + "\n"
                "Rendered offline with studio/sf2_synth.py.\n"
                "Check the original SoundFont license before redistributing.\n",
            )
            with zipfile.ZipFile(SRC_ZIP) as src:
                z.writestr("assets/qzpno/sounds.json", src.read("assets/qzpno/sounds.json"))
            for p in rendered:
                z.write(str(p), "assets/qzpno/sounds/" + p.name)
        log(f"pack written: {out_zip} ({len(rendered)} samples)")
        return out_zip
    finally:
        shutil.rmtree(work, ignore_errors=True)

def _parse_bank_prog(text: str, default_bank: int = 0) -> tuple[int, int]:
    if ":" in text:
        b, p = text.split(":", 1)
        return int(b), int(p)
    return default_bank, int(text)


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Build a RedPiano resource pack from a SoundFont.")
    ap.add_argument("--sf2", required=True, help="path to .sf2/.sf3 file")
    ap.add_argument("--out", default="output/online_instrument_pack.zip")
    ap.add_argument("--pno", default="0", help="piano preset: bank:program or program")
    ap.add_argument("--lead", default="29", help="lead/preset: bank:program or program")
    ap.add_argument("--pad", default="48", help="pad/preset: bank:program or program")
    ap.add_argument("--bass", default="33", help="bass/preset: bank:program or program")
    ap.add_argument("--drum", default="128:0", help="drum kit preset: bank:program or program")
    ap.add_argument("--list", action="store_true", help="list presets and exit")
    args = ap.parse_args(argv)

    if args.list:
        for i, bank, prog, name in SoundFont(args.sf2).list_presets():
            print(f"{i}\tbank={bank}\tprog={prog}\t{name}")
        return 0

    sfo = SoundFont(args.sf2)
    mapping = {}
    for fam, text in (("pno", args.pno), ("lead", args.lead), ("pad", args.pad), ("bass", args.bass)):
        bank, prog = _parse_bank_prog(text)
        idx = sfo.find_preset(bank, prog)
        if idx is None:
            print(f"warning: no preset bank={bank} program={prog} for {fam}")
            continue
        mapping[fam] = idx
    bank, prog = _parse_bank_prog(args.drum, 128)
    idx = sfo.find_preset(bank, prog)
    if idx is not None:
        mapping["drum"] = idx
    else:
        print(f"warning: no drum preset bank={bank} program={prog}")

    print("mapping:", mapping)
    build_pack(args.sf2, mapping, out_zip=args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
