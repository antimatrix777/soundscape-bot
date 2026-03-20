"""
STEP 2 — Audio Generator
========================
3 major improvements over previous version:

1. RANDOM PAGINATION on Freesound — same query, different sounds every run
2. LAYERED SOUND RECIPES — 2-3 sounds mixed at different volumes per category
3. MULTIPLE QUERIES per theme — rotated randomly for variety

Audio sources by category:
  ambient (rain/nature/cozy/study/urban): Freesound → Pixabay → Archive
  jazz:                                   Jamendo → ccMixter → Freesound
  focus_noise:                            Generated locally with numpy
"""
import os, json, glob, time, random, requests
from pydub import AudioSegment
from pydub.effects import normalize
from io import BytesIO
from dotenv import load_dotenv

load_dotenv()

FREESOUND_KEY = os.environ.get("FREESOUND_API_KEY", "")
JAMENDO_KEY   = os.environ.get("JAMENDO_CLIENT_ID", "")
PIXABAY_KEY   = os.environ.get("PIXABAY_API_KEY", "")

TARGET_LUFS    = -18
CROSSFADE_MS   = 6000
FADE_IN_MS     = 20000
FADE_OUT_MS    = 30000
MIN_SAMPLE_SEC = 20
SAMPLE_RATE    = 44100

BAD_TAGS = {
    "voice","speech","talking","conversation","song","singing",
    "vocal","lyrics","glitch","error","test","beep","alarm",
    "scream","cry","laugh","crowd","traffic","engine","machine",
    "electric","digital","synth","electronic","distortion",
    "frog","cricket","insect","cicada",
}

# ─────────────────────────────────────────────────────────
# SOUND RECIPES — layered mixing per category
# Each recipe has a primary layer + optional ambient layers.
# Layers are mixed at specified dB reduction from primary.
#
# Format per category:
#   {
#     "primary":  [list of query options — one picked randomly],
#     "layers": [
#       {"queries": [...], "db_reduction": -12}   # softer layer
#     ]
#   }
# ─────────────────────────────────────────────────────────
SOUND_RECIPES = {
    "rain": {
        "primary": [
            "heavy rain window night",
            "rain window glass indoor",
            "rain rooftop night steady",
            "pouring rain outside window",
        ],
        "layers": [
            {"queries": ["distant thunder low rumble","thunder far away soft"], "db_reduction": -14},
            {"queries": ["indoor room tone ambience quiet","quiet room interior"], "db_reduction": -20},
        ],
    },
    "nature": {
        "primary": [
            "forest ambience birds gentle morning",
            "woodland birds soft dawn",
            "forest nature birds peaceful",
            "deep forest morning gentle",
        ],
        "layers": [
            {"queries": ["stream water flowing gentle","babbling brook soft"], "db_reduction": -10},
            {"queries": ["wind through trees gentle","breeze leaves soft"], "db_reduction": -16},
        ],
    },
    "cozy": {
        "primary": [
            "coffee shop cafe ambience background",
            "cafe indoor background quiet",
            "coffee shop morning soft murmur",
            "cafe restaurant gentle background",
        ],
        "layers": [
            {"queries": ["fireplace crackling wood fire","fire crackling gentle"], "db_reduction": -11},
            {"queries": ["vinyl record noise crackle","vinyl crackle soft"], "db_reduction": -18},
        ],
    },
    "study": {
        "primary": [
            "library quiet indoor ambience",
            "quiet study room indoor",
            "library night quiet peaceful",
            "indoor quiet room soft",
        ],
        "layers": [
            {"queries": ["rain window soft gentle","rain outside window"], "db_reduction": -10},
            {"queries": ["page turning book soft","pencil writing paper"], "db_reduction": -20},
        ],
    },
    "urban": {
        "primary": [
            "city night ambience quiet",
            "urban night sounds distant",
            "city street night gentle",
            "night city ambient distant",
        ],
        "layers": [
            {"queries": ["rain city street night","rain on pavement urban"], "db_reduction": -8},
            {"queries": ["distant bar music muffled","muffled music distant cafe"], "db_reduction": -20},
        ],
    },
    "jazz": {
        "primary_jamendo_tags": [
            "jazz", "piano jazz", "jazz piano", "bossanova", "jazz guitar",
        ],
        "layers": [
            {"queries": ["bar cafe ambience background soft","jazz club ambience"], "db_reduction": -14},
            {"queries": ["rain window soft","gentle rain indoor"], "db_reduction": -18},
        ],
    },
    "focus_noise": {
        "noise_type": "brown",
        "layers": [
            {"queries": ["distant rain soft","rain far away gentle"], "db_reduction": -16},
        ],
    },
}


# ══════════════════════════════════════════════════════════
# FREESOUND — random page for variety every run
# ══════════════════════════════════════════════════════════
def freesound_search(query, num=8, randomize_page=True):
    if not FREESOUND_KEY:
        raise ValueError("FREESOUND_API_KEY not set")

    # Random page = different sounds every run for the same query
    page = random.randint(1, 5) if randomize_page else 1
    print(f"   [Freesound] '{query}' (page {page})")

    r = requests.get("https://freesound.org/apiv2/search/text/", params={
        "query":     query,
        "token":     FREESOUND_KEY,
        "fields":    "id,name,previews,duration,license,tags,avg_rating,num_ratings,num_downloads",
        "filter":    f"duration:[{MIN_SAMPLE_SEC} TO 480] license:(\"Creative Commons 0\" OR \"Attribution\")",
        "sort":      "rating_desc",
        "page_size": 15,
        "page":      page,
    }, timeout=30)
    r.raise_for_status()
    results = r.json().get("results", [])

    clean = [s for s in results
             if not ({t.lower() for t in s.get("tags", [])} & BAD_TAGS)
             and s.get("num_ratings", 0) >= 1]
    clean.sort(
        key=lambda s: s.get("avg_rating", 0) * min(s.get("num_downloads", 0) / 500, 5),
        reverse=True,
    )
    # Shuffle top results slightly for more variety
    top = clean[:max(num * 2, 10)]
    random.shuffle(top)
    chosen = top[:num]
    print(f"   -> {len(results)} found, {len(chosen)} selected (page {page})")
    return chosen


def freesound_download(sound, folder="audio_tmp"):
    os.makedirs(folder, exist_ok=True)
    url = sound["previews"].get("preview-hq-mp3") or sound["previews"].get("preview-lq-mp3")
    if not url:
        return None
    path = os.path.join(folder, f"fs_{sound['id']}.mp3")
    if os.path.exists(path):
        return path
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    with open(path, "wb") as f:
        f.write(r.content)
    time.sleep(0.3)
    return path


def fetch_freesound_audio(query, num=8):
    """Fetches sounds from Freesound and returns processed segments."""
    sounds = freesound_search(query, num=num)
    if not sounds:
        raise RuntimeError(f"Freesound: no sounds for '{query}'")
    files = [freesound_download(s) for s in sounds]
    files = [f for f in files if f]
    if not files:
        raise RuntimeError("Freesound: download failed")
    return load_segments(files, channels=1)


# ══════════════════════════════════════════════════════════
# PIXABAY AUDIO — fallback ambient
# ══════════════════════════════════════════════════════════
def pixabay_audio_search(query, num=8):
    if not PIXABAY_KEY:
        raise ValueError("PIXABAY_API_KEY not set")
    print(f"   [Pixabay Audio] '{query}'")
    r = requests.get("https://pixabay.com/api/sounds/", params={
        "key": PIXABAY_KEY, "q": query, "per_page": num,
    }, timeout=30)
    r.raise_for_status()
    hits = r.json().get("hits", [])
    print(f"   -> {len(hits)} found")
    return hits


def pixabay_download(hit, folder="audio_tmp"):
    os.makedirs(folder, exist_ok=True)
    url = hit.get("audio") or hit.get("audioURL")
    if not url:
        for k, v in hit.items():
            if isinstance(v, str) and v.endswith(".mp3"):
                url = v
                break
    if not url:
        return None
    path = os.path.join(folder, f"pb_{hit['id']}.mp3")
    if os.path.exists(path):
        return path
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    with open(path, "wb") as f:
        f.write(r.content)
    time.sleep(0.3)
    return path


def fetch_pixabay_audio(query, num=8):
    hits = pixabay_audio_search(query, num=num)
    if not hits:
        raise RuntimeError(f"Pixabay: no sounds for '{query}'")
    files = [pixabay_download(h) for h in hits]
    files = [f for f in files if f]
    if not files:
        raise RuntimeError("Pixabay: download failed")
    return load_segments(files, channels=1)


# ══════════════════════════════════════════════════════════
# INTERNET ARCHIVE — last fallback
# ══════════════════════════════════════════════════════════
def fetch_archive_audio(query, num=6):
    print(f"   [Internet Archive] '{query}'")
    r = requests.get("https://archive.org/advancedsearch.php", params={
        "q": f"{query} AND mediatype:audio AND format:MP3",
        "fl": "identifier,title",
        "rows": num, "output": "json",
    }, timeout=30)
    r.raise_for_status()
    docs = r.json().get("response", {}).get("docs", [])
    print(f"   -> {len(docs)} items")

    files = []
    for doc in docs:
        identifier = doc.get("identifier", "")
        if not identifier:
            continue
        try:
            meta = requests.get(f"https://archive.org/metadata/{identifier}", timeout=15)
            mp3s = [f for f in meta.json().get("files", [])
                    if f.get("name", "").endswith(".mp3")]
            if not mp3s:
                continue
            mp3s.sort(key=lambda f: int(f.get("size", 9999999999)))
            target = mp3s[0]
            url  = f"https://archive.org/download/{identifier}/{target['name']}"
            path = os.path.join("audio_tmp", f"ia_{identifier[:20]}.mp3")
            os.makedirs("audio_tmp", exist_ok=True)
            if not os.path.exists(path):
                r2 = requests.get(url, timeout=120, stream=True)
                r2.raise_for_status()
                with open(path, "wb") as f:
                    for chunk in r2.iter_content(32768):
                        f.write(chunk)
            files.append(path)
        except Exception as e:
            print(f"   IA item error: {e}")

    if not files:
        raise RuntimeError("Archive: no files downloaded")
    return load_segments(files, channels=1)


# ══════════════════════════════════════════════════════════
# JAMENDO — jazz instrumental
# ══════════════════════════════════════════════════════════
def fetch_jamendo(tags, num=12):
    if not JAMENDO_KEY:
        raise ValueError("JAMENDO_CLIENT_ID not set")

    attempts = list(dict.fromkeys([tags, "jazz", "piano", "acoustic", "instrumental"]))
    for attempt in attempts:
        print(f"   [Jamendo] tags='{attempt}'")
        try:
            r = requests.get("https://api.jamendo.com/v3.0/tracks/", params={
                "client_id":         JAMENDO_KEY,
                "format":            "json",
                "limit":             num,
                "tags":              attempt,
                "audioformat":       "mp31",
                "boost":             "popularity_month",
                "vocalinstrumental": "instrumental",
                "offset":            random.randint(0, 50),  # variety
            }, timeout=30)
            r.raise_for_status()
            results = r.json().get("results", [])
            print(f"   -> {len(results)} tracks")
            if results:
                random.shuffle(results)
                files = []
                for t in results[:10]:
                    url = t.get("audio")
                    if not url:
                        continue
                    path = os.path.join("audio_tmp", f"jm_{t['id']}.mp3")
                    os.makedirs("audio_tmp", exist_ok=True)
                    if not os.path.exists(path):
                        print(f"   -> {t.get('name','')[:45]}")
                        r2 = requests.get(url, timeout=120, stream=True)
                        r2.raise_for_status()
                        with open(path, "wb") as f:
                            for chunk in r2.iter_content(32768):
                                f.write(chunk)
                        time.sleep(0.5)
                    files.append(path)
                if files:
                    return load_segments(files, channels=2)
        except Exception as e:
            print(f"   Jamendo error '{attempt}': {e}")
    raise RuntimeError("Jamendo: no results after all fallbacks")


# ══════════════════════════════════════════════════════════
# CCMIXTER — jazz fallback
# ══════════════════════════════════════════════════════════
def fetch_ccmixter(query="jazz instrumental", num=12):
    print(f"   [ccMixter] '{query}'")
    try:
        r = requests.get("http://ccmixter.org/api/query", params={
            "tags": query, "type": "instrumentals",
            "format": "json", "limit": num, "sort": "rank",
        }, timeout=30)
        r.raise_for_status()
        results = r.json() if isinstance(r.json(), list) else []
        print(f"   -> {len(results)} tracks")
        if not results:
            raise RuntimeError("ccMixter: no results")
        random.shuffle(results)
        files = []
        for t in results[:8]:
            for fdata in t.get("files", []):
                url = fdata.get("download_url") or fdata.get("file_page_url")
                if url and url.endswith(".mp3"):
                    tid = str(t.get("upload_id", random.randint(1000, 9999)))
                    path = os.path.join("audio_tmp", f"cc_{tid}.mp3")
                    os.makedirs("audio_tmp", exist_ok=True)
                    if not os.path.exists(path):
                        try:
                            r2 = requests.get(url, timeout=120, stream=True, allow_redirects=True)
                            r2.raise_for_status()
                            with open(path, "wb") as f:
                                for chunk in r2.iter_content(32768):
                                    f.write(chunk)
                            if os.path.getsize(path) < 10000:
                                os.remove(path)
                                continue
                        except Exception:
                            continue
                    files.append(path)
                    break
        if not files:
            raise RuntimeError("ccMixter: no files downloaded")
        return load_segments(files, channels=2)
    except Exception as e:
        raise RuntimeError(f"ccMixter failed: {e}")


# ══════════════════════════════════════════════════════════
# NUMPY — focus noise (locally generated, perfect quality)
# ══════════════════════════════════════════════════════════
def generate_brown_noise(duration_ms):
    import numpy as np
    n = int(SAMPLE_RATE * duration_ms / 1000)
    def _brown(seed_offset=0):
        rng   = np.random.default_rng(int(time.time() * 1000) % 999999 + seed_offset)
        white = rng.normal(0, 1, n)
        b     = np.cumsum(white)
        b    -= np.mean(b)
        b    /= (np.max(np.abs(b)) + 1e-8)
        return (b * 0.5 * 32767).astype(np.int16)
    stereo = np.column_stack([_brown(0), _brown(7)]).flatten()
    return AudioSegment(stereo.tobytes(), frame_rate=SAMPLE_RATE, sample_width=2, channels=2)

def generate_white_noise(duration_ms):
    import numpy as np
    n = int(SAMPLE_RATE * duration_ms / 1000)
    rng = np.random.default_rng(int(time.time() * 1000) % 999999)
    L = np.clip(rng.normal(0, 0.15, n), -1, 1)
    R = np.clip(rng.normal(0, 0.15, n), -1, 1)
    stereo = np.column_stack([(L * 32767).astype(np.int16), (R * 32767).astype(np.int16)]).flatten()
    return AudioSegment(stereo.tobytes(), frame_rate=SAMPLE_RATE, sample_width=2, channels=2)

def generate_pink_noise(duration_ms):
    import numpy as np
    n = int(SAMPLE_RATE * duration_ms / 1000)
    def _pink():
        f = np.fft.rfftfreq(n, d=1/SAMPLE_RATE)
        f[0] = 1
        power = 1 / np.sqrt(f); power[0] = 0
        phase = np.random.uniform(0, 2 * np.pi, len(f))
        p = np.fft.irfft(power * np.exp(1j * phase), n=n)
        p /= (np.max(np.abs(p)) + 1e-8)
        return (p * 0.5 * 32767).astype(np.int16)
    stereo = np.column_stack([_pink(), _pink()]).flatten()
    return AudioSegment(stereo.tobytes(), frame_rate=SAMPLE_RATE, sample_width=2, channels=2)

def build_noise(noise_type, duration_hours):
    print(f"   Generating {noise_type} noise ({duration_hours}h)...")
    block_ms  = 10 * 60 * 1000
    target_ms = duration_hours * 3600 * 1000
    n_blocks  = (target_ms // block_ms) + 2
    gen = {"white": generate_white_noise, "brown": generate_brown_noise, "pink": generate_pink_noise}
    fn  = gen.get(noise_type, generate_brown_noise)
    combined = AudioSegment.empty()
    for i in range(n_blocks):
        block    = fn(block_ms)
        combined = combined.append(block, crossfade=3000) if len(combined) > 0 else combined + block
        print(f"   {min(100, len(combined)/target_ms*100):.0f}%", end="\r")
    print()
    return combined[:target_ms]


# ══════════════════════════════════════════════════════════
# AUDIO PROCESSING
# ══════════════════════════════════════════════════════════
def load_segments(files, channels=1):
    """Load audio files into normalized AudioSegment list."""
    segments = []
    for f in files:
        try:
            seg = AudioSegment.from_mp3(f)
            seg = seg.set_channels(channels).set_frame_rate(SAMPLE_RATE)
            seg = normalize(seg)
            if len(seg) < MIN_SAMPLE_SEC * 1000:
                continue
            segments.append(seg)
            print(f"   + {os.path.basename(f)} ({len(seg)/1000:.0f}s)")
        except Exception as e:
            print(f"   ! {f}: {e}")
    if not segments:
        raise RuntimeError("No valid segments after processing")
    return segments


def loop_to_duration(segments, duration_hours):
    """Loop segments with smooth crossfade until target duration."""
    target_ms = duration_hours * 3600 * 1000
    random.shuffle(segments)
    combined  = AudioSegment.empty()
    i = 0
    while len(combined) < target_ms:
        seg            = segments[i % len(segments)]
        safe_crossfade = min(CROSSFADE_MS, len(seg) // 4)
        combined       = combined.append(seg, crossfade=safe_crossfade) if len(combined) > 0 else combined + seg
        i += 1
        if i % 5 == 0:
            print(f"   {min(100, len(combined)/target_ms*100):.0f}% ({len(combined)//60000}min)")
    return combined[:target_ms]


def mix_layer(base, layer_segs, db_reduction, duration_hours):
    """
    Overlays a softer layer on top of the base audio.
    db_reduction: how many dB quieter the layer is (e.g. -12 = 12dB softer)
    """
    try:
        layer = loop_to_duration(layer_segs, duration_hours)
        layer = normalize(layer) + db_reduction  # make it quieter
        # Match channels
        if base.channels != layer.channels:
            layer = layer.set_channels(base.channels)
        result = base.overlay(layer)
        print(f"   Layer mixed at {db_reduction}dB")
        return result
    except Exception as e:
        print(f"   Layer skipped: {e}")
        return base


def finalize_audio(combined, output="output_audio.mp3"):
    print("\n   Finalizing audio...")
    combined = combined.fade_in(FADE_IN_MS).fade_out(FADE_OUT_MS)
    combined = normalize(combined)
    db = combined.dBFS
    if db < TARGET_LUFS - 3:
        combined = combined + (TARGET_LUFS - db)
    combined = combined.set_frame_rate(SAMPLE_RATE)
    combined.export(output, format="mp3", bitrate="192k",
                    tags={"artist": "Comfort Sounds", "album": "Ambient Collection"})
    mb = os.path.getsize(output) / (1024 * 1024)
    print(f"   Done: {output} ({mb:.0f}MB, {len(combined)/3600000:.1f}h)")
    return output


def cleanup_tmp():
    for f in glob.glob("audio_tmp/*.mp3"):
        try:
            os.remove(f)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════
# FETCH AMBIENT — cascade with fallbacks
# ══════════════════════════════════════════════════════════
def fetch_ambient(query):
    """Try Freesound → Pixabay → Archive for ambient sounds."""
    for name, fn, args in [
        ("Freesound",        fetch_freesound_audio,  (query,)),
        ("Pixabay Audio",    fetch_pixabay_audio,    (query,)),
        ("Internet Archive", fetch_archive_audio,    (query,)),
    ]:
        try:
            print(f"\n   Trying {name}...")
            return fn(*args)
        except Exception as e:
            print(f"   {name} failed: {e}")
    raise RuntimeError(f"All ambient sources failed for '{query}'")


def fetch_jazz(tags):
    """Try Jamendo → ccMixter → Freesound for jazz."""
    for name, fn, args in [
        ("Jamendo",   fetch_jamendo,   (tags,)),
        ("ccMixter",  fetch_ccmixter,  ("jazz instrumental",)),
        ("Freesound", fetch_freesound_audio, ("jazz piano soft instrumental",)),
    ]:
        try:
            print(f"\n   Trying {name}...")
            return fn(*args)
        except Exception as e:
            print(f"   {name} failed: {e}")
    raise RuntimeError("All jazz sources failed")


# ══════════════════════════════════════════════════════════
# MAIN — build audio with layered recipes
# ══════════════════════════════════════════════════════════
def main():
    meta_files = sorted(glob.glob("metadata_*.json"), key=os.path.getmtime, reverse=True)
    if not meta_files:
        raise FileNotFoundError("Run step1_metadata.py first")

    with open(meta_files[0]) as f:
        metadata = json.load(f)

    category   = metadata["category"]
    duration   = metadata["duration_hours"]
    theme_data = metadata.get("theme_data", {})
    recipe     = SOUND_RECIPES.get(category, {})

    print(f"\nGenerating audio: {metadata['theme']} ({duration}h)")
    print(f"Category: {category}")

    # ── Focus noise ────────────────────────────────────────
    if category == "focus_noise":
        noise_type = theme_data.get("noise_type", "brown")
        combined   = build_noise(noise_type, duration)

        # Optionally layer distant rain for warmth
        for layer in recipe.get("layers", []):
            query = random.choice(layer["queries"])
            try:
                layer_segs = fetch_ambient(query)
                combined   = mix_layer(combined, layer_segs, layer["db_reduction"], duration)
            except Exception as e:
                print(f"   Focus layer skipped: {e}")

    # ── Jazz ───────────────────────────────────────────────
    elif category == "jazz":
        tags       = theme_data.get("tags", "jazz")
        primary    = fetch_jazz(tags)
        combined   = loop_to_duration(primary, duration)

        # Layer ambient sounds (bar, rain) underneath jazz
        for layer in recipe.get("layers", []):
            query = random.choice(layer["queries"])
            try:
                layer_segs = fetch_ambient(query)
                combined   = mix_layer(combined, layer_segs, layer["db_reduction"], duration)
            except Exception as e:
                print(f"   Jazz layer skipped: {e}")

    # ── Ambient (rain/nature/cozy/study/urban) ─────────────
    else:
        # Pick a random primary query from recipe options
        primary_queries = recipe.get("primary", [theme_data.get("query", metadata["theme"])])
        primary_query   = random.choice(primary_queries)
        print(f"\n   Primary query: '{primary_query}'")

        primary_segs = fetch_ambient(primary_query)
        combined     = loop_to_duration(primary_segs, duration)

        # Mix in each layer
        for layer in recipe.get("layers", []):
            query = random.choice(layer["queries"])
            print(f"\n   Adding layer: '{query}'")
            try:
                layer_segs = fetch_ambient(query)
                combined   = mix_layer(combined, layer_segs, layer["db_reduction"], duration)
            except Exception as e:
                print(f"   Layer skipped: {e}")

    finalize_audio(combined, "output_audio.mp3")
    cleanup_tmp()


if __name__ == "__main__":
    main()
