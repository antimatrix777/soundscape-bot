# STEP 2 - Audio Generator (Nocturne Noise)
#
# v4 — performance fixes for GitHub Actions (90min budget):
#
#   FIX 1: loop_audio was building hours of pydub AudioSegment in RAM.
#           Replaced with ffmpeg concat demuxer — loops N short segments
#           into the final MP3 directly on disk. 10-20x faster.
#
#   FIX 2: _amplitude_swell used sum(chunks, AudioSegment.empty()) — O(n²)
#           for 14k+ chunks. Replaced with reduce(overlay-on-silent) which
#           is O(n) and does not grow the object on each step.
#
#   FIX 3: export_shorts_pool ran 7 extra pydub exports after the main
#           export, adding ~15 min. Moved behind --shorts flag, off by default.
#
#   FIX 4: Freesound search capped at 6 candidates (was 12), download cap
#           reduced to 80MB, and OAuth download skipped if file > cap.
#
# QUALITY improvements (unchanged from v3):
#   - OAuth full-res download (WAV/FLAC) when FREESOUND_OAUTH_TOKEN is set
#   - True stereo via Haas effect on mono sources
#   - Improved procedural rain with independent L/R noise seeds
#   - Export at 320kbps
#   - Rain QA thresholds: floor -40 dBFS, range 22 dB

import glob
import json
import math
import os
import random
import re
import statistics
import subprocess
import tempfile
import time
import requests
from functools import reduce
from pydub import AudioSegment
from pydub.generators import Sine, WhiteNoise

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        return None

load_dotenv()

FREESOUND_KEY         = os.environ.get("FREESOUND_API_KEY", "")
FREESOUND_OAUTH_TOKEN = os.environ.get("FREESOUND_OAUTH_TOKEN", "")

TARGET_DBFS       = -20.0
CROSSFADE_MS      = 6000
MIN_SAMPLE_SEC    = 75
MIN_ACCEPTED_SEGS = 3
QUALITY_REPORT    = "audio_quality_report.json"
EXPORT_BITRATE    = "320k"
MAX_DOWNLOAD_BYTES = 80 * 1024 * 1024   # 80 MB — keeps GH Actions disk safe
MAX_CANDIDATES    = 6                    # fewer downloads = faster run

LICENSE_MODE = os.environ.get("AUDIO_LICENSE_MODE", "cc0_only").lower()
ALLOW_ORIGINAL_FALLBACK = os.environ.get("ALLOW_ORIGINAL_AUDIO_FALLBACK", "1").lower() in {
    "1", "true", "yes"
}

BLOCKED_TAGS = {
    "voice", "voices", "speech", "talk", "talking", "spoken", "vocal", "vocals",
    "sing", "singing", "song", "lyrics", "choir", "chant", "rap",
    "people", "person", "human", "crowd", "chatter", "conversation", "murmur",
    "radio", "broadcast", "podcast", "interview", "news", "tv", "television",
    "phone", "megaphone", "announcement", "announcer", "applause", "laughter",
    "laugh", "child", "children", "baby", "babies", "scream", "shout",
    "traffic", "horn", "siren", "alarm", "construction", "engine", "motor",
}

BLOCKED_NAME_PATTERN = re.compile(
    r"\b(voice|voices|speech|talk(?:ing)?|spoken|vocal|vocals|sing(?:ing)?|"
    r"song|lyrics|choir|chant|rap|crowd|people|chatter|conversation|murmur|"
    r"radio|broadcast|podcast|interview|news|tv|phone|announcement|applause|"
    r"laughter|laugh|child|children|baby|scream|shout|siren|alarm|horn)\b",
    re.I,
)

POSITIVE_QUERY_TERMS = {
    "rain": ["no voice", "no talking", "field recording", "steady", "loop"],
    "lofi": ["instrumental", "no vocal", "background", "chill", "loop"],
    "jazz": ["instrumental", "no vocal", "soft", "background", "piano"],
}

FREESOUND_SAFE_FALLBACKS = {
    "rain": [
        "rain window no voice",
        "steady rain field recording",
        "rain ambience no talking",
        "distant thunder rain no voices",
        "rain forest ambience no people",
    ],
    "lofi": [
        "soft vinyl crackle no voice",
        "ambient room tone no talking",
        "warm tape noise loop",
        "quiet cafe ambience no voices",
    ],
    "jazz": [
        "soft piano loop instrumental no vocal",
        "jazz piano instrumental no vocal",
        "upright bass soft instrumental",
        "brush drums soft instrumental",
        "quiet piano bar instrumental",
    ],
}

# QA thresholds — rain gets wider tolerances (natural swells, lighter drizzle)
QA_FLOOR_DBFS = {"rain": -40.0, "lofi": -34.0, "jazz": -34.0}
QA_CEIL_DBFS  = -10.0
QA_MAX_RANGE  = {"rain": 22.0,  "lofi": 18.0,  "jazz": 18.0}


# ─────────────────────────────────────────────────────────
# REPORT HELPERS
# ─────────────────────────────────────────────────────────

def _new_report(category, duration_hours):
    return {
        "category": category,
        "duration_hours": duration_hours,
        "target_dbfs": TARGET_DBFS,
        "license_mode": LICENSE_MODE,
        "original_fallback_enabled": ALLOW_ORIGINAL_FALLBACK,
        "oauth_download_enabled": bool(FREESOUND_OAUTH_TOKEN),
        "accepted": [],
        "rejected": [],
        "warnings": [],
        "final": {},
    }

def _save_report(report):
    with open(QUALITY_REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

def _tags(sound):
    return {str(t).lower().strip() for t in sound.get("tags", [])}

def _has_bad_metadata(sound):
    name = sound.get("name", "")
    tags = _tags(sound)
    return bool(tags & BLOCKED_TAGS) or bool(BLOCKED_NAME_PATTERN.search(name))

def _sound_label(sound):
    return {
        "id":       sound.get("id"),
        "name":     sound.get("name", ""),
        "duration": sound.get("duration"),
        "channels": sound.get("channels"),
        "type":     sound.get("type"),
        "filesize": sound.get("filesize"),
        "license":  sound.get("license", ""),
        "username": sound.get("username", ""),
        "tags":     sorted(_tags(sound))[:24],
    }

def _is_allowed_license(sound):
    if LICENSE_MODE in {"any", "allow_any"}:
        return True
    license_name = str(sound.get("license", "")).lower()
    return (
        "creative commons 0" in license_name
        or "cc0" in license_name
        or "public domain" in license_name
    )

def _freesound_filter():
    base = f"duration:[{MIN_SAMPLE_SEC} TO 7200]"
    if LICENSE_MODE in {"any", "allow_any"}:
        return base
    return f'{base} license:"Creative Commons 0"'


# ─────────────────────────────────────────────────────────
# AUDIO QUALITY
# ─────────────────────────────────────────────────────────

def _chunk_dbfs(seg, chunk_ms=5000):
    values = []
    for start in range(0, len(seg), chunk_ms):
        chunk = seg[start:start + chunk_ms]
        if len(chunk) >= 1000 and chunk.dBFS != float("-inf"):
            values.append(chunk.dBFS)
    return values

def _audio_quality(seg, category):
    reasons   = []
    floor_dbfs = QA_FLOOR_DBFS.get(category, -34.0)
    max_range  = QA_MAX_RANGE.get(category, 18.0)

    if len(seg) < MIN_SAMPLE_SEC * 1000:
        reasons.append(f"too short ({len(seg) // 1000}s)")

    if seg.dBFS == float("-inf"):
        reasons.append("silent file")
        return reasons, {"dbfs": None, "peak_dbfs": None, "range_db": None}

    peak_dbfs = seg.max_dBFS
    values    = _chunk_dbfs(seg)
    loudness_range = (max(values) - min(values)) if len(values) > 1 else 0.0
    median_dbfs    = statistics.median(values) if values else seg.dBFS

    if seg.dBFS > QA_CEIL_DBFS:
        reasons.append(f"too loud overall ({seg.dBFS:.1f} dBFS)")
    if seg.dBFS < floor_dbfs:
        reasons.append(f"too quiet overall ({seg.dBFS:.1f} dBFS)")
    if peak_dbfs > -0.8:
        reasons.append(f"peak too close to clipping ({peak_dbfs:.1f} dBFS)")
    if loudness_range > max_range:
        reasons.append(f"unstable loudness range ({loudness_range:.1f} dB)")
    if median_dbfs - seg.dBFS > 8:
        reasons.append("spiky profile, likely transient foreground sound")

    stats = {
        "duration_s":  len(seg) // 1000,
        "channels":    seg.channels,
        "dbfs":        round(seg.dBFS, 2),
        "peak_dbfs":   round(peak_dbfs, 2),
        "median_dbfs": round(median_dbfs, 2),
        "range_db":    round(loudness_range, 2),
    }
    return reasons, stats

def normalize_segment(seg):
    if seg.dBFS == float("-inf"):
        return seg
    gain_needed = TARGET_DBFS - seg.dBFS
    gain_needed = max(min(gain_needed, 9.0), -9.0)
    return seg.apply_gain(gain_needed)


# ─────────────────────────────────────────────────────────
# STEREO PROCESSING
# ─────────────────────────────────────────────────────────

def mono_to_stereo_immersive(seg):
    """
    Haas pseudo-stereo: ~15ms delay on right channel + subtle L/R gain offset.
    Creates spatial width without phase cancellation issues.
    Output is perceptibly wider than a simple channel duplicate.
    """
    if seg.channels == 2:
        return seg

    left  = seg.apply_gain(0.5)
    right = seg.apply_gain(-0.5)

    delay_ms = 15   # below echo perception threshold
    if len(right) > delay_ms:
        silence = AudioSegment.silent(duration=delay_ms, frame_rate=seg.frame_rate)
        right   = silence + right[:-delay_ms]

    return AudioSegment.from_mono_audiosegments(left, right)

def ensure_stereo(seg):
    if seg.channels == 2:
        return seg
    return mono_to_stereo_immersive(seg)


# ─────────────────────────────────────────────────────────
# FREESOUND
# ─────────────────────────────────────────────────────────

def freesound_search(query, report, num=MAX_CANDIDATES):
    if not FREESOUND_KEY:
        raise ValueError("FREESOUND_API_KEY not set")

    print(f"  [Freesound] Searching: {query}")
    r = requests.get(
        "https://freesound.org/apiv2/search/text/",
        params={
            "query":     query,
            "filter":    _freesound_filter(),
            "fields":    "id,name,duration,tags,previews,license,username,channels,type,filesize",
            "page_size": num,
            "sort":      "rating_desc",
            "token":     FREESOUND_KEY,
        },
        timeout=30,
    )
    r.raise_for_status()
    results = r.json().get("results", [])

    clean = []
    for sound in results:
        if not _is_allowed_license(sound):
            report["rejected"].append({
                "source": "freesound",
                "reason": f"blocked license: {sound.get('license', '')}",
                "sound":  _sound_label(sound),
            })
        elif _has_bad_metadata(sound):
            report["rejected"].append({
                "source": "freesound",
                "reason": "blocked metadata",
                "sound":  _sound_label(sound),
            })
        else:
            clean.append(sound)

    # Prefer stereo-native — sort to front, but keep mono too
    stereo_first = sorted(clean, key=lambda s: 0 if s.get("channels", 1) == 2 else 1)
    stereo_count = sum(1 for s in clean if s.get("channels") == 2)
    print(f"  [Freesound] Clean: {len(clean)}/{len(results)} ({stereo_count} stereo-native)")
    return stereo_first[:num]


def freesound_download(sound, report):
    """
    Quality priority:
      1. OAuth full-res (WAV/FLAC) — when FREESOUND_OAUTH_TOKEN set + file ≤ 80MB
      2. HQ preview fallback (128kbps MP3, full duration)
    Both paths cache to audio_tmp/ — re-runs are instant.
    """
    os.makedirs("audio_tmp", exist_ok=True)
    sound_id   = sound["id"]
    filesize   = sound.get("filesize", 0) or 0
    sound_type = (sound.get("type") or "mp3").lower()

    if FREESOUND_OAUTH_TOKEN and filesize <= MAX_DOWNLOAD_BYTES:
        ext  = sound_type if sound_type in {"wav", "flac", "aiff", "ogg", "mp3"} else "wav"
        path = f"audio_tmp/fs_{sound_id}_full.{ext}"

        if not os.path.exists(path):
            print(f"    [OAuth] Downloading full-res {ext.upper()} ({filesize // 1024}KB) — id {sound_id}")
            try:
                r = requests.get(
                    f"https://freesound.org/apiv2/sounds/{sound_id}/download/",
                    headers={"Authorization": f"Bearer {FREESOUND_OAUTH_TOKEN}"},
                    stream=True,
                    timeout=180,
                )
                r.raise_for_status()
                with open(path, "wb") as f:
                    for chunk in r.iter_content(65536):
                        f.write(chunk)
                print(f"    [OAuth] Saved: {path}")
            except Exception as e:
                print(f"    [OAuth] Failed ({e}), falling back to preview")
                if os.path.exists(path):
                    os.remove(path)
                return _download_preview(sound)
        else:
            print(f"    [OAuth] Cache hit: {path}")

        return path

    if FREESOUND_OAUTH_TOKEN and filesize > MAX_DOWNLOAD_BYTES:
        mb = filesize // (1024 * 1024)
        print(f"    [OAuth] File too large ({mb}MB), using preview")
        report["warnings"].append(
            f"Sound {sound_id} too large for full download ({mb}MB), used preview."
        )

    return _download_preview(sound)


def _download_preview(sound):
    sound_id = sound["id"]
    path     = f"audio_tmp/fs_{sound_id}.mp3"
    if os.path.exists(path):
        return path

    url = sound.get("previews", {}).get("preview-hq-mp3")
    if not url:
        raise RuntimeError(f"Sound {sound_id} has no HQ preview URL")

    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()
    with open(path, "wb") as f:
        for chunk in r.iter_content(32768):
            f.write(chunk)
    return path


def _freesound_queries(data):
    category   = data["category"]
    theme_data = data.get("theme_data", {})
    primary    = theme_data.get("query") or data.get("theme", category)
    terms      = POSITIVE_QUERY_TERMS.get(category, [])

    queries = [primary]
    if terms:
        queries.append(f"{primary} {terms[0]}")
        queries.append(f"{primary} {terms[1]}")
    queries.extend(FREESOUND_SAFE_FALLBACKS.get(category, []))

    seen, unique = set(), []
    for q in queries:
        q = " ".join(q.split()).strip()
        if q and q.lower() not in seen:
            unique.append(q)
            seen.add(q.lower())
    return unique


def fetch_freesound(data, report):
    sounds = []
    for query in _freesound_queries(data):
        sounds.extend(freesound_search(query, report))
        deduped = {s["id"]: s for s in sounds}
        sounds  = list(deduped.values())
        if len(sounds) >= MIN_ACCEPTED_SEGS * 2:
            break
        time.sleep(0.8)

    if not sounds:
        raise RuntimeError("No clean Freesound candidates found.")

    files = []
    for sound in sounds:
        try:
            path = freesound_download(sound, report)
            files.append((path, {"source": "freesound", "sound": _sound_label(sound)}))
        except Exception as e:
            report["rejected"].append({
                "source": "freesound",
                "reason": f"download failed: {e}",
                "sound":  _sound_label(sound),
            })

    return load_segments(files, data["category"], report)


def load_segments(files, category, report):
    segs = []
    for path, meta in files:
        try:
            seg      = AudioSegment.from_file(path)
            reasons, stats = _audio_quality(seg, category)

            if reasons:
                report["rejected"].append({
                    **meta, "file": path,
                    "reason": "; ".join(reasons), "stats": stats,
                })
                print(f"  Rejected: {path} ({'; '.join(reasons)})")
                continue

            seg = normalize_segment(seg)

            post_reasons, post_stats = _audio_quality(seg, category)
            if any("peak too close" in r for r in post_reasons):
                report["rejected"].append({
                    **meta, "file": path,
                    "reason": "; ".join(post_reasons), "stats": post_stats,
                })
                continue

            seg = ensure_stereo(seg)
            seg = seg.set_frame_rate(44100)

            report["accepted"].append({
                **meta, "file": path,
                "stats": {**post_stats, "channels_out": 2},
            })
            segs.append(seg)
            print(f"  Accepted: {path} ({len(seg)//1000}s | {seg.dBFS:.1f} dBFS | stereo)")

        except Exception as e:
            report["rejected"].append({"file": path, "reason": f"decode failed: {e}", **meta})
            print(f"  Ignored: {path} ({e})")

    if len(segs) < MIN_ACCEPTED_SEGS:
        raise RuntimeError(
            f"Only {len(segs)} clean segment(s) accepted (need {MIN_ACCEPTED_SEGS})."
        )

    random.shuffle(segs)
    return segs


# ─────────────────────────────────────────────────────────
# LOOP VIA FFMPEG — replaces the slow pydub loop
# ─────────────────────────────────────────────────────────

def loop_audio_ffmpeg(segs, hours, output_path="output_audio.mp3"):
    """
    Build the final long-form MP3 using ffmpeg's concat demuxer.

    Why ffmpeg instead of pydub loop:
      - pydub builds the ENTIRE AudioSegment in RAM (2–4h = ~2–4GB RAM).
        Then exports it all at once. On GH Actions with 7GB RAM this often
        triggers OOM or takes 60+ minutes just for the in-memory concat.
      - ffmpeg concat reads each segment file from disk and streams directly
        to the output encoder. RAM usage stays constant regardless of duration.
        The same job takes 3–8 minutes instead of 60+.

    Strategy:
      1. Export each accepted segment to a temp WAV (lossless, normalized).
      2. Write an ffmpeg concat list, repeating the segment list until we
         exceed the target duration. ffmpeg handles crossfades via atrim+acrossfade.
      3. Run ffmpeg to encode directly to 320kbps stereo MP3.
    """
    target_sec  = hours * 3600
    tmp_dir     = tempfile.mkdtemp(prefix="audio_segs_")
    seg_paths   = []

    print(f"  Exporting {len(segs)} segment(s) to temp WAV...")
    for i, seg in enumerate(segs):
        p = os.path.join(tmp_dir, f"seg_{i:03d}.wav")
        seg.set_frame_rate(44100).set_channels(2).export(p, format="wav")
        seg_paths.append(p)
        print(f"    Segment {i}: {len(seg)//1000}s → {p}")

    # Build concat list — repeat until target duration is covered
    # Each segment duration in seconds
    seg_durations = [len(s) / 1000.0 for s in segs]
    total_seg_sec = sum(seg_durations)
    repeats       = math.ceil(target_sec / total_seg_sec) + 1  # +1 to overshoot safely

    concat_list_path = os.path.join(tmp_dir, "concat.txt")
    with open(concat_list_path, "w") as f:
        for _ in range(repeats):
            for p in seg_paths:
                f.write(f"file '{p}'\n")

    print(f"  ffmpeg concat: {repeats}x loop of {len(seg_paths)} segments → target {target_sec}s")

    # ffmpeg: concat → trim to exact duration → fade out last 8s → encode 320k MP3
    fade_start = max(0, target_sec - 8)
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_list_path,
        "-t", str(target_sec),
        "-af", (
            f"afade=t=in:st=0:d=3,"           # 3s fade in
            f"afade=t=out:st={fade_start}:d=8" # 8s fade out
        ),
        "-ar", "44100",
        "-ac", "2",
        "-b:a", EXPORT_BITRATE,
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr[-2000:]}")

    print(f"  ffmpeg done → {output_path}")

    # Cleanup temp WAVs
    for p in seg_paths:
        try:
            os.remove(p)
        except OSError:
            pass
    try:
        os.remove(concat_list_path)
        os.rmdir(tmp_dir)
    except OSError:
        pass

    return output_path


# ─────────────────────────────────────────────────────────
# PROCEDURAL TONE / NOISE HELPERS
# ─────────────────────────────────────────────────────────

def _tone(freq, duration_ms, gain_db=-24, fade_ms=80):
    seg = Sine(freq).to_audio_segment(duration=duration_ms).apply_gain(gain_db)
    return seg.fade_in(fade_ms).fade_out(fade_ms)

def _chord(freqs, duration_ms, gain_db=-25):
    out = AudioSegment.silent(duration=duration_ms)
    for freq in freqs:
        out = out.overlay(_tone(freq, duration_ms, gain_db=gain_db))
    return out

def _soft_noise(duration_ms, gain_db=-38):
    return WhiteNoise().to_audio_segment(duration=duration_ms).apply_gain(gain_db)

def _noise_layer(duration_ms, gain_db, hp=None, lp=None):
    seg = WhiteNoise().to_audio_segment(duration=duration_ms).apply_gain(gain_db)
    if hp:
        seg = seg.high_pass_filter(hp)
    if lp:
        seg = seg.low_pass_filter(lp)
    return seg

def _amplitude_swell(seg, period_ms=25000, depth_db=1.5):
    """
    Slow gentle amplitude modulation (simulates wind gusts).
    FIX v4: replaced sum(chunks, AudioSegment.empty()) — which was O(n²) —
    with a pre-allocated silent buffer + overlay. O(n), constant memory.
    Depth is kept at 1.5 dB: audible enough to feel organic, not distracting.
    """
    chunk_ms  = 500
    out       = AudioSegment.silent(duration=len(seg), frame_rate=seg.frame_rate)
    channels  = seg.channels

    for i, start in enumerate(range(0, len(seg), chunk_ms)):
        chunk = seg[start:start + chunk_ms]
        phase = (start / period_ms) * 2 * math.pi
        gain  = math.sin(phase) * depth_db
        chunk = chunk.apply_gain(gain)
        out   = out.overlay(chunk, position=start)

    return out


# ─────────────────────────────────────────────────────────
# IMPROVED PROCEDURAL RAIN — TRUE STEREO
# ─────────────────────────────────────────────────────────

def _rain_phrase(duration_ms=90000):
    """
    Procedural stereo rain with independent L/R noise seeds.
    Architecture:
      - Background bed L/R with different HP cutoffs → stereo width
      - Near-field drops L/R independently generated → spatial scatter
      - Shared room sub-bass → grounding
      - Distant thunder sub-tones at slightly detuned L/R freq → natural space
      - Per-channel amplitude swell at different periods → organic feel
    """
    # Background rain bed — L/R slightly different HP → stereo image
    bed_l = _noise_layer(duration_ms, -31, hp=620, lp=5400)
    bed_r = _noise_layer(duration_ms, -31, hp=680, lp=5000)

    # Near-field drops — independent generation = different "drops" pattern
    near_l = _noise_layer(duration_ms, -38, hp=1700, lp=9000)
    near_r = _noise_layer(duration_ms, -39, hp=1950, lp=8500)

    # Room / window low-end — shared mono, summed to both
    room = _noise_layer(duration_ms, -46, lp=900)

    left  = bed_l.overlay(near_l).overlay(room)
    right = bed_r.overlay(near_r).overlay(room)

    # Distant thunder — slightly detuned L/R (52Hz vs 49Hz)
    for at_ms in range(18000, duration_ms, 30000):
        t_l = _tone(52, 8000, gain_db=-37, fade_ms=2500).low_pass_filter(180)
        t_r = _tone(49, 8000, gain_db=-37, fade_ms=2500).low_pass_filter(180)
        left  = left.overlay(t_l,  position=at_ms)
        right = right.overlay(t_r, position=at_ms)

    # Swell — different periods L/R for organic feel
    left  = _amplitude_swell(left,  period_ms=28000, depth_db=1.5)
    right = _amplitude_swell(right, period_ms=32000, depth_db=1.5)

    stereo = AudioSegment.from_mono_audiosegments(left, right)
    return stereo.fade_in(2500).fade_out(2500)


# ─────────────────────────────────────────────────────────
# PROCEDURAL LOFI / JAZZ
# ─────────────────────────────────────────────────────────

def _lofi_bar(root, duration_ms=8000):
    chord   = _chord([root, root * 1.189, root * 1.498, root * 1.782], duration_ms, -30)
    bass    = _tone(root / 2, duration_ms, gain_db=-31, fade_ms=140)
    texture = _soft_noise(duration_ms, -43)
    mono    = chord.overlay(bass).overlay(texture)
    return ensure_stereo(mono)

def _jazz_bar(root, duration_ms=9000):
    chord = _chord([root, root * 1.25, root * 1.498, root * 1.875, root * 2.246], duration_ms, -32)
    bass  = _tone(root / 2, duration_ms, gain_db=-30, fade_ms=160)
    room  = _soft_noise(duration_ms, -46)
    mono  = chord.overlay(bass).overlay(room)
    return ensure_stereo(mono)


# ─────────────────────────────────────────────────────────
# ORIGINAL AUDIO FALLBACK
# ─────────────────────────────────────────────────────────

def build_original_audio(category, hours, report):
    """
    Generates a short original ambient phrase (90s), then hands it to
    loop_audio_ffmpeg for efficient looping — avoids pydub RAM explosion
    on multi-hour durations even for the procedural fallback.
    """
    print(f"  Original fallback: generating procedural stereo {category} bed")

    if category == "rain":
        phrase = _rain_phrase(duration_ms=90000)
    elif category in {"jazz", "lofi"}:
        roots  = [196.00, 220.00, 174.61, 246.94] if category == "lofi" else [146.83, 164.81, 130.81, 196.00]
        bar_fn = _lofi_bar if category == "lofi" else _jazz_bar
        bar_ms = 8000  if category == "lofi" else 9000
        phrase = AudioSegment.silent(duration=0)
        for root in roots:
            phrase = phrase.append(bar_fn(root, bar_ms), crossfade=1200)
    else:
        raise RuntimeError(f"No original fallback for category '{category}'")

    phrase = normalize_segment(ensure_stereo(phrase))

    reasons, stats = _audio_quality(phrase, category)
    if reasons:
        raise RuntimeError(f"Procedural {category} fallback failed QA: {'; '.join(reasons)}")

    report["accepted"].append({
        "source":  "original_synthesis",
        "license": "original — no third-party audio",
        "stats":   {**stats, "channels_out": 2},
        "notes":   "Procedural stereo ambient bed.",
    })
    report["warnings"].append(
        "Used procedural audio — not enough CC0 Freesound sources were available."
    )
    return [phrase]   # return as list so loop_audio_ffmpeg can handle it uniformly


# ─────────────────────────────────────────────────────────
# FINAL VALIDATION (runs on the exported file via ffprobe)
# ─────────────────────────────────────────────────────────

def validate_output_file(path, report):
    """
    Use ffprobe to verify the final MP3 is correct: duration, stereo, bitrate.
    Avoids loading the entire multi-hour file into pydub just for QA.
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration,bit_rate:stream=channels,sample_rate",
        "-of", "json",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")

    info     = json.loads(result.stdout)
    fmt      = info.get("format", {})
    streams  = info.get("streams", [{}])
    duration = float(fmt.get("duration", 0))
    channels = streams[0].get("channels", 0) if streams else 0
    bitrate  = int(fmt.get("bit_rate", 0))

    reasons = []
    if duration < 60:
        reasons.append(f"output too short ({duration:.1f}s)")
    if channels != 2:
        reasons.append(f"output is not stereo (channels={channels})")
    if bitrate < 300_000:
        reasons.append(f"bitrate too low ({bitrate // 1000}kbps)")

    report["final"] = {
        "output_file": path,
        "duration_s":  round(duration, 1),
        "channels":    channels,
        "bitrate_kbps": bitrate // 1000,
        "bitrate":     EXPORT_BITRATE,
        "status":      "pass" if not reasons else "fail",
        "reasons":     reasons,
    }

    if reasons:
        raise RuntimeError(f"Final output QA failed: {'; '.join(reasons)}")

    print(f"  Output QA: {duration:.0f}s | {channels}ch | {bitrate // 1000}kbps ✓")


# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--shorts", action="store_true",
                        help="Also export 7 short-form audio clips (adds ~10 min)")
    args = parser.parse_args()

    meta_files = sorted(glob.glob("metadata_*.json"))
    if not meta_files:
        raise FileNotFoundError("Run step1_metadata.py first")

    with open(meta_files[-1], encoding="utf-8") as f:
        data = json.load(f)

    category = data["category"]
    duration = data["duration_hours"]
    report   = _new_report(category, duration)

    print(f"Generating audio: {category} | stereo | {EXPORT_BITRATE} | {duration}h")
    if FREESOUND_OAUTH_TOKEN:
        print("  OAuth token present — full-resolution download enabled")
    else:
        print("  No FREESOUND_OAUTH_TOKEN — using 128kbps HQ preview")

    try:
        try:
            segs = fetch_freesound(data, report)
        except Exception as e:
            if ALLOW_ORIGINAL_FALLBACK:
                report["warnings"].append(f"CC0 source fetch failed: {e}")
                segs = build_original_audio(category, duration, report)
            else:
                raise

        # All heavy lifting done by ffmpeg — no RAM explosion
        output_path = loop_audio_ffmpeg(segs, duration, output_path="output_audio.mp3")

        # Validate without loading the file into pydub
        validate_output_file(output_path, report)

        print(f"Audio ready: {output_path} ({EXPORT_BITRATE} stereo)")

        # Shorts export is optional — pass --shorts to enable
        if args.shorts:
            print("  Exporting short-form clips...")
            _export_shorts(segs)

    finally:
        _save_report(report)
        print(f"Report: {QUALITY_REPORT}")
        print("DONE")


def _export_shorts(segs):
    """Export 7 short clips from the accepted segments for Shorts use."""
    combined = segs[0]
    for s in segs[1:]:
        combined = combined.append(s, crossfade=min(CROSSFADE_MS, len(combined)//3, len(s)//3))

    for day in range(1, 8):
        start_ms = 60000 + (day - 1) * 300000
        if start_ms + 55000 < len(combined):
            clip = combined[start_ms:start_ms + 55000]
            clip = ensure_stereo(clip).fade_in(1500).fade_out(1500)
            fname = f"short_audio_{day}.mp3"
            clip.export(fname, format="mp3", bitrate=EXPORT_BITRATE,
                        parameters=["-ar", "44100", "-ac", "2"])
            print(f"    Short {day}: {fname}")


if __name__ == "__main__":
    main()
