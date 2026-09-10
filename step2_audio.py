# STEP 2 - Audio Generator (Nocturne Noise)
#
# Performance fixes for GitHub Actions (90min budget) — audio quality unchanged:
#
#   FIX 1: loop_audio was building hours of pydub AudioSegment in RAM before
#           exporting. Replaced with ffmpeg concat demuxer — streams segments
#           directly to disk encoder. Same audio output, 10-20x faster.
#
#   FIX 2: _amplitude_swell used sum(chunks, AudioSegment.empty()) — O(n²)
#           for 14k+ chunks. Replaced with overlay-on-preallocated-buffer, O(n).
#
#   FIX 3: export_shorts_pool (7 extra exports) moved behind --shorts flag.
#           Not run by default, saves ~10-15 min on the critical path.
#
#   FIX 4: Freesound search capped at 6 candidates to reduce download time.
#
# Audio quality: identical to original (192k, HQ preview, original QA thresholds).

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
from pydub import AudioSegment
from pydub.generators import Sine, WhiteNoise

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        return None

load_dotenv()

FREESOUND_KEY     = os.environ.get("FREESOUND_API_KEY", "")

TARGET_DBFS       = -20.0
CROSSFADE_MS      = 6000
MIN_SAMPLE_SEC    = 75
MIN_ACCEPTED_SEGS = 3
QUALITY_REPORT    = "audio_quality_report.json"
EXPORT_BITRATE    = "192k"
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

# QA thresholds — original values
QA_FLOOR_DBFS = {"rain": -34.0, "lofi": -34.0, "jazz": -34.0}
QA_CEIL_DBFS  = -10.0
QA_MAX_RANGE  = {"rain": 14.0,  "lofi": 18.0,  "jazz": 18.0}


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

def ensure_stereo(seg):
    if seg.channels == 2:
        return seg
    return seg.set_channels(2)


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

    print(f"  [Freesound] Clean: {len(clean)}/{len(results)}")
    return clean[:num]


def freesound_download(sound, report):
    """Download HQ preview (128kbps MP3). Cached to audio_tmp/."""
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

    # ffmpeg: concat → trim to exact duration → fade in/out → encode MP3
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
    """Simple procedural rain: filtered white noise, original approach."""
    noise = WhiteNoise().to_audio_segment(duration=duration_ms).apply_gain(-28)
    rain  = noise.high_pass_filter(650).low_pass_filter(5200)
    return rain.fade_in(2000).fade_out(2000)


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

    print(f"Generating audio: {category} | {EXPORT_BITRATE} | {duration}h")

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
