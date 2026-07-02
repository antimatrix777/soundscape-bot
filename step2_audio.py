# STEP 2 - Audio Generator (Nocturne Noise)
#
# v3 — Multi-source, filtros mínimos, máxima variedade
#
# Fontes de áudio:
#   1. Freesound (qualquer licença CC — CC0, CC-BY, CC-BY-NC)
#   2. Pixabay Audio (gratuito, royalty-free, sem API key necessária)
#
# Filosofia:
#   - Aceitar o máximo de sons reais de campo possível
#   - Só rejeitar o que é REALMENTE inutilizável (silêncio total, clipping grave)
#   - Variedade: combinar 8–20 segmentos diferentes por vídeo, nunca só 1 em loop
#   - Fallback sintético só quando absolutamente zero fontes disponíveis

import glob
import json
import os
import random
import re
import time
import requests
from pydub import AudioSegment
from pydub.generators import Sine, WhiteNoise

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        return None

load_dotenv()

FREESOUND_KEY = os.environ.get("FREESOUND_API_KEY", "")

# Configurações relaxadas para máxima aceitação
TARGET_DBFS      = -18.0   # nível alvo de normalização
CROSSFADE_MS     = 8000    # crossfade mais longo = transições suaves entre samples
MIN_SAMPLE_SEC   = 10      # aceita qualquer coisa acima de 10s
MIN_ACCEPTED_SEGMENTS = 5  # queremos pelo menos 5 samples diferentes
MAX_SEGMENTS     = 25      # máximo de samples — mais variedade, menos loop repetitivo
QUALITY_REPORT   = "audio_quality_report.json"

# Licenças aceitas no Freesound
LICENSE_MODE = os.environ.get("AUDIO_LICENSE_MODE", "cc_any").lower()

# Pixabay não precisa de API key para busca pública de áudio
PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY", "")

# ──────────────────────────────────────────────
# Queries de busca — muita variedade para chuva
# ──────────────────────────────────────────────

RAIN_QUERIES_FREESOUND = [
    "rain",
    "heavy rain",
    "light rain",
    "rain on roof",
    "rain on window",
    "rain forest",
    "rain thunder",
    "storm rain",
    "rain ambience",
    "rain drops",
    "rain night",
    "gentle rain",
    "tropical rain",
    "rain puddle",
    "rain on leaves",
    "rain on tent",
    "rain on umbrella",
    "rain on car",
    "drizzle",
    "downpour",
    "rain stream",
    "rain field recording",
    "rain relaxing",
    "rain sleep",
    "rain nature",
]

RAIN_QUERIES_PIXABAY = [
    "rain",
    "heavy rain",
    "rain thunder",
    "rain ambience",
    "light rain",
    "rain forest",
    "storm",
    "rain relaxing",
    "rain sleep",
    "gentle rain",
]

# ──────────────────────────────────────────────
# Relatório
# ──────────────────────────────────────────────

def _new_report(category, duration_hours):
    return {
        "category": category,
        "duration_hours": duration_hours,
        "target_dbfs": TARGET_DBFS,
        "accepted": [],
        "rejected": [],
        "warnings": [],
        "final": {},
    }

def _save_report(report):
    with open(QUALITY_REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

# ──────────────────────────────────────────────
# QA mínima — só rejeita o inutilizável
# ──────────────────────────────────────────────

def _audio_quality_check(seg):
    """
    Rejeição mínima: só arquivo completamente silencioso
    ou clipping tão grave que distorce.
    Tudo mais é aceito e normalizado.
    """
    reasons = []

    if len(seg) < MIN_SAMPLE_SEC * 1000:
        reasons.append(f"muito curto ({len(seg)//1000}s < {MIN_SAMPLE_SEC}s mínimo)")

    if seg.dBFS == float("-inf"):
        reasons.append("arquivo completamente silencioso")
        return reasons

    # Só rejeita clipping extremo (acima de -0.3 dBFS de pico)
    if seg.max_dBFS > -0.3:
        reasons.append(f"pico de clipping crítico ({seg.max_dBFS:.1f} dBFS)")

    return reasons


def normalize_segment(seg):
    """Normaliza para TARGET_DBFS com gain máximo de ±12 dB."""
    if seg.dBFS == float("-inf"):
        return seg
    gain = TARGET_DBFS - seg.dBFS
    gain = max(min(gain, 12.0), -12.0)
    return seg.apply_gain(gain)

# ──────────────────────────────────────────────
# Freesound
# ──────────────────────────────────────────────

def _is_allowed_license(sound):
    if LICENSE_MODE in {"any", "cc_any", "allow_any"}:
        return True  # aceita qualquer CC
    license_name = str(sound.get("license", "")).lower()
    return (
        "creative commons 0" in license_name
        or "cc0" in license_name
        or "public domain" in license_name
    )


def freesound_search(query, num=20):
    if not FREESOUND_KEY:
        return []

    try:
        r = requests.get(
            "https://freesound.org/apiv2/search/text/",
            params={
                "query": query,
                "filter": f"duration:[{MIN_SAMPLE_SEC} TO 7200]",
                "fields": "id,name,duration,tags,previews,license,username",
                "page_size": num,
                "sort": "rating_desc",
                "token": FREESOUND_KEY,
            },
            timeout=30,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        # Filtro de licença apenas (sem filtro de tags)
        clean = [s for s in results if _is_allowed_license(s)]
        print(f"  [Freesound] '{query}': {len(clean)}/{len(results)} com licença OK")
        return clean
    except Exception as e:
        print(f"  [Freesound] Erro na busca '{query}': {e}")
        return []


def freesound_download(sound):
    os.makedirs("audio_tmp", exist_ok=True)
    path = f"audio_tmp/fs_{sound['id']}.mp3"
    if os.path.exists(path):
        return path

    url = sound.get("previews", {}).get("preview-hq-mp3")
    if not url:
        raise RuntimeError(f"Sound {sound['id']} sem preview HQ")

    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()
    with open(path, "wb") as f:
        for chunk in r.iter_content(32768):
            f.write(chunk)
    return path


def fetch_freesound_segments(category, report):
    queries = RAIN_QUERIES_FREESOUND if category == "rain" else [category]

    all_sounds = {}
    for query in queries:
        if len(all_sounds) >= MAX_SEGMENTS * 2:
            break
        sounds = freesound_search(query, num=20)
        for s in sounds:
            all_sounds[s["id"]] = s
        time.sleep(0.5)

    print(f"  [Freesound] Total candidatos únicos: {len(all_sounds)}")

    segs = []
    for sound in list(all_sounds.values()):
        if len(segs) >= MAX_SEGMENTS:
            break
        try:
            path = freesound_download(sound)
            seg = AudioSegment.from_file(path)
            reasons = _audio_quality_check(seg)
            if reasons:
                report["rejected"].append({
                    "source": "freesound",
                    "name": sound.get("name"),
                    "reason": "; ".join(reasons),
                })
                print(f"  Rejeitado: {sound.get('name')} — {'; '.join(reasons)}")
                continue

            seg = normalize_segment(seg).set_frame_rate(44100).set_channels(2)
            segs.append(seg)
            report["accepted"].append({
                "source": "freesound",
                "name": sound.get("name"),
                "license": sound.get("license"),
                "duration_s": len(seg) // 1000,
                "dbfs": round(seg.dBFS, 2),
            })
            print(f"  ✓ Freesound: {sound.get('name')} ({len(seg)//1000}s | {seg.dBFS:.1f} dBFS)")

        except Exception as e:
            report["rejected"].append({
                "source": "freesound",
                "name": sound.get("name"),
                "reason": str(e),
            })

    return segs

# ──────────────────────────────────────────────
# Pixabay Audio
# ──────────────────────────────────────────────

def pixabay_search(query, num=20):
    """
    Pixabay Audio API.
    Requer PIXABAY_API_KEY. Gratuita, royalty-free, sem atribuição necessária.
    https://pixabay.com/api/docs/#api_music
    """
    if not PIXABAY_KEY:
        return []

    try:
        r = requests.get(
            "https://pixabay.com/api/music/",
            params={
                "key": PIXABAY_KEY,
                "q": query,
                "per_page": num,
                "category": "nature",  # best for rain sounds
            },
            timeout=30,
        )
        r.raise_for_status()
        hits = r.json().get("hits", [])
        print(f"  [Pixabay] '{query}': {len(hits)} resultados")
        return hits
    except Exception as e:
        print(f"  [Pixabay] Erro na busca '{query}': {e}")
        return []


def pixabay_download(hit):
    os.makedirs("audio_tmp", exist_ok=True)
    pid = hit.get("id")
    path = f"audio_tmp/pb_{pid}.mp3"
    if os.path.exists(path):
        return path

    url = hit.get("audio", {}).get("mp3") or hit.get("url")
    if not url:
        raise RuntimeError(f"Pixabay hit {pid} sem URL de download")

    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()
    with open(path, "wb") as f:
        for chunk in r.iter_content(32768):
            f.write(chunk)
    return path


def fetch_pixabay_segments(category, report):
    queries = RAIN_QUERIES_PIXABAY if category == "rain" else [category]

    all_hits = {}
    for query in queries:
        if len(all_hits) >= MAX_SEGMENTS * 2:
            break
        hits = pixabay_search(query, num=20)
        for h in hits:
            all_hits[h.get("id")] = h
        time.sleep(0.3)

    print(f"  [Pixabay] Total candidatos únicos: {len(all_hits)}")

    segs = []
    for hit in list(all_hits.values()):
        if len(segs) >= MAX_SEGMENTS:
            break
        try:
            path = pixabay_download(hit)
            seg = AudioSegment.from_file(path)
            reasons = _audio_quality_check(seg)
            if reasons:
                report["rejected"].append({
                    "source": "pixabay",
                    "name": hit.get("title", str(hit.get("id"))),
                    "reason": "; ".join(reasons),
                })
                continue

            seg = normalize_segment(seg).set_frame_rate(44100).set_channels(2)
            segs.append(seg)
            report["accepted"].append({
                "source": "pixabay",
                "name": hit.get("title", str(hit.get("id"))),
                "license": "Pixabay License (royalty-free)",
                "duration_s": len(seg) // 1000,
                "dbfs": round(seg.dBFS, 2),
            })
            print(f"  ✓ Pixabay: {hit.get('title', hit.get('id'))} ({len(seg)//1000}s | {seg.dBFS:.1f} dBFS)")

        except Exception as e:
            report["rejected"].append({
                "source": "pixabay",
                "name": str(hit.get("id")),
                "reason": str(e),
            })

    return segs

# ──────────────────────────────────────────────
# Fallback sintético (último recurso)
# ──────────────────────────────────────────────

def _tone(freq, duration_ms, gain_db=-24, fade_ms=80):
    seg = Sine(freq).to_audio_segment(duration=duration_ms).apply_gain(gain_db)
    return seg.fade_in(fade_ms).fade_out(fade_ms)


def _rain_phrase_synthetic(duration_ms=90000):
    """
    Pink noise aproximado — só usado se Freesound e Pixabay falharem.
    Concentrado em 200–3500 Hz, sem agudos que causam chiado.
    """
    base    = WhiteNoise().to_audio_segment(duration=duration_ms).apply_gain(-28).low_pass_filter(2200)
    near    = WhiteNoise().to_audio_segment(duration=duration_ms).apply_gain(-36).high_pass_filter(400).low_pass_filter(3500)
    surface = WhiteNoise().to_audio_segment(duration=duration_ms).apply_gain(-44).high_pass_filter(600).low_pass_filter(2800)
    room    = WhiteNoise().to_audio_segment(duration=duration_ms).apply_gain(-50).low_pass_filter(400)

    phrase = base.overlay(near).overlay(surface).overlay(room)

    for at_ms in range(18000, duration_ms, 30000):
        thunder = _tone(52, 8000, gain_db=-37, fade_ms=2500).low_pass_filter(180)
        phrase = phrase.overlay(thunder, position=at_ms)

    return phrase.fade_in(2500).fade_out(2500)


def build_synthetic_fallback(hours, report):
    target = hours * 3600 * 1000
    print("  Usando fallback sintético (sem fontes externas disponíveis)")
    phrase = normalize_segment(_rain_phrase_synthetic())
    audio = phrase
    while len(audio) < target + CROSSFADE_MS:
        audio = audio.append(phrase, crossfade=CROSSFADE_MS)
    audio = audio[:target].fade_in(3000).fade_out(8000)
    report["warnings"].append("Fallback sintético usado — zero fontes externas disponíveis.")
    return audio

# ──────────────────────────────────────────────
# Loop com alta variedade
# ──────────────────────────────────────────────

def loop_audio(segs, hours):
    """
    Monta o áudio final com todos os segmentos embaralhados,
    repetindo o ciclo até cobrir a duração alvo.
    Com 10–20 segmentos diferentes o loop é quase imperceptível.
    """
    target = hours * 3600 * 1000
    random.shuffle(segs)

    out = segs[0].fade_in(3000)
    i = 1
    while len(out) < target + CROSSFADE_MS:
        next_seg = segs[i % len(segs)]
        # Embaralha de novo a cada ciclo completo para variar a ordem
        if i % len(segs) == 0:
            random.shuffle(segs)
        fade_ms = min(CROSSFADE_MS, len(out) // 4, len(next_seg) // 4)
        out = out.append(next_seg, crossfade=fade_ms)
        i += 1

    return out[:target].fade_out(8000)

# ──────────────────────────────────────────────
# Export de shorts
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
            print(f"  Short {day} salvo: {fname}")

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

    print(f"\n=== Gerando áudio: {category} ({duration}h) ===\n")

    # ── Coleta de segmentos de múltiplas fontes ──
    all_segs = []

    # 1. Freesound
    if FREESOUND_KEY:
        print("── Freesound ──")
        fs_segs = fetch_freesound_segments(category, report)
        all_segs.extend(fs_segs)
        print(f"   {len(fs_segs)} segmentos aceitos do Freesound\n")
    else:
        print("  [Freesound] FREESOUND_API_KEY não configurada — pulando\n")

    # 2. Pixabay
    if PIXABAY_KEY:
        print("── Pixabay ──")
        pb_segs = fetch_pixabay_segments(category, report)
        all_segs.extend(pb_segs)
        print(f"   {len(pb_segs)} segmentos aceitos do Pixabay\n")
    else:
        print("  [Pixabay] PIXABAY_API_KEY não configurada — pulando\n")

    print(f"── Total aceito: {len(all_segs)} segmentos de {report['accepted'].__len__()} fontes ──\n")

    # ── Montagem do áudio ──
    try:
        if len(all_segs) >= MIN_ACCEPTED_SEGMENTS:
            print(f"Montando {duration}h com {len(all_segs)} segmentos...")
            audio = loop_audio(all_segs, duration)
        elif len(all_segs) > 0:
            report["warnings"].append(
                f"Poucos segmentos ({len(all_segs)}) — usando o que tiver. "
                "Adicione PIXABAY_API_KEY para mais variedade."
            )
            print(f"Aviso: apenas {len(all_segs)} segmentos, mas vamos usar.")
            audio = loop_audio(all_segs, duration)
        else:
            print("Nenhuma fonte externa disponível — usando fallback sintético")
            audio = build_synthetic_fallback(duration, report)

        # Export
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
            "segments_used": len(all_segs),
            "bitrate": "192k",
            "status": "ok",
        }
        print(f"\n✓ output_audio.mp3 gerado com {len(all_segs)} segmentos diferentes")

    except Exception as e:
        report["final"]["status"] = "error"
        report["final"]["error"] = str(e)
        raise

    finally:
        _save_report(report)
        print(f"Relatório salvo: {QUALITY_REPORT}")

    print("\nDONE")


if __name__ == "__main__":
    main()
