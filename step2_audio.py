# STEP 2 — Audio Generator (Nocturne Noise) [FIXED FREESOUND API]

import os, json, glob, time, random, re, requests
from pydub import AudioSegment
from dotenv import load_dotenv

load_dotenv()

FREESOUND_KEY = os.environ.get("FREESOUND_API_KEY", "")
PIXABAY_KEY   = os.environ.get("PIXABAY_API_KEY", "")
JAMENDO_KEY   = os.environ.get("JAMENDO_CLIENT_ID", "")

TARGET_LUFS = -18
MIN_SAMPLE_SEC = 45
SAMPLE_RATE = 44100

BAD_TAGS = {"voice","speech","talk","vocal","sing","song","music","people","human"}

_BAD_WORDS_PATTERN = re.compile(r'\b(voice|speech|talk|song|vocal|podcast|interview)\b', re.I)

def has_bad_content(name):
    return bool(_BAD_WORDS_PATTERN.search(name))


# ══════════════════════════════════════════════════════════
# FREESOUND (FIXED — API KEY)
# ══════════════════════════════════════════════════════════

def freesound_search(query, num=10):
    if not FREESOUND_KEY:
        raise ValueError("FREESOUND_API_KEY not set")

    r = requests.get(
        "https://freesound.org/apiv2/search/text/",
        params={
            "query": query,
            "filter": f"duration:[{MIN_SAMPLE_SEC} TO 7200]",
            "fields": "id,name,duration,tags",
            "page_size": num,
            "token": FREESOUND_KEY
        },
        timeout=30
    )

    r.raise_for_status()
    results = r.json().get("results", [])

    clean = [
        s for s in results
        if not ({t.lower() for t in s.get("tags", [])} & BAD_TAGS)
        and not has_bad_content(s.get("name",""))
    ]

    if not clean:
        raise RuntimeError("Freesound empty")

    return clean[:num]


def freesound_download(sound):
    os.makedirs("audio_tmp", exist_ok=True)

    path = f"audio_tmp/fs_{sound['id']}.mp3"
    if os.path.exists(path):
        return path

    url = f"https://freesound.org/apiv2/sounds/{sound['id']}/download/?token={FREESOUND_KEY}"

    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()

    with open(path, "wb") as f:
        for chunk in r.iter_content(32768):
            f.write(chunk)

    return path


def fetch_freesound(query):
    sounds = freesound_search(query)
    files = [freesound_download(s) for s in sounds]
    return load_segments(files)


# ══════════════════════════════════════════════════════════
# PIXABAY
# ══════════════════════════════════════════════════════════

def fetch_pixabay(query):
    if not PIXABAY_KEY:
        raise ValueError("PIXABAY_API_KEY not set")

    r = requests.get(
        "https://pixabay.com/api/sounds/",
        params={"key": PIXABAY_KEY, "q": query},
        timeout=30
    )

    hits = r.json().get("hits", [])
    if not hits:
        raise RuntimeError("Pixabay empty")

    files = []
    os.makedirs("audio_tmp", exist_ok=True)

    for h in hits[:5]:
        url = h.get("audio")
        if not url:
            continue

        path = f"audio_tmp/pb_{h['id']}.mp3"
        if not os.path.exists(path):
            r2 = requests.get(url)
            with open(path, "wb") as f:
                f.write(r2.content)

        files.append(path)

    return load_segments(files)


# ══════════════════════════════════════════════════════════
# JAMENDO
# ══════════════════════════════════════════════════════════

def fetch_jamendo():
    r = requests.get(
        "https://api.jamendo.com/v3.0/tracks/",
        params={
            "client_id": JAMENDO_KEY,
            "format": "json",
            "limit": 5,
            "tags": "jazz",
            "audioformat": "mp31"
        },
        timeout=30
    )

    results = r.json().get("results", [])
    files = []

    os.makedirs("audio_tmp", exist_ok=True)

    for t in results:
        url = t.get("audio")
        if not url:
            continue

        path = f"audio_tmp/jm_{t['id']}.mp3"
        if not os.path.exists(path):
            r2 = requests.get(url)
            with open(path, "wb") as f:
                f.write(r2.content)

        files.append(path)

    return load_segments(files)


# ══════════════════════════════════════════════════════════
# AUDIO CORE
# ══════════════════════════════════════════════════════════

def load_segments(files):
    segs = []
    for f in files:
        try:
            seg = AudioSegment.from_mp3(f)
            if len(seg) > MIN_SAMPLE_SEC * 1000:
                segs.append(seg)
        except:
            pass

    if not segs:
        raise RuntimeError("No valid audio")

    return segs


def loop_audio(segs, hours):
    target = hours * 3600 * 1000
    out = AudioSegment.empty()

    i = 0
    while len(out) < target:
        out += segs[i % len(segs)]
        i += 1

    return out[:target]


# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════

def main():
    meta = sorted(glob.glob("metadata_*.json"))[-1]

    with open(meta) as f:
        data = json.load(f)

    category = data["category"]
    duration = data["duration_hours"]

    print("Generating:", category)

    if category == "jazz":
        segs = fetch_jamendo()
    else:
        try:
            segs = fetch_freesound(data["theme"])
        except:
            segs = fetch_pixabay(data["theme"])

    audio = loop_audio(segs, duration)

    audio.export("output_audio.mp3", format="mp3", bitrate="128k")

    print("DONE")


if __name__ == "__main__":
    main()
