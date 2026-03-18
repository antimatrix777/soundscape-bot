"""
ETAPA 1 — Gerador de Metadata com 3 provedores em cascata
══════════════════════════════════════════════════════════
Tenta os provedores nesta ordem até um funcionar:

  1. Groq      — Llama 3.3 70B (grátis, sem cartão, o mais rápido)
  2. Mistral   — Mistral Small (grátis, 1B tokens/mês)
  3. Gemini    — Gemini 1.5 Flash (grátis, fallback final)

Se todos falharem, salva metadata básico para não travar o pipeline.
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

CATEGORY_CONTEXT = {
    "rain":        ("sleep, relaxation, and stress relief",      "rain sounds, sleep sounds, relaxing rain"),
    "nature":      ("relaxation, meditation, and mindfulness",   "nature sounds, calming nature, ambient sounds"),
    "cozy":        ("relaxation, focus, and cozy comfort",       "cozy ambience, cafe sounds, background noise"),
    "jazz":        ("late night focus, relaxation, and mood",    "jazz music, instrumental jazz, background jazz"),
    "focus_noise": ("deep focus, studying, and sleep",           "brown noise, white noise, focus sounds"),
    "study":       ("studying, concentration, and productivity", "study music, focus background, lo-fi ambience"),
    "urban":       ("relaxation, mood, and urban comfort",       "city sounds, urban ambience, night sounds"),
}

SYSTEM_PROMPT = """You are a YouTube SEO specialist for a premium ambient/soundscape channel called 'Comfort Sounds'.
Channel identity: warm, trustworthy, high-quality, peaceful. No clickbait, no ALL CAPS titles.
Respond ONLY with valid JSON — no markdown, no code fences, no extra text."""


def build_prompt(theme_data, category, duration_hours):
    audience, support_kw = CATEGORY_CONTEXT[category]
    dur_label = f"{duration_hours} Hours"
    return f"""Generate YouTube metadata for a comfort soundscape channel.

Theme: "{theme_data['theme']}"
Category: {category}
Duration: {duration_hours} hours
Target audience: {audience}
Support keywords: {support_kw}
Channel name: Comfort Sounds

Return ONLY this JSON (no markdown, no explanation):
{{
  "title": "max 70 chars, include '{dur_label}', include main keyword, warm tone, no ALL CAPS",
  "description": "400-500 chars, hook in first 2 lines, 3-4 keyword mentions, end with: Subscribe for new soundscapes every week.",
  "tags": ["30 tags", "lowercase", "no hashtags", "mix broad and specific"],
  "thumbnail_text": "max 5 words, warm and inviting, example: '{dur_label} of Rain'",
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
        raise ValueError(f"JSON invalido:\n{raw[:300]}")


# ── PROVEDOR 1: GROQ ─────────────────────────────────────
# console.groq.com → API Keys → Create API Key (sem cartão)
def call_groq(prompt: str) -> str:
    import requests
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        raise ValueError("GROQ_API_KEY nao configurada")
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 1000,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


# ── PROVEDOR 2: MISTRAL ───────────────────────────────────
# console.mistral.ai → API Keys → Create new key (sem cartão)
def call_mistral(prompt: str) -> str:
    import requests
    key = os.environ.get("MISTRAL_API_KEY", "")
    if not key:
        raise ValueError("MISTRAL_API_KEY nao configurada")
    r = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": "mistral-small-latest",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 1000,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


# ── PROVEDOR 3: GEMINI ────────────────────────────────────
# aistudio.google.com → Get API Key (sem cartão)
def call_gemini(prompt: str) -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise ValueError("GEMINI_API_KEY nao configurada")
    import google.generativeai as genai
    genai.configure(api_key=key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content(f"{SYSTEM_PROMPT}\n\n{prompt}")
    return response.text


# ── CASCADE ───────────────────────────────────────────────
PROVIDERS = [
    ("Groq Llama 3.3 70B", call_groq),
    ("Mistral Small",       call_mistral),
    ("Gemini 1.5 Flash",    call_gemini),
]

def call_ai_cascade(prompt: str):
    errors = []
    for name, fn in PROVIDERS:
        try:
            print(f"   Tentando: {name}...")
            raw = fn(prompt)
            result = clean_json(raw)
            print(f"   OK: {name}")
            return result
        except Exception as e:
            print(f"   Falhou {name}: {e}")
            errors.append(f"{name}: {e}")
    print(f"   Todos os provedores falharam. Usando fallback.")
    return None


def build_fallback_metadata(theme_data, category, duration_hours):
    dur = f"{duration_hours} Hours"
    title_map = {
        "rain":        f"Relaxing Rain Sounds {dur} | Sleep & Study",
        "nature":      f"Nature Ambience {dur} | Relaxation & Meditation",
        "cozy":        f"Cozy Ambience {dur} | Focus & Comfort",
        "jazz":        f"Smooth Jazz {dur} | Relax & Focus",
        "focus_noise": f"Brown Noise {dur} | Deep Focus & Concentration",
        "study":       f"Study Ambience {dur} | Focus & Concentration",
        "urban":       f"City Rain Ambience {dur} | Sleep & Relax",
    }
    return {
        "title":               title_map.get(category, f"Comfort Sounds {dur} | Relax & Focus"),
        "description":         f"Relax and unwind with {duration_hours} hours of {theme_data['theme']}. Perfect for sleep, study, and focus. Subscribe for new soundscapes every week.",
        "tags":                ["relaxing sounds","sleep sounds","ambient music","white noise","study music",
                                "focus music","lofi","calm music","meditation","soundscape","sleep aid",
                                "background music","cozy vibes","nature sounds","rain sounds","stress relief",
                                "chillout","work from home","deep focus","concentration","peaceful","relax",
                                "sleep meditation","ambient noise","comfort sounds","calming music","quiet",
                                "night sounds","zen","instrumental"],
        "thumbnail_text":      f"{dur} of {category.replace('_',' ').title()}",
        "youtube_category_id": "10",
        "_fallback":           True,
    }


def pick_theme(theme_override=None, category=None):
    if category and category not in THEMES:
        raise ValueError(f"Categoria invalida. Use: {list(THEMES.keys())}")
    cat = category or random.choice(list(THEMES.keys()))
    themes = THEMES[cat]
    if theme_override:
        match = next((t for t in themes if theme_override.lower() in t["theme"].lower()), None)
        return (match or themes[0]), cat
    return random.choice(themes), cat


def generate_metadata(theme_override=None, duration_hours=None, category=None):
    theme_data, category = pick_theme(theme_override, category)
    if not duration_hours:
        duration_hours = random.choice(DURATIONS)

    print(f"\nTema: {theme_data['theme']}")
    print(f"Categoria: {category} | Duracao: {duration_hours}h")

    prompt   = build_prompt(theme_data, category, duration_hours)
    metadata = call_ai_cascade(prompt)

    if metadata is None:
        metadata = build_fallback_metadata(theme_data, category, duration_hours)

    metadata["theme"]          = theme_data["theme"]
    metadata["theme_data"]     = theme_data
    metadata["category"]       = category
    metadata["duration_hours"] = duration_hours
    metadata["generated_at"]   = datetime.now().isoformat()

    fname = f"metadata_{theme_data['theme'][:30].replace(' ','_')}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print(f"Titulo: {metadata.get('title','')}")
    print(f"Tags: {len(metadata.get('tags', []))} | Salvo: {fname}\n")
    return metadata


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--theme",    type=str)
    p.add_argument("--category", choices=list(THEMES.keys()))
    p.add_argument("--duration", type=int, choices=DURATIONS)
    args = p.parse_args()
    generate_metadata(theme_override=args.theme, duration_hours=args.duration, category=args.category)
