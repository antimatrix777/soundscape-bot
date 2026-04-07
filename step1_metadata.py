"""
STEP 1 — Metadata Generator (3-provider cascade)
Providers: Groq → Mistral → Gemini → fallback
All content in English for maximum CPM reach.

SEO STRATEGY: Hybrid titles — keyword cluster FIRST for search discoverability,
cinematic line SECOND for brand identity and CTR.
Formula: "[SEO Keyword] • [Cinematic Line]"

FIXES vs previous version:
  - Title separator unified: prompt now correctly uses • (bullet) to match
    FALLBACK_TITLES format — was using | (pipe) causing branding inconsistency
  - mark_theme_used: reset now saves [] instead of [theme_name], preventing
    the last used theme from being immediately re-picked after a full cycle
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
        {"theme": "thunderstorm with heavy lightning",  "query": "thunderstorm lightning",  "pexels": "lightning storm night"},
        {"theme": "rolling thunder in the distance",    "query": "rolling thunder distant", "pexels": "dark storm clouds"},
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
    "lofi": [
        {"theme": "lofi beats for late night studying",    "query": "lofi study beats chill",         "tags": "lofi",        "pexels": "desk lamp night study"},
        {"theme": "lofi chill morning vibes",             "query": "lofi morning chill relaxing",    "tags": "lofi chill",  "pexels": "morning window sunlight"},
        {"theme": "rainy lofi hip hop",                   "query": "lofi hip hop rain chill",        "tags": "lofi",        "pexels": "rain window cozy desk"},
        {"theme": "lofi cafe beats afternoon",            "query": "lofi cafe chill beats",          "tags": "lofi cafe",   "pexels": "cozy cafe afternoon"},
        {"theme": "sleepy lofi beats for relaxation",     "query": "lofi sleep relax calm",          "tags": "lofi sleep",  "pexels": "bedroom night calm"},
        {"theme": "lofi jazz hop evening",                "query": "lofi jazz hop instrumental",     "tags": "lofi jazz",   "pexels": "vinyl record player"},
        {"theme": "nostalgic lofi beats sunset",          "query": "lofi nostalgic sunset chill",    "tags": "lofi",        "pexels": "sunset window golden"},
        {"theme": "lofi beats cozy winter night",         "query": "lofi winter cozy beats",         "tags": "lofi winter", "pexels": "snow window night cozy"},
    ],
}

# ─────────────────────────────────────────────────────────
# SEO KEYWORD CLUSTERS
# ─────────────────────────────────────────────────────────
KEYWORD_CLUSTERS = {
    "rain": [
        "Rain Sounds for Sleep",
        "Rainy Night Ambience",
        "Heavy Rain Sounds",
        "Rain Sounds",
        "Relaxing Rain",
        "Thunderstorm Sounds",
    ],
    "jazz": [
        "Late Night Jazz",
        "Smooth Jazz",
        "Jazz Piano",
        "Jazz for Studying",
        "Relaxing Jazz Music",
    ],
    "lofi": [
        "Lofi Beats",
        "Lofi Hip Hop",
        "Lofi Music for Studying",
        "Chill Lofi Beats",
        "Lofi Chill Music",
    ],
}

USE_CASE_TAGS = {
    "rain":  ["rain sounds for sleep", "rain for studying", "rain to fall asleep",
              "rain for anxiety", "rain sounds 2 hours", "rain sounds 3 hours",
              "thunderstorm sounds for sleep", "thunder and rain"],
    "jazz":  ["jazz for studying", "jazz for working", "jazz for sleep",
              "jazz background music", "jazz focus music", "jazz 2 hours",
              "jazz 3 hours", "smooth jazz for studying"],
    "lofi":  ["lofi for studying", "lofi for sleep", "lofi beats to relax",
              "lofi hip hop study", "lofi chill beats", "lofi 2 hours",
              "lofi 3 hours", "lofi music for work"],
}

# ─────────────────────────────────────────────────────────
# SERIES COUNTER
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
# USED THEMES TRACKER
# FIX: reset now saves [] instead of [theme_name] — prevents the last
#      used theme from being immediately excluded on the next full cycle
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
    # FIX: was `used = [theme_name]` — kept the just-used theme as the only
    # "used" entry, meaning it could be re-picked immediately after reset.
    # Correct behavior: clear fully so all themes are available next cycle.
    if len(used) >= len(all_themes):
        used = []
    with open(USED_THEMES_FILE, "w") as f:
        json.dump(used, f)

# ─────────────────────────────────────────────────────────
# HASHTAGS PER CATEGORY
# ─────────────────────────────────────────────────────────
CATEGORY_HASHTAGS = {
    "rain":  "#nocturnoise #rainambience #sleepsounds #rainsounds #relaxingsounds #thunderstorm",
    "jazz":  "#nocturnoise #jazzambience #instrumentaljazz #smoothjazz #jazzmusic",
    "lofi":  "#nocturnoise #lofi #lofihiphop #lofibeats #chillbeats #studymusic",
}

# ─────────────────────────────────────────────────────────
# CREATIVE FALLBACK TITLES
# ─────────────────────────────────────────────────────────
FALLBACK_TITLES = {
    "rain": [
        "Rain Sounds for Sleep • It Won't Stop Raining and That's Perfect",
        "Heavy Rain Sounds • You Forgot to Close the Window",
        "Rainy Night Ambience • The Rain Started While You Were Reading",
        "Rain Sounds • A Quiet Night with Nothing to Worry About",
        "Relaxing Rain • It's Been Raining Since This Morning",
        "Thunderstorm Sounds • The Storm Arrived Without Warning",
    ],
    "jazz": [
        "Late Night Jazz • For Nobody in Particular",
        "Jazz Piano • The Last Set of the Night",
        "Smooth Jazz • The Piano Player Stayed After Closing",
        "Jazz for Studying • A Jazz Bar Somewhere in Paris",
        "Relaxing Jazz Music • One More Song Before We Go",
    ],
    "lofi": [
        "Lofi Beats • The Playlist That Never Ends",
        "Lofi Hip Hop • Late Night, Headphones On",
        "Chill Lofi Beats • You Pressed Play and Forgot the World",
        "Lofi Music for Studying • The Coffee Got Cold Hours Ago",
        "Lofi Chill Music • Sunday Morning, No Plans",
    ],
}

CATEGORY_CONTEXT = {
    "rain":  ("sleep, relaxation, and stress relief",   "rain sounds, sleep sounds, relaxing rain, thunderstorm"),
    "jazz":  ("late night focus, relaxation, and mood", "jazz music, instrumental jazz, background jazz"),
    "lofi":  ("studying, relaxation, and chill vibes",  "lofi beats, lofi hip hop, chill music, study beats"),
}

SYSTEM_PROMPT = """You are a YouTube SEO specialist for an ambient/soundscape channel called 'Nocturne Noise'.
Channel language: ENGLISH ONLY. Everything in English.
Channel promise: "The sound of wherever you want to be" — sounds for working, relaxing, before sleep, daily life.
Channel tone: intimate, present, cinematic. Like a friend who knows exactly what you need.
No clickbait. No ALL CAPS. No generic product descriptions.

SEO STRATEGY: Hybrid titles.
- Line 1 (the title): starts with a HIGH-SEARCH keyword cluster, then adds a cinematic line after a bullet (•).
- This gives you discoverability AND identity at the same time.
- The keyword cluster brings the click from search. The cinematic line creates the fan.

Respond ONLY with valid JSON — no markdown, no code fences, no extra text."""


def build_prompt(theme_data, category, duration_hours, series_num):
    audience, support_kw = CATEGORY_CONTEXT[category]
    dur_label   = f"{duration_hours} Hours"
    hashtags    = CATEGORY_HASHTAGS[category]
    kw_clusters = KEYWORD_CLUSTERS.get(category, ["Relaxing Sounds"])
    kw_examples = "\n  ".join(kw_clusters)
    use_cases   = USE_CASE_TAGS.get(category, [])
    use_case_ex = ", ".join(use_cases[:4])

    # FIX: separator is now • (bullet) in the prompt, matching FALLBACK_TITLES.
    # Previous version used | (pipe) here but • everywhere else — inconsistency
    # caused the AI to use | while fallback titles used •, breaking visual branding.
    return f"""Generate YouTube metadata for the Nocturne Noise ambient channel.

Theme: "{theme_data['theme']}"
Category: {category}
Duration: {duration_hours} hours
Series number: Vol. {series_num}
Target audience: {audience}
Keywords to weave in: {support_kw}
Channel name: Nocturne Noise
Channel URL: https://www.youtube.com/@NocturneNoise

--- TITLE RULES ---
Format: "[SEO Keyword Cluster] • [Cinematic Line]"
Max 80 chars total. Use a bullet character • to separate the two parts.

Available keyword clusters for this category (pick ONE - the most relevant):
  {kw_examples}

Cinematic line rules:
- Short, evocative, scene-setting - like a story in one line
- Intimate, second person when possible
- Specific moment, not a product category

Good full title examples:
  "Rain Sounds for Sleep • You Forgot to Close the Window"
  "Late Night Jazz • The Last Set of the Evening"
  "Coffee Shop Ambience • A Quiet Corner, Just You"
  "Brown Noise for Focus • Block Everything Out"
  "Forest Sounds • Somewhere Far from Everything"
  "Tokyo Night Ambience • 3AM and the City Is Still Breathing"

Bad title examples:
  "A quiet corner of the jazz club long after everyone's gone" (no SEO keyword)
  "RELAXING RAIN SOUNDS 3 HOURS" (no identity)
  "Heavy Rain Ambience for Sleep" (no cinematic hook)
  "Rain Sounds | You Forgot to Close the Window" (wrong separator — must use •, not |)

--- DESCRIPTION RULES ---
Total: 500-700 chars.

IMPORTANT: The description is a single JSON string. Use \\n for line breaks, never raw newlines.

Structure (in this exact order):
1. HOOK (2 sentences): Second-person cinematic sentences placing the listener in the scene. Example: "You opened the window a few minutes ago. The rain started softly. Now it won't stop, and you don't want it to."
2. USE-CASE LINE: "Perfect for: studying, working, falling asleep, unwinding after a long day."
3. KEYWORD LINE: Natural sentence with duration and theme. Example: "{duration_hours} hours of uninterrupted {theme_data['theme']}."
4. TIMESTAMPS: "0:00 Intro\\n0:30 {theme_data['theme'].title()}\\n[end time] Fade out"
5. CTA: "New sounds twice a week: https://www.youtube.com/@NocturneNoise"
6. HASHTAGS: {hashtags}

--- TAGS RULES ---
Generate exactly 25 tags as a JSON array of strings.
- All lowercase, no hashtags, no special characters
- Each tag is a standalone phrase - NO commas inside a tag
- MUST include at least 2 duration-based tags: "{duration_hours} hour {category}", "{duration_hours} hours of {theme_data['theme'].split()[0]}", etc.
- MUST include use-case tags like: {use_case_ex}
- MUST include "nocturne noise" as one tag
- Mix: exact match, broad, long-tail

--- THUMBNAIL TEXT RULES ---
- Max 4 words, warm, readable, example: '{dur_label} {theme_data['theme'].split()[0].title()}'
- Should match the SEO keyword cluster you chose for the title

Return ONLY this JSON:
{{
  "title": "...",
  "description": "...",
  "tags": ["tag one", "tag two", "tag three"],
  "thumbnail_text": "max 4 words",
  "youtube_category_id": "10"
}}"""


def clean_json(raw: str) -> dict:
    """
    Robust JSON cleaner. Handles:
    - Code fences
    - Raw (unescaped) newlines/tabs inside JSON strings causing 'Invalid control character'
    - BOM characters
    """
    raw = raw.strip().lstrip('\ufeff')
    raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    def escape_string_internals(text):
        result  = []
        in_str  = False
        escaped = False
        for ch in text:
            if escaped:
                result.append(ch)
                escaped = False
            elif ch == '\\' and in_str:
                result.append(ch)
                escaped = True
            elif ch == '"':
                in_str = not in_str
                result.append(ch)
            elif in_str and ch == '\n':
                result.append('\\n')
            elif in_str and ch == '\r':
                result.append('\\r')
            elif in_str and ch == '\t':
                result.append('\\t')
            elif in_str and ord(ch) < 32:
                result.append(f'\\u{ord(ch):04x}')
            else:
                result.append(ch)
        return ''.join(result)

    try:
        return json.loads(escape_string_internals(raw))
    except json.JSONDecodeError:
        pass

    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m:
        try:
            return json.loads(escape_string_internals(m.group()))
        except Exception:
            pass

    raise ValueError(f"Invalid JSON after all cleanup attempts:\n{raw[:300]}")


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
              "temperature": 0.7, "max_tokens": 1200},
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
              "temperature": 0.7, "max_tokens": 1200},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def call_gemini(prompt):
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key: raise ValueError("GEMINI_API_KEY not set")
    try:
        from google import genai
        client   = genai.Client(api_key=key)
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"{SYSTEM_PROMPT}\n\n{prompt}",
        )
        return response.text
    except ImportError:
        import google.generativeai as genai_old
        genai_old.configure(api_key=key)
        model    = genai_old.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(f"{SYSTEM_PROMPT}\n\n{prompt}")
        return response.text


PROVIDERS = [
    ("Groq Llama 3.3 70B", call_groq),
    ("Mistral Small",       call_mistral),
    ("Gemini 2.0 Flash",    call_gemini),
]


def call_ai_cascade(prompt):
    for name, fn in PROVIDERS:
        try:
            print(f"   Trying: {name}...")
            raw    = fn(prompt)
            result = clean_json(raw)
            tags   = result.get("tags", [])
            if tags and tags[0] in ("30 tags", "tag one", "lowercase"):
                raise ValueError("Provider returned example tags instead of real ones")
            print(f"   OK: {name}")
            return result
        except Exception as e:
            print(f"   Failed {name}: {e}")
    print("   All providers failed. Using fallback.")
    return None


def build_fallback_metadata(theme_data, category, duration_hours, series_num):
    dur      = f"{duration_hours} Hours"
    titles   = FALLBACK_TITLES.get(category, ["Relaxing Sounds • A Quiet Place to Rest"])
    title    = random.choice(titles)
    hashtags = CATEGORY_HASHTAGS[category]
    kw       = random.choice(KEYWORD_CLUSTERS.get(category, ["Relaxing Sounds"]))
    use_tags = USE_CASE_TAGS.get(category, [])

    base_tags = [
        "relaxing sounds", "sleep sounds", "ambient music",
        "study music", "focus music", "lofi", "calm music",
        "soundscape", "sleep aid", "background music",
        "nature sounds", "stress relief", "chillout",
        "work from home", "deep focus", "concentration",
        "peaceful", "relax", "ambient noise", "nocturne noise",
        f"{duration_hours} hour ambient", f"{duration_hours} hours relaxing",
    ]
    all_tags = list(dict.fromkeys(use_tags[:6] + base_tags))[:25]

    return {
        "title": title[:80],
        "description": (
            f"Close the door, put this on, and let everything else disappear.\n"
            f"{duration_hours} hours of {theme_data['theme']}. No interruptions.\n\n"
            f"🎧 Perfect for: studying, working, falling asleep, unwinding.\n"
            f"{duration_hours} hours of uninterrupted {theme_data['theme']}.\n\n"
            f"0:00 Intro\n0:30 {theme_data['theme'].title()}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👍 If this helped, leave a like — it really helps.\n"
            f"🔔 New sounds twice a week → https://www.youtube.com/@NocturneNoise\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{hashtags}"
        ),
        "tags": all_tags,
        "thumbnail_text":      f"{dur} • {theme_data['theme'].split()[0].title()}",
        "youtube_category_id": "10",
        "_fallback":           True,
    }


def pick_theme(theme_override=None, category=None):
    if category and category not in THEMES:
        raise ValueError(f"Invalid category. Use: {list(THEMES.keys())}")

    used = get_used_themes()

    if category:
        cat    = category
        themes = THEMES[cat]
    else:
        all_themes = [(t, cat) for cat, themes in THEMES.items() for t in themes]
        unused     = [(t, c) for t, c in all_themes if t["theme"] not in used]
        if not unused:
            unused = all_themes
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
