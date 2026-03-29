"""
STEP 6 — Shorts Generator (Nocturne Noise)
==========================================
Cron separado: roda ~6h depois do vídeo longo.

Fluxo:
  1. YouTube API → pega último vídeo publicado (título, ID, categoria)
  2. yt-dlp      → baixa áudio do vídeo
  3. pydub       → corta melhor trecho de 55s + fade seamless
  4. Groq        → gera título evocativo derivado do título original
  5. AI cascade  → gera thumbnail 9:16 identidade do canal
  6. inputProps  → salva JSON para o Remotion
  7. Node.js     → Remotion renderiza o Short (1080x1920, 59s)
  8. YouTube API → sobe como Short com link pro vídeo original
"""
import os, json, subprocess, sys, time, random, re, base64, requests
from pathlib import Path
from datetime import datetime
from pydub import AudioSegment
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance
from io import BytesIO

load_dotenv()

# ─── Config ───────────────────────────────────────────────
GROQ_KEY       = os.environ.get("GROQ_API_KEY", "")
TOGETHER_KEY   = os.environ.get("TOGETHER_API_KEY", "")
FAL_KEY        = os.environ.get("FAL_API_KEY", "")
GEMINI_KEY     = os.environ.get("GEMINI_API_KEY", "")
PEXELS_KEY     = os.environ.get("PEXELS_API_KEY", "")
PIXABAY_KEY    = os.environ.get("PIXABAY_API_KEY", "")

SHORT_DURATION_S  = 55        # segundos do corte (deixa 4s de margem pro loop)
FADE_MS           = 1500      # fade in/out em ms para seamless loop
SHORT_FPS         = 30
REMOTION_DIR      = Path(__file__).parent / "remotion-short"
PROPS_FILE        = REMOTION_DIR / "inputProps.json"
SHORT_OUTPUT      = Path("short_final.mp4")
SHORT_AUDIO       = Path("short_audio.mp3")
SHORT_THUMB       = Path("short_thumb.jpg")

# Estilo base da identidade visual do canal
STYLE_BASE = (
    "nocturne lofi illustration, portrait 9:16, intimate night scene, "
    "warm amber lamp glow, crescent moon and city skyline through large window, "
    "cozy interior, houseplants, vinyl record, deep indigo night sky, "
    "warm golden light contrasting dark blue exterior, "
    "cinematic digital art, no text, no watermark, no people, "
    "high detail, painterly, dreamlike atmosphere"
)

CATEGORY_THUMB_PROMPTS = {
    "rain":        "rain drops on window glass at night, steaming coffee mug, warm desk lamp, city lights blurred through rain, " + STYLE_BASE,
    "nature":      "misty forest at dawn, wooden desk near large window, fern plants, soft morning fog, " + STYLE_BASE,
    "cozy":        "crackling fireplace close-up, armchair with wool blanket, open book, cup of tea, " + STYLE_BASE,
    "jazz":        "vinyl record spinning on turntable, warm amber light, jazz album covers on shelf, headphones, " + STYLE_BASE,
    "focus_noise": "minimalist home office at night, single desk lamp, open notebook, clean aesthetic, city through window, " + STYLE_BASE,
    "study":       "late night study desk, open books, coffee, warm lamp, rain visible outside window, " + STYLE_BASE,
    "urban":       "city rain at night, neon reflections on wet pavement, cozy window view from above, " + STYLE_BASE,
}

# ─── 1. Pega último vídeo publicado ───────────────────────
def get_latest_video():
    """Retorna (video_id, title, category) do último vídeo público do canal."""
    import google.oauth2.credentials as goc
    from googleapiclient.discovery import build

    token_b64 = os.environ.get("YT_TOKEN_B64")
    if not token_b64:
        raise RuntimeError("YT_TOKEN_B64 não definido")

    token_data = json.loads(base64.b64decode(token_b64).decode())
    creds = goc.Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=["https://www.googleapis.com/auth/youtube"],
    )

    yt = build("youtube", "v3", credentials=creds)

    # Pega canal próprio
    me = yt.channels().list(part="id", mine=True).execute()
    channel_id = me["items"][0]["id"]

    # Últimos 5 uploads
    search = yt.search().list(
        part="snippet",
        channelId=channel_id,
        maxResults=5,
        order="date",
        type="video",
    ).execute()

    for item in search.get("items", []):
        vid_id  = item["id"]["videoId"]
        title   = item["snippet"]["title"]
        desc    = item["snippet"].get("description", "")

        # Detecta categoria pelos hashtags ou palavras-chave do título/descrição
        category = detect_category(title + " " + desc)
        print(f"   Último vídeo: [{vid_id}] {title} → categoria: {category}")
        return vid_id, title, category

    raise RuntimeError("Nenhum vídeo encontrado no canal")


def detect_category(text):
    text = text.lower()
    if any(w in text for w in ["rain", "raining", "drizzle", "storm", "thunder"]):
        return "rain"
    if any(w in text for w in ["jazz", "piano", "bossa", "saxophone"]):
        return "jazz"
    if any(w in text for w in ["fire", "fireplace", "cozy", "café", "cafe", "library", "cabin"]):
        return "cozy"
    if any(w in text for w in ["forest", "ocean", "river", "waterfall", "bird", "nature"]):
        return "nature"
    if any(w in text for w in ["tokyo", "paris", "london", "new york", "city", "urban", "neon"]):
        return "urban"
    if any(w in text for w in ["brown noise", "white noise", "pink noise"]):
        return "focus_noise"
    if any(w in text for w in ["study", "focus", "concentration"]):
        return "study"
    return "cozy"  # fallback mais neutro


# ─── 2. Baixa áudio via yt-dlp ────────────────────────────
def download_audio(video_id):
    url = f"https://www.youtube.com/watch?v={video_id}"
    out = "yt_audio_raw.%(ext)s"
    print(f"   Baixando áudio: {url}")

    result = subprocess.run([
        "yt-dlp",
        "-x", "--audio-format", "mp3",
        "--audio-quality", "0",
        "-o", out,
        "--no-playlist",
        url,
    ], capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp falhou:\n{result.stderr[-1000:]}")

    files = list(Path(".").glob("yt_audio_raw.*"))
    if not files:
        raise FileNotFoundError("yt-dlp não gerou arquivo")
    return str(files[0])


# ─── 3. Corta melhor trecho de 55s ────────────────────────
def cut_best_segment(audio_path, duration_s=SHORT_DURATION_S):
    """Pega o trecho de maior energia RMS depois de 60s (evita intro)."""
    print(f"   Cortando {duration_s}s do áudio...")
    audio = AudioSegment.from_file(audio_path)

    total_ms    = len(audio)
    start_ms    = 60_000                          # skip 1min de intro
    chunk_ms    = duration_s * 1000
    best_start  = start_ms
    best_rms    = 0

    # Testa a cada 2 minutos qual janela tem mais energia
    for t in range(start_ms, min(total_ms - chunk_ms, 600_000), 120_000):
        rms = audio[t : t + chunk_ms].rms
        if rms > best_rms:
            best_rms   = rms
            best_start = t

    segment = audio[best_start : best_start + chunk_ms]

    # Fade in/out para loop seamless
    segment = segment.fade_in(FADE_MS).fade_out(FADE_MS)

    # Normaliza
    from pydub.effects import normalize
    segment = normalize(segment)

    segment.export(str(SHORT_AUDIO), format="mp3", bitrate="192k")
    print(f"   Corte salvo: {SHORT_AUDIO} ({duration_s}s @ {best_start//1000}s do original)")
    return str(SHORT_AUDIO)


# ─── 4. Gera título evocativo via Groq ────────────────────
EVOCATIVE_FALLBACKS = {
    "rain":        ["Still raining.", "You left the window open.", "The rain found you again.",
                    "It won't stop tonight.", "Let it rain a little longer."],
    "cozy":        ["Stay a little longer.", "No one needs you right now.", "The fire is still going.",
                    "Just this corner of the world.", "Nothing to do but be here."],
    "nature":      ["You found the quiet place.", "Nobody knows where you are.",
                    "The forest doesn't need anything from you.", "Still here. Still breathing."],
    "jazz":        ["One more song.", "The bar is almost empty.", "The piano player stayed late.",
                    "Nobody's leaving yet.", "Just the music now."],
    "focus_noise": ["Disappear into the work.", "Everything else fades.", "Just you and the silence.",
                    "The world can wait.", "Block it all out."],
    "study":       ["One more hour.", "The lamp is still on.", "You still have time.",
                    "Late night. Just you.", "The desk is yours tonight."],
    "urban":       ["The city is still awake.", "You're not the only one up.",
                    "Somewhere out there, the night goes on.", "The lights never really go out."],
}

def generate_short_title(video_title, category):
    """Gera título evocativo derivado do título do vídeo longo."""
    if not GROQ_KEY:
        return random.choice(EVOCATIVE_FALLBACKS.get(category, ["The night is yours."]))

    prompt = f"""The YouTube soundscape video is titled: "{video_title}"
Category: {category}

Write exactly 1 evocative short title for a YouTube Short that is a fragment or emotional echo of that video.

Rules:
- Maximum 7 words
- No punctuation except a period at the end (optional)
- Lowercase preferred
- Second person OR atmospheric fragment — never a description
- Must feel like a private thought, not a product title
- Do NOT repeat words from the original title
- Tone: intimate, cinematic, quiet

Good examples:
  "Still raining."
  "You left the window open."
  "The fire is still going."
  "Nobody knows where you are."
  "One more hour."
  "The city is still awake."

Bad examples:
  "Relaxing rain sounds for sleep"
  "Cozy ambience vol 2"

Output ONLY the title. Nothing else."""

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.9,
                "max_tokens": 30,
            },
            timeout=20,
        )
        r.raise_for_status()
        title = r.json()["choices"][0]["message"]["content"].strip().strip('"')
        # Valida tamanho
        if len(title) < 3 or len(title) > 60:
            raise ValueError(f"Título inválido: {title}")
        print(f"   Título do Short: {title}")
        return title
    except Exception as e:
        print(f"   Groq falhou: {e} → usando fallback")
        return random.choice(EVOCATIVE_FALLBACKS.get(category, ["The night is yours."]))


# ─── 5. Gera thumbnail 9:16 via cascade de IA ─────────────
def generate_thumbnail(video_title, category):
    """Gera imagem 1080x1920 identidade do canal. Cascade: Together → fal → Gemini → Pollinations → Pexels."""
    base_prompt = CATEGORY_THUMB_PROMPTS.get(category, CATEGORY_THUMB_PROMPTS["cozy"])
    # Enriquece com palavras-chave do título
    keywords = " ".join([w for w in video_title.lower().split() if len(w) > 3][:4])
    prompt = f"{keywords}, {base_prompt}"

    img = None

    # 1. Together AI FLUX.1-schnell
    if TOGETHER_KEY and img is None:
        try:
            print("   Thumbnail: tentando Together AI FLUX.1...")
            r = requests.post(
                "https://api.together.xyz/v1/images/generations",
                headers={"Authorization": f"Bearer {TOGETHER_KEY}", "Content-Type": "application/json"},
                json={"model": "black-forest-labs/FLUX.1-schnell-Free",
                      "prompt": prompt, "width": 1080, "height": 1920, "n": 1},
                timeout=60,
            )
            r.raise_for_status()
            url = r.json()["data"][0]["url"]
            img = Image.open(BytesIO(requests.get(url, timeout=30).content)).convert("RGB")
            print("   Thumbnail: Together OK")
        except Exception as e:
            print(f"   Together falhou: {e}")

    # 2. fal.ai FLUX Schnell
    if FAL_KEY and img is None:
        try:
            print("   Thumbnail: tentando fal.ai...")
            r = requests.post(
                "https://fal.run/fal-ai/flux/schnell",
                headers={"Authorization": f"Key {FAL_KEY}", "Content-Type": "application/json"},
                json={"prompt": prompt, "image_size": "portrait_4_3",
                      "num_images": 1, "enable_safety_checker": False},
                timeout=60,
            )
            r.raise_for_status()
            url = r.json()["images"][0]["url"]
            img = Image.open(BytesIO(requests.get(url, timeout=30).content)).convert("RGB")
            img = img.resize((1080, 1920), Image.LANCZOS)
            print("   Thumbnail: fal.ai OK")
        except Exception as e:
            print(f"   fal.ai falhou: {e}")

    # 3. Pollinations (sem key)
    if img is None:
        try:
            print("   Thumbnail: tentando Pollinations...")
            encoded = requests.utils.quote(prompt)
            url = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1920&nologo=true&seed={random.randint(1,9999)}"
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            print("   Thumbnail: Pollinations OK")
        except Exception as e:
            print(f"   Pollinations falhou: {e}")

    # 4. Pexels fallback
    if PEXELS_KEY and img is None:
        try:
            print("   Thumbnail: fallback Pexels...")
            query = CATEGORY_THUMB_PROMPTS.get(category, "cozy night")[:30]
            r = requests.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": PEXELS_KEY},
                params={"query": query, "per_page": 5, "orientation": "portrait"},
                timeout=20,
            )
            r.raise_for_status()
            photos = r.json().get("photos", [])
            if photos:
                url = random.choice(photos)["src"]["large2x"]
                img = Image.open(BytesIO(requests.get(url, timeout=30).content)).convert("RGB")
                img = img.resize((1080, 1920), Image.LANCZOS)
                print("   Thumbnail: Pexels OK")
        except Exception as e:
            print(f"   Pexels falhou: {e}")

    if img is None:
        # Último fallback: gradiente programático
        print("   Thumbnail: gerando gradiente fallback...")
        img = _make_gradient_thumb()

    img.save(str(SHORT_THUMB), "JPEG", quality=95)
    print(f"   Thumbnail salva: {SHORT_THUMB}")
    return str(SHORT_THUMB)


def _make_gradient_thumb():
    img = Image.new("RGB", (1080, 1920))
    draw = ImageDraw.Draw(img)
    for y in range(1920):
        t = y / 1920
        r = int(10  + t * 5)
        g = int(8   + t * 3)
        b = int(20  + t * 15)
        draw.line([(0, y), (1080, y)], fill=(r, g, b))
    # Adiciona mancha âmbar no canto inferior esquerdo
    for i in range(200):
        alpha = 1 - i/200
        r2 = int(180 * alpha)
        g2 = int(100 * alpha)
        b2 = int(20  * alpha)
        draw.ellipse(
            [(100-i*2, 1400-i*2), (600+i*2, 1900+i*2)],
            fill=(r2, g2, b2),
        )
    return img.filter(ImageFilter.GaussianBlur(80))


# ─── 6. Salva inputProps.json para o Remotion ─────────────
def save_input_props(title, category, audio_path, thumb_path, video_id, video_title):
    props = {
        "title":          title,
        "category":       category,
        "audioPath":      str(Path(audio_path).resolve()),
        "thumbPath":      str(Path(thumb_path).resolve()),
        "sourceVideoId":  video_id,
        "sourceTitle":    video_title,
        "fps":            SHORT_FPS,
        "durationSeconds": SHORT_DURATION_S + 4,  # +4 para o loop seamless
        "generatedAt":    datetime.now().isoformat(),
    }
    PROPS_FILE.parent.mkdir(exist_ok=True)
    with open(PROPS_FILE, "w", encoding="utf-8") as f:
        json.dump(props, f, ensure_ascii=False, indent=2)
    print(f"   Props salvas: {PROPS_FILE}")
    return props


# ─── 7. Roda Remotion ─────────────────────────────────────
def render_with_remotion():
    print("\n   Instalando deps Node.js...")
    subprocess.run(["npm", "install"], cwd=REMOTION_DIR, check=True, capture_output=True)

    print("   Renderizando Short com Remotion...")
    result = subprocess.run(
        ["node", "render-short.mjs"],
        cwd=REMOTION_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
        raise RuntimeError("Remotion falhou")
    print(result.stdout[-500:])
    print("   Render concluído!")


# ─── 8. Upload como Short ─────────────────────────────────
def upload_short(title, category, video_id, thumb_path):
    import google.oauth2.credentials as goc
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    token_b64  = os.environ.get("YT_TOKEN_B64")
    token_data = json.loads(base64.b64decode(token_b64).decode())
    creds = goc.Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=["https://www.googleapis.com/auth/youtube",
                "https://www.googleapis.com/auth/youtube.upload"],
    )

    yt = build("youtube", "v3", credentials=creds)

    hashtag_map = {
        "rain":        "#nocturnoise #rainambience #shorts",
        "cozy":        "#nocturnoise #cozyambience #shorts",
        "nature":      "#nocturnoise #naturesounds #shorts",
        "jazz":        "#nocturnoise #jazzambience #shorts",
        "focus_noise": "#nocturnoise #brownnoise #shorts",
        "study":       "#nocturnoise #studyambience #shorts",
        "urban":       "#nocturnoise #cityambience #shorts",
    }

    description = (
        f"{title}\n\n"
        f"🎧 Full version → https://www.youtube.com/watch?v={video_id}\n\n"
        f"Nocturne Noise — sounds for wherever you want to be.\n"
        f"Subscribe for new soundscapes every week → https://www.youtube.com/@NocturneNoise\n\n"
        f"{hashtag_map.get(category, '#nocturnoise #shorts')}"
    )

    print(f"   Fazendo upload do Short: {title}")
    media = MediaFileUpload(str(SHORT_OUTPUT), mimetype="video/mp4", resumable=True)

    request = yt.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title":       f"{title} #shorts",
                "description": description,
                "tags":        ["shorts", "nocturne noise", "soundscape", category,
                                "ambient", "lofi", "sleep sounds", "relaxing"],
                "categoryId":  "10",
            },
            "status": {
                "privacyStatus":           "public",
                "selfDeclaredMadeForKids": False,
            },
        },
        media_body=media,
    )

    response = None
    while response is None:
        _, response = request.next_chunk()

    short_id  = response["id"]
    short_url = f"https://www.youtube.com/shorts/{short_id}"
    print(f"   Short publicado: {short_url}")

    # Thumbnail dedicada
    if thumb_path and Path(thumb_path).exists():
        try:
            yt.thumbnails().set(
                videoId=short_id,
                media_body=MediaFileUpload(thumb_path, mimetype="image/jpeg"),
            ).execute()
            print("   Thumbnail definida")
        except Exception as e:
            print(f"   Thumbnail falhou (não crítico): {e}")

    with open("last_short.json", "w") as f:
        json.dump({"id": short_id, "url": short_url, "title": title}, f, indent=2)

    return short_url


# ─── Main ──────────────────────────────────────────────────
def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-upload", action="store_true")
    args_cli = ap.parse_args()
    print(f"\nNOCTURNE NOISE SHORTS — {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Busca último vídeo
    print("\n[1/8] Buscando último vídeo publicado...")
    video_id, video_title, category = get_latest_video()

    # Baixa áudio
    print("\n[2/8] Baixando áudio via yt-dlp...")
    raw_audio = download_audio(video_id)

    # Corta trecho
    print("\n[3/8] Cortando melhor trecho...")
    short_audio = cut_best_segment(raw_audio)

    # Gera título
    print("\n[4/8] Gerando título evocativo...")
    short_title = generate_short_title(video_title, category)

    # Gera thumbnail
    print("\n[5/8] Gerando thumbnail 9:16...")
    thumb_path = generate_thumbnail(video_title, category)

    # Salva props
    print("\n[6/8] Salvando inputProps para Remotion...")
    save_input_props(short_title, category, short_audio, thumb_path, video_id, video_title)

    # Renderiza
    print("\n[7/8] Renderizando com Remotion...")
    render_with_remotion()

    # Upload
    print("\n[8/8] Fazendo upload do Short...")
    url = upload_short(short_title, category, video_id, thumb_path)

    # Cleanup
    for f in [raw_audio, str(SHORT_AUDIO)]:
        try:
            Path(f).unlink(missing_ok=True)
        except Exception:
            pass

    print(f"\n✓ SHORT PUBLICADO: {url}")
    print(f"  Título: {short_title}")
    print(f"  Baseado em: {video_title}")


if __name__ == "__main__":
    main()
