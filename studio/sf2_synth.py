"""Minimal pure-Python SoundFont 2 (.sf2) parser and sampler.

Supports the subset needed to render single notes from a preset:
- RIFF sfbk parsing (INFO, sdta, pdta)
- preset / instrument / bag / generator / sample-header parsing
- key & velocity range selection
- sample loop, root key, coarse/fine tune, attenuation, simple ADSR
No modulators, filters or LFOs.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np
from scipy.signal import resample_poly

SR = 44100

# Generator oper codes
GEN_START_ADDRS = 0
GEN_END_ADDRS = 1
GEN_STARTLOOP_ADDRS = 2
GEN_ENDLOOP_ADDRS = 3
GEN_START_ADDRS_COARSE = 4
GEN_END_ADDRS_COARSE = 12
GEN_STARTLOOP_ADDRS_COARSE = 45
GEN_ENDLOOP_ADDRS_COARSE = 50
GEN_KEY_RANGE = 43
GEN_VEL_RANGE = 44
GEN_INSTRUMENT = 41
GEN_SAMPLE_ID = 53
GEN_SAMPLE_MODES = 54
GEN_OVERRIDING_ROOT_KEY = 58
GEN_COARSE_TUNE = 51
GEN_FINE_TUNE = 52
GEN_SCALE_TUNING = 56
GEN_INITIAL_ATTENUATION = 48
GEN_PAN = 17
GEN_DELAY_VOL_ENV = 33
GEN_ATTACK_VOL_ENV = 34
GEN_HOLD_VOL_ENV = 35
GEN_DECAY_VOL_ENV = 36
GEN_SUSTAIN_VOL_ENV = 37
GEN_RELEASE_VOL_ENV = 38


@dataclass
class SampleHeader:
    name: str
    start: int
    end: int
    startloop: int
    endloop: int
    sample_rate: int
    original_key: int
    correction: int
    sample_link: int
    sample_type: int


@dataclass
class Zone:
    gens: dict[int, int] = field(default_factory=dict)
    sample: SampleHeader | None = None
    instrument: int = 0
    key_low: int = 0
    key_high: int = 127
    vel_low: int = 0
    vel_high: int = 127

    def refresh(self) -> None:
        kr = self.gens.get(GEN_KEY_RANGE)
        if kr is not None:
            self.key_low = kr & 0xFF
            self.key_high = (kr >> 8) & 0xFF
        vr = self.gens.get(GEN_VEL_RANGE)
        if vr is not None:
            self.vel_low = vr & 0xFF
            self.vel_high = (vr >> 8) & 0xFF


@dataclass
class Instrument:
    name: str
    bag_index: int = 0
    zones: list[Zone] = field(default_factory=list)


@dataclass
class Preset:
    name: str
    bank: int
    preset: int
    bag_index: int = 0
    zones: list[Zone] = field(default_factory=list)


class SoundFont:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.presets: list[Preset] = []
        self.instruments: list[Instrument] = []
        self.samples: list[SampleHeader] = []
        self.smpl: np.ndarray | None = None
        self._parse()

    # ---------------------------------------------------------------- parsing
    def _parse(self) -> None:
        data = self.path.read_bytes()
        if data[:4] != b"RIFF" or data[8:12] != b"sfbk":
            raise ValueError("not a SoundFont 2 file: " + str(self.path))
        self._parse_riff(data)

    def _parse_riff(self, data: bytes) -> None:
        pos = 12
        end = len(data)
        while pos + 8 <= end:
            cid = data[pos:pos + 4]
            size = struct.unpack_from("<I", data, pos + 4)[0]
            body = pos + 8
            body_end = body + size
            if cid == b"LIST":
                list_type = data[body:body + 4]
                if list_type == b"sdta":
                    self._parse_sdta(data, body + 4, body_end)
                elif list_type == b"pdta":
                    self._parse_pdta(data, body + 4, body_end)
            pos = body_end + (size & 1)

    def _parse_sdta(self, data: bytes, start: int, end: int) -> None:
        pos = start
        while pos + 8 <= end:
            cid = data[pos:pos + 4]
            size = struct.unpack_from("<I", data, pos + 4)[0]
            body = pos + 8
            if cid == b"smpl":
                self.smpl = np.frombuffer(data[body:body + size], dtype="<i2").astype(np.float32)
            pos = body + size + (size & 1)

    def _parse_pdta(self, data: bytes, start: int, end: int) -> None:
        chunks: dict[bytes, bytes] = {}
        pos = start
        while pos + 8 <= end:
            cid = data[pos:pos + 4]
            size = struct.unpack_from("<I", data, pos + 4)[0]
            body = pos + 8
            chunks[cid] = data[body:body + size]
            pos = body + size + (size & 1)

        # ---- phdr
        raw = chunks.get(b"phdr", b"")
        presets: list[Preset] = []
        for i in range(len(raw) // 38):
            base = i * 38
            name = raw[base:base + 20].split(b"\0")[0].decode("latin-1")
            preset, bank, bag = struct.unpack_from("<HHH", raw, base + 20)
            presets.append(Preset(name=name, bank=bank, preset=preset, bag_index=bag))
            if not name and preset == 0 and bank == 0 and i > 0:
                # terminal EOP preset, keep but it has no zones
                pass
        # last record is terminal
        presets = presets[:-1]

        # ---- inst
        raw = chunks.get(b"inst", b"")
        insts: list[Instrument] = []
        for i in range(len(raw) // 22):
            base = i * 22
            name = raw[base:base + 20].split(b"\0")[0].decode("latin-1")
            bag = struct.unpack_from("<H", raw, base + 20)[0]
            insts.append(Instrument(name=name, bag_index=bag))
        insts = insts[:-1]

        # ---- shdr
        raw = chunks.get(b"shdr", b"")
        samples: list[SampleHeader] = []
        for i in range(len(raw) // 46):
            base = i * 46
            name = raw[base:base + 20].split(b"\0")[0].decode("latin-1")
            start_, end_, sl, el, rate = struct.unpack_from("<IIIII", raw, base + 20)
            key, corr, link, stype = struct.unpack_from("<BbHH", raw, base + 40)
            samples.append(SampleHeader(name, start_, end_, sl, el, rate, key, corr, link, stype))
        samples = samples[:-1]

        # ---- bags / generators
        def parse_bags(chunk: bytes) -> list[tuple[int, int]]:
            out = []
            for i in range(len(chunk) // 4):
                g, m = struct.unpack_from("<HH", chunk, i * 4)
                out.append((g, m))
            return out

        def parse_gens(chunk: bytes) -> list[tuple[int, int]]:
            out = []
            for i in range(len(chunk) // 4):
                oper, amount = struct.unpack_from("<HH", chunk, i * 4)
                out.append((oper, amount))
            return out

        pbag = parse_bags(chunks.get(b"pbag", b""))
        pgen = parse_gens(chunks.get(b"pgen", b""))
        ibag = parse_bags(chunks.get(b"ibag", b""))
        igen = parse_gens(chunks.get(b"igen", b""))

        def gens_for(gens_raw: list[tuple[int, int]], lo: int, hi: int) -> dict[int, int]:
            d: dict[int, int] = {}
            for i in range(lo, min(hi, len(gens_raw))):
                oper, amount = gens_raw[i]
                d[oper] = amount
            return d

        def signed16(v: int) -> int:
            return v - 65536 if v & 0x8000 else v

        # resolve instruments
        for idx, inst in enumerate(insts):
            bag = inst.bag_index
            next_bag = insts[idx + 1].bag_index if idx + 1 < len(insts) else len(ibag)
            zones: list[Zone] = []
            for zi in range(bag, next_bag):
                gi = ibag[zi][0] if zi < len(ibag) else len(igen)
                gj = ibag[zi + 1][0] if zi + 1 < len(ibag) else len(igen)
                gens = gens_for(igen, gi, gj)
                z = Zone(gens=gens)
                sid = gens.get(GEN_SAMPLE_ID)
                if sid is not None and 0 <= sid < len(samples):
                    z.sample = samples[sid]
                z.refresh()
                zones.append(z)
            inst.zones = zones

        # resolve presets
        for idx, preset in enumerate(presets):
            bag = preset.bag_index
            next_bag = presets[idx + 1].bag_index if idx + 1 < len(presets) else len(pbag)
            zones: list[Zone] = []
            for zi in range(bag, next_bag):
                gi = pbag[zi][0] if zi < len(pbag) else len(pgen)
                gj = pbag[zi + 1][0] if zi + 1 < len(pbag) else len(pgen)
                pgens = gens_for(pgen, gi, gj)
                inst_idx = pgens.get(GEN_INSTRUMENT, 0)
                inst = insts[inst_idx] if 0 <= inst_idx < len(insts) else None
                if inst is None:
                    continue
                for iz in inst.zones:
                    if iz.sample is None:
                        continue
                    merged = dict(iz.gens)
                    # preset-level key/vel range narrows the instrument zone
                    for key in (GEN_KEY_RANGE, GEN_VEL_RANGE):
                        if key in pgens and key in merged:
                            a = pgens[key]
                            b = merged[key]
                            lo_k = max(a & 0xFF, b & 0xFF)
                            hi_k = min((a >> 8) & 0xFF, (b >> 8) & 0xFF)
                            if lo_k > hi_k:
                                merged.pop(key, None)
                            else:
                                merged[key] = lo_k | (hi_k << 8)
                        elif key in pgens:
                            merged[key] = pgens[key]
                    # preset instrument generator itself is not a real generator
                    merged.pop(GEN_INSTRUMENT, None)
                    z = Zone(gens=merged, sample=iz.sample, instrument=inst_idx)
                    z.refresh()
                    zones.append(z)
            preset.zones = zones

        self.presets = presets
        self.instruments = insts
        self.samples = samples

    # ---------------------------------------------------------------- query
    def list_presets(self) -> list[tuple[int, int, int, str]]:
        return [(i, p.bank, p.preset, p.name) for i, p in enumerate(self.presets)]

    def find_preset(self, bank: int, program: int) -> int | None:
        for i, p in enumerate(self.presets):
            if p.bank == bank and p.preset == program:
                return i
        return None

    # ---------------------------------------------------------------- synth
    def render_note(self, preset_index: int, note: int, velocity: int = 100,
                    duration: float = 2.0, sr: int = SR) -> np.ndarray:
        if self.smpl is None:
            raise RuntimeError("soundfont has no sample data")
        if not (0 <= preset_index < len(self.presets)):
            raise IndexError("preset index out of range")
        preset = self.presets[preset_index]
        out = np.zeros(int(duration * sr) + 1, dtype=np.float32)
        any_zone = False
        for z in preset.zones:
            if z.sample is None:
                continue
            if not (z.key_low <= note <= z.key_high):
                continue
            if not (z.vel_low <= velocity <= z.vel_high):
                continue
            any_zone = True
            self._render_zone(z, note, velocity, duration, sr, out)
        if not any_zone:
            return out
        peak = float(np.max(np.abs(out)))
        if peak > 1e-9:
            out /= peak
        return out

    def _render_zone(self, z: Zone, note: int, velocity: int, duration: float,
                     sr: int, out: np.ndarray) -> None:
        g = z.gens
        smp = z.sample
        assert smp is not None and self.smpl is not None
        data = self.smpl

        def addr(offset_key: int, coarse_key: int) -> int:
            v = g.get(offset_key, 0)
            c = g.get(coarse_key, 0)
            # signed 16-bit
            if v & 0x8000:
                v -= 65536
            if c & 0x8000:
                c -= 65536
            return v + c * 32768

        start = smp.start + addr(GEN_START_ADDRS, GEN_START_ADDRS_COARSE)
        end = smp.end + addr(GEN_END_ADDRS, GEN_END_ADDRS_COARSE)
        loop_start = smp.startloop + addr(GEN_STARTLOOP_ADDRS, GEN_STARTLOOP_ADDRS_COARSE)
        loop_end = smp.endloop + addr(GEN_ENDLOOP_ADDRS, GEN_ENDLOOP_ADDRS_COARSE)
        start = max(0, min(start, len(data) - 1))
        end = max(start + 1, min(end, len(data)))
        loop_start = max(start, min(loop_start, end))
        loop_end = max(loop_start, min(loop_end, end))

        root = g.get(GEN_OVERRIDING_ROOT_KEY, 255)
        if root == 255 or root > 127:
            root = smp.original_key
        coarse = g.get(GEN_COARSE_TUNE, 0)
        if coarse & 0x8000:
            coarse -= 65536
        fine = g.get(GEN_FINE_TUNE, 0)
        if fine & 0x8000:
            fine -= 65536
        # sample.correction is signed cents, fine is cents
        semis = (note - root) + coarse + (fine + smp.correction) / 100.0
        ratio = 2.0 ** (semis / 12.0)

        modes = g.get(GEN_SAMPLE_MODES, 0)
        do_loop = modes in (1, 3) and loop_end > loop_start

        src_rate = max(1, smp.sample_rate)
        need = int(duration * src_rate * ratio) + 1
        pre = data[start:loop_start] if do_loop and loop_start > start else data[start:end]
        if do_loop:
            loop_seg = data[loop_start:loop_end]
            if len(loop_seg) == 0:
                do_loop = False
            else:
                reps = int(math.ceil(need / len(loop_seg))) + 1
                buf = np.concatenate([pre, np.tile(loop_seg, reps)])
        if not do_loop:
            buf = data[start:end]
        if len(buf) > need:
            buf = buf[:need]
        elif len(buf) < need:
            buf = np.pad(buf, (0, need - len(buf)))

        # resample: output length = len(buf) * (sr/ src_rate) / ratio
        from fractions import Fraction
        frac = Fraction(sr, src_rate) / Fraction(ratio).limit_denominator(10000)
        up = frac.numerator
        down = frac.denominator
        # keep resample_poly arguments manageable
        if up > 10000 or down > 10000:
            up = int(round(frac * 1000))
            down = 1000
        y = resample_poly(buf.astype(np.float32), up, down).astype(np.float32)
        if len(y) > len(out):
            y = y[:len(out)]
        elif len(y) < len(out):
            y = np.pad(y, (0, len(out) - len(y)))

        # envelope
        env = self._envelope(g, duration, sr)
        atten = g.get(GEN_INITIAL_ATTENUATION, 0)
        if atten & 0x8000:
            atten -= 65536
        gain = 10.0 ** (-atten / 200.0)
        pan = g.get(GEN_PAN, 0)
        if pan & 0x8000:
            pan -= 65536
        # simple equal-power pan (mono output here; kept for later stereo)
        vel_gain = (velocity / 127.0) ** 1.5
        y = y * env * gain * vel_gain
        out[:len(y)] += y[:len(out)]

    @staticmethod
    def _envelope(g: dict[int, int], duration: float, sr: int) -> np.ndarray:
        def tc(v: int, default: float) -> float:
            if v == 0:
                return default
            # 16-bit signed timecents
            if v & 0x8000:
                v -= 65536
            return 2.0 ** (v / 1200.0)

        attack = max(0.001, tc(g.get(GEN_ATTACK_VOL_ENV, 0), 0.001))
        hold = max(0.0, tc(g.get(GEN_HOLD_VOL_ENV, 0), 0.001))
        decay = max(0.0, tc(g.get(GEN_DECAY_VOL_ENV, 0), 0.001))
        sustain_cb = g.get(GEN_SUSTAIN_VOL_ENV, 0)
        if sustain_cb & 0x8000:
            sustain_cb -= 65536
        sustain = max(0.0, min(1.0, 10.0 ** (-sustain_cb / 200.0)))
        release = max(0.001, tc(g.get(GEN_RELEASE_VOL_ENV, 0), 0.001))
        n = int(duration * sr) + 1
        t = np.arange(n, dtype=np.float32) / sr
        env = np.zeros(n, dtype=np.float32)
        on_len = max(0.0, duration - release)
        # attack
        a_end = attack
        h_end = a_end + hold
        d_end = h_end + decay
        # build piecewise
        for i in range(n):
            ti = t[i]
            if ti < a_end:
                v = ti / attack if attack > 0 else 1.0
            elif ti < h_end:
                v = 1.0
            elif ti < d_end:
                r = (ti - h_end) / decay if decay > 0 else 1.0
                v = 1.0 + (sustain - 1.0) * r
            elif ti < on_len:
                v = sustain
            else:
                if release > 0:
                    r = (ti - on_len) / release
                    v = sustain * max(0.0, 1.0 - r)
                else:
                    v = 0.0
            env[i] = v
        return env

    def preview(self, preset_index: int, note: int = 60, velocity: int = 100,
                duration: float = 2.0) -> np.ndarray:
        return self.render_note(preset_index, note, velocity, duration)
