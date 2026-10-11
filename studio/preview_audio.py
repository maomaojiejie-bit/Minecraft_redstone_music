"""Audio preview renderer for MIDI files.

Renders a WAV preview of the RedPiano mapping output. When the bundled
qzpno_mv.zip sample pack is available, the real .ogg samples are used (the
same samples the in-game note blocks play); otherwise it falls back to simple
synthesized timbres so a preview is still possible.
"""
import io
import json
import subprocess
import zipfile
from pathlib import Path

import mido
import numpy as np

try:
    import soundfile as sf
    SOUNDFILE_OK = True
except Exception:
    SOUNDFILE_OK = False

try:
    import winsound
    WINSOUND_OK = True
except Exception:
    WINSOUND_OK = False

from .paths import BASE_DIR

SR = 44100

DEFAULT_FAMILY_MAP = {
    0: "pno", 1: "pno", 2: "pad", 3: "lead", 4: "bass", 5: "pad", 6: "pad", 7: "lead",
    8: "lead", 9: "lead", 10: "lead", 11: "pad", 12: "pad", 13: "lead", 14: "drum", 15: "drum",
}
DEFAULT_DRUM_MAP = {
    35: "kick", 36: "kick", 38: "snare", 40: "snare", 37: "snare",
    42: "hihat_closed", 44: "hihat_closed", 46: "hihat_closed", 54: "hihat_closed",
    41: "tom", 43: "tom", 45: "tom", 47: "tom", 48: "tom", 50: "tom",
    49: "crash", 51: "ride", 52: "crash", 55: "crash", 57: "crash", 59: "ride",
}
CRASH_TYPES = {"crash", "ride", "china", "splash"}


SAMPLE_ZIP_NAME = "qzpno_mv.zip"
_SAMPLE_CACHE = {}


def _sample_zip_path(skill_dir=None):
    if skill_dir:
        p = Path(skill_dir) / "assets" / SAMPLE_ZIP_NAME
    else:
        p = BASE_DIR / "minecraft-redstone-music" / "assets" / SAMPLE_ZIP_NAME
    return p if p.is_file() else None


def load_instrument_map(skill_dir=None):
    path = Path(skill_dir) / "assets" / "redpiano_map_multi.json" if skill_dir else \
        BASE_DIR / "minecraft-redstone-music" / "assets" / "redpiano_map_multi.json"
    if not path.is_file():
        return None, None
    try:
        mm = json.loads(path.read_text(encoding="utf-8"))
        instruments = mm.get("instruments")
        gm_drum_map = {int(k): v for k, v in (mm.get("gm_drum_map") or {}).items()}
        if not instruments:
            return None, None
        return instruments, gm_drum_map
    except Exception:
        return None, None


def _layer_for(vel01, instr, layers):
    if instr == "pno":
        layer = "p" if vel01 < 0.40 else ("mf" if vel01 < 0.72 else "f")
    else:
        layer = "mf"
    if layer not in layers:
        layer = "mf" if "mf" in layers else layers[0]
    return layer


def _resolve_note(instruments, gm_drum_map, family, midi, vel01):
    inst = instruments[family]
    if not inst.get("pitched", False):
        dtype = gm_drum_map.get(midi, "snare")
        if dtype not in inst["types"]:
            dtype = next(iter(inst["types"]))
        key = "drum:" + dtype
        return inst["sound"][key], 12, key
    bands = inst["bands"]
    band = min(bands, key=lambda b: abs(b - midi))
    raw = 12 + (midi - band)
    m = midi
    for _ in range(12):
        if raw < 0:
            m += 12
        elif raw > 24:
            m -= 12
        else:
            break
        band = min(bands, key=lambda b: abs(b - m))
        raw = 12 + (m - band)
        if 0 <= raw <= 24:
            break
    nv = max(0, min(24, raw))
    layer = _layer_for(vel01, family, inst["layers"])
    key = f"{band}_{layer}"
    return inst["sound"][key], nv, key


def _read_sample(zf, sound_event):
    if sound_event in _SAMPLE_CACHE:
        return _SAMPLE_CACHE[sound_event]
    name = sound_event.split(":", 1)[1]
    data = zf.read("assets/qzpno/sounds/" + name + ".ogg")
    audio, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    if audio.shape[1] > 1:
        audio = audio.mean(axis=1, keepdims=True)
    out = (audio[:, 0], sr)
    _SAMPLE_CACHE[sound_event] = out
    return out


def _resample(sample, ratio):
    if abs(ratio - 1.0) < 1e-9:
        return sample
    n = int(len(sample) / ratio)
    if n <= 1:
        return np.zeros(0, dtype=np.float32)
    x = np.arange(n, dtype=np.float64) * ratio
    i = np.floor(x).astype(np.int64)
    i = np.clip(i, 0, len(sample) - 2)
    frac = (x - i).astype(np.float32)
    return (sample[i] * (1.0 - frac) + sample[i + 1] * frac).astype(np.float32)


def render_notes_sampled(notes, out_wav, sr=SR, max_seconds=None, guitar=False, pad_flute=False,
                         volumes=None, crash_volume=0.35, progress=None, skill_dir=None,
                         sample_zip=None):
    if not notes:
        raise ValueError("MIDI has no renderable notes")
    if not SOUNDFILE_OK:
        raise RuntimeError("soundfile is required to write WAV")
    if sample_zip:
        zip_path = Path(sample_zip)
        if not zip_path.is_file():
            raise RuntimeError("sample pack not found: " + str(zip_path))
    else:
        zip_path = _sample_zip_path(skill_dir)
        if zip_path is None:
            raise RuntimeError("sample pack not found")
    instruments, gm_drum_map = load_instrument_map(skill_dir)
    if not instruments:
        raise RuntimeError("instrument map not found")
    volumes = volumes or {}
    total = max(float(n["end"]) for n in notes)
    if max_seconds and max_seconds > 0:
        total = min(total, float(max_seconds))
    n_samples = int(total * sr) + int(0.5 * sr)
    buf = np.zeros(n_samples, dtype=np.float32)
    total_notes = len(notes)
    _SAMPLE_CACHE.clear()
    zf = zipfile.ZipFile(zip_path)
    try:
        for i, raw in enumerate(notes):
            note = dict(raw)
            if float(note["start"]) >= total:
                continue
            note["end"] = min(float(note["end"]), total)
            if note["end"] <= note["start"]:
                continue
            fam = note["family"]
            use_synth = (guitar and fam == "lead") or (pad_flute and fam == "pad")
            if use_synth:
                w = _synth_note(note, sr=sr, guitar=guitar, pad_flute=pad_flute)
                scale = 1.0 / 2.6
                scale *= float(volumes.get(fam, 100)) / 100.0
                if fam == "drum" and note.get("drum_type") in CRASH_TYPES:
                    scale *= float(crash_volume)
                w = w * scale
                s0 = int(float(note["start"]) * sr)
                e0 = min(n_samples, s0 + len(w))
                if e0 > s0:
                    buf[s0:e0] += w[:e0 - s0]
                if progress and (i % 250 == 0 or i == total_notes - 1):
                    progress(i + 1, total_notes)
                continue
            if fam not in instruments:
                continue
            vel = max(0.0, min(1.0, float(note["vel"])))
            try:
                event, nv, key = _resolve_note(instruments, gm_drum_map, fam, int(note["midi"]), vel)
                sample, ssr = _read_sample(zf, event)
            except Exception:
                continue
            ratio = 2.0 ** ((nv - 12) / 12.0)
            w = _resample(sample, ratio)
            if ssr != sr:
                w = _resample(w, ssr / sr)
            inst = instruments[fam]
            vol = float(inst.get("vol", {}).get(key, 1.0))
            scale = vel * vol / 2.6
            scale *= float(volumes.get(fam, 100)) / 100.0
            if fam == "drum" and note.get("drum_type") in CRASH_TYPES:
                scale *= float(crash_volume)
            w = w * scale
            s = int(float(note["start"]) * sr)
            e = min(n_samples, s + len(w))
            if e > s:
                buf[s:e] += w[:e - s]
            if progress and (i % 250 == 0 or i == total_notes - 1):
                progress(i + 1, total_notes)
    finally:
        zf.close()
    peak = float(np.max(np.abs(buf))) if buf.size else 0.0
    if peak > 0:
        buf *= 0.95 / peak
    sf.write(str(out_wav), buf, sr, subtype="PCM_16")
    return str(out_wav)



def load_maps(skill_dir=None):
    family_map = dict(DEFAULT_FAMILY_MAP)
    drum_map = dict(DEFAULT_DRUM_MAP)
    path = Path(skill_dir) / "assets" / "redpiano_map_multi.json" if skill_dir else \
        BASE_DIR / "minecraft-redstone-music" / "assets" / "redpiano_map_multi.json"
    if path.is_file():
        try:
            mm = json.loads(path.read_text(encoding="utf-8"))
            if "family_map" in mm:
                family_map = {int(k): v for k, v in mm["family_map"].items()}
            if "gm_drum_map" in mm:
                drum_map = {int(k): v for k, v in mm["gm_drum_map"].items()}
        except Exception:
            pass
    return family_map, drum_map


def parse_midi(path, family_map=None, drum_map=None, voice_to_piano=False):
    family_map = family_map or DEFAULT_FAMILY_MAP
    drum_map = drum_map or DEFAULT_DRUM_MAP
    mid = mido.MidiFile(path)
    tempo = 500000
    t = 0.0
    cur_prog = {}
    active = {}
    notes = []
    for msg in mido.merge_tracks(mid.tracks):
        if msg.time:
            t += mido.tick2second(msg.time, mid.ticks_per_beat, tempo)
        if msg.is_meta:
            if msg.type == "set_tempo":
                tempo = msg.tempo
            continue
        if msg.type == "program_change":
            cur_prog[msg.channel] = msg.program
        elif msg.type == "note_on" and msg.velocity > 0:
            prog = cur_prog.get(msg.channel, 0)
            active[(msg.channel, msg.note)] = (t, msg.velocity, prog)
        elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            key = (msg.channel, msg.note)
            if key in active:
                start, vel, prog = active.pop(key)
                fam = "drum" if msg.channel == 9 else family_map.get(prog // 8, "pno")
                if voice_to_piano and msg.channel != 9 and prog in (52, 53, 54):
                    fam = "pno"
                dtype = drum_map.get(msg.note, "snare") if fam == "drum" else ""
                notes.append({
                    "midi": msg.note, "start": start, "end": t, "vel": vel / 127.0,
                    "family": fam, "program": prog, "channel": msg.channel, "drum_type": dtype,
                })
    for (ch, note), (start, vel, prog) in list(active.items()):
        fam = "drum" if ch == 9 else family_map.get(prog // 8, "pno")
        notes.append({
            "midi": note, "start": start, "end": t + 0.2, "vel": vel / 127.0,
            "family": fam, "program": prog, "channel": ch, "drum_type": "",
        })
    notes.sort(key=lambda n: n["start"])
    return notes


def _synth_note(note, sr=SR, guitar=True, pad_flute=True):
    midi = int(note["midi"])
    dur = max(0.05, float(note["end"]) - float(note["start"]))
    n = max(1, int(dur * sr))
    t = np.arange(n, dtype=np.float32) / sr
    freq = 440.0 * (2.0 ** ((midi - 69) / 12.0))
    fam = note["family"]
    vel = max(0.05, float(note["vel"]))
    if fam == "pno":
        env = np.exp(-t * 3.2) * np.minimum(1.0, t / 0.004)
        w = (np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(4 * np.pi * freq * t)
             + 0.16 * np.sin(6 * np.pi * freq * t) + 0.08 * np.sin(8 * np.pi * freq * t)) * env
    elif fam == "lead":
        if guitar:
            env = np.exp(-t * 6.5) * np.minimum(1.0, t / 0.002)
            w = (np.sin(2 * np.pi * freq * t) + 0.5 * np.sin(4 * np.pi * freq * t)
                 + 0.3 * np.sin(6 * np.pi * freq * t) + 0.15 * np.sin(8 * np.pi * freq * t)) * env
        else:
            env = np.exp(-t * 1.8) * np.minimum(1.0, t / 0.01)
            w = (2.0 * ((freq * t) % 1.0) - 1.0) * env
    elif fam == "pad":
        if pad_flute:
            env = np.minimum(1.0, t / 0.08) * np.exp(-t * 1.1)
            vib = 0.012 * np.sin(2 * np.pi * 5.0 * t)
            w = (np.sin(2 * np.pi * freq * t + vib) + 0.15 * np.sin(4 * np.pi * freq * t + vib)) * env
        else:
            env = np.minimum(1.0, t / 0.25) * np.exp(-t * 0.7)
            vib = 0.008 * np.sin(2 * np.pi * 4.5 * t)
            w = (np.sin(2 * np.pi * freq * t + vib) + 0.5 * np.sin(4 * np.pi * freq * t + vib)
                 + 0.25 * np.sin(6 * np.pi * freq * t + vib)) * env
    elif fam == "bass":
        env = np.exp(-t * 2.6) * np.minimum(1.0, t / 0.004)
        w = (np.sin(2 * np.pi * freq * t) + 0.4 * np.sin(4 * np.pi * freq * t)
             + 0.15 * np.sin(6 * np.pi * freq * t)) * env
    elif fam == "drum":
        dtype = note.get("drum_type", "snare")
        rng = np.random.default_rng((midi * 131 + int(float(note["start"]) * 1000)) % (2 ** 31 - 1))
        if dtype == "kick":
            env = np.exp(-t * 18.0)
            f_sweep = freq * (0.5 + 0.5 * np.exp(-t * 25.0))
            w = np.sin(2 * np.pi * f_sweep * t) * env
        elif dtype.startswith("hihat"):
            env = np.exp(-t * 55.0)
            w = rng.standard_normal(n).astype(np.float32) * env
        elif dtype == "tom":
            env = np.exp(-t * 12.0)
            w = np.sin(2 * np.pi * freq * t) * env
        elif dtype in CRASH_TYPES:
            env = np.exp(-t * 3.5)
            w = rng.standard_normal(n).astype(np.float32) * env
        else:
            env = np.exp(-t * 22.0)
            w = (0.6 * np.sin(2 * np.pi * freq * 1.5 * t) * np.exp(-t * 18.0)
                 + 0.8 * rng.standard_normal(n).astype(np.float32) * env)
    else:
        w = np.sin(2 * np.pi * freq * t) * np.exp(-t * 3.0)
    return (w * vel).astype(np.float32)


def render_notes(notes, out_wav, sr=SR, max_seconds=None, guitar=True, pad_flute=True,
                 volumes=None, crash_volume=0.35, progress=None):
    if not notes:
        raise ValueError("MIDI has no renderable notes")
    if not SOUNDFILE_OK:
        raise RuntimeError("soundfile is required to write WAV")
    volumes = volumes or {}
    total = max(float(n["end"]) for n in notes)
    if max_seconds and max_seconds > 0:
        total = min(total, float(max_seconds))
    n_samples = int(total * sr) + int(0.5 * sr)
    buf = np.zeros(n_samples, dtype=np.float32)
    total_notes = len(notes)
    for i, raw in enumerate(notes):
        if float(raw["start"]) >= total:
            continue
        note = dict(raw)
        note["end"] = min(float(note["end"]), total)
        if note["end"] <= note["start"]:
            continue
        w = _synth_note(note, sr=sr, guitar=guitar, pad_flute=pad_flute)
        fam = note["family"]
        scale = float(volumes.get(fam, 100)) / 100.0
        if fam == "drum" and note.get("drum_type") in CRASH_TYPES:
            scale *= float(crash_volume)
        w = w * scale
        s = int(float(note["start"]) * sr)
        e = min(n_samples, s + len(w))
        if e > s:
            buf[s:e] += w[:e - s]
        if progress and (i % 250 == 0 or i == total_notes - 1):
            progress(i + 1, total_notes)
    peak = float(np.max(np.abs(buf))) if buf.size else 0.0
    if peak > 0:
        buf *= 0.95 / peak
    sf.write(str(out_wav), buf, sr, subtype="PCM_16")
    return str(out_wav)


def render_midi_to_wav(midi_path, out_wav, max_seconds=None, guitar=True, pad_flute=True,
                       voice_to_piano=False, volumes=None, crash_volume=0.35, progress=None,
                       sample_zip=None):
    family_map, drum_map = load_maps()
    notes = parse_midi(midi_path, family_map, drum_map, voice_to_piano=voice_to_piano)
    if SOUNDFILE_OK and (sample_zip or _sample_zip_path() is not None):
        try:
            return render_notes_sampled(notes, out_wav, max_seconds=max_seconds,
                                        guitar=guitar, pad_flute=pad_flute,
                                        volumes=volumes, crash_volume=crash_volume,
                                        progress=progress, sample_zip=sample_zip)
        except Exception:
            pass
    return render_notes(notes, out_wav, max_seconds=max_seconds, guitar=guitar,
                        pad_flute=pad_flute, volumes=volumes, crash_volume=crash_volume,
                        progress=progress)


def play_audio(path):
    path = str(path)
    if WINSOUND_OK and path.lower().endswith(".wav"):
        try:
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return True
        except Exception:
            pass
    try:
        subprocess.Popen(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path])
        return True
    except Exception:
        return False


def stop_audio():
    if WINSOUND_OK:
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass
