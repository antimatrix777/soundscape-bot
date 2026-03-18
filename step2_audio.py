"""
ETAPA 2 — Gerador de Áudio
3 fontes de áudio dependendo da categoria:
  • Freesound  → rain, nature, cozy, study, urban (sons ambiente)
  • Jamendo    → jazz (música instrumental real com licença CC)
  • numpy      → focus_noise (gerado matematicamente — qualidade perfeita)

Todas as fontes são 100% gratuitas e royalty-free.
"""
import os, json, glob, time, random, requests
from pydub import AudioSegment
from pydub.effects import normalize
from io import BytesIO
from dotenv import load_dotenv

load_dotenv()
FREESOUND_KEY = os.environ.get("FREESOUND_API_KEY", "")
JAMENDO_KEY   = os.environ.get("JAMENDO_CLIENT_ID", "")

# ─────────────────────────────────────────────────────────
# CONFIGURAÇÕES DE QUALIDADE SONORA
# ─────────────────────────────────────────────────────────
TARGET_LUFS    = -18   # volume alvo (dBFS normalizado)
CROSSFADE_MS   = 8000  # 8s de crossfade — transições suaves e imperceptíveis
FADE_IN_MS     = 20000 # 20s de fade in no início do vídeo
FADE_OUT_MS    = 30000 # 30s de fade out no final
MIN_SAMPLE_SEC = 20    # descartar samples menores que 20 segundos
SAMPLE_RATE    = 44100 # Hz — qualidade CD


# ══════════════════════════════════════════════════════════
# FONTE 1: FREESOUND — sons ambiente
# ══════════════════════════════════════════════════════════

# Tags que indicam sons de baixa qualidade ou inadequados
BAD_TAGS = {
    "voice","speech","talking","conversation","music","song","singing",
    "vocal","lyrics","noise","glitch","error","test","beep","alarm",
    "scream","cry","laugh","crowd","traffic","engine","machine",
    "electric","digital","synth","electronic","distortion",
    "frog","cricket","insect","cicada",  # sons agudos irritantes
}

def freesound_search(query, num=10):
    """Busca sons de alta qualidade no Freesound com filtros de qualidade."""
    if not FREESOUND_KEY:
        raise ValueError("FREESOUND_API_KEY não configurada no .env")

    print(f"   🔍 Freesound: '{query}'")
    r = requests.get("https://freesound.org/apiv2/search/text/", params={
        "query":     query,
        "token":     FREESOUND_KEY,
        "fields":    "id,name,previews,duration,license,tags,avg_rating,num_ratings,num_downloads",
        "filter":    f"duration:[{MIN_SAMPLE_SEC} TO 600] license:(\"Creative Commons 0\" OR \"Attribution\")",
        "sort":      "rating_desc",
        "page_size": 20,  # pega mais e filtra pela qualidade
    }, timeout=30)
    r.raise_for_status()
    results = r.json().get("results", [])

    # Filtra sons com tags problemáticas e avaliação baixa
    clean = []
    for s in results:
        tags = {t.lower() for t in s.get("tags", [])}
        if tags & BAD_TAGS:
            continue
        if s.get("num_ratings", 0) < 2:
            continue
        clean.append(s)

    # Ordena por score combinado (rating × popularidade)
    clean.sort(key=lambda s: s.get("avg_rating", 0) * min(s.get("num_downloads", 0) / 1000, 5), reverse=True)
    chosen = clean[:num]
    print(f"   → {len(results)} encontrados · {len(clean)} limpos · usando top {len(chosen)}")
    return chosen

def freesound_download(sound, folder="audio_tmp"):
    """Baixa preview HQ de um som do Freesound."""
    os.makedirs(folder, exist_ok=True)
    url = sound["previews"].get("preview-hq-mp3") or sound["previews"].get("preview-lq-mp3")
    if not url:
        return None
    path = os.path.join(folder, f"fs_{sound['id']}.mp3")
    if os.path.exists(path):
        return path
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    with open(path, "wb") as f:
        f.write(r.content)
    time.sleep(0.4)
    return path

def build_from_freesound(query, duration_hours):
    """Constrói áudio longo a partir de sons do Freesound."""
    sounds = freesound_search(query, num=10)
    if not sounds:
        raise RuntimeError(f"Nenhum som adequado encontrado para '{query}'")

    # Baixa samples
    files = [freesound_download(s) for s in sounds]
    files = [f for f in files if f]
    if not files:
        raise RuntimeError("Falha ao baixar samples")

    print(f"\n   🔧 Processando {len(files)} samples...")
    segments = []
    for f in files:
        try:
            seg = AudioSegment.from_mp3(f)
            # Converte para mono (consistência)
            seg = seg.set_channels(1).set_frame_rate(SAMPLE_RATE)
            # Normaliza volume
            seg = normalize(seg)
            # Garante duração mínima
            if len(seg) < MIN_SAMPLE_SEC * 1000:
                continue
            segments.append(seg)
            print(f"   ✓ {os.path.basename(f)} — {len(seg)/1000:.0f}s")
        except Exception as e:
            print(f"   ✗ {f}: {e}")

    if not segments:
        raise RuntimeError("Nenhum sample válido após processamento")

    return loop_to_duration(segments, duration_hours)


# ══════════════════════════════════════════════════════════
# FONTE 2: JAMENDO — jazz instrumental
# ══════════════════════════════════════════════════════════

def jamendo_search(tags, num=15):
    """Busca faixas instrumentais no Jamendo."""
    if not JAMENDO_KEY:
        raise ValueError("JAMENDO_CLIENT_ID não configurada no .env")

    print(f"   🎷 Jamendo: tags='{tags}'")
    r = requests.get("https://api.jamendo.com/v3.0/tracks/", params={
        "client_id":    JAMENDO_KEY,
        "format":       "json",
        "limit":        num,
        "tags":         tags,
        "include":      "musicinfo",
        "audioformat":  "mp31",        # mp3 128kbps — qualidade suficiente
        "boost":        "popularity_month",
        "vocalinstrumental": "instrumental",  # APENAS instrumental
        "lang":         "null",               # sem letras
    }, timeout=30)
    r.raise_for_status()
    results = r.json().get("results", [])
    print(f"   → {len(results)} faixas encontradas")
    return results

def jamendo_download(track, folder="audio_tmp"):
    """Baixa faixa do Jamendo."""
    os.makedirs(folder, exist_ok=True)
    url = track.get("audio")
    if not url:
        return None
    path = os.path.join(folder, f"jm_{track['id']}.mp3")
    if os.path.exists(path):
        return path
    print(f"   ⬇ {track.get('name','')[:45]}...")
    r = requests.get(url, timeout=120, stream=True)
    r.raise_for_status()
    with open(path, "wb") as f:
        for chunk in r.iter_content(32768):
            f.write(chunk)
    time.sleep(0.5)
    return path

def build_from_jamendo(tags, duration_hours):
    """Constrói mix de jazz a partir do Jamendo."""
    tracks = jamendo_search(tags, num=15)
    if not tracks:
        raise RuntimeError(f"Nenhuma faixa encontrada para '{tags}'")

    random.shuffle(tracks)
    files = []
    for t in tracks:
        f = jamendo_download(t)
        if f:
            files.append(f)
        if len(files) >= 10:
            break

    print(f"\n   🔧 Processando {len(files)} faixas jazz...")
    segments = []
    for f in files:
        try:
            seg = AudioSegment.from_mp3(f)
            seg = seg.set_channels(2).set_frame_rate(SAMPLE_RATE)
            seg = normalize(seg)
            if len(seg) < 60_000:  # ignora faixas menores que 1 min
                continue
            segments.append(seg)
            print(f"   ✓ {os.path.basename(f)} — {len(seg)/60000:.1f} min")
        except Exception as e:
            print(f"   ✗ {f}: {e}")

    if not segments:
        raise RuntimeError("Nenhuma faixa jazz válida")

    return loop_to_duration(segments, duration_hours)


# ══════════════════════════════════════════════════════════
# FONTE 3: NUMPY — ruídos de foco gerados matematicamente
# Qualidade perfeita, sem dependência de API
# ══════════════════════════════════════════════════════════

def generate_white_noise(duration_ms, sample_rate=SAMPLE_RATE):
    """Gera ruído branco puro."""
    import numpy as np
    n_samples = int(sample_rate * duration_ms / 1000)
    samples = np.random.normal(0, 0.15, n_samples)
    samples = np.clip(samples, -1.0, 1.0)
    pcm = (samples * 32767).astype(np.int16)
    return AudioSegment(pcm.tobytes(), frame_rate=sample_rate, sample_width=2, channels=1)

def generate_brown_noise(duration_ms, sample_rate=SAMPLE_RATE):
    """
    Gera ruído marrom (Brownian noise / 1/f²).
    Sons graves, quentes — os mais relaxantes para foco e sono.
    """
    import numpy as np
    n_samples = int(sample_rate * duration_ms / 1000)
    white = np.random.normal(0, 1, n_samples)
    # Integração cumulativa = ruído marrom
    brown = np.cumsum(white)
    # Normaliza para evitar drift
    brown = brown - np.mean(brown)
    # Aplica janela para evitar clipping gradual
    brown = brown / (np.max(np.abs(brown)) + 1e-8)
    brown *= 0.5
    pcm = (brown * 32767).astype(np.int16)
    return AudioSegment(pcm.tobytes(), frame_rate=sample_rate, sample_width=2, channels=1)

def generate_pink_noise(duration_ms, sample_rate=SAMPLE_RATE):
    """
    Gera ruído rosa (1/f) — entre branco e marrom.
    Muito usado para foco e concentração.
    """
    import numpy as np
    n_samples = int(sample_rate * duration_ms / 1000)
    # Algoritmo de Voss-McCartney simplificado via FFT
    f = np.fft.rfftfreq(n_samples, d=1/sample_rate)
    f[0] = 1  # evita divisão por zero
    power = 1 / np.sqrt(f)
    power[0] = 0
    phase = np.random.uniform(0, 2 * np.pi, len(f))
    spectrum = power * np.exp(1j * phase)
    pink = np.fft.irfft(spectrum, n=n_samples)
    pink = pink / (np.max(np.abs(pink)) + 1e-8)
    pink *= 0.5
    pcm = (pink * 32767).astype(np.int16)
    return AudioSegment(pcm.tobytes(), frame_rate=sample_rate, sample_width=2, channels=1)

def build_noise(noise_type, duration_hours):
    """Gera ruído de foco matematicamente."""
    import numpy as np

    print(f"   ⚙️  Gerando {noise_type} noise ({duration_hours}h)...")

    # Gera em blocos de 10 minutos para não explodir a RAM
    block_ms = 10 * 60 * 1000
    target_ms = duration_hours * 3600 * 1000
    n_blocks  = (target_ms // block_ms) + 1

    generators = {
        "white": generate_white_noise,
        "brown": generate_brown_noise,
        "pink":  generate_pink_noise,
    }
    gen_fn = generators.get(noise_type, generate_brown_noise)

    combined = AudioSegment.empty()
    for i in range(n_blocks):
        block = gen_fn(block_ms)
        if len(combined) > 0:
            combined = combined.append(block, crossfade=2000)
        else:
            combined += block
        pct = min(100, len(combined) / target_ms * 100)
        print(f"   🔄 {pct:.0f}%", end="\r")

    combined = combined[:target_ms]
    print(f"   ✓ {noise_type} noise gerado ({len(combined)/60000:.0f} min)")
    return combined


# ══════════════════════════════════════════════════════════
# MONTAGEM FINAL — comum a todas as fontes
# ══════════════════════════════════════════════════════════

def loop_to_duration(segments, duration_hours):
    """Loopa segments com crossfade suave até atingir a duração alvo."""
    target_ms = duration_hours * 3600 * 1000
    random.shuffle(segments)
    combined = AudioSegment.empty()
    i = 0
    while len(combined) < target_ms:
        seg = segments[i % len(segments)]
        if len(combined) > 0:
            combined = combined.append(seg, crossfade=CROSSFADE_MS)
        else:
            combined += seg
        i += 1
        pct = min(100, len(combined) / target_ms * 100)
        if i % 5 == 0:
            print(f"   🔄 {pct:.0f}% ({len(combined)//60000} min)")

    return combined[:target_ms]

def finalize_audio(combined, output="output_audio.mp3"):
    """Aplica fade in/out, normaliza e exporta."""
    print(f"\n   ✨ Finalizando áudio...")
    combined = combined.fade_in(FADE_IN_MS).fade_out(FADE_OUT_MS)
    combined = normalize(combined)
    # Aplica ganho leve para atingir target LUFS (aproximação com pydub)
    current_db = combined.dBFS
    if current_db < TARGET_LUFS - 3:
        combined = combined + (TARGET_LUFS - current_db)
    combined = combined.set_frame_rate(SAMPLE_RATE)
    combined.export(output, format="mp3", bitrate="192k",
                    tags={"artist": "Comfort Sounds", "album": "Ambient Collection"})
    size_mb = os.path.getsize(output) / (1024 * 1024)
    print(f"   ✅ Exportado: {output} ({size_mb:.0f}MB, {len(combined)/3600000:.1f}h)")
    return output

def cleanup_tmp():
    for f in glob.glob("audio_tmp/*.mp3"):
        try: os.remove(f)
        except: pass

# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════

def main():
    meta_files = sorted(glob.glob("metadata_*.json"), key=os.path.getmtime, reverse=True)
    if not meta_files:
        raise FileNotFoundError("Execute step1_metadata.py primeiro")

    with open(meta_files[0]) as f:
        metadata = json.load(f)

    category      = metadata["category"]
    duration      = metadata["duration_hours"]
    theme_data    = metadata.get("theme_data", {})

    print(f"\n🎵 Gerando áudio: {metadata['theme']} ({duration}h)")
    print(f"   Categoria: {category}")

    # ── Roteamento por categoria ──────────────────────────
    if category == "focus_noise":
        noise_type = theme_data.get("noise_type", "brown")
        combined = build_noise(noise_type, duration)

    elif category == "jazz":
        tags = theme_data.get("tags", "jazz instrumental")
        combined = build_from_jamendo(tags, duration)

    else:
        # rain, nature, cozy, study, urban → Freesound
        query = theme_data.get("query", metadata["theme"])
        combined = build_from_freesound(query, duration)

    # ── Para jazz: mistura com ambiente suave se disponível ──
    # (ex: jazz + chuva leve de fundo = mais confortável)
    if category == "jazz" and theme_data.get("theme", "").find("rain") >= 0:
        try:
            print("\n   🌧 Adicionando chuva suave de fundo para o jazz...")
            rain_sounds = freesound_search("gentle rain soft background", num=3)
            if rain_sounds:
                rain_files = [freesound_download(s) for s in rain_sounds[:2]]
                rain_files = [f for f in rain_files if f]
                if rain_files:
                    rain_seg = AudioSegment.from_mp3(rain_files[0])
                    rain_seg = rain_seg.set_channels(2).set_frame_rate(SAMPLE_RATE)
                    rain_seg = normalize(rain_seg) - 12  # chuva 12dB mais baixo que o jazz
                    # Loopa a chuva até a duração do combined
                    while len(rain_seg) < len(combined):
                        rain_seg = rain_seg.append(rain_seg, crossfade=5000)
                    rain_seg = rain_seg[:len(combined)]
                    combined = combined.overlay(rain_seg)
                    print("   ✓ Chuva suave adicionada")
        except Exception as e:
            print(f"   ⚠ Chuva de fundo não adicionada: {e}")

    finalize_audio(combined, "output_audio.mp3")
    cleanup_tmp()

if __name__ == "__main__":
    main()
