"""
STEP 2 — Audio Generator (Rain Sleep Channel)

Foco exclusivo: chuva para dormir, alta qualidade sonora.

Estratégia de áudio:
1. Tenta buscar amostras reais CC0 do Freesound (chuva real > sintética)
2. Se não achar o suficiente, usa síntese procedural avançada com camadas

Síntese procedural de chuva (fallback):
- Usa ruído rosa filtrado (mais natural que white noise)
- Múltiplas camadas com texturas diferentes
- Sub-rumble suave para peso e presença
- Gotas esporádicas sobre o leito
- Sem sine tones, sem lofi, sem jazz — só chuva
"""

import glob, json, math, os, random, re, statistics, struct, time
import requests
from pydub import AudioSegment
from pydub.generators import WhiteNoise

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(): return None

load_dotenv()

FREESOUND_KEY    = os.environ.get("FREESOUND_API_KEY", "")
TARGET_DBFS      = -20.0
CROSSFADE_MS     = 8000
MIN_SAMPLE_SEC   = 60
MIN_ACCEPTED_SEGS = 3
QUALITY_REPORT   = "audio_quality_report.json"
LICENSE_MODE     = os.environ.get("AUDIO_LICENSE_MODE", "cc0_only").lower()
ALLOW_SYNTH_FALLBACK = os.environ.get("ALLOW_ORIGINAL_AUDIO_FALLBACK", "1").lower() in {"1", "true", "yes"}

# Apenas tags que indicam sons indesejados numa gravação de chuva
BLOCKED_TAGS = {
    "voice", "voices", "speech", "talk", "talking", "spoken", "vocal", "vocals",
    "sing", "singing", "song", "lyrics", "choir", "chant", "rap",
    "people", "person", "human", "crowd", "chatter", "conversation",
    "radio", "broadcast", "podcast", "interview", "news", "tv",
    "phone", "announcement", "applause", "laughter", "laugh",
    "child", "children", "baby", "babies", "scream", "shout",
    "horn", "siren", "alarm", "construction",
}

BLOCKED_NAME_PATTERN = re.compile(
    r"\b(voice|voices|speech|talk(?:ing)?|spoken|vocal|sing(?:ing)?|"
    r"song|lyrics|choir|chant|rap|crowd|people|chatter|conversation|"
    r"radio|broadcast|podcast|interview|news|tv|phone|announcement|"
    r"applause|laughter|laugh|child|children|baby|scream|shout|"
    r"siren|alarm|horn)\b",
    re.I,
)

# Queries Freesound especializadas em chuva
RAIN_QUERIES = [
    "heavy rain window field recording no voices",
    "rain ambience steady loop no talking",
    "rain on roof recording cc0",
    "gentle rain forest no people",
    "thunderstorm rain ambient no voices",
    "rain on glass window night",
    "distant rain steady ambience",
    "rain drops steady loopable",
    "indoor rain recording window",
    "rain on metal roof steady",
]


# ─────────────────────────────────────────────────────────
# UTILIDADES DE RELATÓRIO
# ─────────────────────────────────────────────────────────

def _new_report(duration_hours):
    return {
        "category": "rain",
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
        "tags": sorted(_tags(sound))[:20],
    }

def _is_allowed_license(sound):
    if LICENSE_MODE in {"any", "allow_any"}:
        return True
    lic = str(sound.get("license", "")).lower()
    return "creative commons 0" in lic or "cc0" in lic or "public domain" in lic

def _freesound_filter():
    base = f"duration:[{MIN_SAMPLE_SEC} TO 7200]"
    if LICENSE_MODE in {"any", "allow_any"}:
        return base
    return f'{base} license:"Creative Commons 0"'


# ─────────────────────────────────────────────────────────
# CONTROLE DE QUALIDADE DE ÁUDIO
# ─────────────────────────────────────────────────────────

def _chunk_dbfs(seg, chunk_ms=5000):
    values = []
    for start in range(0, len(seg), chunk_ms):
        chunk = seg[start:start + chunk_ms]
        if len(chunk) >= 1000 and chunk.dBFS != float("-inf"):
            values.append(chunk.dBFS)
    return values

def _audio_quality(seg):
    """Retorna (lista_de_razões_para_rejeitar, dict_de_stats)"""
    reasons = []
    if len(seg) < MIN_SAMPLE_SEC * 1000:
        reasons.append(f"too short ({len(seg) // 1000}s < {MIN_SAMPLE_SEC}s)")
    if seg.dBFS == float("-inf"):
        reasons.append("silent file")
        return reasons, {"dbfs": None, "peak_dbfs": None, "range_db": None}

    peak_dbfs = seg.max_dBFS
    values = _chunk_dbfs(seg)
    loudness_range = (max(values) - min(values)) if len(values) > 1 else 0.0
    median_dbfs = statistics.median(values) if values else seg.dBFS

    if seg.dBFS > -10:
        reasons.append(f"too loud ({seg.dBFS:.1f} dBFS)")
    if seg.dBFS < -40:
        # Limiar mais permissivo — chuva suave pode ser bem quiet
        reasons.append(f"too quiet ({seg.dBFS:.1f} dBFS)")
    if peak_dbfs > -0.5:
        reasons.append(f"clipping risk ({peak_dbfs:.1f} dBFS)")
    if loudness_range > 16:
        # Chuva pode variar um pouco; 16dB é limite razoável
        reasons.append(f"unstable loudness ({loudness_range:.1f} dB range)")
    if median_dbfs - seg.dBFS > 10:
        reasons.append("spiky profile — likely voice or transient intrusion")

    stats = {
        "duration_s": len(seg) // 1000,
        "dbfs": round(seg.dBFS, 2),
        "peak_dbfs": round(peak_dbfs, 2),
        "median_dbfs": round(median_dbfs, 2),
        "range_db": round(loudness_range, 2),
    }
    return reasons, stats

def normalize_segment(seg, target_dbfs=TARGET_DBFS, max_gain=12.0):
    if seg.dBFS == float("-inf"):
        return seg
    gain = target_dbfs - seg.dBFS
    gain = max(min(gain, max_gain), -max_gain)
    return seg.apply_gain(gain)


# ─────────────────────────────────────────────────────────
# FREESOUND
# ─────────────────────────────────────────────────────────

def freesound_search(query, report, num=15):
    if not FREESOUND_KEY:
        raise ValueError("FREESOUND_API_KEY not set")
    print(f"  [Freesound] Searching: {query}")
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
                "reason": "blocked metadata (voice/person tags)",
                "sound": _sound_label(sound),
            })
        else:
            clean.append(sound)

    print(f"  [Freesound] Clean: {len(clean)}/{len(results)}")
    return clean

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

def fetch_freesound(report):
    all_sounds = []
    for query in RAIN_QUERIES:
        sounds = freesound_search(query, report)
        all_sounds.extend(sounds)
        deduped = {s["id"]: s for s in all_sounds}
        all_sounds = list(deduped.values())
        if len(all_sounds) >= MIN_ACCEPTED_SEGS * 3:
            break
        time.sleep(0.8)

    if not all_sounds:
        raise RuntimeError("No clean Freesound rain candidates found.")

    files = []
    for sound in all_sounds:
        try:
            path = freesound_download(sound)
            files.append((path, {"source": "freesound", "sound": _sound_label(sound)}))
        except Exception as e:
            report["rejected"].append({
                "source": "freesound",
                "reason": f"download failed: {e}",
                "sound": _sound_label(sound),
            })

    return load_segments(files, report)

def load_segments(files, report):
    segs = []
    for path, meta in files:
        try:
            seg = AudioSegment.from_file(path)
            reasons, stats = _audio_quality(seg)
            if reasons:
                report["rejected"].append({**meta, "file": path, "reason": "; ".join(reasons), "stats": stats})
                print(f"  Rejected: {os.path.basename(path)} — {'; '.join(reasons)}")
                continue

            seg = normalize_segment(seg)
            post_reasons, post_stats = _audio_quality(seg)
            if any("clipping" in r for r in post_reasons):
                report["rejected"].append({**meta, "file": path, "reason": "; ".join(post_reasons), "stats": post_stats})
                print(f"  Rejected after normalize: {os.path.basename(path)}")
                continue

            report["accepted"].append({**meta, "file": path, "stats": post_stats})
            segs.append(seg.set_frame_rate(44100).set_channels(2))
            print(f"  Accepted: {os.path.basename(path)} ({len(seg)//1000}s | {seg.dBFS:.1f} dBFS)")
        except Exception as e:
            report["rejected"].append({"file": path, "reason": f"decode failed: {e}", **meta})
            print(f"  Ignored: {os.path.basename(path)} ({e})")

    if len(segs) < MIN_ACCEPTED_SEGS:
        raise RuntimeError(
            f"Only {len(segs)} clean segment(s) accepted (need {MIN_ACCEPTED_SEGS}). "
            "Triggering synthesis fallback."
        )
    random.shuffle(segs)
    return segs


# ─────────────────────────────────────────────────────────
# SÍNTESE PROCEDURAL DE CHUVA (alta qualidade)
# ─────────────────────────────────────────────────────────
#
# Por que pink noise filtrado é melhor que white noise para chuva:
# - Chuva real tem energia maior nas baixas e médias frequências
# - White noise soa mecânico / "hiss de fita"
# - Pink noise filtrado soa mais "molhado" e natural
#
# Aproximamos pink noise somando white noise em múltiplas oitavas
# com atenuação crescente, depois filtramos por banda.

def _pink_noise(duration_ms, gain_db=-20):
    """
    Pink noise aproximado: sobreposição de white noise em múltiplas oitavas.
    Cada oitava tem -3dB adicional (lei do pink noise).
    """
    base = WhiteNoise().to_audio_segment(duration=duration_ms)
    result = base.apply_gain(-10)

    # Adiciona 4 camadas com downsampling virtual (gain progressivo)
    for i, extra_gain in enumerate([-3, -6, -9, -12]):
        layer = WhiteNoise().to_audio_segment(duration=duration_ms)
        layer = layer.apply_gain(extra_gain)
        result = result.overlay(layer)

    return result.apply_gain(gain_db - result.dBFS)


def build_rain_layer(duration_ms, theme_variant="heavy_window"):
    """
    Constrói uma camada de chuva sintética de alta qualidade.

    Variantes:
    - heavy_window:  Chuva pesada em vidro, mais energia nas médias
    - gentle_forest: Chuva suave com graves mais presentes (folhas)
    - distant:       Chuva distante, filtro low-pass agressivo
    - rooftop:       Chuva em telhado, impactos percussivos leves
    """
    print(f"  [Synth] Building rain layer: {theme_variant} ({duration_ms//1000}s)")

    if theme_variant == "heavy_window":
        # Leito principal — banda de chuva em vidro (600Hz-8kHz)
        bed = _pink_noise(duration_ms, -22)
        bed = bed.high_pass_filter(600).low_pass_filter(8000)

        # Camada de impacto (gotas grandes) — banda mais alta
        impact = _pink_noise(duration_ms, -32)
        impact = impact.high_pass_filter(2000).low_pass_filter(12000)

        # Sub-rumble (som de ar/pressão da chuva pesada)
        sub = _pink_noise(duration_ms, -38)
        sub = sub.low_pass_filter(200)

        rain = bed.overlay(impact).overlay(sub)

    elif theme_variant == "gentle_forest":
        # Chuva suave — menos high-frequency, mais corpo
        bed = _pink_noise(duration_ms, -24)
        bed = bed.high_pass_filter(300).low_pass_filter(6000)

        # Gotas em folhas — mais espalhadas nas frequências
        drops = _pink_noise(duration_ms, -34)
        drops = drops.high_pass_filter(800).low_pass_filter(5000)

        # Graves leves das folhas grandes
        leaves = _pink_noise(duration_ms, -40)
        leaves = leaves.high_pass_filter(100).low_pass_filter(500)

        rain = bed.overlay(drops).overlay(leaves)

    elif theme_variant == "distant":
        # Chuva distante — tudo low-pass, muito suave
        bed = _pink_noise(duration_ms, -26)
        bed = bed.high_pass_filter(200).low_pass_filter(3000)

        room_tone = _pink_noise(duration_ms, -42)
        room_tone = room_tone.low_pass_filter(800)

        rain = bed.overlay(room_tone)

    elif theme_variant == "rooftop":
        # Chuva em telhado — mais impacto, menos corpo suave
        bed = _pink_noise(duration_ms, -22)
        bed = bed.high_pass_filter(800).low_pass_filter(9000)

        # Metal ressoa — leve mid-range peak
        metal = _pink_noise(duration_ms, -30)
        metal = metal.high_pass_filter(1500).low_pass_filter(6000)

        sub = _pink_noise(duration_ms, -36)
        sub = sub.low_pass_filter(150)

        rain = bed.overlay(metal).overlay(sub)

    else:
        # Fallback genérico
        rain = _pink_noise(duration_ms, -22)
        rain = rain.high_pass_filter(500).low_pass_filter(7000)

    return rain.set_frame_rate(44100).set_channels(2)


def _pick_synth_variant(theme_str):
    """Escolhe variante sintética baseado no tema do metadata."""
    theme_lower = theme_str.lower()
    if "forest" in theme_lower or "bamboo" in theme_lower or "leaves" in theme_lower:
        return "gentle_forest"
    if "distant" in theme_lower or "rolling" in theme_lower or "far" in theme_lower:
        return "distant"
    if "roof" in theme_lower or "metal" in theme_lower or "cabin" in theme_lower:
        return "rooftop"
    return "heavy_window"


def build_rain_audio(hours, theme_str, report):
    """
    Gera o áudio de chuva procedural em camadas.
    Cria frases de 10 minutos e concatena com crossfade longo.
    """
    target_ms   = int(hours * 3600 * 1000)
    phrase_ms   = 10 * 60 * 1000  # frases de 10 min
    variant     = _pick_synth_variant(theme_str)

    print(f"  [Synth] Generating {hours}h rain ({variant}) via layered pink noise")

    # Gera a frase base
    phrase = build_rain_layer(phrase_ms, variant)
    phrase = normalize_segment(phrase, TARGET_DBFS)

    # Valida a frase antes de usar
    reasons, stats = _audio_quality(phrase)
    if reasons:
        raise RuntimeError(f"Synth rain phrase failed QA: {'; '.join(reasons)}")

    # Constrói o áudio completo com crossfades suaves
    audio = phrase.fade_in(5000)
    while len(audio) < target_ms + CROSSFADE_MS:
        # Gera cada frase levemente diferente para evitar repetição perceptível
        next_phrase = build_rain_layer(phrase_ms, variant)
        next_phrase = normalize_segment(next_phrase, TARGET_DBFS)
        fade = min(CROSSFADE_MS, len(audio) // 4, len(next_phrase) // 4)
        audio = audio.append(next_phrase, crossfade=fade)

    audio = audio[:target_ms].fade_out(10000)

    report["accepted"].append({
        "source": "procedural_synthesis",
        "variant": variant,
        "license": "original — no third-party audio",
        "notes": f"Layered pink noise rain ({variant})",
        "stats": stats,
    })
    report["warnings"].append(
        f"Used procedural synthesis ({variant}) — no CC0 Freesound samples available."
    )

    return audio


# ─────────────────────────────────────────────────────────
# LOOP DE AMOSTRAS REAIS
# ─────────────────────────────────────────────────────────

def loop_audio(segs, hours):
    target = int(hours * 3600 * 1000)
    out = segs[0].fade_in(5000)
    i = 1
    while len(out) < target + CROSSFADE_MS:
        nxt = segs[i % len(segs)]
        fade = min(CROSSFADE_MS, len(out) // 4, len(nxt) // 4)
        out = out.append(nxt, crossfade=fade)
        i += 1
    return out[:target].fade_out(10000)


# ─────────────────────────────────────────────────────────
# VALIDAÇÃO FINAL
# ─────────────────────────────────────────────────────────

def validate_final_audio(audio, report):
    # Amostra os primeiros 20 min para não demorar demais
    sample = audio[:min(len(audio), 20 * 60 * 1000)]
    reasons, stats = _audio_quality(sample)
    report["final"] = {
        "duration_s": len(audio) // 1000,
        "sample_stats": stats,
        "status": "pass" if not reasons else "fail",
        "reasons": reasons,
    }
    if reasons:
        raise RuntimeError(f"Final audio QA failed: {'; '.join(reasons)}")


# ─────────────────────────────────────────────────────────
# POOL DE SHORTS
# ─────────────────────────────────────────────────────────

def export_shorts_pool(audio):
    """Exporta 7 clips de ~55s para o pool de Shorts."""
    if len(audio) <= 120000:
        return
    for day in range(1, 8):
        start_ms = 90000 + (day - 1) * 600000  # Começa 90s dentro, espaçado 10min
        if start_ms + 60000 < len(audio):
            clip = audio[start_ms:start_ms + 55000]
            clip = clip.fade_in(1500).fade_out(1500)
            fname = f"short_audio_{day}.mp3"
            clip.export(fname, format="mp3", bitrate="192k", parameters=["-ar", "44100"])
            print(f"  Short {day} saved: {fname}")


# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────

def main():
    meta_files = sorted(glob.glob("metadata_*.json"))
    if not meta_files:
        raise FileNotFoundError("Run step1_metadata.py first")

    with open(meta_files[-1], encoding="utf-8") as f:
        data = json.load(f)

    duration    = data["duration_hours"]
    theme_str   = data.get("theme", "heavy rain")
    report      = _new_report(duration)

    print(f"Generating audio: {theme_str} ({duration}h)")

    try:
        # Tentativa 1: Freesound CC0
        try:
            segs  = fetch_freesound(report)
            audio = loop_audio(segs, duration)
            print("  Using real Freesound rain samples.")
        except Exception as e:
            if not ALLOW_SYNTH_FALLBACK:
                raise
            report["warnings"].append(f"Freesound fetch failed: {e}")
            print(f"  Freesound failed ({e}). Switching to synthesis.")
            audio = build_rain_audio(duration, theme_str, report)

        validate_final_audio(audio, report)

        audio.export(
            "output_audio.mp3",
            format="mp3",
            bitrate="192k",
            parameters=["-ar", "44100", "-q:a", "0"],
        )

        export_shorts_pool(audio)

        report["final"]["output_file"]  = "output_audio.mp3"
        report["final"]["bitrate"]      = "192k"
        print("Audio QA passed ✓")

    finally:
        _save_report(report)
        print(f"Audio QA report: {QUALITY_REPORT}")
        print("DONE")


if __name__ == "__main__":
    main()
