"""
STEP 2 — Audio Generator (Nocturne Noise)
==========================================
Audio sources by category:
  ambient: Freesound OAuth (primary) → Pixabay Audio (sounds only, no videos)
  jazz:    Jamendo → ccMixter → Freesound OAuth
  noise:   Generated locally with numpy (perfect quality)

FIXES vs previous version:
  - REMOVED Internet Archive — primary source of voice contamination
  - REMOVED Pixabay /api/videos/ endpoint — video files frequently contain narration
  - fetch_ambient cascade is now: Freesound OAuth → Pixabay (sounds only)
  - has_bad_content() rewritten with regex word boundaries — fixes false positives
    ("birdsong" no longer blocked by "song", "cocktail" by "talk", etc.)
  - BAD_TAGS expanded: guided, meditation, affirmation, human, people, speaking, story, lecture
  - Freesound filter uses correct Solr/Lucene syntax: -tag:x instead of NOT tag:x
    (NOT operator caused 400 Bad Request errors)
"""
import os, json, glob, time, random, re, requests, base64
from pydub import AudioSegment
from pydub.effects import normalize
from io import BytesIO
from dotenv import load_dotenv

load_dotenv()

FREESOUND_KEY    = os.environ.get("FREESOUND_API_KEY", "")
FREESOUND_TOKEN  = os.environ.get("FREESOUND_TOKEN_B64", "")
FREESOUND_CID    = os.environ.get("FREESOUND_CLIENT_ID", "")
FREESOUND_CSEC   = os.environ.get("FREESOUND_CLIENT_SECRET", "")
JAMENDO_KEY      = os.environ.get("JAMENDO_CLIENT_ID", "")
PIXABAY_KEY      = os.environ.get("PIXABAY_API_KEY", "")

TARGET_LUFS     = -18
CROSSFADE_MS    = 6000
FADE_IN_MS      = 20000
FADE_OUT_MS     = 30000
MIN_SAMPLE_SEC  = 45
SAMPLE_RATE     = 44100

# ─────────────────────────────────────────────────────────
# BAD_TAGS — filters out ANY audio with voice/speech/music
# Applied to: Freesound tags, Pixabay title/tags, filename guard
# ─────────────────────────────────────────────────────────
BAD_TAGS = {
    # Voice & speech
    "voice", "speech", "talking", "conversation", "spoken", "narrator",
    "narration", "voiceover", "vocal", "vocals", "singing", "singer",
    "song", "lyrics", "lyric", "words", "reading", "audiobook",
    "podcast", "interview", "commentary", "announcement", "broadcast",
    "radio", "news", "monologue", "dialogue", "chant", "speaking",
    "human", "people", "man", "woman", "person",
    # Guided content (always has voice)
    "guided", "meditation guided", "affirmation", "sleep talk",
    "story", "storytelling", "tale", "lecture", "lesson",
    # Music genres that typically have vocals
    "rap", "hiphop", "hip hop", "folk", "pop", "rock", "blues",
    "country", "rnb", "r&b", "soul", "reggae", "opera", "gospel",
    "metal", "punk", "indie", "acoustic song", "music",
    # Technical artifacts
    "glitch", "error", "test", "beep", "alarm", "sample", "remix",
    # Disturbing/unwanted sounds
    "scream", "cry", "laugh", "crowd", "traffic", "engine",
    "machine", "electric", "digital", "synth", "electronic",
    "distortion", "frog", "cricket", "insect", "cicada",
    # Music-adjacent that implies vocals
    "band", "concert", "performance", "live music",
}

# ─────────────────────────────────────────────────────────
# FILENAME / TITLE GUARD — uses regex word boundaries
# Prevents false positives: "birdsong" != "song", "cocktail" != "talk"
# ─────────────────────────────────────────────────────────
_BAD_WORDS_PATTERN = re.compile(
    r'\b(' + '|'.join([
        r"vocal", r"voice", r"speech", r"spoken", r"song", r"lyric",
        r"podcast", r"interview", r"narrator", r"narration", r"rap",
        r"singing", r"singer", r"broadcast", r"radio", r"guided",
        r"affirmation", r"story", r"lecture", r"speaking",
        r"human", r"people", r"talking", r"chant", r"talk",
    ]) + r')\b',
    re.IGNORECASE,
)

def has_bad_content(name: str) -> bool:
    """
    Returns True if a filename or title contains vocal/speech indicators.
    Uses regex word boundaries — 'birdsong' is NOT blocked by 'song',
    'cocktail' is NOT blocked by 'talk', 'passwords' NOT blocked by 'words'.
    """
    return bool(_BAD_WORDS_PATTERN.search(name))


SOUND_RECIPES = {
    "rain": {
        "primary": [
            "heavy rain window night",
            "rain window indoor",
            "rain rooftop steady",
            "heavy rain window",
            "rain glass ambient",
        ],
        "layers": [
            {"queries": ["distant thunder low rumble", "thunder far away soft"], "db_reduction": -14},
            {"queries": ["indoor room tone ambience quiet", "quiet room interior"], "db_reduction": -20},
        ],
        "eq": "high_cut",
    },
    "nature": {
        "primary": [
            "forest birds morning",
            "birds forest dawn",
            "forest birds peaceful",
            "deep forest ambience",
            "forest stream ambient",
        ],
        "layers": [
            {"queries": ["stream water flowing gentle", "babbling brook soft"], "db_reduction": -10},
            {"queries": ["wind through trees gentle", "breeze leaves soft"], "db_reduction": -16},
        ],
        "eq": "natural",
    },
    "cozy": {
        "primary": [
            "coffee shop ambience",
            "cafe indoor quiet",
            "coffee shop sounds",
            "cafe ambient soft",
        ],
        "layers": [
            {"queries": ["fireplace crackling wood fire", "fire crackling gentle"], "db_reduction": -11},
            {"queries": ["indoor room tone quiet", "quiet room ambience interior"], "db_reduction": -18},
        ],
        "eq": "natural",
    },
    "study": {
        "primary": [
            "library quiet indoor ambience",
            "quiet study room indoor",
            "library quiet night",
            "indoor quiet ambient",
        ],
        "layers": [
            {"queries": ["rain window soft gentle", "rain outside window"], "db_reduction": -10},
            {"queries": ["page turning book paper", "pencil writing paper soft"], "db_reduction": -20},
        ],
        "eq": "natural",
    },
    "urban": {
        "primary": [
            "city night ambience",
            "urban night sounds",
            "city street night",
            "night city ambient",
        ],
        "layers": [
            {"queries": ["rain city pavement", "rain urban street ambient"], "db_reduction": -8},
            {"queries": ["distant traffic hum night", "city ambient hum quiet"], "db_reduction": -20},
        ],
        "eq": "natural",
    },
    "jazz": {
        "primary_jamendo_tags": [
            "jazz", "piano jazz", "jazz piano", "bossanova", "jazz guitar",
            "smooth jazz", "acoustic jazz", "jazz quartet",
        ],
        "layers": [
            {"queries": ["bar cafe ambience background quiet", "indoor cafe ambient soft"], "db_reduction": -14},
            {"queries": ["rain window soft", "gentle rain indoor"], "db_reduction": -18},
        ],
        "eq": "natural",
    },
    "focus_noise": {
        "noise_type": "brown",
        "layers": [
            {"queries": ["distant rain soft", "rain far away gentle"], "db_reduction": -16},
        ],
        "eq": "high_cut",
    },
}


# ══════════════════════════════════════════════════════════
# FREESOUND OAUTH — primary ambient source
# ══════════════════════════════════════════════════════════
def get_freesound_token():
    if not FREESOUND_TOKEN:
        raise ValueError("FREESOUND_TOKEN_B64 not set")

    token_data    = json.loads(base64.b64decode(FREESOUND_TOKEN).decode())
    access_token  = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")

    if refresh_token and FREESOUND_CID and FREESOUND_CSEC:
        try:
            r = requests.post("https://freesound.org/apiv2/oauth2/access_token/", data={
                "client_id":     FREESOUND_CID,
                "client_secret": FREESOUND_CSEC,
                "grant_type":    "refresh_token",
                "refresh_token": refresh_token,
            }, timeout=20)
            if r.status_code == 200:
                new_data     = r.json()
                access_token = new_data.get("access_token", access_token)
                print("   Freesound token refreshed OK")
        except Exception as e:
            print(f"   Token refresh failed (using existing): {e}")

    return access_token


def freesound_oauth_search(query, num=12):
    token = get_freesound_token()
    page  = random.randint(1, 4)
    print(f"   [Freesound OAuth] '{query}' (page {page})")

    # Freesound uses Solr/Lucene syntax.
    # Exclusion operator is -tag:x — NOT tag:x causes 400 Bad Request.
    # Defined once and reused for both the main search and the short-query retry.
    solr_filter = (
        f"duration:[{MIN_SAMPLE_SEC} TO 7200] "
        f"license:(\"Creative Commons 0\" OR \"Attribution\") "
        f"-tag:music -tag:vocal -tag:voice -tag:speech -tag:singing"
    )

    r = requests.get("https://freesound.org/apiv2/search/text/", params={
        "query":     query,
        "fields":    "id,name,download,duration,license,tags,avg_rating,num_ratings,num_downloads",
        "filter":    solr_filter,
        "sort":      "rating_desc",
        "page_size": 15,
        "page":      page,
    }, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    results = r.json().get("results", [])

    # Secondary filter: BAD_TAGS set + filename guard on top of API filter
    clean = [s for s in results
             if not ({t.lower() for t in s.get("tags", [])} & BAD_TAGS)
             and not has_bad_content(s.get("name", ""))
             and s.get("num_ratings", 0) >= 1]
    clean.sort(
        key=lambda s: s.get("avg_rating", 0) * min(s.get("num_downloads", 0) / 500, 5),
        reverse=True,
    )
    top = clean[:max(num * 2, 12)]
    random.shuffle(top)
    chosen = top[:num]

    if not chosen and len(query.split()) > 2:
        short_q = " ".join(query.split()[:2])
        print(f"   Retrying with: '{short_q}'")
        try:
            r2 = requests.get("https://freesound.org/apiv2/search/text/", params={
                "query":     short_q,
                "fields":    "id,name,download,duration,license,tags,avg_rating,num_ratings,num_downloads",
                "filter":    solr_filter,
                "sort":      "rating_desc",
                "page_size": 15,
                "page":      1,
            }, headers={"Authorization": f"Bearer {token}"}, timeout=30)
            if r2.status_code == 200:
                results2 = r2.json().get("results", [])
                chosen   = [s for s in results2
                            if not ({t.lower() for t in s.get("tags", [])} & BAD_TAGS)
                            and not has_bad_content(s.get("name", ""))][:num]
                print(f"   -> {len(chosen)} found with short query")
        except Exception as e:
            print(f"   Short query also failed: {e}")

    if not chosen:
        raise RuntimeError(f"Freesound OAuth: no sounds for '{query}'")
    print(f"   -> {len(chosen)} selected total")
    return chosen


def freesound_oauth_download(sound, folder="audio_tmp"):
    os.makedirs(folder, exist_ok=True)
    sound_id = sound["id"]
    path     = os.path.join(folder, f"fs_full_{sound_id}.mp3")
    if os.path.exists(path):
        return path

    token        = get_freesound_token()
    download_url = f"https://freesound.org/apiv2/sounds/{sound_id}/download/"

    print(f"   Downloading full: {sound.get('name','')[:45]} ({sound.get('duration',0):.0f}s)")
    r = requests.get(download_url,
                     headers={"Authorization": f"Bearer {token}"},
                     timeout=120, stream=True)
    r.raise_for_status()
    with open(path, "wb") as f:
        for chunk in r.iter_content(32768):
            f.write(chunk)
    time.sleep(0.3)
    return path


def fetch_freesound_oauth(query, num=10):
    sounds = freesound_oauth_search(query, num=num)
    if not sounds:
        raise RuntimeError(f"Freesound OAuth: no sounds for '{query}'")
    files = [freesound_oauth_download(s) for s in sounds]
    files = [f for f in files if f]
    if not files:
        raise RuntimeError("Freesound OAuth: download failed")
    return load_segments(files, channels=2)


# ══════════════════════════════════════════════════════════
# PIXABAY AUDIO — fallback ambient source
# Only /api/sounds/ — /api/videos/ removed (vocal contamination)
# ══════════════════════════════════════════════════════════
def fetch_pixabay_audio(query, num=10):
    if not PIXABAY_KEY:
        raise ValueError("PIXABAY_API_KEY not set")
    print(f"   [Pixabay Audio] '{query}'")

    hits = []
    try:
        r = requests.get("https://pixabay.com/api/sounds/", params={
            "key": PIXABAY_KEY, "q": query, "per_page": num * 2,
        }, timeout=30)
        if r.status_code == 200:
            hits = r.json().get("hits", [])
            print(f"   -> {len(hits)} found (pre-filter)")
    except Exception as e:
        raise RuntimeError(f"Pixabay sounds endpoint failed: {e}")

    if not hits:
        raise RuntimeError(f"Pixabay: no sounds for '{query}'")

    clean_hits = []
    for hit in hits:
        title = (hit.get("title") or hit.get("description") or "").lower()
        tags  = hit.get("tags", "").lower()
        combined = title + " " + tags
        tag_set  = {t.strip() for t in combined.replace(",", " ").split()}
        if tag_set & BAD_TAGS:
            print(f"   Skipped (bad tags): {title[:40]}")
            continue
        if has_bad_content(title):
            print(f"   Skipped (bad title): {title[:40]}")
            continue
        clean_hits.append(hit)

    print(f"   -> {len(clean_hits)} after vocal filter")
    if not clean_hits:
        raise RuntimeError(f"Pixabay: all results filtered for '{query}'")

    os.makedirs("audio_tmp", exist_ok=True)
    files = []
    random.shuffle(clean_hits)
    for hit in clean_hits[:num]:
        url = hit.get("audio") or hit.get("audioURL")
        if not url:
            for k, v in hit.items():
                if isinstance(v, str) and v.endswith(".mp3"):
                    url = v
                    break
        if not url:
            continue
        if has_bad_content(url):
            continue
        path = os.path.join("audio_tmp", f"pb_{hit['id']}.mp3")
        if not os.path.exists(path):
            r2 = requests.get(url, timeout=60)
            r2.raise_for_status()
            with open(path, "wb") as f:
                f.write(r2.content)
            time.sleep(0.3)
        files.append(path)

    if not files:
        raise RuntimeError("Pixabay: download failed after filtering")
    return load_segments(files, channels=2)


# ══════════════════════════════════════════════════════════
# JAMENDO — jazz instrumental (primary jazz source)
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
                "offset":            random.randint(0, 50),
            }, timeout=30)
            r.raise_for_status()
            results = r.json().get("results", [])
            print(f"   -> {len(results)} tracks")
            if not results:
                continue
            random.shuffle(results)
            os.makedirs("audio_tmp", exist_ok=True)
            files = []
            for t in results[:10]:
                url = t.get("audio")
                if not url:
                    continue
                if has_bad_content(t.get("name", "")):
                    continue
                path = os.path.join("audio_tmp", f"jm_{t['id']}.mp3")
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
def fetch_ccmixter(query="jazz instrumental", num=10):
    print(f"   [ccMixter] '{query}'")
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
    os.makedirs("audio_tmp", exist_ok=True)
    files = []
    for t in results[:8]:
        if has_bad_content(t.get("upload_name", "")):
            continue
        for fdata in t.get("files", []):
            url = fdata.get("download_url") or fdata.get("file_page_url")
            if url and url.endswith(".mp3") and not has_bad_content(url):
                tid  = str(t.get("upload_id", random.randint(1000, 9999)))
                path = os.path.join("audio_tmp", f"cc_{tid}.mp3")
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


# ══════════════════════════════════════════════════════════
# NUMPY — focus noise (locally generated — always clean)
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
    n   = int(SAMPLE_RATE * duration_ms / 1000)
    rng = np.random.default_rng(int(time.time() * 1000) % 999999)
    L   = np.clip(rng.normal(0, 0.15, n), -1, 1)
    R   = np.clip(rng.normal(0, 0.15, n), -1, 1)
    stereo = np.column_stack([(L * 32767).astype(np.int16),
                               (R * 32767).astype(np.int16)]).flatten()
    return AudioSegment(stereo.tobytes(), frame_rate=SAMPLE_RATE, sample_width=2, channels=2)

def generate_pink_noise(duration_ms):
    import numpy as np
    n = int(SAMPLE_RATE * duration_ms / 1000)
    def _pink():
        f        = np.fft.rfftfreq(n, d=1/SAMPLE_RATE)
        f[0]     = 1
        power    = 1 / np.sqrt(f); power[0] = 0
        phase    = np.random.uniform(0, 2 * np.pi, len(f))
        p        = np.fft.irfft(power * np.exp(1j * phase), n=n)
        p       /= (np.max(np.abs(p)) + 1e-8)
        return (p * 0.5 * 32767).astype(np.int16)
    stereo = np.column_stack([_pink(), _pink()]).flatten()
    return AudioSegment(stereo.tobytes(), frame_rate=SAMPLE_RATE, sample_width=2, channels=2)

def build_noise(noise_type, duration_hours):
    print(f"   Generating {noise_type} noise ({duration_hours}h)...")
    block_ms  = 10 * 60 * 1000
    target_ms = duration_hours * 3600 * 1000
    n_blocks  = (target_ms // block_ms) + 2
    gen = {"white": generate_white_noise,
           "brown": generate_brown_noise,
           "pink":  generate_pink_noise}
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
def rms_normalize(seg, target_dbrms=-20.0):
    diff = target_dbrms - seg.dBFS
    if abs(diff) > 1:
        return seg + diff
    return seg


def apply_haas_stereo(seg, delay_ms=18):
    if seg.channels == 2:
        return seg
    try:
        import numpy as np
        samples   = np.array(seg.get_array_of_samples(), dtype=np.float32)
        delay_smp = int(seg.frame_rate * delay_ms / 1000)
        L         = samples.copy()
        R         = np.roll(samples, delay_smp)
        R[:delay_smp] = 0
        stereo    = np.column_stack([L, R]).flatten().astype(np.int16)
        return AudioSegment(stereo.tobytes(), frame_rate=seg.frame_rate,
                            sample_width=2, channels=2)
    except Exception:
        return seg.set_channels(2)


def apply_eq(seg, eq_type="natural"):
    if eq_type != "high_cut":
        return seg
    try:
        import numpy as np
        samples    = np.array(seg.get_array_of_samples(), dtype=np.float32)
        channels   = seg.channels
        frame_rate = seg.frame_rate

        if channels == 2:
            samples = samples.reshape(-1, 2)

        def gentle_highshelf_cut(ch_samples):
            alpha  = 0.85
            out    = np.zeros_like(ch_samples)
            out[0] = ch_samples[0]
            for i in range(1, len(ch_samples)):
                out[i] = alpha * out[i-1] + (1 - alpha) * ch_samples[i]
            return out

        if channels == 2:
            processed = np.column_stack([
                gentle_highshelf_cut(samples[:, 0]),
                gentle_highshelf_cut(samples[:, 1]),
            ]).flatten()
        else:
            processed = gentle_highshelf_cut(samples)

        processed = np.clip(processed, -32767, 32767).astype(np.int16)
        return AudioSegment(processed.tobytes(), frame_rate=frame_rate,
                            sample_width=2, channels=channels)
    except Exception as e:
        print(f"   EQ skipped: {e}")
        return seg


def load_segments(files, channels=2):
    segments = []
    for f in files:
        try:
            seg = AudioSegment.from_mp3(f)
            seg = seg.set_frame_rate(SAMPLE_RATE)
            seg = rms_normalize(seg, target_dbrms=-20.0)
            if seg.channels == 1:
                seg = apply_haas_stereo(seg)
            else:
                seg = seg.set_channels(2)
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
    target_ms = duration_hours * 3600 * 1000
    random.shuffle(segments)
    combined  = AudioSegment.empty()
    i = 0
    while len(combined) < target_ms:
        seg            = segments[i % len(segments)]
        safe_crossfade = min(CROSSFADE_MS, len(seg) // 4)
        combined       = combined.append(seg, crossfade=safe_crossfade) \
                         if len(combined) > 0 else combined + seg
        i += 1
        if i % 5 == 0:
            print(f"   {min(100, len(combined)/target_ms*100):.0f}% "
                  f"({len(combined)//60000}min)")
    return combined[:target_ms]


def mix_layer(base, layer_segs, db_reduction, duration_hours):
    try:
        layer = loop_to_duration(layer_segs, duration_hours)
        layer = rms_normalize(layer) + db_reduction

        if len(layer) > 60000:
            offset = random.randint(0, len(layer) // 3)
            layer  = layer[offset:] + layer[:offset]

        if base.channels != layer.channels:
            layer = layer.set_channels(base.channels)

        result = base.overlay(layer)
        print(f"   Layer mixed at {db_reduction}dB")
        return result
    except Exception as e:
        print(f"   Layer skipped: {e}")
        return base


def finalize_audio(combined, output="output_audio.mp3", bitrate="128k"):
    print("\n   Finalizing audio...")
    combined = combined.fade_in(FADE_IN_MS).fade_out(FADE_OUT_MS)
    combined = rms_normalize(combined, target_dbrms=TARGET_LUFS)
    combined = combined.set_frame_rate(SAMPLE_RATE)
    combined.export(output, format="mp3", bitrate=bitrate,
                    tags={"artist": "Nocturne Noise",
                          "album":  "Nocturne Noise Collection"})
    mb = os.path.getsize(output) / (1024 * 1024)
    print(f"   Done: {output} ({mb:.0f}MB, {len(combined)/3600000:.1f}h, {bitrate})")
    return output


def cleanup_tmp():
    for f in glob.glob("audio_tmp/*.mp3"):
        try:
            os.remove(f)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════
# SOURCE CASCADES
# Freesound OAuth (primary) → Pixabay sounds (fallback)
# Internet Archive removed
# ══════════════════════════════════════════════════════════
def fetch_ambient(query):
    """Freesound OAuth (primary) → Pixabay sounds (fallback)"""
    for name, fn, args in [
        ("Freesound OAuth", fetch_freesound_oauth, (query,)),
        ("Pixabay Audio",   fetch_pixabay_audio,   (query,)),
    ]:
        try:
            print(f"\n   Trying {name}...")
            return fn(*args)
        except Exception as e:
            print(f"   {name} failed: {e}")
    raise RuntimeError(f"All ambient sources failed for '{query}'")


def fetch_jazz(tags):
    """Jamendo → ccMixter → Freesound OAuth"""
    for name, fn, args in [
        ("Jamendo",         fetch_jamendo,         (tags,)),
        ("ccMixter",        fetch_ccmixter,        ("jazz instrumental",)),
        ("Freesound OAuth", fetch_freesound_oauth, ("jazz piano soft instrumental",)),
    ]:
        try:
            print(f"\n   Trying {name}...")
            return fn(*args)
        except Exception as e:
            print(f"   {name} failed: {e}")
    raise RuntimeError("All jazz sources failed")


# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════
def main():
    meta_files = sorted(glob.glob("metadata_*.json"),
                        key=os.path.getmtime, reverse=True)
    if not meta_files:
        raise FileNotFoundError("Run step1_metadata.py first")

    with open(meta_files[0]) as f:
        metadata = json.load(f)

    category   = metadata["category"]
    duration   = metadata["duration_hours"]
    theme_data = metadata.get("theme_data", {})
    recipe     = SOUND_RECIPES.get(category, {})
    eq_type    = recipe.get("eq", "natural")

    print(f"\nGenerating audio: {metadata['theme']} ({duration}h)")
    print(f"Category: {category} | EQ: {eq_type}")

    # ── Focus noise ────────────────────────────────────────
    if category == "focus_noise":
        noise_type = theme_data.get("noise_type", "brown")
        combined   = build_noise(noise_type, duration)
        combined   = apply_eq(combined, eq_type)

        for layer in recipe.get("layers", []):
            query = random.choice(layer["queries"])
            try:
                layer_segs = fetch_ambient(query)
                combined   = mix_layer(combined, layer_segs,
                                       layer["db_reduction"], duration)
            except Exception as e:
                print(f"   Focus layer skipped: {e}")
        bitrate = "128k"

    # ── Jazz ───────────────────────────────────────────────
    elif category == "jazz":
        jazz_tags = recipe.get("primary_jamendo_tags", ["jazz"])
        tags      = random.choice(jazz_tags)
        print(f"   Jazz tag: '{tags}'")

        primary  = fetch_jazz(tags)
        combined = loop_to_duration(primary, duration)
        combined = apply_eq(combined, eq_type)

        for layer in recipe.get("layers", []):
            query = random.choice(layer["queries"])
            try:
                layer_segs = fetch_ambient(query)
                combined   = mix_layer(combined, layer_segs,
                                       layer["db_reduction"], duration)
            except Exception as e:
                print(f"   Jazz layer skipped: {e}")
        bitrate = "192k"

    # ── Ambient ────────────────────────────────────────────
    else:
        primary_queries = recipe.get("primary",
                          [theme_data.get("query", metadata["theme"])])
        primary_query   = random.choice(primary_queries)
        print(f"\n   Primary query: '{primary_query}'")

        primary_segs = fetch_ambient(primary_query)
        combined     = loop_to_duration(primary_segs, duration)
        combined     = apply_eq(combined, eq_type)

        for layer in recipe.get("layers", []):
            query = random.choice(layer["queries"])
            print(f"\n   Adding layer: '{query}'")
            try:
                layer_segs = fetch_ambient(query)
                combined   = mix_layer(combined, layer_segs,
                                       layer["db_reduction"], duration)
            except Exception as e:
                print(f"   Layer skipped: {e}")
        bitrate = "128k"

    finalize_audio(combined, "output_audio.mp3", bitrate=bitrate)
    cleanup_tmp()


if __name__ == "__main__":
    main()
