# STEP 2 - Audio Generator (Nocturne Noise)
#
# v4 — Freesound only, sem filtros, mistura inteligente de samples
#
# Estratégia:
#   - Busca agressiva no Freesound com muitas queries de chuva
#   - Zero filtros de conteúdo — aceita qualquer sample que não seja silêncio puro
#   - Mistura real: camadas sobrepostas de samples diferentes (não só loop sequencial)
#   - Resultado: textura rica, nenhum sample dominante, sem loop perceptível

import glob
import json
import os
import random
import time
import requests
from pydub import AudioSegment
from pydub.generators import Sine, WhiteNoise

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(): return None

load_dotenv()

FREESOUND_KEY    = os.environ.get("FREESOUND_API_KEY", "")
TARGET_DBFS      = -18.0
CROSSFADE_MS     = 10000   # crossfade longo para transições suaves
MIN_SAMPLE_SEC   = 8       # só rejeita samples menores que 8s
MAX_SEGMENTS     = 30      # busca até 30 samples diferentes
QUALITY_REPORT   = "audio_quality_report.json"

# ──────────────────────────────────────────────
# Queries — variedade máxima de tipos de chuva
# ──────────────────────────────────────────────

RAIN_QUERIES = [
    "rain",
    "heavy rain",
    "light rain",
    "rain on roof",
    "rain on window",
    "rain forest",
    "rain thunder",
    "thunderstorm",
    "storm rain",
    "rain ambience",
    "rain drops",
    "rain night",
    "gentle rain",
    "tropical rain",
    "rain puddle",
    "rain on leaves",
    "rain on tent",
    "rain on car",
    "drizzle",
    "downpour",
    "rain stream",
    "rain relaxing",
    "rain sleep",
    "rain nature",
    "rain meditation",
    "rain lofi",
    "rain white noise",
    "rainstorm",
    "rain outside",
    "rain indoors",
]

CATEGORY_QUERIES = {
    "rain":  RAIN_QUERIES,
    "lofi":  ["lofi", "vinyl crackle", "ambient lo-fi", "tape hiss", "room tone", "cafe ambience"],
    "jazz":  ["jazz piano", "soft jazz", "jazz trio", "jazz bass", "brush drums jazz", "jazz bar"],
}

# ──────────────────────────────────────────────
# Relatório
# ──────────────────────────────────────────────

def _new_report(category, duration_hours):
    return {
        "category": category,
        "duration_hours": duration_hours,
        "accepted": [],
        "rejected": [],
        "warnings": [],
        "final": {},
    }

def _save_report(report):
    with open(QUALITY_REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

# ──────────────────────────────────────────────
# QA mínima — só rejeita inutilizável
# ──────────────────────────────────────────────

def _is_usable(seg):
    """
    Retorna (ok, motivo).
    Rejeita apenas:
      - Arquivo silencioso (dBFS = -inf)
      - Menor que MIN_SAMPLE_SEC
      - Clipping crítico (pico > -0.1 dBFS)
    """
    if len(seg) < MIN_SAMPLE_SEC * 1000:
        return False, f"muito curto ({len(seg)//1000}s)"
    if seg.dBFS == float("-inf"):
        return False, "silêncio total"
    if seg.max_dBFS > -0.1:
        return False, f"clipping crítico ({seg.max_dBFS:.1f} dBFS)"
    return True, ""


def normalize(seg):
    if seg.dBFS == float("-inf"):
        return seg
    gain = TARGET_DBFS - seg.dBFS
    gain = max(min(gain, 15.0), -15.0)
    return seg.apply_gain(gain)

# ──────────────────────────────────────────────
# Freesound
# ──────────────────────────────────────────────

def freesound_search(query, num=20):
    if not FREESOUND_KEY:
        return []
    try:
        r = requests.get(
            "https://freesound.org/apiv2/search/text/",
            params={
                "query": query,
                "filter": f"duration:[{MIN_SAMPLE_SEC} TO 7200]",
                "fields": "id,name,duration,previews,license,username",
                "page_size": num,
                "sort": "rating_desc",
                "token": FREESOUND_KEY,
            },
            timeout=30,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        print(f"  [Freesound] '{query}': {len(results)} resultados")
        return results
    except Exception as e:
        print(f"  [Freesound] Erro '{query}': {e}")
        return []


def freesound_download(sound):
    os.makedirs("audio_tmp", exist_ok=True)
    path = f"audio_tmp/fs_{sound['id']}.mp3"
    if os.path.exists(path):
        return path
    url = sound.get("previews", {}).get("preview-hq-mp3")
    if not url:
        raise RuntimeError("sem preview HQ")
    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()
    with open(path, "wb") as f:
        for chunk in r.iter_content(32768):
            f.write(chunk)
    return path


def fetch_all_segments(category, report):
    queries = CATEGORY_QUERIES.get(category, [category])
    seen_ids = set()
    all_sounds = []

    for query in queries:
        if len(all_sounds) >= MAX_SEGMENTS * 2:
            break
        sounds = freesound_search(query, num=20)
        for s in sounds:
            if s["id"] not in seen_ids:
                seen_ids.add(s["id"])
                all_sounds.append(s)
        time.sleep(0.4)

    print(f"\n  Total candidatos únicos: {len(all_sounds)}")

    segs = []
    for sound in all_sounds:
        if len(segs) >= MAX_SEGMENTS:
            break
        try:
            path = freesound_download(sound)
            seg = AudioSegment.from_file(path).set_frame_rate(44100).set_channels(2)
            ok, reason = _is_usable(seg)
            if not ok:
                report["rejected"].append({"name": sound.get("name"), "reason": reason})
                print(f"  ✗ {sound.get('name')} — {reason}")
                continue

            seg = normalize(seg)
            segs.append(seg)
            report["accepted"].append({
                "name": sound.get("name"),
                "license": sound.get("license"),
                "duration_s": len(seg) // 1000,
                "dbfs": round(seg.dBFS, 2),
            })
            print(f"  ✓ {sound.get('name')} ({len(seg)//1000}s | {seg.dBFS:.1f} dBFS)")

        except Exception as e:
            report["rejected"].append({"name": sound.get("name"), "reason": str(e)})

    return segs

# ──────────────────────────────────────────────
# Mistura de samples — coração do v4
# ──────────────────────────────────────────────

def build_layered_audio(segs, hours):
    """
    Constrói o áudio final misturando samples em camadas sobrepostas.

    Estratégia:
      - Divide os samples em dois grupos: BASE (fundo contínuo) e ACCENT (detalhes)
      - BASE: 2–4 samples longos sobrepostos com volume levemente mais baixo
        criam a "massa" da chuva
      - ACCENT: samples menores ou mais específicos aparecem em pontos aleatórios
        do timeline, dando textura e variação (gotas próximas, trovão, etc.)
      - Resultado final: sem loop perceptível, textura rica e em camadas

    Para vídeos de 8h, isso equivale a centenas de combinações diferentes.
    """
    target_ms = int(hours * 3600 * 1000)

    # Ordena por duração — samples longos primeiro (base), curtos depois (accent)
    segs_sorted = sorted(segs, key=lambda s: len(s), reverse=True)

    # Base: top 40% dos samples (mais longos) — formarão o fundo contínuo
    base_count  = max(2, len(segs_sorted) * 40 // 100)
    accent_count = len(segs_sorted) - base_count

    base_pool   = segs_sorted[:base_count]
    accent_pool = segs_sorted[base_count:] if accent_count > 0 else segs_sorted

    print(f"\n  Camadas base: {len(base_pool)} samples")
    print(f"  Camadas accent: {len(accent_pool)} samples")

    # ── 1. Constrói faixa base (loop com crossfade longo) ──
    random.shuffle(base_pool)
    base_track = base_pool[0].fade_in(3000)
    i = 1
    while len(base_track) < target_ms + CROSSFADE_MS:
        next_seg = base_pool[i % len(base_pool)]
        if i % len(base_pool) == 0:
            random.shuffle(base_pool)
        fade_ms = min(CROSSFADE_MS, len(base_track) // 4, len(next_seg) // 4)
        base_track = base_track.append(next_seg, crossfade=fade_ms)
        i += 1

    base_track = base_track[:target_ms]

    # Baixa levemente o volume da base para dar espaço aos accents
    base_track = base_track.apply_gain(-2.0)

    # ── 2. Sobrepõe accent samples em posições aleatórias ──
    if accent_pool:
        # Quantos accents colocar? ~1 a cada 3–8 minutos
        num_accents = target_ms // (random.randint(3, 8) * 60 * 1000)
        num_accents = max(num_accents, len(accent_pool))  # pelo menos 1 de cada

        print(f"  Posicionando {num_accents} accent overlays no timeline...")

        for _ in range(num_accents):
            accent_seg = random.choice(accent_pool)

            # Volume levemente variável para naturalidade (-3 a +1 dB)
            volume_var = random.uniform(-3.0, 1.0)
            accent_seg = accent_seg.apply_gain(volume_var)

            # Posição aleatória, garantindo que caiba
            max_pos = max(0, target_ms - len(accent_seg) - 5000)
            if max_pos <= 0:
                continue
            position = random.randint(0, max_pos)

            # Fade in/out curto no accent para entrada suave
            fade = min(2000, len(accent_seg) // 4)
            accent_seg = accent_seg.fade_in(fade).fade_out(fade)

            base_track = base_track.overlay(accent_seg, position=position)

    # ── 3. Fade final e normalização de saída ──
    final = base_track.fade_in(4000).fade_out(10000)

    # Garante que o output final está no nível correto
    final = normalize(final)

    return final

# ──────────────────────────────────────────────
# Fallback sintético (zero fontes externas)
# ──────────────────────────────────────────────

def _tone(freq, duration_ms, gain_db=-24, fade_ms=80):
    return Sine(freq).to_audio_segment(duration=duration_ms).apply_gain(gain_db).fade_in(fade_ms).fade_out(fade_ms)

def build_synthetic_fallback(hours, report):
    target_ms = int(hours * 3600 * 1000)
    print("  Fallback sintético (pink noise aproximado — sem fontes externas)")

    def rain_phrase(duration_ms=90000):
        base    = WhiteNoise().to_audio_segment(duration=duration_ms).apply_gain(-28).low_pass_filter(2200)
        near    = WhiteNoise().to_audio_segment(duration=duration_ms).apply_gain(-36).high_pass_filter(400).low_pass_filter(3500)
        surface = WhiteNoise().to_audio_segment(duration=duration_ms).apply_gain(-44).high_pass_filter(600).low_pass_filter(2800)
        room    = WhiteNoise().to_audio_segment(duration=duration_ms).apply_gain(-50).low_pass_filter(400)
        phrase  = base.overlay(near).overlay(surface).overlay(room)
        for at_ms in range(18000, duration_ms, 30000):
            thunder = _tone(52, 8000, gain_db=-37, fade_ms=2500).low_pass_filter(180)
            phrase = phrase.overlay(thunder, position=at_ms)
        return phrase.fade_in(2500).fade_out(2500)

    phrase = normalize(rain_phrase())
    audio  = phrase
    while len(audio) < target_ms + CROSSFADE_MS:
        audio = audio.append(phrase, crossfade=CROSSFADE_MS)

    report["warnings"].append("Fallback sintético usado — FREESOUND_API_KEY não configurada ou sem resultados.")
    return audio[:target_ms].fade_in(4000).fade_out(10000)

# ──────────────────────────────────────────────
# Export shorts
# ──────────────────────────────────────────────

def export_shorts_pool(audio):
    if len(audio) <= 120000:
        return
    for day in range(1, 8):
        start_ms = 60000 + (day - 1) * 300000
        if start_ms + 60000 < len(audio):
            short_seg = audio[start_ms:start_ms + 55000].fade_in(1500).fade_out(1500)
            fname = f"short_audio_{day}.mp3"
            short_seg.export(fname, format="mp3", bitrate="192k", parameters=["-ar", "44100"])
            print(f"  Short {day}: {fname}")

# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    meta_files = sorted(glob.glob("metadata_*.json"))
    if not meta_files:
        raise FileNotFoundError("Execute step1_metadata.py primeiro")

    with open(meta_files[-1], encoding="utf-8") as f:
        data = json.load(f)

    category = data["category"]
    duration = data["duration_hours"]
    report   = _new_report(category, duration)

    print(f"\n=== Nocturne Noise — Audio Builder v4 ===")
    print(f"    Categoria : {category}")
    print(f"    Duração   : {duration}h")
    print(f"    Meta alvo : {TARGET_DBFS} dBFS\n")

    try:
        segs = []

        if FREESOUND_KEY:
            segs = fetch_all_segments(category, report)
            print(f"\n  {len(segs)} samples aceitos")
        else:
            print("  FREESOUND_API_KEY não configurada")

        if len(segs) >= 2:
            print(f"\nMontando {duration}h com mistura de {len(segs)} samples em camadas...")
            audio = build_layered_audio(segs, duration)
        elif len(segs) == 1:
            # Um único sample — loop simples
            report["warnings"].append("Apenas 1 sample encontrado — loop simples.")
            target_ms = int(duration * 3600 * 1000)
            audio = segs[0]
            while len(audio) < target_ms:
                audio = audio.append(segs[0], crossfade=CROSSFADE_MS)
            audio = audio[:target_ms].fade_in(4000).fade_out(10000)
        else:
            audio = build_synthetic_fallback(duration, report)

        audio.export(
            "output_audio.mp3",
            format="mp3",
            bitrate="192k",
            parameters=["-ar", "44100"],
        )
        export_shorts_pool(audio)

        report["final"] = {
            "output_file": "output_audio.mp3",
            "duration_s": len(audio) // 1000,
            "segments_used": len(segs),
            "bitrate": "192k",
            "status": "ok",
        }

        print(f"\n✓ output_audio.mp3 — {len(segs)} samples, {duration}h, 192k")

    except Exception as e:
        report["final"]["status"] = "error"
        report["final"]["error"]  = str(e)
        raise

    finally:
        _save_report(report)
        print(f"Relatório: {QUALITY_REPORT}")

    print("\nDONE")


if __name__ == "__main__":
    main()
