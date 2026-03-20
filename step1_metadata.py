"""
STEP 1 — Metadata Generator (3-provider cascade)
Providers: Groq → Mistral → Gemini → fallback
All content in English for maximum CPM reach.
"""
import json, os, random, argparse, re
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DURATIONS = [2, 3, 4]

THEMES = {
    "rain": [
        {"theme": "heavy rain on window at night",   "query": "heavy rain window",      "pexels": "rain window night"},
        {"theme": "gentle rain in forest",           "query": "gentle rain forest",     "pexels": "forest rain"},
        {"theme": "distant thunderstorm with rain",  "query": "distant thunder rain",   "pexels": "storm clouds rain"},
        {"theme": "rain on rooftop",                 "query": "rain rooftop",           "pexels": "rain rooftop"},
        {"theme": "rain on car roof while parked",   "query": "rain car",               "pexels": "rain car window"},
        {"theme": "light drizzle at night city",     "query": "light rain city night",  "pexels": "city rain night"},
        {"theme": "rain on tent in forest",          "query": "rain tent camping",      "pexels": "tent forest rain"},
        {"theme": "rain on lake surface",            "query": "rain lake water",        "pexels": "rain lake"},
    ],
    "nature": [
        {"theme": "soft forest ambience with gentle birds",  "query": "forest birds soft ambience",  "pexels": "misty forest morning"},
        {"theme": "ocean waves on sandy beach",              "query": "ocean waves beach soft",      "pexels": "ocean waves sandy beach"},
        {"theme": "gentle river flowing through forest",     "query": "river stream forest",         "pexels": "river forest"},
        {"theme": "distant waterfall in forest",             "query": "waterfall distant forest",    "pexels": "waterfall forest"},
        {"theme": "wind through pine trees softly",          "query": "wind pine trees gentle",      "pexels": "pine forest wind"},
        {"theme": "calm birds singing at dawn",              "query": "birds dawn morning gentle",   "pexels": "sunrise forest birds"},
        {"theme": "mountain stream babbling",                "query": "mountain stream babbling",    "pexels": "mountain stream"},
        {"theme": "summer meadow soft breeze",               "query": "meadow breeze summer",        "pexels": "green meadow summer"},
    ],
    "cozy": [
        {"theme": "cozy coffee shop ambience morning",     "query": "coffee shop cafe ambience",     "pexels": "cozy coffee shop"},
        {"theme": "fireplace crackling cozy indoors",      "query": "fireplace crackling wood fire", "pexels": "fireplace cozy"},
        {"theme": "quiet library ambience soft",           "query": "library quiet ambience",        "pexels": "cozy library books"},
        {"theme": "japanese tea house ambience",           "query": "tea house soft ambience",       "pexels": "japanese tea house"},
        {"theme": "bookstore with rain outside",           "query": "bookstore indoor ambience",     "pexels": "bookstore cozy rain"},
        {"theme": "cozy cabin during snowstorm",           "query": "cabin indoor fire snow",        "pexels": "cabin snow winter cozy"},
        {"theme": "bakery ambience early morning",         "query": "bakery morning ambience",       "pexels": "bakery morning"},
        {"theme": "rainy afternoon indoors with kettle",   "query": "indoor rain kettle soft",       "pexels": "cozy home rain"},
        {"theme": "vintage reading nook with fireplace",   "query": "fireplace crackling gentle",    "pexels": "reading nook vintage books"},
        {"theme": "cozy bed and breakfast morning",        "query": "morning indoor soft ambience",  "pexels": "cozy morning bedroom"},
    ],
    "jazz": [
        {"theme": "late night jazz cafe",              "query": "jazz cafe night instrumental",    "tags": "jazz",        "pexels": "jazz cafe night"},
        {"theme": "smooth piano jazz for relaxation",  "query": "smooth jazz piano instrumental",  "tags": "piano jazz",  "pexels": "grand piano low light"},
        {"theme": "soft jazz with gentle rain",        "query": "soft jazz instrumental mellow",   "tags": "jazz",        "pexels": "jazz rain window"},
        {"theme": "bossa nova instrumental morning",   "query": "bossa nova instrumental",         "tags": "bossanova",   "pexels": "coffee morning sunlight"},
        {"theme": "mellow jazz guitar evening",        "query": "jazz guitar mellow instrumental", "tags": "jazz guitar", "pexels": "guitar low light evening"},
        {"theme": "slow jazz piano bar night",         "query": "jazz piano bar slow",             "tags": "jazz piano",  "pexels": "piano bar night"},
        {"theme": "peaceful jazz trio afternoon",      "query": "jazz trio acoustic peaceful",     "tags": "jazz",        "pexels": "jazz musician"},
        {"theme": "winter jazz by the fireplace",      "query": "jazz warm cozy instrumental",     "tags": "jazz",        "pexels": "fireplace winter cozy"},
    ],
    "focus_noise": [
        {"theme": "brown noise for deep focus",        "noise_type": "brown", "pexels": "minimalist desk study"},
        {"theme": "white noise for concentration",     "noise_type": "white", "pexels": "clean minimal workspace"},
        {"theme": "pink noise for studying",           "noise_type": "pink",  "pexels": "student studying calm"},
        {"theme": "soft brown noise for sleep",        "noise_type": "brown", "pexels": "bedroom night peaceful"},
        {"theme": "gentle white noise for baby sleep", "noise_type": "white", "pexels": "peaceful nursery soft light"},
        {"theme": "brown noise with distant rain",     "noise_type": "brown", "pexels": "rainy window night desk"},
    ],
    "study": [
        {"theme": "late night study session with rain",  "query": "study rain indoor soft",     "pexels": "desk lamp study rain"},
        {"theme": "quiet library late at night",         "query": "library quiet night",        "pexels": "library night lamp"},
        {"theme": "morning study cafe with soft music",  "query": "cafe morning soft ambience", "pexels": "cafe morning study"},
        {"theme": "focused study room afternoon",        "query": "indoor quiet focus room",    "pexels": "study room afternoon light"},
    ],
    "urban": [
        {"theme": "rainy night in tokyo",             "query": "rain city night japan",      "pexels": "tokyo rain night"},
        {"theme": "paris cafe terrace evening",       "query": "paris cafe outdoor evening", "pexels": "paris cafe evening"},
        {"theme": "new york apartment rain at night", "query": "city rain night apartment",  "pexels": "new york apartment rain"},
        {"theme": "london evening rain street",       "query": "london rain evening street", "pexels": "london rain evening"},
    ],
}

# ─────────────────────────────────────────────────────────
# SERIES COUNTER — tracks volume per category for series titles
# ─────────────────────────────────────────────────────────
SERIES_FILE = "series_counter.json"

def get_series_number(category):
    counters = {}
    if os.path.exists(SERIES_FILE):
        try:
            with open(SERIES_FILE) as f:
                counters = json.load(f)
        except Exception:
            counters = {}
    counters[category] = counters.get(category, 0) + 1
    with open(SERIES_FILE, "w") as f:
        json.dump(counters, f)
    return counters[category]

# ─────────────────────────────────────────────────────────
# USED THEMES TRACKER — avoids repeating themes
# ─────────────────────────────────────────────────────────
USED_THEMES_FILE = "used_themes.json"

def get_used_themes():
    if os.path.exists(USED_THEMES_FILE):
        try:
            with open(USED_THEMES_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []

def mark_theme_used(theme_name):
    used = get_used_themes()
    all_themes = [t["theme"] for cat in THEMES.values() for t in cat]
    used.append(theme_name)
    # Reset when all themes have been used
    if len(used) >= len(all_themes):
        used = [theme_name]
    with open(USED_THEMES_FILE, "w") as f:
        json.dump(used, f)

# ─────────────────────────────────────────────────────────
# HASHTAGS PER CATEGORY
# ─────────────────────────────────────────────────────────
CATEGORY_HASHTAGS = {
    "rain":        "#rainysounds #sleepsounds #rainambience",
    "nature":      "#naturesounds #ambientmusic #relaxingsounds",
    "cozy":        "#cozysounds #cafeambience #lofi",
    "jazz":        "#jazzmusic #instrumentaljazz #jazzambience",
    "focus_noise": "#brownnoise #whitenoise #focusmusic",
    "study":       "#studymusic #focussounds #lofi",
    "urban":       "#cityambience #urbansounds #nightambience",
}

# ─────────────────────────────────────────────────────────
# CREATIVE FALLBACK TITLES — varied, not generic
# ─────────────────────────────────────────────────────────
FALLBACK_TITLES = {
    "rain": [
        "It's Raining Outside • {dur}",
        "Rain at 2AM • Sleep & Focus • {dur}",
        "The Rain Won't Stop • {dur} Lofi Ambience",
        "Gentle Rain All Night Long • {dur}",
    ],
    "nature": [
        "Deep in the Forest • {dur} Nature Ambience",
        "The River Never Stops • {dur}",
        "Nature at Dawn • {dur} Relaxing Ambience",
        "Somewhere in the Woods • {dur}",
    ],
    "cozy": [
        "A Corner of the Cafe • {dur}",
        "Stay In Tonight • {dur} Cozy Ambience",
        "The Fireplace is On • {dur}",
        "Quiet Evening Indoors • {dur} Cozy Sounds",
    ],
    "jazz": [
        "Late Night at the Jazz Club • {dur}",
        "One More Song • {dur} Jazz Ambience",
        "Smooth Jazz for a Slow Evening • {dur}",
        "The Piano Plays On • {dur} Jazz Lounge",
    ],
    "focus_noise": [
        "Brown Noise for Deep Work • {dur}",
        "Block Everything Out • {dur} Focus Noise",
        "Pure Concentration • {dur} Brown Noise",
        "White Noise All Night • {dur} Sleep Aid",
    ],
    "study": [
        "Late Night Study Session • {dur}",
        "Focus Mode: On • {dur} Study Ambience",
        "The Library at Midnight • {dur}",
        "One More Chapter • {dur} Study Sounds",
    ],
    "urban": [
        "Tokyo at 3AM • {dur} Night Ambience",
        "The City Never Sleeps • {dur}",
        "Rain on the Streets • {dur} Urban Sounds",
        "Night Drive • {dur} City Ambience",
    ],
}

CATEGORY_CONTEXT = {
    "rain":        ("sleep, relaxation, and stress relief",      "rain sounds, sleep sounds, relaxing rain"),
    "nature":      ("relaxation, meditation, and mindfulness",   "nature sounds, calming nature, ambient sounds"),
    "cozy":        ("relaxation, focus, and cozy comfort",       "cozy ambience, cafe sounds, background noise"),
    "jazz":        ("late night focus, relaxation, and mood",    "jazz music, instrumental jazz, background jazz"),
    "focus_noise": ("deep focus, studying, and sleep",           "brown noise, white noise, focus sounds"),
    "study":       ("studying, concentration, and productivity", "study music, focus background, lofi ambience"),
    "urban":       ("relaxation, mood, and urban comfort",       "city sounds, urban ambience, night sounds"),
}

SYSTEM_PROMPT = """You are a YouTube SEO specialist for a premium ambient/soundscape channel called 'Comfort Sounds'.
Channel language: ENGLISH ONLY. All titles, descriptions and tags must be in English.
Channel identity: warm, trustworthy, high-quality, peaceful. No clickbait, no ALL CAPS.
Respond ONLY with valid JSON — no markdown, no code fences, no extra text."""


def build_prompt(theme_data, category, duration_hours, series_num):
    audience, support_kw = CATEGORY_CONTEXT[category]
    dur_label = f"{duration_hours} Hours"
    hashtags  = CATEGORY_HASHTAGS[category]

    return f"""Generate YouTube metadata for an English-language comfort soundscape channel.

Theme: "{theme_data['theme']}"
Category: {category}
Duration: {duration_hours} hours
Series number: Vol. {series_num}
Target audience: {audience}
Keywords to weave in: {support_kw}
Channel name: Comfort Sounds
Channel URL: https://www.youtube.com/@ComfortSounds

Rules for title:
- Max 70 chars
- Include "{dur_label}"
- Include "Vol. {series_num}" at the end
- Warm, inviting tone — NOT generic
- Good example: "Heavy Rain on Window {dur_label} | Sleep & Relaxation • Vol. {series_num}"
- Bad example: "RELAXING RAIN SOUNDS {dur_label}" (too generic, ALL CAPS)

Rules for description:
- 400-500 chars total
- First 2 lines: strong hook (shown before "more")
- Include 3-4 natural keyword mentions
- Include timestamps: 0:00 Intro\n0:30 {theme_data['theme'].title()}\n[duration] Fade out
- End with: 🔔 Subscribe for new soundscapes every week.\n🎧 More sounds → https://www.youtube.com/@ComfortSounds\n{hashtags}

Rules for tags (return as JSON array of strings):
- Generate exactly 25 individual tags
- Each tag is a standalone phrase — do NOT use commas inside a tag
- All lowercase
- No hashtags, no special characters
- Mix: exact match, broad, long-tail

Return ONLY this JSON:
{{
  "title": "...",
  "description": "...",
  "tags": ["tag one", "tag two", "tag three"],
  "thumbnail_text": "max 4 words, warm, example: '{dur_label} of Rain'",
  "youtube_category_id": "10"
}}"""


def clean_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
    raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            return json.loads(m.group())
        raise ValueError(f"Invalid JSON:\n{raw[:300]}")


def call_groq(prompt):
    import requests
    key = os.environ.get("GROQ_API_KEY", "")
    if not key: raise ValueError("GROQ_API_KEY not set")
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": "llama-3.3-70b-versatile",
              "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                           {"role": "user", "content": prompt}],
              "temperature": 0.7, "max_tokens": 1000},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def call_mistral(prompt):
    import requests
    key = os.environ.get("MISTRAL_API_KEY", "")
    if not key: raise ValueError("MISTRAL_API_KEY not set")
    r = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": "mistral-small-latest",
              "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                           {"role": "user", "content": prompt}],
              "temperature": 0.7, "max_tokens": 1000},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def call_gemini(prompt):
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key: raise ValueError("GEMINI_API_KEY not set")
    import google.generativeai as genai
    genai.configure(api_key=key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content(f"{SYSTEM_PROMPT}\n\n{prompt}")
    return response.text


PROVIDERS = [
    ("Groq Llama 3.3 70B", call_groq),
    ("Mistral Small",       call_mistral),
    ("Gemini 1.5 Flash",    call_gemini),
]


def call_ai_cascade(prompt):
    for name, fn in PROVIDERS:
        try:
            print(f"   Trying: {name}...")
            raw    = fn(prompt)
            result = clean_json(raw)
            # Validate tags are actual tags, not the example strings
            tags = result.get("tags", [])
            if tags and tags[0] in ("30 tags", "tag one", "lowercase"):
                raise ValueError("Provider returned example tags instead of real ones")
            print(f"   OK: {name}")
            return result
        except Exception as e:
            print(f"   Failed {name}: {e}")
    print("   All providers failed. Using fallback.")
    return None


def build_fallback_metadata(theme_data, category, duration_hours, series_num):
    dur       = f"{duration_hours} Hours"
    titles    = FALLBACK_TITLES.get(category, ["Comfort Sounds {dur} | Relax & Focus"])
    title_tpl = random.choice(titles)
    title     = title_tpl.format(dur=dur) + f" • Vol. {series_num}"
    hashtags  = CATEGORY_HASHTAGS[category]
    return {
        "title": title[:100],
        "description": (
            f"Lose yourself in {duration_hours} hours of {theme_data['theme']}. "
            f"Perfect for sleep, deep focus, and unwinding after a long day.\n\n"
            f"0:00 Intro\n0:30 {theme_data['theme'].title()}\n\n"
            f"🔔 Subscribe for new soundscapes every week.\n"
            f"🎧 More sounds → https://www.youtube.com/@ComfortSounds\n"
            f"{hashtags}"
        ),
        "tags": [
            "relaxing sounds", "sleep sounds", "ambient music", "white noise",
            "study music", "focus music", "lofi", "calm music", "meditation",
            "soundscape", "sleep aid", "background music", "cozy vibes",
            "nature sounds", "rain sounds", "stress relief", "chillout",
            "work from home", "deep focus", "concentration", "peaceful",
            "relax", "sleep meditation", "ambient noise", "comfort sounds",
        ],
        "thumbnail_text":      f"{dur} of {theme_data['theme'].split()[0].title()}",
        "youtube_category_id": "10",
        "_fallback":           True,
    }


def pick_theme(theme_override=None, category=None):
    """Picks a theme, avoiding recently used ones."""
    if category and category not in THEMES:
        raise ValueError(f"Invalid category. Use: {list(THEMES.keys())}")

    used = get_used_themes()

    if category:
        cat    = category
        themes = THEMES[cat]
    else:
        # Pick directly from all themes (weighted by category size)
        all_themes = [(t, cat) for cat, themes in THEMES.items() for t in themes]
        unused     = [(t, c) for t, c in all_themes if t["theme"] not in used]
        if not unused:
            unused = all_themes  # reset if all used
        chosen_theme, cat = random.choice(unused)
        return chosen_theme, cat

    if theme_override:
        match = next((t for t in themes if theme_override.lower() in t["theme"].lower()), None)
        return (match or themes[0]), cat

    unused = [t for t in themes if t["theme"] not in used]
    if not unused:
        unused = themes
    return random.choice(unused), cat


def generate_metadata(theme_override=None, duration_hours=None, category=None):
    theme_data, category = pick_theme(theme_override, category)
    if not duration_hours:
        duration_hours = random.choice(DURATIONS)

    series_num = get_series_number(category)

    print(f"\nTheme: {theme_data['theme']}")
    print(f"Category: {category} | Duration: {duration_hours}h | Vol. {series_num}")

    prompt   = build_prompt(theme_data, category, duration_hours, series_num)
    metadata = call_ai_cascade(prompt)

    if metadata is None:
        metadata = build_fallback_metadata(theme_data, category, duration_hours, series_num)

    metadata["theme"]          = theme_data["theme"]
    metadata["theme_data"]     = theme_data
    metadata["category"]       = category
    metadata["duration_hours"] = duration_hours
    metadata["series_num"]     = series_num
    metadata["generated_at"]   = datetime.now().isoformat()

    # Mark theme as used
    mark_theme_used(theme_data["theme"])

    fname = f"metadata_{theme_data['theme'][:30].replace(' ','_')}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print(f"Title: {metadata.get('title','')}")
    print(f"Tags: {len(metadata.get('tags', []))} | Saved: {fname}\n")
    return metadata


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--theme",    type=str)
    p.add_argument("--category", choices=list(THEMES.keys()))
    p.add_argument("--duration", type=int, choices=DURATIONS)
    args = p.parse_args()
    generate_metadata(theme_override=args.theme, duration_hours=args.duration, category=args.category)
