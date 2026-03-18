"""
ETAPA 1 — Gerador de Metadata (Gemini API — GRÁTIS)
Canal de conforto: cada tema foi curado para garantir sons agradáveis.
"""
import google.generativeai as genai
import json, os, random, argparse
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

DURATIONS = [2, 3, 4]

# ─────────────────────────────────────────────────────────
# CATÁLOGO CURADO — 48 temas em 7 categorias
# Cada tema foi selecionado para garantir sons agradáveis.
# ─────────────────────────────────────────────────────────
THEMES = {

    # Sons de chuva — o nicho #1 em soundscapes
    # Fonte: Freesound (sons ambientes)
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

    # Natureza suave — sem sapos, grilos ou sons agudos
    # Fonte: Freesound (sons ambientes)
    "nature": [
        {"theme": "soft forest ambience with gentle birds",  "query": "forest birds soft ambience",   "pexels": "misty forest morning"},
        {"theme": "ocean waves on sandy beach",              "query": "ocean waves beach soft",       "pexels": "ocean waves sandy beach"},
        {"theme": "gentle river flowing through forest",     "query": "river stream forest",          "pexels": "river forest"},
        {"theme": "distant waterfall in forest",             "query": "waterfall distant forest",     "pexels": "waterfall forest"},
        {"theme": "wind through pine trees softly",          "query": "wind pine trees gentle",       "pexels": "pine forest wind"},
        {"theme": "calm birds singing at dawn",              "query": "birds dawn morning gentle",    "pexels": "sunrise forest birds"},
        {"theme": "mountain stream babbling",                "query": "mountain stream babbling",     "pexels": "mountain stream"},
        {"theme": "summer meadow soft breeze",               "query": "meadow breeze summer",         "pexels": "green meadow summer"},
    ],

    # Ambientes aconchegantes — o mais alto watch time do nicho
    # Fonte: Freesound (sons ambientes)
    "cozy": [
        {"theme": "cozy coffee shop ambience morning",        "query": "coffee shop cafe ambience",       "pexels": "cozy coffee shop"},
        {"theme": "fireplace crackling cozy indoors",         "query": "fireplace crackling wood fire",   "pexels": "fireplace cozy"},
        {"theme": "quiet library ambience soft",              "query": "library quiet ambience",          "pexels": "cozy library books"},
        {"theme": "japanese tea house ambience",              "query": "tea house soft ambience",         "pexels": "japanese tea house"},
        {"theme": "bookstore with rain outside",              "query": "bookstore indoor ambience",       "pexels": "bookstore cozy rain"},
        {"theme": "cozy cabin during snowstorm",              "query": "cabin indoor fire snow",          "pexels": "cabin snow winter cozy"},
        {"theme": "bakery ambience early morning",            "query": "bakery morning ambience",         "pexels": "bakery morning"},
        {"theme": "rainy afternoon indoors with kettle",      "query": "indoor rain kettle soft",         "pexels": "cozy home rain"},
        {"theme": "vintage reading nook with fireplace",      "query": "fireplace crackling gentle",      "pexels": "reading nook vintage books"},
        {"theme": "cozy bed and breakfast morning",           "query": "morning indoor soft ambience",    "pexels": "cozy morning bedroom"},
    ],

    # Jazz instrumental real — músicas com licença CC via Jamendo
    # Fonte: Jamendo API (música real, não efeitos sonoros)
    "jazz": [
        {"theme": "late night jazz cafe",               "query": "jazz cafe night instrumental",       "tags": "jazz",         "pexels": "jazz cafe night"},
        {"theme": "smooth piano jazz for relaxation",   "query": "smooth jazz piano instrumental",     "tags": "piano jazz",   "pexels": "grand piano low light"},
        {"theme": "soft jazz with gentle rain",         "query": "soft jazz instrumental mellow",      "tags": "jazz",         "pexels": "jazz rain window"},
        {"theme": "bossa nova instrumental morning",    "query": "bossa nova instrumental",            "tags": "bossanova",    "pexels": "coffee morning sunlight"},
        {"theme": "mellow jazz guitar evening",         "query": "jazz guitar mellow instrumental",    "tags": "jazz guitar",  "pexels": "guitar low light evening"},
        {"theme": "slow jazz piano bar night",          "query": "jazz piano bar slow",                "tags": "jazz piano",   "pexels": "piano bar night"},
        {"theme": "peaceful jazz trio afternoon",       "query": "jazz trio acoustic peaceful",        "tags": "jazz",         "pexels": "jazz musician"},
        {"theme": "winter jazz by the fireplace",       "query": "jazz warm cozy instrumental",        "tags": "jazz",         "pexels": "fireplace winter cozy"},
    ],

    # Ruídos de foco — gerados matematicamente (qualidade perfeita)
    # Fonte: geração local com numpy (sem dependência de API)
    "focus_noise": [
        {"theme": "brown noise for deep focus",                 "noise_type": "brown", "pexels": "minimalist desk study"},
        {"theme": "white noise for concentration",              "noise_type": "white", "pexels": "clean minimal workspace"},
        {"theme": "pink noise for studying",                    "noise_type": "pink",  "pexels": "student studying calm"},
        {"theme": "soft brown noise for sleep",                 "noise_type": "brown", "pexels": "bedroom night peaceful"},
        {"theme": "gentle white noise for baby sleep",          "noise_type": "white", "pexels": "peaceful nursery soft light"},
        {"theme": "brown noise with distant rain",              "noise_type": "brown", "pexels": "rainy window night desk"},
    ],

    # Estudo e foco — combinação de ambiente + ruído suave
    # Fonte: Freesound (sons ambientes)
    "study": [
        {"theme": "late night study session with rain",        "query": "study rain indoor soft",     "pexels": "desk lamp study rain"},
        {"theme": "quiet library late at night",               "query": "library quiet night",        "pexels": "library night lamp"},
        {"theme": "morning study cafe with soft music",        "query": "cafe morning soft ambience", "pexels": "cafe morning study"},
        {"theme": "focused study room afternoon",              "query": "indoor quiet focus room",    "pexels": "study room afternoon light"},
    ],

    # Urbano noturno — apenas cidades que evocam conforto
    # Fonte: Freesound (sons ambientes)
    "urban": [
        {"theme": "rainy night in tokyo",              "query": "rain city night japan",      "pexels": "tokyo rain night"},
        {"theme": "paris cafe terrace evening",        "query": "paris cafe outdoor evening", "pexels": "paris cafe evening"},
        {"theme": "new york apartment rain at night",  "query": "city rain night apartment",  "pexels": "new york apartment rain"},
        {"theme": "london evening rain street",        "query": "london rain evening street", "pexels": "london rain evening"},
    ],
}

# Contexto por categoria para o prompt de metadata
CATEGORY_CONTEXT = {
    "rain":        ("sleep, relaxation, and stress relief",     "rain sounds, sleep sounds, relaxing rain"),
    "nature":      ("relaxation, meditation, and mindfulness",  "nature sounds, calming nature, ambient sounds"),
    "cozy":        ("relaxation, focus, and cozy comfort",      "cozy ambience, cafe sounds, background noise"),
    "jazz":        ("late night focus, relaxation, and mood",   "jazz music, instrumental jazz, background jazz"),
    "focus_noise": ("deep focus, studying, and sleep",          "brown noise, white noise, focus sounds"),
    "study":       ("studying, concentration, and productivity","study music, focus background, lo-fi ambience"),
    "urban":       ("relaxation, mood, and urban comfort",      "city sounds, urban ambience, night sounds"),
}

SYSTEM_PROMPT = """You are a YouTube SEO specialist for a premium ambient/soundscape channel called 'Comfort Sounds'.
The channel's identity: warm, trustworthy, high-quality, peaceful. No clickbait, no ALL CAPS titles.
Respond ONLY with valid JSON — no markdown, no code fences, no explanation."""

def pick_theme(theme_override=None, category=None):
    if category and category not in THEMES:
        raise ValueError(f"Categoria inválida. Use: {list(THEMES.keys())}")
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

    print(f"🎯 Tema: {theme_data['theme']}")
    print(f"   Categoria: {category} | Duração: {duration_hours}h")

    audience, support_kw = CATEGORY_CONTEXT[category]
    dur_label = f"{duration_hours} Hours"

    prompt = f"""Generate YouTube metadata for a comfort soundscape channel.

Theme: "{theme_data['theme']}"
Category: {category}
Duration: {duration_hours} hours
Target audience: {audience}
Support keywords: {support_kw}
Channel name: Comfort Sounds

Return ONLY this JSON structure:
{{
  "title": "max 70 chars · include '{dur_label}' · natural keyword · no ALL CAPS · examples: 'Heavy Rain on Window {dur_label} | Sleep & Relaxation' or 'Late Night Jazz Cafe {dur_label} | Focus & Chill'",
  "description": "400-500 chars · hook in first 2 lines (shown before More) · 3-4 natural keyword mentions · warm tone · end with: 🔔 Subscribe for new soundscapes every week.",
  "tags": ["exactly 30 tags · lowercase · no hashtags · mix: exact match, broad, long-tail"],
  "thumbnail_text": "max 5 words · warm and inviting · example: '{dur_label} of Rain' or 'Jazz Cafe • {duration_hours}h'",
  "youtube_category_id": "10"
}}"""

    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content(prompt)
    raw = response.text.strip()
    # Remove markdown fences if present
    raw = raw.strip("```").strip()
    if raw.startswith("json"):
        raw = raw[4:].strip()

    try:
        metadata = json.loads(raw)
    except Exception:
        import re
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        metadata = json.loads(m.group()) if m else {}

    # Injeta dados de controle
    metadata["theme"]          = theme_data["theme"]
    metadata["theme_data"]     = theme_data
    metadata["category"]       = category
    metadata["duration_hours"] = duration_hours
    metadata["generated_at"]   = datetime.now().isoformat()

    fname = f"metadata_{theme_data['theme'][:30].replace(' ','_')}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print(f"\n📌 Título: {metadata.get('title','')}")
    print(f"🏷️  {len(metadata.get('tags',[]))} tags | 💾 Salvo: {fname}\n")
    return metadata

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--theme",    type=str)
    p.add_argument("--category", choices=list(THEMES.keys()))
    p.add_argument("--duration", type=int, choices=DURATIONS)
    args = p.parse_args()
    generate_metadata(theme_override=args.theme, duration_hours=args.duration, category=args.category)
