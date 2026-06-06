"""
STEP 1 — Metadata Generator (Rain Sleep Channel)
Canal: Nocturne Noise — sons de chuva para dormir
Providers: Groq → Mistral → Gemini → fallback
"""

import json, os, random, argparse, re
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

DURATIONS = [2, 3, 4]

THEMES = [
    {"theme": "heavy rain on window at night",        "query": "heavy rain window night",        "pexels": "rain window night dark"},
    {"theme": "gentle rain in forest",                "query": "gentle rain forest ambience",     "pexels": "forest rain mist"},
    {"theme": "distant thunderstorm with soft rain",  "query": "distant thunder rain steady",     "pexels": "storm clouds rain dark"},
    {"theme": "rain on rooftop at night",             "query": "rain rooftop night",              "pexels": "rain rooftop night"},
    {"theme": "rain on car roof while parked",        "query": "rain car roof recording",         "pexels": "rain car window dark"},
    {"theme": "light drizzle in the city at night",   "query": "light drizzle city night",        "pexels": "city rain night wet street"},
    {"theme": "rain on a tent deep in the forest",    "query": "rain tent forest camping",        "pexels": "tent forest rain"},
    {"theme": "rain on a lake surface",               "query": "rain lake water ripples",         "pexels": "rain lake water"},
    {"theme": "thunderstorm rolling in the distance", "query": "rolling thunder rain distance",   "pexels": "dark storm horizon"},
    {"theme": "rain on a cabin roof in the mountains","query": "rain cabin mountain roof",        "pexels": "cabin rain mountain forest"},
    {"theme": "heavy rain on a metal roof",           "query": "heavy rain metal roof",           "pexels": "rain metal roof dark"},
    {"theme": "soft rain at dawn in the countryside", "query": "soft rain dawn countryside",      "pexels": "dawn countryside misty rain"},
    {"theme": "rain in a bamboo forest",              "query": "rain bamboo forest ambience",     "pexels": "bamboo forest rain"},
    {"theme": "rain on leaves in a garden",           "query": "rain leaves garden quiet",        "pexels": "garden rain drops leaves"},
    {"theme": "winter rain on a cold window",         "query": "winter rain cold window night",   "pexels": "winter rain dark window"},
]

KEYWORD_CLUSTERS = [
    "Rain Sounds for Sleep",
    "Rainy Night Ambience",
    "Heavy Rain Sounds",
    "Rain Sounds",
    "Relaxing Rain",
    "Thunderstorm Sounds for Sleep",
    "Rain and Thunder",
    "ASMR Rain",
    "Window Rain at Night",
    "Rain Sounds No Music",
    "Gentle Rain for Sleep",
    "Rain White Noise",
    "Sleeping Rain Sounds",
    "Rain Sounds to Fall Asleep",
]

USE_CASE_TAGS = [
    "rain sounds for sleep", "rain to fall asleep", "rain for deep sleep",
    "rain sounds 2 hours", "rain sounds 3 hours", "rain sounds 4 hours",
    "thunderstorm sounds for sleep", "thunder and rain for sleeping",
    "asmr rain no talking", "rain sounds no music", "window rain at night",
    "heavy rain for sleep", "rain white noise sleep", "rain sounds anxiety",
    "sleep sounds", "relaxing rain sounds",
]

HASHTAGS = "#nocturnoise #rainambience #sleepsounds #rainsounds #relaxingsounds #rainfordsleep #sleepaid"

FALLBACK_TITLES = [
    "Rain Sounds for Sleep • You Forgot to Close the Window",
    "Heavy Rain Sounds • The Rain Started While You Were Reading",
    "Rainy Night Ambience • A Quiet Night with Nothing to Worry About",
    "Rain Sounds • It's Been Raining Since This Morning",
    "Thunderstorm Sounds • The Kind of Rain You Fall Asleep To",
    "Window Rain at Night • You're Warm and the World Is Wet",
    "Rain Sounds for Sleep • The Same Rain from That December",
    "ASMR Rain • You've Heard This Rain Before",
    "Thunderstorm Sounds • The Storm Arrived Without Warning",
    "Heavy Rain Sounds • The City Disappeared Hours Ago",
    "Rain Sounds No Music • Let It All Wash Away Tonight",
    "Gentle Rain for Sleep • One Last Storm Before Morning",
    "Rain Sounds for Sleep • Nothing but the Rain and You",
    "Rainy Night Ambience • The Window Was Open All Along",
    "Heavy Rain Sounds • You Don't Have to Go Anywhere Tonight",
]

SERIES_FILE = "series_counter.json"

def get_series_number():
    counters = {}
    if os.path.exists(SERIES_FILE):
        try:
            with open(SERIES_FILE) as f:
                counters = json.load(f)
        except Exception:
            counters = {}
    counters["rain"] = counters.get("rain", 0) + 1
    with open(SERIES_FILE, "w") as f:
        json.dump(counters, f)
    return counters["rain"]

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
    used.append(theme_name)
    if len(used) >= len(THEMES):
        used = []
    with open(USED_THEMES_FILE, "w") as f:
        json.dump(used, f)

USED_TITLES_FILE = "used_titles_long.json"

def get_used_titles():
    if not os.path.exists(USED_TITLES_FILE):
        return {}
    try:
        with open(USED_TITLES_FILE) as f:
            data = json.load(f)
        cutoff = (datetime.now() - timedelta(days=90)).isoformat()
        return {t: ts for t, ts in data.items() if ts > cutoff}
    except Exception:
        return {}

def save_title(title):
    used = get_used_titles()
    used[title.lower().strip()] = datetime.now().isoformat()
    with open(USED_TITLES_FILE, "w") as f:
        json.dump(used, f, indent=2)

SYSTEM_PROMPT = """You are a YouTube SEO specialist for 'Nocturne Noise', a rain sounds sleep channel.
Channel language: ENGLISH ONLY.
Channel focus: rain sounds for sleep, relaxation, and deep rest. Nothing else.
Channel tone: intimate, calm, cinematic. Like a quiet voice in a dark room.
No clickbait. No ALL CAPS beyond the keyword cluster.

SEO STRATEGY: Hybrid titles.
Format: "[SEO Keyword Cluster] • [Cinematic Line]"
- Keyword cluster: high-search rain/sleep term, brings traffic
- Cinematic line: short, scene-setting, intimate — creates the fan

Respond ONLY with valid JSON — no markdown, no code fences, no extra text."""

def build_prompt(theme_data, duration_hours, series_num):
    dur_label = f"{duration_hours} Hours"
    kw_examples = "\n  ".join(KEYWORD_CLUSTERS)
    use_case_ex = ", ".join(USE_CASE_TAGS[:6])

    used_titles = get_used_titles()
    avoid_section = ""
    if used_titles:
        recent = list(used_titles.keys())[-8:]
        avoid_lines = "\n  ".join(f'- "{t}"' for t in recent)
        avoid_section = f"""
--- AVOID THESE RECENTLY USED TITLES ---
  {avoid_lines}
"""

    return f"""Generate YouTube metadata for the Nocturne Noise rain sleep channel.

Theme: "{theme_data['theme']}"
Duration: {duration_hours} hours
Series number: Vol. {series_num}
Channel URL: https://www.youtube.com/@NocturneNoise

--- TITLE RULES ---
Format: "[SEO Keyword Cluster] • [Cinematic Line]"
Max 80 chars total. Use • (bullet) to separate the two parts.

Available keyword clusters (pick the most relevant one):
  {kw_examples}

Cinematic line rules:
- Short, evocative, intimate — one sentence max
- Second person when possible ("You", "Your")
- Specific moment or feeling, not a product description
- Must feel unique and tied to this specific rain scene

Good title examples:
"Rain Sounds for Sleep • You Forgot to Close the Window"
"Heavy Rain Sounds • The City Disappeared Hours Ago"
"Thunderstorm Sounds for Sleep • The Storm You Slept Through"
"Window Rain at Night • Warm Bed, Cold Glass, Perfect Night"
"Rain Sounds No Music • Nothing but the Rain"

{avoid_section}

--- DESCRIPTION RULES ---
Total: 500-700 chars. Use \\n for line breaks inside the JSON string.

Structure (exact order):
1. HOOK (2-3 sentences): Place the listener in the rain scene. Second person. Cinematic.
2. CTA: "🔔 New rain sounds every week — subscribe → https://www.youtube.com/@NocturneNoise"
3. USE-CASE: "Perfect for: falling asleep, deep rest, anxiety relief, studying."
4. KEYWORD LINE: "{duration_hours} hours of uninterrupted {theme_data['theme']}."
5. TIMESTAMPS: "0:00 Intro\\n0:30 {theme_data['theme'].title()}\\n{duration_hours}:00:00 Fade out"
6. CTA 2: "👍 If this helped you sleep, leave a like — it really helps the channel."
7. HASHTAGS: {HASHTAGS}

--- TAGS RULES ---
Generate 12-18 tags as a JSON array of lowercase strings.
- No hashtags, no special characters, no commas inside a tag
- MUST include: "rain sounds for sleep", "rain sounds", "sleep sounds", "nocturne noise"
- MUST include 2 duration tags: "{duration_hours} hour rain sounds", "{duration_hours} hours rain"
- Include long-tail: {use_case_ex}
- All tags must be truthful to the rain sleep audio

--- THUMBNAIL TEXT ---
Max 4 words, readable, warm. Example: '{dur_label} Rain Sounds'

Return ONLY this JSON:
{{
  "title": "...",
  "description": "...",
  "tags": ["tag one", "tag two"],
  "thumbnail_text": "max 4 words",
  "youtube_category_id": "10"
}}"""

def clean_json(raw: str) -> dict:
    raw = raw.strip().lstrip('\ufeff')
    raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    def escape_internals(text):
        result = []
        in_str = False
        escaped = False
        for ch in text:
            if escaped:
                result.append(ch); escaped = False
            elif ch == '\\' and in_str:
                result.append(ch); escaped = True
            elif ch == '"':
                in_str = not in_str; result.append(ch)
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
        return json.loads(escape_internals(raw))
    except json.JSONDecodeError:
        pass

    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m:
        try:
            return json.loads(escape_internals(m.group()))
        except Exception:
            pass

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
              "temperature": 0.8, "max_tokens": 1200},
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
              "temperature": 0.8, "max_tokens": 1200},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

def call_gemini(prompt):
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key: raise ValueError("GEMINI_API_KEY not set")
    try:
        from google import genai
        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"{SYSTEM_PROMPT}\n\n{prompt}",
        )
        return response.text
    except ImportError:
        import google.generativeai as genai_old
        genai_old.configure(api_key=key)
        model = genai_old.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(f"{SYSTEM_PROMPT}\n\n{prompt}")
        return response.text

PROVIDERS = [
    ("Groq Llama 3.3 70B", call_groq),
    ("Mistral Small", call_mistral),
    ("Gemini 2.0 Flash", call_gemini),
]

def call_ai_cascade(prompt):
    for name, fn in PROVIDERS:
        try:
            print(f"  Trying: {name}...")
            raw = fn(prompt)
            result = clean_json(raw)
            tags = result.get("tags", [])
            if tags and tags[0] in ("30 tags", "tag one", "lowercase"):
                raise ValueError("Provider returned example tags")
            print(f"  OK: {name}")
            return result
        except Exception as e:
            print(f"  Failed {name}: {e}")
    print("  All providers failed. Using fallback.")
    return None

def build_fallback_metadata(theme_data, duration_hours, series_num):
    used_titles = get_used_titles()
    available = [t for t in FALLBACK_TITLES if t.lower().strip() not in used_titles]
    if not available:
        available = FALLBACK_TITLES
    title = random.choice(available)

    tags = list(dict.fromkeys([
        "rain sounds for sleep", "rain sounds", "sleep sounds", "heavy rain sounds",
        "rainy night ambience", "rain white noise", "rain sounds no music",
        "thunderstorm sounds for sleep", "rain to fall asleep", "asmr rain",
        "window rain at night", "relaxing rain sounds", "rain for anxiety",
        f"{duration_hours} hour rain sounds", f"{duration_hours} hours rain",
        "nocturne noise", "sleep aid", "deep sleep sounds",
    ]))[:18]

    return {
        "title": title[:80],
        "description": (
            f"The rain started while you weren't paying attention.\n"
            f"Now it's everywhere. And it's exactly what you needed.\n\n"
            f"🔔 New rain sounds every week — subscribe → https://www.youtube.com/@NocturneNoise\n\n"
            f"Perfect for: falling asleep, deep rest, anxiety relief, studying.\n"
            f"{duration_hours} hours of uninterrupted {theme_data['theme']}.\n\n"
            f"0:00 Intro\n0:30 {theme_data['theme'].title()}\n\n"
            f"👍 If this helped you sleep, leave a like — it really helps the channel.\n"
            f"{HASHTAGS}"
        ),
        "tags": tags,
        "thumbnail_text": f"{duration_hours} Hours Rain",
        "youtube_category_id": "10",
        "_fallback": True,
    }

def pick_theme(theme_override=None):
    used = get_used_themes()
    if theme_override:
        match = next((t for t in THEMES if theme_override.lower() in t["theme"].lower()), None)
        return match or THEMES[0]
    unused = [t for t in THEMES if t["theme"] not in used]
    if not unused:
        unused = THEMES
    return random.choice(unused)

REQUIRED_TAGS = ["rain sounds for sleep", "rain sounds", "sleep sounds"]
MISLEADING_TAGS = {"study with me", "viral", "trending", "tiktok", "sounds for babies"}

def postprocess_metadata(metadata, duration_hours, theme_data):
    metadata["title"] = metadata.get("title", "").strip()[:80]
    metadata["description"] = metadata.get("description", "").strip()

    raw_tags = metadata.get("tags", [])
    clean_tags = []
    for tag in raw_tags:
        tag = re.sub(r"[^a-z0-9 ]+", "", str(tag).lower()).strip()
        tag = re.sub(r"\s+", " ", tag)
        if not tag or tag in MISLEADING_TAGS:
            continue
        if tag not in clean_tags:
            clean_tags.append(tag)

    for tag in REQUIRED_TAGS:
        if tag not in clean_tags:
            clean_tags.insert(0, tag)

    for tag in [f"{duration_hours} hour rain sounds", f"{duration_hours} hours rain"]:
        if tag not in clean_tags:
            clean_tags.append(tag)

    if "nocturne noise" not in clean_tags:
        clean_tags.append("nocturne noise")

    metadata["tags"] = clean_tags[:18]
    return metadata

def generate_metadata(theme_override=None, duration_hours=None):
    theme_data = pick_theme(theme_override)
    if not duration_hours:
        duration_hours = random.choice(DURATIONS)
    series_num = get_series_number()

    print(f"\nTheme: {theme_data['theme']}")
    print(f"Duration: {duration_hours}h | Vol. {series_num}")

    prompt = build_prompt(theme_data, duration_hours, series_num)
    metadata = call_ai_cascade(prompt)
    if metadata is None:
        metadata = build_fallback_metadata(theme_data, duration_hours, series_num)

    metadata = postprocess_metadata(metadata, duration_hours, theme_data)
    metadata["theme"] = theme_data["theme"]
    metadata["theme_data"] = theme_data
    metadata["category"] = "rain"
    metadata["duration_hours"] = duration_hours
    metadata["series_num"] = series_num
    metadata["generated_at"] = datetime.now().isoformat()

    mark_theme_used(theme_data["theme"])
    save_title(metadata.get("title", ""))

    fname = f"metadata_{theme_data['theme'][:30].replace(' ','_')}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print(f"Title: {metadata.get('title','')}")
    print(f"Tags: {len(metadata.get('tags', []))} | Saved: {fname}\n")
    return metadata

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--theme", type=str)
    p.add_argument("--duration", type=int, choices=DURATIONS)
    args = p.parse_args()
    generate_metadata(theme_override=args.theme, duration_hours=args.duration)
