"""
step1_metadata.py
Gera metadados (título, descrição, tags, playlist) para vídeos de chuva/raios
do canal Nocturne Noise. Foco exclusivo: rain sounds for sleeping.
"""

import os
import json
import random
from datetime import datetime

# ── Configuração do nicho ────────────────────────────────────────────────────

CHANNEL_NAME = "Nocturne Noise"

RAIN_VARIANTS = [
    {
        "id": "heavy_rain",
        "label": "Heavy Rain",
        "description_pt": "chuva forte e constante",
        "search_terms": ["heavy rain", "torrential rain", "pouring rain"],
    },
    {
        "id": "gentle_rain",
        "label": "Gentle Rain",
        "description_pt": "chuva suave e relaxante",
        "search_terms": ["gentle rain", "soft rain", "light rain"],
    },
    {
        "id": "rain_window",
        "label": "Rain on Window",
        "description_pt": "chuva batendo na janela",
        "search_terms": ["rain on window", "rain against glass", "rain on glass"],
    },
    {
        "id": "rain_roof",
        "label": "Rain on Roof",
        "description_pt": "chuva no telhado",
        "search_terms": ["rain on roof", "rain on tin roof", "rain on metal roof"],
    },
    {
        "id": "rain_forest",
        "label": "Rain in Forest",
        "description_pt": "chuva na floresta",
        "search_terms": ["rain in forest", "forest rain", "jungle rain"],
    },
    {
        "id": "rain_thunder",
        "label": "Thunderstorm",
        "description_pt": "tempestade com raios e trovões",
        "search_terms": ["thunderstorm", "thunder and rain", "lightning storm"],
    },
    {
        "id": "thunder_heavy",
        "label": "Heavy Thunderstorm",
        "description_pt": "tempestade intensa com raios",
        "search_terms": ["heavy thunderstorm", "severe thunderstorm", "powerful thunder"],
    },
    {
        "id": "rain_night",
        "label": "Night Rain",
        "description_pt": "chuva noturna para dormir",
        "search_terms": ["night rain", "rain at night", "rainy night"],
    },
    {
        "id": "rain_cozy",
        "label": "Cozy Rainy Day",
        "description_pt": "dia chuvoso e aconchegante",
        "search_terms": ["cozy rainy day", "rainy day inside", "rainy day relaxing"],
    },
    {
        "id": "rain_meditation",
        "label": "Rain for Meditation",
        "description_pt": "chuva para meditação e foco",
        "search_terms": ["rain meditation", "rain for focus", "rain white noise"],
    },
]

# ── Templates de título ──────────────────────────────────────────────────────

TITLE_TEMPLATES = [
    "{label} for Sleeping 😴 | {hours} Hours | {channel}",
    "{label} Sounds for Deep Sleep | {hours} Hours",
    "{hours} Hours of {label} | Fall Asleep Fast",
    "{label} White Noise | {hours} Hours for Sleep & Relaxation",
    "Sleep to {label} | {hours} Hours of Rain Sounds",
    "{label} for Study & Sleep | {hours} Hours | {channel}",
    "Relaxing {label} | {hours} Hours | White Noise for Sleep",
    "{hours} Hour {label} | No Ads | Sleeping & Relaxation",
    "{label} ASMR | {hours} Hours | {channel}",
    "Fall Asleep Fast with {label} | {hours} Hours",
]

# ── Templates de descrição ───────────────────────────────────────────────────

DESCRIPTION_INTRO = [
    "🌧️ Let the sound of {description_pt} carry you into a deep, restful sleep.",
    "🌧️ Immerse yourself in {description_pt} — perfect for sleep, study, or relaxation.",
    "🌧️ Drift off to the natural sound of {description_pt}.",
    "🌧️ {hours} hours of uninterrupted {description_pt} to help you sleep through the night.",
]

DESCRIPTION_BODY = """\
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌙 Nocturne Noise — Rain & Thunder Sounds for Sleep
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ No music, no interruptions — just pure rain sounds
✅ Ideal for deep sleep, insomnia, anxiety, and focus
✅ Baby sleep | Study | Meditation | ASMR

🔔 Subscribe for new rain sounds every week!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⏱️ Timestamps:
0:00 — {label} Begins
{half_hours}:00 — Midpoint
{hours}:00:00 — End

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

DESCRIPTION_TAGS_BLOCK = """\
#RainSounds #SleepSounds #{tag1} #{tag2} #WhiteNoise #ASMR #NocturneNoise
"""

# ── Tags YouTube ─────────────────────────────────────────────────────────────

BASE_TAGS = [
    "rain sounds",
    "rain sounds for sleeping",
    "sleep sounds",
    "white noise",
    "rain white noise",
    "sleeping sounds",
    "relaxing rain",
    "rain asmr",
    "rain for study",
    "rain sounds 10 hours",
    "rain sounds 8 hours",
    "rain for insomnia",
    "deep sleep music",
    "nocturne noise",
    "rain meditation",
]

VARIANT_TAGS = {
    "heavy_rain":    ["heavy rain", "pouring rain", "torrential rain", "heavy rain sounds"],
    "gentle_rain":   ["gentle rain", "soft rain", "light rain sounds", "calm rain"],
    "rain_window":   ["rain on window", "rain on glass", "rain against window"],
    "rain_roof":     ["rain on roof", "tin roof rain", "rain on metal roof"],
    "rain_forest":   ["forest rain", "jungle rain", "rain in woods"],
    "rain_thunder":  ["thunderstorm", "thunder rain", "thunder sounds", "storm sounds"],
    "thunder_heavy": ["heavy thunderstorm", "severe storm", "powerful thunder", "lightning sounds"],
    "rain_night":    ["night rain", "rainy night", "rain at night", "midnight rain"],
    "rain_cozy":     ["cozy rain", "rainy day", "cozy rainy day", "rainy day sounds"],
    "rain_meditation": ["rain focus", "rain study", "concentration sounds", "rain mindfulness"],
}

# ── Playlists ─────────────────────────────────────────────────────────────────

PLAYLISTS = {
    "rain":       "Rain Sounds for Sleeping",
    "thunder":    "Thunderstorm & Lightning Sounds",
    "all":        "Nocturne Noise — All Rain Sounds",
}

def get_playlist_for_variant(variant_id: str) -> list[str]:
    """Retorna lista de playlists adequadas para o variant."""
    thunder_variants = {"rain_thunder", "thunder_heavy"}
    playlists = [PLAYLISTS["all"]]
    if variant_id in thunder_variants:
        playlists.append(PLAYLISTS["thunder"])
    else:
        playlists.append(PLAYLISTS["rain"])
    return playlists


# ── Função principal ──────────────────────────────────────────────────────────

def generate_metadata(variant_id: str = None, hours: int = 8) -> dict:
    """
    Gera metadados completos para um vídeo do canal.

    Args:
        variant_id: ID do variant (ex: 'heavy_rain'). Se None, escolhe aleatório.
        hours: Duração do vídeo em horas (padrão 8).

    Returns:
        dict com title, description, tags, playlists, variant_id, search_terms.
    """
    # Selecionar variante
    if variant_id:
        variant = next((v for v in RAIN_VARIANTS if v["id"] == variant_id), None)
        if not variant:
            raise ValueError(f"Variant '{variant_id}' não encontrado.")
    else:
        variant = random.choice(RAIN_VARIANTS)

    # Título
    title_template = random.choice(TITLE_TEMPLATES)
    title = title_template.format(
        label=variant["label"],
        hours=hours,
        channel=CHANNEL_NAME,
    )

    # Descrição
    intro = random.choice(DESCRIPTION_INTRO).format(
        description_pt=variant["description_pt"],
        hours=hours,
    )
    variant_tags = VARIANT_TAGS.get(variant["id"], [])
    tag1 = variant_tags[0].replace(" ", "") if variant_tags else "RainSounds"
    tag2 = variant_tags[1].replace(" ", "") if len(variant_tags) > 1 else "SleepSounds"

    body = DESCRIPTION_BODY.format(
        label=variant["label"],
        hours=hours,
        half_hours=hours // 2,
    )
    tags_block = DESCRIPTION_TAGS_BLOCK.format(tag1=tag1.title(), tag2=tag2.title())
    description = f"{intro}\n\n{body}{tags_block}"

    # Tags completas (max 500 chars para YouTube)
    all_tags = BASE_TAGS + variant_tags
    all_tags = list(dict.fromkeys(all_tags))  # deduplica

    # Playlists
    playlists = get_playlist_for_variant(variant["id"])

    metadata = {
        "variant_id":   variant["id"],
        "variant_label": variant["label"],
        "title":        title,
        "description":  description,
        "tags":         all_tags,
        "playlists":    playlists,
        "search_terms": variant["search_terms"],
        "hours":        hours,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }

    return metadata


# ── CLI / teste ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Gera metadados para vídeo Nocturne Noise")
    parser.add_argument("--variant", type=str, default=None, help="ID do variant (ex: heavy_rain)")
    parser.add_argument("--hours",   type=int, default=8,    help="Duração em horas")
    parser.add_argument("--output",  type=str, default=None, help="Arquivo JSON de saída")
    args = parser.parse_args()

    meta = generate_metadata(variant_id=args.variant, hours=args.hours)

    print("=" * 60)
    print(f"VARIANT:  {meta['variant_id']}")
    print(f"TÍTULO:   {meta['title']}")
    print(f"TAGS:     {', '.join(meta['tags'][:8])}...")
    print(f"PLAYLIST: {meta['playlists']}")
    print("=" * 60)
    print("\nDESCRIÇÃO:\n")
    print(meta["description"])

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(f"\n✅ Metadados salvos em: {args.output}")
