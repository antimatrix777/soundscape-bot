# STEP 2 - Audio Generator (Nocturne Noise)
#
# Editorial rule: never publish questionable or copyright-risk audio.
# The pipeline fails closed when it cannot find clean sources, instead of
# accepting unfiltered previews that may contain voices, radio, or chatter.
# Default license mode is CC0/public domain only.
#
# IMPROVEMENTS v3:
# - Freesound OAuth download: fetches original WAV/FLAC instead of 128kbps preview
#   when FREESOUND_OAUTH_TOKEN env var is present. Falls back to HQ preview if not.
# - True stereo: prefers stereo-native sounds from Freesound; converts mono to
#   immersive pseudo-stereo via Haas effect + per-channel gain variation.
# - Improved procedural rain fallback: true stereo with independent noise seeds
#   per channel, multi-layer texture, and subtle amplitude modulation.
# - Export bitrate raised to 320kbps.
# - QA thresholds adjusted for rain: floor -40 dBFS, range 22 dB.
#
# SETUP (optional, for OAuth download quality):
#   1. Register a Freesound app at freesound.org/apiv2/apply
#   2. Get an access token via OAuth2 (see freesound.org/docs/api)
#   3. Save as secret FREESOUND_OAUTH_TOKEN in GitHub repo settings
#   Without this secret, the pipeline falls back to HQ preview (128kbps) — still works.

import glob
import json
import os
import random
import re
import statistics
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

FREESOUND_KEY          = os.environ.get("FREESOUND_API_KEY", "")
FREESOUND_OAUTH_TOKEN  = os.environ.get("FREESOUND_OAUTH_TOKEN", "")  # optional, enables full-res download

TARGET_DBFS            = -20.0
CROSSFADE_MS           = 6000
MIN_SAMPLE_SEC         = 75
MIN_ACCEPTED_SEGMENTS  = 3
QUALITY_REPORT         = "audio_quality_report.json"
EXPORT_BITRATE         = "320k"
MAX_DOWNLOAD_BYTES     = 120 * 1024 * 1024  # 120 MB cap — keeps GH Actions disk safe

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

# ─────────────────────────────────────────────────────────
# QA THRESHOLDS — per category
# Rain has naturally wider loudness range and can be quieter than music.
# ─────────────────────────────────────────────────────────
QA_FLOOR_DBFS = {
    "rain": -40.0,   # light drizzle legitimately lives around -36 to -40
    "lofi": -34.0,
    "jazz": -34.0,
}
QA_CEIL_DBFS = -10.0   # same for all: too hot = clipping risk
QA_MAX_RANGE = {
    "rain": 22.0,    # storms have natural swells — 14 was too tight
    "lofi": 18.0,
    "jazz": 18.0,
}


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
        "id": sound.get("id"),
        "name": sound.get("name", ""),
        "duration": sound.get("duration"),
        "channels": sound.get("channels"),
        "type": sound.get("type"),
        "filesize": sound.get("filesize"),
        "license": sound.get("license", ""),
        "username": sound.get("username", ""),
        "tags": sorted(_tags(sound))[:24],
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
    reasons = []
    floor_dbfs  = QA_FLOOR_DBFS.get(category, -34.0)
    max_range   = QA_MAX_RANGE.get(category, 18.0)

    if len(seg) < MIN_SAMPLE_SEC * 1000:
        reasons.append(f"too short ({len(seg) // 1000}s)")

    if seg.dBFS == float("-inf"):
        reasons.append("silent file")
        return reasons, {"dbfs": None, "peak_dbfs": None, "range_db": None}

    peak_dbfs = seg.max_dBFS
    values = _chunk_dbfs(seg)
    loudness_range = (max(values) - min(values)) if len(values) > 1 else 0.0
    median_dbfs = statistics.median(values) if values else seg.dBFS

    if seg.dBFS > QA_CEIL_DBFS:
        reasons.append(f"too loud overall ({seg.dBFS:.1f} dBFS)")
    if seg.dBFS < floor_dbfs:
        reasons.append(f"too quiet overall ({seg.dBFS:.1f} dBFS)")
    if peak_dbfs > -0.8:
        reasons.append(f"peak too close to clipping ({peak_dbfs:.1f} dBFS)")
    if loudness_range > max_range:
        reasons.append(f"unstable loudness range ({loudness_range:.1f} dB)")
    if median_dbfs - seg.dBFS > 8:
        reasons.append("spiky profile, likely transient or intrusive foreground sound")

    stats = {
        "duration_s": len(seg) // 1000,
        "channels": seg.channels,
        "dbfs": round(seg.dBFS, 2),
        "peak_dbfs": round(peak_dbfs, 2),
        "median_dbfs": round(median_dbfs, 2),
        "range_db": round(loudness_range, 2),
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
    Convert a mono segment to immersive pseudo-stereo.
    Uses the Haas effect (~15ms delay on right) plus subtle per-channel
    gain variation (+0.5 / -0.5 dB) to create natural spatial width.
    Output sounds wider and more enveloping than a simple channel duplicate.
    """
    if seg.channels == 2:
        return seg

    left  = seg.apply_gain(0.5)
    right = seg.apply_gain(-0.5)

    # ~15ms Haas delay on the right channel — below threshold of echo perception
    delay_ms = 15
    if len(right) > delay_ms:
        silence = AudioSegment.silent(duration=delay_ms, frame_rate=seg.frame_rate)
        right = silence + right[:-delay_ms]

    return AudioSegment.from_mono_audiosegments(left, right)

def ensure_stereo(seg):
    """Guarantee a segment is stereo before export."""
    if seg.channels == 2:
        return seg
    return mono_to_stereo_immersive(seg)


# ─────────────────────────────────────────────────────────
# FREESOUND — SEARCH + DOWNLOAD
# ─────────────────────────────────────────────────────────

def freesound_search(query, report, num=12):
    if not FREESOUND_KEY:
        raise ValueError("FREESOUND_API_KEY not set")

    print(f"  [Freesound] Searching: {query}")
    r = requests.get(
        "https://freesound.org/apiv2/search/text/",
        params={
            "query":     query,
            "filter":    _freesound_filter(),
            # channels field: lets us know if a sound is stereo natively
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

    # Prefer stereo-native sounds — put them first, but keep mono too
    stereo_first = sorted(clean, key=lambda s: 0 if s.get("channels", 1) == 2 else 1)
    stereo_count = sum(1 for s in clean if s.get("channels") == 2)
    print(f"  [Freesound] Clean: {len(clean)}/{len(results)} ({stereo_count} stereo-native)")
    return stereo_first[:num]


def freesound_download(sound, report):
    """
    Download strategy (in order of quality):

    1. OAuth full-resolution download (WAV/FLAC original) — if FREESOUND_OAUTH_TOKEN is set
       and file is under MAX_DOWNLOAD_BYTES. This gives the highest quality source.

    2. HQ preview fallback (128kbps MP3, full duration) — used when OAuth is unavailable
       or file is too large/wrong format for direct download.

    Both paths cache to audio_tmp/ to avoid re-downloading on retry.
    """
    os.makedirs("audio_tmp", exist_ok=True)
    sound_id   = sound["id"]
    filesize   = sound.get("filesize", 0) or 0
    sound_type = (sound.get("type") or "mp3").lower()

    # ── Path 1: OAuth full-resolution download ──────────────────────────────
    if FREESOUND_OAUTH_TOKEN and filesize <= MAX_DOWNLOAD_BYTES:
        # Freesound returns the original format — most are wav, flac, aiff, mp3, ogg
        ext = sound_type if sound_type in {"wav", "flac", "aiff", "ogg", "mp3"} else "wav"
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
                # OAuth failed — fall through to preview
                print(f"    [OAuth] Failed ({e}), falling back to preview")
                if os.path.exists(path):
                    os.remove(path)
                return _download_preview(sound)
        else:
            print(f"    [OAuth] Cache hit: {path}")

        return path

    # ── Reason logged if skipping OAuth ─────────────────────────────────────
    if FREESOUND_OAUTH_TOKEN and filesize > MAX_DOWNLOAD_BYTES:
        mb = filesize // (1024 * 1024)
        print(f"    [OAuth] File too large ({mb}MB > {MAX_DOWNLOAD_BYTES // (1024*1024)}MB cap), using preview")
        if report:
            report["warnings"].append(
                f"Sound {sound_id} too large for full download ({mb}MB), used preview."
            )

    if not FREESOUND_OAUTH_TOKEN:
        print(f"    [Preview] FREESOUND_OAUTH_TOKEN not set — using 128kbps HQ preview")

    # ── Path 2: HQ preview fallback ─────────────────────────────────────────
    return _download_preview(sound)


def _download_preview(sound):
    """Download the HQ MP3 preview (128kbps, full duration)."""
    sound_id = sound["id"]
    path = f"audio_tmp/fs_{sound_id}.mp3"

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
        if len(sounds) >= MIN_ACCEPTED_SEGMENTS * 2:
            break
        time.sleep(0.8)

    if not sounds:
        raise RuntimeError("No clean Freesound candidates found. Refusing unsafe audio.")

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
            seg = AudioSegment.from_file(path)
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
                print(f"  Rejected after normalize: {path}")
                continue

            # Ensure stereo — converts mono to immersive pseudo-stereo
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

    if len(segs) < MIN_ACCEPTED_SEGMENTS:
        raise RuntimeError(
            f"Only {len(segs)} clean audio segment(s) accepted. "
            f"Need at least {MIN_ACCEPTED_SEGMENTS}. Refusing upload-quality build."
        )

    random.shuffle(segs)
    return segs


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
    """Generate a mono white noise layer with optional band-pass filtering."""
    seg = WhiteNoise().to_audio_segment(duration=duration_ms).apply_gain(gain_db)
    if hp:
        seg = seg.high_pass_filter(hp)
    if lp:
        seg = seg.low_pass_filter(lp)
    return seg

def _amplitude_swell(seg, period_ms=25000, depth_db=1.5):
    """
    Apply a very slow, gentle amplitude modulation to simulate natural breath in the sound.
    Depth is intentionally small (1.5 dB) — just enough to feel alive, not distracting.
    """
    import math
    chunks = []
    chunk_ms = 500
    for i, start in enumerate(range(0, len(seg), chunk_ms)):
        chunk = seg[start:start + chunk_ms]
        phase = (start / period_ms) * 2 * math.pi
        gain  = math.sin(phase) * depth_db
        chunks.append(chunk.apply_gain(gain))
    return sum(chunks, AudioSegment.empty()) if chunks else seg


# ─────────────────────────────────────────────────────────
# IMPROVED PROCEDURAL RAIN — TRUE STEREO
# ─────────────────────────────────────────────────────────

def _rain_phrase(duration_ms=90000):
    """
    True stereo procedural rain with independent noise seeds per channel.
    Architecture:
      - Background bed L/R: slightly different cutoff frequencies → stereo width
      - Near drops L/R: independent generation → spatial scatter sensation
      - Room sub-bass: shared mono → grounding, summed to both channels
      - Distant thunder swells: slightly detuned L/R → natural room feel
      - Slow amplitude swell: simulates gusts and natural variation
    """
    # ── Background rain bed ─────────────────────────────────────────────────
    # L and R use slightly different HP cutoffs → creates natural stereo image
    bed_l = _noise_layer(duration_ms, -31, hp=620,  lp=5400)
    bed_r = _noise_layer(duration_ms, -31, hp=680,  lp=5000)

    # ── Near-field drops layer ───────────────────────────────────────────────
    # Independent noise generation = each channel has different "drops" pattern
    near_l = _noise_layer(duration_ms, -38, hp=1700, lp=9000)
    near_r = _noise_layer(duration_ms, -39, hp=1950, lp=8500)

    # ── Room / window low-end (mono, summed to both) ─────────────────────────
    room = _noise_layer(duration_ms, -46, lp=900)

    # ── Combine per channel before adding thunder ────────────────────────────
    left  = bed_l.overlay(near_l).overlay(room)
    right = bed_r.overlay(near_r).overlay(room)

    # ── Distant thunder swells ───────────────────────────────────────────────
    # Slightly detuned frequencies L/R (52Hz vs 49Hz) → natural spatial spread
    for at_ms in range(18000, duration_ms, 30000):
        t_l = _tone(52, 8000, gain_db=-37, fade_ms=2500).low_pass_filter(180)
        t_r = _tone(49, 8000, gain_db=-37, fade_ms=2500).low_pass_filter(180)
        left  = left.overlay(t_l, position=at_ms)
        right = right.overlay(t_r, position=at_ms)

    # ── Slow amplitude swell (simulates wind gusts) ───────────────────────────
    left  = _amplitude_swell(left,  period_ms=28000, depth_db=1.5)
    right = _amplitude_swell(right, period_ms=32000, depth_db=1.5)  # different period → organic

    # ── Build stereo and fade ────────────────────────────────────────────────
    stereo = AudioSegment.from_mono_audiosegments(left, right)
    return stereo.fade_in(2500).fade_out(2500)


# ─────────────────────────────────────────────────────────
# PROCEDURAL LOFI / JAZZ (stereo-aware)
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
    Generates a fully original ambient bed when CC0 sources are unavailable.
    All output is true stereo. Avoids Content ID exposure from third-party audio.
    """
    target = hours * 3600 * 1000
    print(f"  Original fallback: generating copyright-safe stereo {category} bed")

    if category == "rain":
        phrase = _rain_phrase()
    elif category in {"jazz", "lofi"}:
        roots  = [196.00, 220.00, 174.61, 246.94] if category == "lofi" else [146.83, 164.81, 130.81, 196.00]
        bar_fn = _lofi_bar if category == "lofi" else _jazz_bar
        bar_ms = 8000  if category == "lofi" else 9000
        phrase = AudioSegment.silent(duration=0)
        for root in roots:
            phrase = phrase.append(bar_fn(root, bar_ms), crossfade=1200)
    else:
        raise RuntimeError(f"No original fallback for category '{category}'")

    phrase = normalize_segment(phrase)
    # Guarantee stereo (rain is already stereo, lofi/jazz go through ensure_stereo in bar fns)
    phrase = ensure_stereo(phrase)

    audio = phrase
    while len(audio) < target + CROSSFADE_MS:
        audio = audio.append(phrase, crossfade=CROSSFADE_MS)
    audio = audio[:target].fade_in(3000).fade_out(8000)

    reasons, stats = _audio_quality(audio[:min(len(audio), 20 * 60 * 1000)], category)
    if reasons:
        raise RuntimeError(f"Original {category} fallback failed QA: {'; '.join(reasons)}")

    report["accepted"].append({
        "source":  "original_synthesis",
        "license": "original - no third-party audio",
        "stats":   {**stats, "channels_out": 2},
        "notes":   "Procedural stereo ambient bed generated by the pipeline.",
    })
    report["warnings"].append(
        "Used original procedural audio because not enough CC0 third-party sources were available."
    )
    return audio


# ─────────────────────────────────────────────────────────
# LOOP + VALIDATE + EXPORT
# ─────────────────────────────────────────────────────────

def loop_audio(segs, hours):
    target = hours * 3600 * 1000
    out    = segs[0].fade_in(2500)
    i      = 1
    while len(out) < target + CROSSFADE_MS:
        next_seg = segs[i % len(segs)]
        fade_ms  = min(CROSSFADE_MS, len(out) // 3, len(next_seg) // 3)
        out      = out.append(next_seg, crossfade=fade_ms)
        i       += 1
    return out[:target].fade_out(8000)

def validate_final_audio(audio, report):
    reasons, stats = _audio_quality(audio[:min(len(audio), 20 * 60 * 1000)], report["category"])
    report["final"] = {
        "duration_s":   len(audio) // 1000,
        "channels":     audio.channels,
        "sample_stats": stats,
        "status":       "pass" if not reasons else "fail",
        "reasons":      reasons,
    }
    if reasons:
        raise RuntimeError(f"Final audio QA failed: {'; '.join(reasons)}")

def export_shorts_pool(audio):
    if len(audio) <= 120000:
        return
    for day in range(1, 8):
        start_ms = 60000 + (day - 1) * 300000
        if start_ms + 60000 < len(audio):
            short_seg = audio[start_ms:start_ms + 55000]
            short_seg = short_seg.fade_in(1500).fade_out(1500)
            short_seg = ensure_stereo(short_seg)
            fname = f"short_audio_{day}.mp3"
            short_seg.export(fname, format="mp3", bitrate=EXPORT_BITRATE,
                             parameters=["-ar", "44100", "-ac", "2"])
            print(f"  Daily segment {day} saved: {fname}")


# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────

def main():
    meta_files = sorted(glob.glob("metadata_*.json"))
    if not meta_files:
        raise FileNotFoundError("Run step1_metadata.py first")

    with open(meta_files[-1], encoding="utf-8") as f:
        data = json.load(f)

    category = data["category"]
    duration = data["duration_hours"]
    report   = _new_report(category, duration)

    print(f"Generating audio: {category} | stereo | {EXPORT_BITRATE}")
    if FREESOUND_OAUTH_TOKEN:
        print("  OAuth token present — full-resolution download enabled")
    else:
        print("  No FREESOUND_OAUTH_TOKEN — using 128kbps HQ preview")
        print("  Tip: add FREESOUND_OAUTH_TOKEN secret for lossless source quality")

    try:
        try:
            segs  = fetch_freesound(data, report)
            audio = loop_audio(segs, duration)
        except Exception as e:
            if ALLOW_ORIGINAL_FALLBACK:
                report["warnings"].append(f"CC0 source fetch failed: {e}")
                audio = build_original_audio(category, duration, report)
            else:
                raise

        # Final stereo guarantee before QA
        audio = ensure_stereo(audio)
        validate_final_audio(audio, report)

        audio.export(
            "output_audio.mp3",
            format="mp3",
            bitrate=EXPORT_BITRATE,
            parameters=["-ar", "44100", "-ac", "2"],  # explicit stereo channels
        )
        export_shorts_pool(audio)

        report["final"]["output_file"] = "output_audio.mp3"
        report["final"]["bitrate"]     = EXPORT_BITRATE
        report["final"]["channels"]    = 2
        print(f"Audio QA passed | stereo | {EXPORT_BITRATE}")

    finally:
        _save_report(report)
        print(f"Audio QA report saved: {QUALITY_REPORT}")
        print("DONE")


if __name__ == "__main__":
    main()
