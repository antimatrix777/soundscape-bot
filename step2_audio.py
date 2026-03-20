"""
ETAPA 2 — Gerador de Áudio
4 fontes em cascata por categoria:

  Ambiente (rain/nature/cozy/study/urban):
    1. Freesound    → sons curados com filtros de qualidade
    2. Pixabay Audio → sons moderados, mesma key da API de fotos
    3. Internet Archive → acervo público, fallback final

  Jazz:
    1. Jamendo  → música instrumental CC (com fallback de tags)
    2. FMA      → Free Music Archive, jazz de alta qualidade
    3. Freesound → fallback genérico

  Foco (focus_noise):
    → Gerado matematicamente com numpy (qualidade perfeita, sem API)
"""
import os, json, glob, time, random, requests
from pydub import AudioSegment
from pydub.effects import normalize
from io import BytesIO
from dotenv import load_dotenv

load_dotenv()

FREESOUND_KEY  = os.environ.get("FREESOUND_API_KEY", "")
JAMENDO_KEY    = os.environ.get("JAMENDO_CLIENT_ID", "")
PIXABAY_KEY    = os.environ.get("PIXABAY_API_KEY", "")
# FMA API foi descontinuada — usando ccMixter (sem key)

TARGET_LUFS    = -18
CROSSFADE_MS   = 8000
FADE_IN_MS     = 20000
FADE_OUT_MS    = 30000
MIN_SAMPLE_SEC = 20
SAMPLE_RATE    = 44100

BAD_TAGS = {
    "voice","speech","talking","conversation","music","song","singing",
    "vocal","lyrics","noise","glitch","error","test","beep","alarm",
    "scream","cry","laugh","crowd","traffic","engine","machine",
    "electric","digital","synth","electronic","distortion",
    "frog","cricket","insect","cicada",
}


# ══════════════════════════════════════════════════════════
# FONTE 1: FREESOUND
# ══════════════════════════════════════════════════════════
def freesound_search(query, num=10):
    if not FREESOUND_KEY:
        raise ValueError("FREESOUND_API_KEY nao configurada")
    print(f"   [Freesound] '{query}'")
    r = requests.get("https://freesound.org/apiv2/search/text/", params={
        "query":     query,
        "token":     FREESOUND_KEY,
        "fields":    "id,name,previews,duration,license,tags,avg_rating,num_ratings,num_downloads",
        "filter":    f"duration:[{MIN_SAMPLE_SEC} TO 600] license:(\"Creative Commons 0\" OR \"Attribution\")",
        "sort":      "rating_desc",
        "page_size": 20,
    }, timeout=30)
    r.raise_for_status()
    results = r.json().get("results", [])
    clean = [s for s in results
             if not ({t.lower() for t in s.get("tags",[])} & BAD_TAGS)
             and s.get("num_ratings",0) >= 2]
    clean.sort(key=lambda s: s.get("avg_rating",0) * min(s.get("num_downloads",0)/1000,5), reverse=True)
    chosen = clean[:num]
    print(f"   -> {len(results)} encontrados, {len(chosen)} aprovados")
    return chosen

def freesound_download(sound, folder="audio_tmp"):
    os.makedirs(folder, exist_ok=True)
    url = sound["previews"].get("preview-hq-mp3") or sound["previews"].get("preview-lq-mp3")
    if not url: return None
    path = os.path.join(folder, f"fs_{sound['id']}.mp3")
    if os.path.exists(path): return path
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    with open(path,"wb") as f: f.write(r.content)
    time.sleep(0.4)
    return path

def build_from_freesound(query, duration_hours):
    sounds = freesound_search(query, num=10)
    if not sounds:
        raise RuntimeError(f"Freesound: nenhum som para '{query}'")
    files = [freesound_download(s) for s in sounds]
    files = [f for f in files if f]
    if not files:
        raise RuntimeError("Freesound: falha no download")
    return _process_and_loop(files, duration_hours, channels=1)


# ══════════════════════════════════════════════════════════
# FONTE 2: PIXABAY AUDIO
# Sons curados com moderação humana — menos lixo que Freesound
# Mesma key da API do Pixabay (PIXABAY_API_KEY)
# pixabay.com/service/about/api → loga e pega a key
# ══════════════════════════════════════════════════════════
def pixabay_audio_search(query, num=10):
    if not PIXABAY_KEY:
        raise ValueError("PIXABAY_API_KEY nao configurada")
    print(f"   [Pixabay Audio] '{query}'")
    r = requests.get("https://pixabay.com/api/sounds/", params={
        "key":      PIXABAY_KEY,
        "q":        query,
        "per_page": num,
    }, timeout=30)
    r.raise_for_status()
    hits = r.json().get("hits", [])
    print(f"   -> {len(hits)} sons encontrados")
    return hits

def pixabay_audio_download(hit, folder="audio_tmp"):
    os.makedirs(folder, exist_ok=True)
    url = hit.get("audio") or hit.get("audioURL") or hit.get("previews",{}).get("audio-hq-mp3")
    if not url:
        # tenta campo generico
        for k,v in hit.items():
            if isinstance(v, str) and v.endswith(".mp3"):
                url = v
                break
    if not url: return None
    path = os.path.join(folder, f"pb_{hit['id']}.mp3")
    if os.path.exists(path): return path
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    with open(path,"wb") as f: f.write(r.content)
    time.sleep(0.4)
    return path

def build_from_pixabay(query, duration_hours):
    hits = pixabay_audio_search(query, num=10)
    if not hits:
        raise RuntimeError(f"Pixabay Audio: nenhum som para '{query}'")
    files = [pixabay_audio_download(h) for h in hits]
    files = [f for f in files if f]
    if not files:
        raise RuntimeError("Pixabay Audio: falha no download")
    return _process_and_loop(files, duration_hours, channels=1)


# ══════════════════════════════════════════════════════════
# FONTE 3: INTERNET ARCHIVE — fallback ambiente
# Sem API key — acervo público massivo
# ══════════════════════════════════════════════════════════
def archive_search(query, num=8):
    print(f"   [Internet Archive] '{query}'")
    r = requests.get("https://archive.org/advancedsearch.php", params={
        "q":      f"{query} AND mediatype:audio AND format:MP3",
        "fl":     "identifier,title,avg_rating",
        "sort":   "avg_rating desc",
        "rows":   num,
        "output": "json",
    }, timeout=30)
    r.raise_for_status()
    docs = r.json().get("response",{}).get("docs",[])
    print(f"   -> {len(docs)} itens encontrados")
    return docs

def archive_download(doc, folder="audio_tmp"):
    os.makedirs(folder, exist_ok=True)
    identifier = doc.get("identifier","")
    if not identifier: return None
    # Busca arquivos MP3 do item
    try:
        r = requests.get(f"https://archive.org/metadata/{identifier}", timeout=20)
        files = r.json().get("files",[])
        mp3s = [f for f in files if f.get("name","").endswith(".mp3")]
        if not mp3s: return None
        # Pega o menor MP3 (preview mais curto)
        mp3s.sort(key=lambda f: int(f.get("size",9999999999)))
        target = mp3s[0]
        url = f"https://archive.org/download/{identifier}/{target['name']}"
        path = os.path.join(folder, f"ia_{identifier[:20]}.mp3")
        if os.path.exists(path): return path
        print(f"   -> Baixando: {target['name'][:40]}")
        r2 = requests.get(url, timeout=120, stream=True)
        r2.raise_for_status()
        with open(path,"wb") as f:
            for chunk in r2.iter_content(32768): f.write(chunk)
        return path
    except Exception as e:
        print(f"   IA erro: {e}")
        return None

def build_from_archive(query, duration_hours):
    docs = archive_search(query, num=8)
    if not docs:
        raise RuntimeError(f"Archive: nenhum item para '{query}'")
    files = [archive_download(d) for d in docs]
    files = [f for f in files if f]
    if not files:
        raise RuntimeError("Archive: falha no download")
    return _process_and_loop(files, duration_hours, channels=1)


# ══════════════════════════════════════════════════════════
# FONTE 4: JAMENDO — jazz instrumental
# developer.jamendo.com → gratis, sem cartao
# ══════════════════════════════════════════════════════════
def jamendo_search(tags, num=15):
    if not JAMENDO_KEY:
        raise ValueError("JAMENDO_CLIENT_ID nao configurada")
    seen = set()
    attempts = [t for t in [tags,"jazz","piano","acoustic","relaxing","instrumental"]
                if not (t in seen or seen.add(t))]
    for attempt in attempts:
        print(f"   [Jamendo] tags='{attempt}'")
        try:
            r = requests.get("https://api.jamendo.com/v3.0/tracks/", params={
                "client_id":         JAMENDO_KEY,
                "format":            "json",
                "limit":             num,
                "tags":              attempt,
                "audioformat":       "mp31",
                "boost":             "popularity_month",
                "vocalinstrumental": "instrumental",
            }, timeout=30)
            r.raise_for_status()
            results = r.json().get("results",[])
            print(f"   -> {len(results)} faixas")
            if results: return results
        except Exception as e:
            print(f"   Jamendo erro '{attempt}': {e}")
    return []

def jamendo_download(track, folder="audio_tmp"):
    os.makedirs(folder, exist_ok=True)
    url = track.get("audio")
    if not url: return None
    path = os.path.join(folder, f"jm_{track['id']}.mp3")
    if os.path.exists(path): return path
    print(f"   -> {track.get('name','')[:45]}")
    r = requests.get(url, timeout=120, stream=True)
    r.raise_for_status()
    with open(path,"wb") as f:
        for chunk in r.iter_content(32768): f.write(chunk)
    time.sleep(0.5)
    return path

def build_from_jamendo(tags, duration_hours):
    tracks = jamendo_search(tags, num=15)
    if not tracks:
        raise RuntimeError(f"Jamendo: nenhuma faixa para '{tags}'")
    random.shuffle(tracks)
    files = []
    for t in tracks:
        f = jamendo_download(t)
        if f: files.append(f)
        if len(files) >= 10: break
    if not files:
        raise RuntimeError("Jamendo: falha no download")
    return _process_and_loop(files, duration_hours, channels=2)


# ══════════════════════════════════════════════════════════
# FONTE 5: CCMIXTER — jazz/ambient fallback
# ccmixter.org/api — sem API key, CC license
# Especializado em música instrumental e ambient
# ══════════════════════════════════════════════════════════
def ccmixter_search(query="jazz instrumental", num=15):
    """Busca faixas instrumentais no ccMixter — sem API key."""
    print(f"   [ccMixter] '{query}'")
    try:
        r = requests.get("http://ccmixter.org/api/query", params={
            "tags":         query,
            "type":         "instrumentals",
            "format":       "json",
            "limit":        num,
            "sort":         "rank",
        }, timeout=30)
        r.raise_for_status()
        results = r.json() if isinstance(r.json(), list) else []
        print(f"   -> {len(results)} faixas ccMixter")
        return results
    except Exception as e:
        print(f"   ccMixter erro: {e}")
        return []

def ccmixter_download(track, folder="audio_tmp"):
    os.makedirs(folder, exist_ok=True)
    # ccMixter retorna campo upload_element_id ou files
    files_list = track.get("files", [])
    url = None
    for f in files_list:
        if f.get("file_format_info",{}).get("default_file","").endswith(".mp3"):
            url = f.get("download_url") or f.get("file_page_url")
            break
    if not url:
        url = track.get("download_url") or track.get("file_url")
    if not url: return None
    tid = str(track.get("upload_id", random.randint(1000,9999)))
    path = os.path.join(folder, f"cc_{tid}.mp3")
    if os.path.exists(path): return path
    print(f"   -> {track.get('upload_name','')[:45]}")
    try:
        r = requests.get(url, timeout=120, stream=True, allow_redirects=True)
        r.raise_for_status()
        with open(path,"wb") as f:
            for chunk in r.iter_content(32768): f.write(chunk)
        if os.path.getsize(path) < 10000:
            os.remove(path)
            return None
        return path
    except Exception as e:
        print(f"   ccMixter download erro: {e}")
        return None

def build_from_ccmixter(query, duration_hours):
    tracks = ccmixter_search(query, num=15)
    if not tracks:
        raise RuntimeError(f"ccMixter: nenhuma faixa para '{query}'")
    random.shuffle(tracks)
    files = []
    for t in tracks:
        f = ccmixter_download(t)
        if f: files.append(f)
        if len(files) >= 10: break
    if not files:
        raise RuntimeError("ccMixter: falha no download")
    return _process_and_loop(files, duration_hours, channels=2)


# ══════════════════════════════════════════════════════════
# FONTE 6: NUMPY — ruidos de foco (gerado localmente)
# ══════════════════════════════════════════════════════════
def generate_brown_noise(duration_ms):
    """FIX: pseudo-stereo — L and R channels with slightly different seeds."""
    import numpy as np
    n = int(SAMPLE_RATE * duration_ms / 1000)
    def _brown(seed_offset=0):
        rng   = np.random.default_rng(int(duration_ms) + seed_offset)
        white = rng.normal(0, 1, n)
        b     = np.cumsum(white)
        b    -= np.mean(b)
        b    /= (np.max(np.abs(b)) + 1e-8)
        return (b * 0.5 * 32767).astype(np.int16)
    L = _brown(0)
    R = _brown(7)  # slightly different — creates natural stereo width
    stereo = np.column_stack([L, R]).flatten()
    return AudioSegment(stereo.tobytes(), frame_rate=SAMPLE_RATE, sample_width=2, channels=2)

def generate_white_noise(duration_ms):
    import numpy as np
    n = int(SAMPLE_RATE * duration_ms / 1000)
    samples = np.random.normal(0, 0.15, n)
    samples = np.clip(samples, -1, 1)
    return AudioSegment((samples * 32767).astype(np.int16).tobytes(),
                        frame_rate=SAMPLE_RATE, sample_width=2, channels=1)

def generate_pink_noise(duration_ms):
    import numpy as np
    n = int(SAMPLE_RATE * duration_ms / 1000)
    f = np.fft.rfftfreq(n, d=1/SAMPLE_RATE)
    f[0] = 1
    power = 1 / np.sqrt(f); power[0] = 0
    phase = np.random.uniform(0, 2*np.pi, len(f))
    pink = np.fft.irfft(power * np.exp(1j*phase), n=n)
    pink /= (np.max(np.abs(pink)) + 1e-8)
    pink *= 0.5
    return AudioSegment((pink * 32767).astype(np.int16).tobytes(),
                        frame_rate=SAMPLE_RATE, sample_width=2, channels=1)

def build_noise(noise_type, duration_hours):
    print(f"   Gerando {noise_type} noise ({duration_hours}h)...")
    block_ms  = 10 * 60 * 1000
    target_ms = duration_hours * 3600 * 1000
    n_blocks  = (target_ms // block_ms) + 1
    gen = {"white": generate_white_noise, "brown": generate_brown_noise, "pink": generate_pink_noise}
    fn  = gen.get(noise_type, generate_brown_noise)
    combined = AudioSegment.empty()
    for i in range(n_blocks):
        block = fn(block_ms)
        combined = combined.append(block, crossfade=2000) if len(combined) > 0 else combined + block
        print(f"   {min(100, len(combined)/target_ms*100):.0f}%", end="\r")
    print()
    return combined[:target_ms]


# ══════════════════════════════════════════════════════════
# PROCESSAMENTO COMUM
# ══════════════════════════════════════════════════════════
def _process_and_loop(files, duration_hours, channels=1):
    target_ms = duration_hours * 3600 * 1000
    segments = []
    for f in files:
        try:
            seg = AudioSegment.from_mp3(f)
            seg = seg.set_channels(channels).set_frame_rate(SAMPLE_RATE)
            seg = normalize(seg)
            if len(seg) < MIN_SAMPLE_SEC * 1000: continue
            segments.append(seg)
            print(f"   ok: {os.path.basename(f)} ({len(seg)/1000:.0f}s)")
        except Exception as e:
            print(f"   erro {f}: {e}")
    if not segments:
        raise RuntimeError("Nenhum sample valido apos processamento")

    random.shuffle(segments)
    combined = AudioSegment.empty()
    i = 0
    while len(combined) < target_ms:
        seg = segments[i % len(segments)]
        # FIX: dynamic crossfade — never more than 25% of segment length
        safe_crossfade = min(CROSSFADE_MS, len(seg) // 4)
        combined = combined.append(seg, crossfade=safe_crossfade) if len(combined) > 0 else combined + seg
        i += 1
        if i % 5 == 0:
            print(f"   {min(100, len(combined)/target_ms*100):.0f}% ({len(combined)//60000}min)")
    return combined[:target_ms]

def finalize_audio(combined, output="output_audio.mp3"):
    print("\n   Finalizando audio...")
    combined = combined.fade_in(FADE_IN_MS).fade_out(FADE_OUT_MS)
    combined = normalize(combined)
    db = combined.dBFS
    if db < TARGET_LUFS - 3:
        combined = combined + (TARGET_LUFS - db)
    combined = combined.set_frame_rate(SAMPLE_RATE)
    combined.export(output, format="mp3", bitrate="192k",
                    tags={"artist":"Comfort Sounds","album":"Ambient Collection"})
    mb = os.path.getsize(output) / (1024*1024)
    print(f"   OK: {output} ({mb:.0f}MB, {len(combined)/3600000:.1f}h)")
    return output

def cleanup_tmp():
    for f in glob.glob("audio_tmp/*.mp3"):
        try: os.remove(f)
        except: pass


# ══════════════════════════════════════════════════════════
# CASCADES POR CATEGORIA
# ══════════════════════════════════════════════════════════
def build_ambient(query, duration_hours):
    """Cascade: Freesound → Pixabay Audio → Internet Archive"""
    for name, fn, args in [
        ("Freesound",        build_from_freesound, (query, duration_hours)),
        ("Pixabay Audio",    build_from_pixabay,   (query, duration_hours)),
        ("Internet Archive", build_from_archive,   (query, duration_hours)),
    ]:
        try:
            print(f"\n   Tentando: {name}...")
            return fn(*args)
        except Exception as e:
            print(f"   {name} falhou: {e}")
    raise RuntimeError("Todas as fontes de ambiente falharam")

def build_jazz(tags, duration_hours):
    """Cascade: Jamendo → ccMixter → Freesound"""
    for name, fn, args in [
        ("Jamendo",   build_from_jamendo,   (tags, duration_hours)),
        ("ccMixter",  build_from_ccmixter,  ("jazz instrumental", duration_hours)),
        ("Freesound", build_from_freesound, ("jazz piano soft instrumental", duration_hours)),
    ]:
        try:
            print(f"\n   Tentando: {name}...")
            return fn(*args)
        except Exception as e:
            print(f"   {name} falhou: {e}")
    raise RuntimeError("Todas as fontes de jazz falharam")


# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════
def main():
    meta_files = sorted(glob.glob("metadata_*.json"), key=os.path.getmtime, reverse=True)
    if not meta_files:
        raise FileNotFoundError("Execute step1_metadata.py primeiro")

    with open(meta_files[0]) as f:
        metadata = json.load(f)

    category   = metadata["category"]
    duration   = metadata["duration_hours"]
    theme_data = metadata.get("theme_data", {})

    print(f"\nGerando audio: {metadata['theme']} ({duration}h)")
    print(f"Categoria: {category}")

    if category == "focus_noise":
        noise_type = theme_data.get("noise_type", "brown")
        combined = build_noise(noise_type, duration)

    elif category == "jazz":
        tags = theme_data.get("tags", "jazz")
        combined = build_jazz(tags, duration)
        # Adiciona chuva suave de fundo se o tema pedir
        if "rain" in theme_data.get("theme",""):
            try:
                print("\n   Adicionando chuva suave de fundo...")
                rain_combined = build_ambient("gentle rain soft", duration)
                rain_combined = normalize(rain_combined) - 12
                if len(rain_combined) < len(combined):
                    while len(rain_combined) < len(combined):
                        rain_combined = rain_combined.append(rain_combined, crossfade=5000)
                rain_combined = rain_combined[:len(combined)]
                combined = combined.overlay(rain_combined)
                print("   Chuva adicionada")
            except Exception as e:
                print(f"   Chuva nao adicionada: {e}")

    else:
        query = theme_data.get("query", metadata["theme"])
        combined = build_ambient(query, duration)

    finalize_audio(combined, "output_audio.mp3")
    cleanup_tmp()


if __name__ == "__main__":
    main()
