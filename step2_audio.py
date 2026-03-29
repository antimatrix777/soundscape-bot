# STEP 2 — Audio Generator (Nocturne Noise)

import os, json, glob, time, random, re, requests
from pydub import AudioSegment
from dotenv import load_dotenv

load_dotenv()

FREESOUND_KEY = os.environ.get("FREESOUND_API_KEY", "")
JAMENDO_KEY   = os.environ.get("JAMENDO_CLIENT_ID", "")

TARGET_DBFS  = -18.0   # Nível alvo por segmento (aproxima -18 LUFS para conteúdo ambient)
CROSSFADE_MS = 4000    # Crossfade de 4s entre clipes — imperceptível, mas elimina o clique
MIN_SAMPLE_SEC = 45
SAMPLE_RATE = 44100

# Tags que indicam CERTAMENTE voz/fala — sempre bloqueados
STRICT_BAD_TAGS = {"voice","speech","talk","vocal","sing","song",
                   "music","people","human","crowd","chatter",
                   "conversation","spoken","narration","radio","broadcast"}

# Tags bloqueadas apenas no filtro estrito (ambiente pode ter fundo de pessoas)
SOFT_BAD_TAGS = {"voice","speech","talk","vocal","sing","song"}

_BAD_WORDS_PATTERN = re.compile(
    r'\b(voice|speech|talk|song|vocal|podcast|interview|'
    r'crowd|chatter|conversation|narrat|spoken|radio|broadcast)\b', re.I
)

def has_bad_content(name):
    return bool(_BAD_WORDS_PATTERN.search(name))


# ══════════════════════════════════════════════════════════
# FREESOUND (FIXED — API KEY)
# ══════════════════════════════════════════════════════════

def freesound_search(query, num=10):
    if not FREESOUND_KEY:
        raise ValueError("FREESOUND_API_KEY not set")

    r = requests.get(
        "https://freesound.org/apiv2/search/text/",
        params={
            "query": query,
            "filter": f"duration:[{MIN_SAMPLE_SEC} TO 7200]",
            "fields": "id,name,duration,tags",
            "page_size": num,
            "token": FREESOUND_KEY
        },
        timeout=30
    )

    r.raise_for_status()
    results = r.json().get("results", [])

    if not results:
        raise RuntimeError("Freesound: API retornou zero resultados para a query")

    # Filtro estrito — bloqueia music, people, crowd, etc.
    clean = [
        s for s in results
        if not ({t.lower() for t in s.get("tags", [])} & STRICT_BAD_TAGS)
        and not has_bad_content(s.get("name",""))
    ]

    if clean:
        return clean[:num]

    # Filtro leve — só bloqueia voz explícita; aceita ambientes com pessoas ao fundo
    print("   [Freesound] Filtro estrito zerou resultados — usando filtro leve")
    soft = [
        s for s in results
        if not ({t.lower() for t in s.get("tags", [])} & SOFT_BAD_TAGS)
        and not has_bad_content(s.get("name",""))
    ]

    if soft:
        return soft[:num]

    # Último recurso — retorna os primeiros sem filtro (melhor que crashar)
    print("   [Freesound] Filtro leve também zerou — usando resultados sem filtro")
    return results[:num]


def freesound_download(sound):
    os.makedirs("audio_tmp", exist_ok=True)

    path = f"audio_tmp/fs_{sound['id']}.mp3"
    if os.path.exists(path):
        return path

    url = f"https://freesound.org/apiv2/sounds/{sound['id']}/download/?token={FREESOUND_KEY}"

    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()

    with open(path, "wb") as f:
        for chunk in r.iter_content(32768):
            f.write(chunk)

    return path


def fetch_freesound(query):
    sounds = freesound_search(query)
    files = [freesound_download(s) for s in sounds]
    return load_segments(files)


# ══════════════════════════════════════════════════════════
# JAMENDO
# ══════════════════════════════════════════════════════════

def fetch_jamendo():
    r = requests.get(
        "https://api.jamendo.com/v3.0/tracks/",
        params={
            "client_id": JAMENDO_KEY,
            "format": "json",
            "limit": 5,
            "tags": "jazz",
            "audioformat": "mp31"
        },
        timeout=30
    )

    results = r.json().get("results", [])
    files = []

    os.makedirs("audio_tmp", exist_ok=True)

    for t in results:
        url = t.get("audio")
        if not url:
            continue

        path = f"audio_tmp/jm_{t['id']}.mp3"
        if not os.path.exists(path):
            r2 = requests.get(url)
            with open(path, "wb") as f:
                f.write(r2.content)

        files.append(path)

    return load_segments(files)


# ══════════════════════════════════════════════════════════
# AUDIO CORE
# ══════════════════════════════════════════════════════════

def normalize_segment(seg):
    """
    Normaliza o segmento para TARGET_DBFS usando RMS.
    Aproxima corretamente -18 LUFS para conteúdo ambient contínuo.
    Evita que clipes de fontes diferentes tenham volumes completamente diferentes.
    """
    if seg.dBFS == float('-inf'):
        return seg  # silêncio total — não aplica gain
    gain_needed = TARGET_DBFS - seg.dBFS
    # Limita a 12 dB de ganho máximo para não amplificar ruído de fundo excessivamente
    gain_needed = min(gain_needed, 12.0)
    return seg.apply_gain(gain_needed)


def load_segments(files):
    segs = []
    for f in files:
        try:
            seg = AudioSegment.from_mp3(f)
            if len(seg) > MIN_SAMPLE_SEC * 1000:
                seg = normalize_segment(seg)
                segs.append(seg)
                print(f"   Carregado: {f} ({len(seg)//1000}s | {seg.dBFS:.1f} dBFS)")
        except Exception as e:
            print(f"   Ignorado: {f} ({e})")

    if not segs:
        raise RuntimeError("No valid audio")

    return segs


def loop_audio(segs, hours):
    """
    Monta o loop com crossfade entre cada clipe.
    CROSSFADE_MS de sobreposição elimina o 'clique' audível na transição.
    O crossfade não encurta o áudio perceptivelmente — apenas suaviza a costura.
    """
    target    = hours * 3600 * 1000
    fade_ms   = min(CROSSFADE_MS, len(segs[0]) // 2)  # nunca maior que metade do clipe
    out       = segs[0]
    i         = 1

    while len(out) < target:
        next_seg = segs[i % len(segs)]
        out      = out.append(next_seg, crossfade=fade_ms)
        i       += 1

    return out[:target]


# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════

def main():
    meta = sorted(glob.glob("metadata_*.json"))[-1]

    with open(meta) as f:
        data = json.load(f)

    category = data["category"]
    duration = data["duration_hours"]

    print("Generating:", category)

    if category == "jazz":
        segs = fetch_jamendo()
    else:
        segs = fetch_freesound(data["theme"])

    audio = loop_audio(segs, duration)

    audio.export("output_audio.mp3", format="mp3", bitrate="128k")

    print("DONE")


if __name__ == "__main__":
    main()
