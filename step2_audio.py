# STEP 2 - Audio Generator (Nocturne Noise)
#
# v5 — FIX DE PERFORMANCE (timeout de 90min)
#
# CAUSA DO TIMEOUT (v4):
#   build_layered_audio() montava as 8h inteiras usando AudioSegment.append()
#   em loop dentro do Python. Cada append copia o buffer INTEIRO já construido
#   ate aquele ponto (nao e O(1)). Para 8h de audio (~5GB de PCM) isso significa
#   ~640 appends, copiando ~1.6 TB de dados no total = travamento.
#
# FIX:
#   1. Monta um "master" curto (~35min) com a mesma mistura em camadas
#      (base + accent overlays) — rapido, escala pequena, sem problema.
#   2. Torna o master um loop perfeito (crossfade do fim com o inicio).
#   3. Usa ffmpeg (-stream_loop) pra repetir o master ate a duracao alvo
#      (8h) — operacao nativa de stream, nao copia buffers gigantes em
#      memoria Python. Isso reduz o tempo de montagem de horas para segundos.
#   4. Shorts diarios sao extraidos com ffmpeg -ss/-t direto do output final,
#      sem carregar o arquivo de 8h inteiro de volta pro pydub.
#
# Continua: Freesound only, sem filtros de conteudo (so rejeita silencio
# total e clipping critico).

import glob
import json
import os
import random
import shutil
import subprocess
import time
import requests
from pydub import AudioSegment
from pydub.generators import Sine, WhiteNoise

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(): return None

load_dotenv()

FREESOUND_KEY   = os.environ.get("FREESOUND_API_KEY", "")
TARGET_DBFS     = -18.0
CROSSFADE_MS    = 8000
LOOP_FADE_MS    = 6000     # crossfade do fim do master com o inicio (loop seamless)
MIN_SAMPLE_SEC  = 8
MAX_SEGMENTS    = 30
# Master curto: monta rapido em Python, depois o ffmpeg repete ate a duracao alvo
MASTER_MINUTES  = float(os.environ.get("AUDIO_MASTER_MINUTES", "35"))
QUALITY_REPORT  = "audio_quality_report.json"

FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"

RAIN_QUERIES = [
    "rain", "heavy rain", "light rain", "rain on roof", "rain on window",
    "rain forest", "rain thunder", "thunderstorm", "storm rain", "rain ambience",
    "rain drops", "rain night", "gentle rain", "tropical rain", "rain puddle",
    "rain on leaves", "rain on tent", "rain on car", "drizzle", "downpour",
    "rain stream", "rain relaxing", "rain sleep", "rain nature",
    "rain meditation", "rain lofi", "rain white noise", "rainstorm",
    "rain outside", "rain indoors",
]

CATEGORY_QUERIES = {
    "rain": RAIN_QUERIES,
    "lofi": ["lofi", "vinyl crackle", "ambient lo-fi", "tape hiss", "room tone", "cafe ambience"],
    "jazz": ["jazz piano", "soft jazz", "jazz trio", "jazz bass", "brush drums jazz", "jazz bar"],
}

# ──────────────────────────────────────────────
# Relatorio
# ──────────────────────────────────────────────

def _new_report(category, duration_hours):
    return {
        "category": category, "duration_hours": duration_hours,
        "master_minutes": MASTER_MINUTES,
        "accepted": [], "rejected": [], "warnings": [], "final": {},
    }

def _save_report(report):
    with open(QUALITY_REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

# ──────────────────────────────────────────────
# QA minima
# ──────────────────────────────────────────────

def _is_usable(seg):
    if len(seg) < MIN_SAMPLE_SEC * 1000:
        return False, f"muito curto ({len(seg)//1000}s)"
    if seg.dBFS == float("-inf"):
        return False, "silencio total"
    if seg.max_dBFS > -0.1:
        return False, f"clipping critico ({seg.max_dBFS:.1f} dBFS)"
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
                "page_size": num, "sort": "rating_desc", "token": FREESOUND_KEY,
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
        time.sleep(0.3)

    print(f"\n  Total candidatos unicos: {len(all_sounds)}")

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
                continue
            seg = normalize(seg)
            segs.append(seg)
            report["accepted"].append({
                "name": sound.get("name"), "license": sound.get("license"),
                "duration_s": len(seg) // 1000, "dbfs": round(seg.dBFS, 2),
            })
            print(f"  OK {sound.get('name')} ({len(seg)//1000}s | {seg.dBFS:.1f} dBFS)")
        except Exception as e:
            report["rejected"].append({"name": sound.get("name"), "reason": str(e)})

    return segs

# ──────────────────────────────────────────────
# Master em camadas (BOUNDED — rapido)
# ──────────────────────────────────────────────

def build_layered_master(segs, master_minutes):
    """
    Monta um master de duracao FIXA E CURTA (ex: 35min) misturando samples
    em camadas base/accent. Como a duracao e limitada, os appends do pydub
    ficam baratos (poucas dezenas de iteracoes, nao centenas).
    """
    target_ms = int(master_minutes * 60 * 1000)

    segs_sorted = sorted(segs, key=lambda s: len(s), reverse=True)
    base_count = max(2, len(segs_sorted) * 40 // 100)
    base_pool = segs_sorted[:base_count]
    accent_pool = segs_sorted[base_count:] or segs_sorted

    print(f"  Base: {len(base_pool)} samples | Accent: {len(accent_pool)} samples")

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
    base_track = base_track[:target_ms].apply_gain(-2.0)

    if accent_pool:
        num_accents = max(len(accent_pool), target_ms // (5 * 60 * 1000))
        print(f"  Posicionando {num_accents} accents no master...")
        for _ in range(num_accents):
            accent_seg = random.choice(accent_pool)
            accent_seg = accent_seg.apply_gain(random.uniform(-3.0, 1.0))
            max_pos = max(0, target_ms - len(accent_seg) - 5000)
            if max_pos <= 0:
                continue
            position = random.randint(0, max_pos)
            fade = min(2000, len(accent_seg) // 4)
            accent_seg = accent_seg.fade_in(fade).fade_out(fade)
            base_track = base_track.overlay(accent_seg, position=position)

    return normalize(base_track)


def make_seamless_loop(seg, fade_ms=LOOP_FADE_MS):
    """
    Prepara o master para ser repetido pelo ffmpeg sem 'click' na emenda:
    aplica fade_out suave no final e fade_in suave no inicio. Quando o
    ffmpeg concatena copias do arquivo, a transicao vira uma respiracao
    natural em vez de um corte abrupto.
    """
    if len(seg) <= fade_ms * 2:
        return seg
    return seg.fade_in(fade_ms).fade_out(fade_ms)

# ──────────────────────────────────────────────
# Fallback sintetico (tambem limitado a MASTER_MINUTES)
# ──────────────────────────────────────────────

def _tone(freq, duration_ms, gain_db=-24, fade_ms=80):
    return Sine(freq).to_audio_segment(duration=duration_ms).apply_gain(gain_db).fade_in(fade_ms).fade_out(fade_ms)

def build_synthetic_master(master_minutes, report):
    target_ms = int(master_minutes * 60 * 1000)
    print("  Fallback sintetico (pink noise aproximado)")

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
    audio = phrase
    while len(audio) < target_ms + CROSSFADE_MS:
        audio = audio.append(phrase, crossfade=CROSSFADE_MS)

    report["warnings"].append("Fallback sintetico usado — FREESOUND_API_KEY ausente ou zero resultados.")
    return audio[:target_ms]

# ──────────────────────────────────────────────
# ffmpeg: loop do master ate a duracao alvo (RAPIDO)
# ──────────────────────────────────────────────

def loop_master_with_ffmpeg(master_path, target_seconds, output_path):
    """
    Repete o master.wav ate atingir target_seconds usando -stream_loop.
    Isso e uma operacao de stream nativa do ffmpeg — nao copia buffers
    gigantes em memoria Python. Para 8h isso leva segundos, nao horas.
    """
    cmd = [
        FFMPEG_BIN, "-y",
        "-stream_loop", "-1",
        "-i", master_path,
        "-t", str(target_seconds),
        "-acodec", "libmp3lame",
        "-b:a", "192k",
        "-ar", "44100",
        "-ac", "2",
        output_path,
    ]
    print(f"  ffmpeg loop: {master_path} -> {target_seconds}s -> {output_path}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou: {result.stderr[-1500:]}")


def extract_clip_with_ffmpeg(source_path, start_s, duration_s, output_path):
    """Extrai um trecho direto do arquivo final via ffmpeg, sem carregar tudo no pydub."""
    cmd = [
        FFMPEG_BIN, "-y",
        "-ss", str(start_s),
        "-t", str(duration_s),
        "-i", source_path,
        "-af", "afade=t=in:st=0:d=1.5,afade=t=out:st={}:d=1.5".format(max(0, duration_s - 1.5)),
        "-acodec", "libmp3lame", "-b:a", "192k", "-ar", "44100",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"  Aviso: falha ao extrair short {output_path}: {result.stderr[-300:]}")
        return False
    return True


def export_shorts_pool(final_audio_path, total_seconds):
    if total_seconds <= 120:
        return
    for day in range(1, 8):
        start_s = 60 + (day - 1) * 300
        if start_s + 60 < total_seconds:
            fname = f"short_audio_{day}.mp3"
            if extract_clip_with_ffmpeg(final_audio_path, start_s, 55, fname):
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
    duration_hours = data["duration_hours"]
    target_seconds = duration_hours * 3600
    report = _new_report(category, duration_hours)

    print(f"\n=== Nocturne Noise — Audio Builder v5 (fix timeout) ===")
    print(f"    Categoria      : {category}")
    print(f"    Duracao alvo   : {duration_hours}h")
    print(f"    Master (build) : {MASTER_MINUTES}min\n")

    try:
        segs = []
        if FREESOUND_KEY:
            segs = fetch_all_segments(category, report)
            print(f"\n  {len(segs)} samples aceitos")
        else:
            print("  FREESOUND_API_KEY nao configurada")

        t0 = time.time()
        if len(segs) >= 2:
            print(f"\nMontando master de {MASTER_MINUTES}min com {len(segs)} samples...")
            master = build_layered_master(segs, MASTER_MINUTES)
        elif len(segs) == 1:
            report["warnings"].append("Apenas 1 sample — master repete o mesmo sample com crossfade.")
            target_ms = int(MASTER_MINUTES * 60 * 1000)
            master = segs[0]
            while len(master) < target_ms:
                master = master.append(segs[0], crossfade=CROSSFADE_MS)
            master = master[:target_ms]
        else:
            master = build_synthetic_master(MASTER_MINUTES, report)

        master = make_seamless_loop(master)
        print(f"  Master pronto em {time.time()-t0:.1f}s ({len(master)/1000:.0f}s de audio)")

        master_path = "audio_master.wav"
        master.export(master_path, format="wav")

        t1 = time.time()
        loop_master_with_ffmpeg(master_path, target_seconds, "output_audio.mp3")
        print(f"  Loop ate {duration_hours}h feito em {time.time()-t1:.1f}s via ffmpeg")

        export_shorts_pool("output_audio.mp3", target_seconds)

        report["final"] = {
            "output_file": "output_audio.mp3",
            "duration_s": target_seconds,
            "master_minutes": MASTER_MINUTES,
            "segments_used": len(segs),
            "bitrate": "192k",
            "status": "ok",
        }
        print(f"\nOK output_audio.mp3 — {len(segs)} samples, {duration_hours}h, 192k")

    except Exception as e:
        report["final"]["status"] = "error"
        report["final"]["error"] = str(e)
        raise
    finally:
        _save_report(report)
        print(f"Relatorio: {QUALITY_REPORT}")

    print("\nDONE")


if __name__ == "__main__":
    main()
