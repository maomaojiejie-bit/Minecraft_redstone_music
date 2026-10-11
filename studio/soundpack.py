"""Small helpers used by the studio GUI for MIDI / sound-pack tweaks."""

import json
import os
import zipfile


def remap_voice_to_piano(src_midi: str, dst_midi: str) -> int:
    """Copy a MIDI and turn every GM program 52 (Voice/Choir) into piano (0).

    Returns the number of program-change messages changed.
    """
    import mido  # imported lazily so the GUI can show a clean error

    mf = mido.MidiFile(src_midi, clip=True)
    changed = 0
    for track in mf.tracks:
        for i, msg in enumerate(track):
            if msg.type == "program_change" and msg.program == 52:
                track[i] = mido.Message(
                    "program_change",
                    channel=msg.channel,
                    program=0,
                    time=msg.time,
                )
                changed += 1
    mf.save(dst_midi)
    return changed


def make_custom_pack(
    src_zip: str,
    dst_zip: str,
    guitar: bool = True,
    pad_flute: bool = True,
    crash_volume: float = 0.35,
    volumes: dict | None = None,
) -> None:
    """Create a qzpno_mv-style pack with selected sound redirections.

    - guitar: lead_* -> vanilla note-block guitar
    - pad_flute: pad_* -> vanilla note-block flute
    - crash_volume: fallback multiplier for drum_crash_x
    - volumes: optional per-family multipliers:
      pno, lead, pad, bass, drum, crash
    """
    volumes = volumes or {}

    def _mult(key, default=1.0):
        try:
            return float(volumes.get(key, default))
        except Exception:
            return default

    os.makedirs(os.path.dirname(os.path.abspath(dst_zip)), exist_ok=True)
    with zipfile.ZipFile(src_zip, "r") as zin, zipfile.ZipFile(
        dst_zip, "w", zipfile.ZIP_DEFLATED
    ) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "assets/qzpno/sounds.json":
                sounds = json.loads(data.decode("utf-8"))
                for key, val in sounds.items():
                    if guitar and key.startswith("lead_"):
                        for s in val.get("sounds", []):
                            s["name"] = "minecraft:block.note_block.guitar"
                    if pad_flute and key.startswith("pad_"):
                        for s in val.get("sounds", []):
                            s["name"] = "minecraft:block.note_block.flute"
                    # family volume multiplier
                    mult = None
                    if key.startswith("pno_"):
                        mult = _mult("pno")
                    elif key.startswith("bass_"):
                        mult = _mult("bass")
                    elif key.startswith("lead_"):
                        mult = _mult("lead")
                    elif key.startswith("pad_"):
                        mult = _mult("pad")
                    elif key.startswith("drum_"):
                        mult = _mult("drum")
                        if "drum_crash" in key:
                            mult *= _mult("crash", float(crash_volume))
                    if mult is not None and abs(mult - 1.0) > 1e-9:
                        for s in val.get("sounds", []):
                            base = float(s.get("volume", 1.0))
                            s["volume"] = round(base * mult, 4)
                data = json.dumps(
                    sounds, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
            zout.writestr(item, data)


def extend_note_durations(src_midi: str, dst_midi: str, max_gap_s: float = 2.0) -> int:
    """Copy a MIDI and lengthen each note into the following rest/gap.

    The goal is a legato/sustain effect: a note-off is moved later, up to
    ``max_gap_s`` seconds, so pad/lead/bass samples can ring through short gaps.
    Returns the number of note-off events changed.
    """
    import mido
    from collections import defaultdict, deque

    mf = mido.MidiFile(src_midi, clip=True)
    tpb = mf.ticks_per_beat
    # Assume 120 BPM when no explicit tempo map is needed; the skill's songs are
    # constant-tempo 120 BPM. A conservative tick budget is fine for a gap cap.
    max_gap_ticks = max(1, int(round(max_gap_s * tpb * 2)))
    new_tracks = []
    changed_total = 0

    for track in mf.tracks:
        abs_events = []
        t = 0
        for msg in track:
            t += msg.time
            abs_events.append([t, msg])
        note_ons = []
        kept = []
        for at, msg in abs_events:
            if msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                continue
            kept.append([at, msg])
            if msg.type == "note_on" and msg.velocity > 0:
                note_ons.append((at, msg.channel, msg.note, msg.velocity))
        offs = []
        for at, msg in abs_events:
            if msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                offs.append((at, msg.channel, msg.note))
        offq = defaultdict(deque)
        for at, ch, note in offs:
            offq[(ch, note)].append(at)
        onq = defaultdict(deque)
        for at, ch, note, vel in note_ons:
            onq[(ch, note)].append(at)
        for at, ch, note, vel in note_ons:
            q = onq[(ch, note)]
            if q and q[0] == at:
                q.popleft()
            next_on = q[0] if q else None
            if offq[(ch, note)]:
                orig_off = offq[(ch, note)].popleft()
            else:
                orig_off = at + max_gap_ticks
            if next_on is not None:
                gap = next_on - orig_off
                if gap > 0 and gap <= max_gap_ticks:
                    new_off = next_on - 1
                else:
                    new_off = min(orig_off + max_gap_ticks, next_on - 1)
            else:
                new_off = orig_off + max_gap_ticks
            if new_off < at:
                new_off = at + 1
            if new_off != orig_off:
                changed_total += 1
            kept.append([new_off, mido.Message("note_off", channel=ch, note=note, velocity=0, time=0)])
        kept.sort(key=lambda x: x[0])
        nt = mido.MidiTrack()
        last = 0
        for at, msg in kept:
            nt.append(msg.copy(time=max(0, at - last)))
            last = at
        new_tracks.append(nt)

    out = mido.MidiFile(type=mf.type, ticks_per_beat=tpb)
    out.tracks = new_tracks
    out.save(dst_midi)
    return changed_total
