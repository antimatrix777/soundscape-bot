# STEP 2 - Audio Generator (Nocturne Noise)
#
# Editorial rule: never publish questionable or copyright-risk audio.
# The pipeline now fails closed when it cannot find clean sources, instead of
# accepting unfiltered previews that may contain voices, radio, chatter, or
# distracting background sounds. Default license mode is CC0/public domain only.

import glob
import json
import os
import random
import re
import statistics
import time

import requests
from dotenv import load_dotenv
from pydub import AudioSegment

load_dotenv()

FREESOUND_KEY = os.environ.get("FREESOUND_API_KEY", "")

TARGET_DBFS = -20.0
CROSSFADE_MS = 6000
MIN_SAMPLE_SEC = 75
MIN_ACCEPTED_SEGMENTS = 3
QUALITY_REPORT = "audio_quality_report.json"
LICENSE_MODE = os.environ.get("AUDIO_LICENSE_MODE", "cc0_only").lower()

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


def _new_report(category, duration_hours):
    return {
        "category": category,
        "duration_hours": duration_hours,
        "target_dbfs": TARGET_DBFS,
        "license_mode": LICENSE_MODE,
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


def _chunk_dbfs(seg, chunk_ms=5000):
    values = []
    for start in range(0, len(seg), chunk_ms):
        chunk = seg[start:start + chunk_ms]
        if len(chunk) >= 1000 and chunk.dBFS != float("-inf"):
            values.append(chunk.dBFS)
    return values


def _audio_quality(seg, category):
    reasons = []

    if len(seg) < MIN_SAMPLE_SEC * 1000:
        reasons.append(f"too short ({len(seg) // 1000}s)")

    if seg.dBFS == float("-inf"):
        reasons.append("silent file")
        return reasons, {"dbfs": None, "peak_dbfs": None, "range_db": None}

    peak_dbfs = seg.max_dBFS
    values = _chunk_dbfs(seg)
    loudness_range = (max(values) - min(values)) if len(values) > 1 else 0.0
    median_dbfs = statistics.median(values) if values else seg.dBFS

    if seg.dBFS > -10:
        reasons.append(f"too loud overall ({seg.dBFS:.1f} dBFS)")
    if seg.dBFS < -34:
        reasons.append(f"too quiet overall ({seg.dBFS:.1f} dBFS)")
    if peak_dbfs > -0.8:
        reasons.append(f"peak too close to clipping ({peak_dbfs:.1f} dBFS)")

    max_range = 18.0 if category in {"jazz", "lofi"} else 14.0
    if loudness_range > max_range:
        reasons.append(f"unstable loudness range ({loudness_range:.1f} dB)")

    if median_dbfs - seg.dBFS > 8:
        reasons.append("spiky profile, likely transient or intrusive foreground sound")

    stats = {
        "duration_s": len(seg) // 1000,
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


def freesound_search(query, report, num=12):
    if not FREESOUND_KEY:
        raise ValueError("FREESOUND_API_KEY not set")

    print(f"   [Freesound] Searching: {query}")
    r = requests.get(
        "https://freesound.org/apiv2/search/text/",
        params={
            "query": query,
            "filter": _freesound_filter(),
            "fields": "id,name,duration,tags,previews,license,username",
            "page_size": num,
            "sort": "rating_desc",
            "token": FREESOUND_KEY,
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
                "sound": _sound_label(sound),
            })
        elif _has_bad_metadata(sound):
            report["rejected"].append({
                "source": "freesound",
                "reason": "blocked metadata",
                "sound": _sound_label(sound),
            })
        else:
            clean.append(sound)

    print(f"   [Freesound] Clean metadata results: {len(clean)}/{len(results)}")
    return clean[:num]


def freesound_download(sound):
    os.makedirs("audio_tmp", exist_ok=True)

    path = f"audio_tmp/fs_{sound['id']}.mp3"
    if os.path.exists(path):
        return path

    url = sound.get("previews", {}).get("preview-hq-mp3")
    if not url:
        raise RuntimeError(f"Sound {sound['id']} has no HQ preview")

    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()

    with open(path, "wb") as f:
        for chunk in r.iter_content(32768):
            f.write(chunk)

    return path


def _freesound_queries(data):
    category = data["category"]
    theme_data = data.get("theme_data", {})
    primary = theme_data.get("query") or data.get("theme", category)
    terms = POSITIVE_QUERY_TERMS.get(category, [])
    queries = [primary]

    if terms:
        queries.append(f"{primary} {terms[0]}")
        queries.append(f"{primary} {terms[1]}")

    queries.extend(FREESOUND_SAFE_FALLBACKS.get(category, []))

    seen = set()
    unique = []
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
        sounds = list(deduped.values())
        if len(sounds) >= MIN_ACCEPTED_SEGMENTS * 2:
            break
        time.sleep(0.8)

    if not sounds:
        raise RuntimeError("No clean Freesound candidates found. Refusing unsafe audio.")

    files = []
    for sound in sounds:
        try:
            path = freesound_download(sound)
            files.append((path, {"source": "freesound", "sound": _sound_label(sound)}))
        except Exception as e:
            report["rejected"].append({
                "source": "freesound",
                "reason": f"download failed: {e}",
                "sound": _sound_label(sound),
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
                    **meta,
                    "file": path,
                    "reason": "; ".join(reasons),
                    "stats": stats,
                })
                print(f"   Rejected: {path} ({'; '.join(reasons)})")
                continue

            seg = normalize_segment(seg)
            post_reasons, post_stats = _audio_quality(seg, category)
            if any("peak too close" in r for r in post_reasons):
                report["rejected"].append({
                    **meta,
                    "file": path,
                    "reason": "; ".join(post_reasons),
                    "stats": post_stats,
                })
                print(f"   Rejected after normalize: {path}")
                continue

            report["accepted"].append({**meta, "file": path, "stats": post_stats})
            segs.append(seg.set_frame_rate(44100).set_channels(2))
            print(f"   Accepted: {path} ({len(seg)//1000}s | {seg.dBFS:.1f} dBFS)")

        except Exception as e:
            report["rejected"].append({"file": path, "reason": f"decode failed: {e}", **meta})
            print(f"   Ignored: {path} ({e})")

    if len(segs) < MIN_ACCEPTED_SEGMENTS:
        raise RuntimeError(
            f"Only {len(segs)} clean audio segment(s) accepted. "
            f"Need at least {MIN_ACCEPTED_SEGMENTS}. Refusing upload-quality build."
        )

    random.shuffle(segs)
    return segs


def loop_audio(segs, hours):
    target = hours * 3600 * 1000
    out = segs[0].fade_in(2500)
    i = 1

    while len(out) < target + CROSSFADE_MS:
        next_seg = segs[i % len(segs)]
        fade_ms = min(CROSSFADE_MS, len(out) // 3, len(next_seg) // 3)
        out = out.append(next_seg, crossfade=fade_ms)
        i += 1

    return out[:target].fade_out(8000)


def validate_final_audio(audio, report):
    reasons, stats = _audio_quality(audio[: min(len(audio), 20 * 60 * 1000)], report["category"])
    report["final"] = {
        "duration_s": len(audio) // 1000,
        "sample_stats": stats,
        "status": "pass" if not reasons else "fail",
        "reasons": reasons,
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
            fname = f"short_audio_{day}.mp3"
            short_seg.export(fname, format="mp3", bitrate="192k", parameters=["-ar", "44100"])
            print(f"   Daily segment {day} saved: {fname}")


def main():
    meta_files = sorted(glob.glob("metadata_*.json"))
    if not meta_files:
        raise FileNotFoundError("Run step1_metadata.py first")

    with open(meta_files[-1], encoding="utf-8") as f:
        data = json.load(f)

    category = data["category"]
    duration = data["duration_hours"]
    report = _new_report(category, duration)

    print("Generating audio:", category)

    try:
        segs = fetch_freesound(data, report)

        audio = loop_audio(segs, duration)
        validate_final_audio(audio, report)

        audio.export("output_audio.mp3", format="mp3", bitrate="192k", parameters=["-ar", "44100"])
        export_shorts_pool(audio)
        report["final"]["output_file"] = "output_audio.mp3"
        report["final"]["bitrate"] = "192k"
        print("Audio QA passed")

    finally:
        _save_report(report)
        print(f"Audio QA report saved: {QUALITY_REPORT}")

    print("DONE")


if __name__ == "__main__":
    main()
