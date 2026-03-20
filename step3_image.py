"""
ETAPA 3 — Gerador de Imagem IA + Thumbnail
Cascade com 6 fontes, 3 tentativas cada antes de pular para a proxima.

Ordem:
  1. Together AI FLUX.1   (melhor qualidade estetica)
  2. fal.ai FLUX Schnell  (rapido, creditos gratis no cadastro)
  3. Gemini Imagen 3      (500/dia gratis)
  4. Stable Horde         (crowdsourced, gratis)
  5. Pollinations         (sem key, gratuito)
  6. Pexels / Pixabay     (foto real, fallback final)
"""
import os, json, glob, time, requests, urllib.parse, random, base64
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance
from io import BytesIO
from dotenv import load_dotenv

load_dotenv()

TOGETHER_KEY     = os.environ.get("TOGETHER_API_KEY", "")
FAL_KEY          = os.environ.get("FAL_API_KEY", "")
GEMINI_KEY       = os.environ.get("GEMINI_API_KEY", "")
STABLE_HORDE_KEY = os.environ.get("STABLE_HORDE_KEY", "0000000000")
PEXELS_KEY       = os.environ.get("PEXELS_API_KEY", "")
PIXABAY_KEY      = os.environ.get("PIXABAY_API_KEY", "")

CHANNEL_NAME = "Comfort Sounds"
MAX_RETRIES  = 3  # tentativas por fonte antes de pular

STYLE_BASE = (
    "lofi illustration, cozy night scene, warm amber lamp light, "
    "crescent moon visible through large window, city skyline at night, "
    "houseplants, detailed and atmospheric, digital art, "
    "no text, no watermark, cinematic lighting, "
    "deep blue night sky, golden warm interior light"
)

CATEGORY_PROMPTS = {
    "rain": [
        f"rain drops on window glass, cozy desk with steaming coffee mug, vinyl record player, open notebook, warm desk lamp, {STYLE_BASE}",
        f"heavy rain outside window at night, reading under blanket, candle light, bookshelf, plants, {STYLE_BASE}",
        f"rain on rooftop terrace, city lights blurred through rain, cozy indoor corner, tea cup, {STYLE_BASE}",
        f"rainy night street lamp reflection on wet pavement, viewed from cozy window, hot drink, {STYLE_BASE}",
    ],
    "nature": [
        f"misty forest at dawn through large window, wooden desk, fern plant, soft morning light, {STYLE_BASE}",
        f"ocean waves visible through floor-to-ceiling window, cozy reading chair, lighthouse in distance, {STYLE_BASE}",
        f"mountain stream and pine forest outside window, log cabin interior, fireplace glow, {STYLE_BASE}",
        f"bamboo forest swaying gently, japanese-inspired interior, tea ceremony set, zen atmosphere, {STYLE_BASE}",
    ],
    "cozy": [
        f"vintage coffee shop interior at night, exposed brick, warm Edison bulbs, vinyl records on wall, coffee and croissant, {STYLE_BASE}",
        f"crackling fireplace close-up, armchair with blanket, open book, cup of tea, cat sleeping, {STYLE_BASE}",
        f"old library with floor-to-ceiling bookshelves, reading nook, vintage lamp, stacked books, {STYLE_BASE}",
        f"cozy cabin in snowstorm, fireplace, hot cocoa with marshmallows, frost on window, pine trees outside, {STYLE_BASE}",
        f"japanese tea house at night, paper lanterns, wooden table, matcha tea, bonsai plant, {STYLE_BASE}",
    ],
    "jazz": [
        f"jazz musician silhouette at grand piano, late night bar, neon sign glow, saxophone on stand, {STYLE_BASE}",
        f"vintage jazz club interior, art deco lighting, small round tables, trumpet on stage, record player, {STYLE_BASE}",
        f"paris sidewalk cafe at night, accordion player, warm cafe lights, cobblestone street, {STYLE_BASE}",
        f"vinyl record spinning on turntable, warm amber light, bookshelf with jazz albums, headphones, {STYLE_BASE}",
        f"bossa nova beach bar at dusk, acoustic guitar, tropical plants, fairy lights, ocean in background, {STYLE_BASE}",
    ],
    "focus_noise": [
        f"minimalist home office at night, single desk lamp, open notebook, pencils, plant, clean aesthetic, {STYLE_BASE}",
        f"student desk late at night, glowing monitor, coffee cup, notes scattered, city view through window, {STYLE_BASE}",
        f"zen meditation corner, candle, cushion, soft light through curtain, {STYLE_BASE}",
        f"cozy bedroom at night, moonlight through window, peaceful, minimal decor, {STYLE_BASE}",
    ],
    "study": [
        f"late night study session, desk with open books and laptop, coffee, desk lamp, rain on window, {STYLE_BASE}",
        f"university library at night, long wooden table, stacked books, warm reading lamps, {STYLE_BASE}",
        f"bedroom desk study corner, fairy lights, sticky notes, textbooks, plant, {STYLE_BASE}",
        f"coffee shop study session at night, laptop, coffee, rainy window, cozy crowd, {STYLE_BASE}",
    ],
    "urban": [
        f"tokyo street at night in rain, neon signs reflected on wet streets, ramen shop glow, {STYLE_BASE}",
        f"paris rooftop at night, eiffel tower in distance, wine glass, fairy lights, warm bistro interior, {STYLE_BASE}",
        f"new york apartment window at night, manhattan skyline, rain on glass, interior lamp, {STYLE_BASE}",
        f"london rainy evening, red phone box, cobblestone street, pub warm light, fog, {STYLE_BASE}",
    ],
}


def retry(fn, name, *args, retries=MAX_RETRIES, **kwargs):
    """Tenta uma funcao até MAX_RETRIES vezes antes de lancar excecao."""
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            print(f"   [{name}] Tentativa {attempt}/{retries}...")
            result = fn(*args, attempt=attempt, **kwargs)
            print(f"   [{name}] OK na tentativa {attempt}")
            return result
        except Exception as e:
            last_error = e
            print(f"   [{name}] Tentativa {attempt} falhou: {e}")
            if attempt < retries:
                time.sleep(3 * attempt)  # espera progressiva: 3s, 6s, 9s
    raise RuntimeError(f"{name} falhou em {retries} tentativas. Ultimo erro: {last_error}")


# ══════════════════════════════════════════════════════════
# FONTE 1: TOGETHER AI — FLUX.1 Schnell (melhor estetica)
# api.together.ai → cadastro gratis, sem cartao
# ══════════════════════════════════════════════════════════
def _together(prompt, attempt=1, **kw):
    if not TOGETHER_KEY:
        raise ValueError("TOGETHER_API_KEY nao configurada")
    seed = int(time.time()) + attempt * 100
    r = requests.post(
        "https://api.together.xyz/v1/images/generations",
        headers={"Authorization": f"Bearer {TOGETHER_KEY}", "Content-Type": "application/json"},
        json={
            "model":  "black-forest-labs/FLUX.1-schnell-Free",
            "prompt": prompt[:900],
            "width":  1024, "height": 1024,
            "steps":  4, "n": 1, "seed": seed,
        },
        timeout=90,
    )
    r.raise_for_status()
    item = r.json().get("data", [{}])[0]
    if item.get("url"):
        img_r = requests.get(item["url"], timeout=60)
        return Image.open(BytesIO(img_r.content)).convert("RGB")
    elif item.get("b64_json"):
        return Image.open(BytesIO(base64.b64decode(item["b64_json"]))).convert("RGB")
    raise RuntimeError("Together AI: sem imagem na resposta")


# ══════════════════════════════════════════════════════════
# FONTE 2: FAL.AI — FLUX Schnell (rapido, creditos gratis)
# fal.ai → cadastro gratis, creditos no signup
# Adicione FAL_API_KEY nos GitHub Secrets
# ══════════════════════════════════════════════════════════
def _fal(prompt, attempt=1, **kw):
    if not FAL_KEY:
        raise ValueError("FAL_API_KEY nao configurada")
    seed = int(time.time()) + attempt * 200
    r = requests.post(
        "https://fal.run/fal-ai/flux/schnell",
        headers={"Authorization": f"Key {FAL_KEY}", "Content-Type": "application/json"},
        json={
            "prompt":      prompt[:900],
            "image_size":  "landscape_16_9",
            "num_images":  1,
            "num_inference_steps": 4,
            "seed":        seed,
        },
        timeout=90,
    )
    r.raise_for_status()
    images = r.json().get("images", [])
    if not images:
        raise RuntimeError("fal.ai: sem imagens na resposta")
    url = images[0].get("url")
    if not url:
        raise RuntimeError("fal.ai: sem URL na resposta")
    img_r = requests.get(url, timeout=60)
    return Image.open(BytesIO(img_r.content)).convert("RGB")


# ══════════════════════════════════════════════════════════
# FONTE 3: GEMINI IMAGEN — 500 imagens/dia gratis
# Usa a GEMINI_API_KEY que voce ja tem configurada
# ══════════════════════════════════════════════════════════
def _gemini(prompt, attempt=1, **kw):
    if not GEMINI_KEY:
        raise ValueError("GEMINI_API_KEY nao configurada")
    # Tenta Imagen 3 primeiro
    imagen_url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:predict?key={GEMINI_KEY}"
    try:
        r = requests.post(imagen_url, json={
            "instances":  [{"prompt": prompt[:900]}],
            "parameters": {"sampleCount": 1, "aspectRatio": "16:9"},
        }, timeout=90)
        if r.status_code == 200:
            predictions = r.json().get("predictions", [])
            if predictions and predictions[0].get("bytesBase64Encoded"):
                data = base64.b64decode(predictions[0]["bytesBase64Encoded"])
                return Image.open(BytesIO(data)).convert("RGB")
    except Exception as e:
        print(f"   Imagen3 falhou: {e}")

    # Fallback para gemini flash com imagem
    for model in ["gemini-2.0-flash-exp-image-generation", "gemini-2.0-flash"]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_KEY}"
        try:
            r = requests.post(url, json={
                "contents": [{"parts": [{"text": prompt[:900]}]}],
                "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
            }, timeout=90)
            if r.status_code == 200:
                for candidate in r.json().get("candidates", []):
                    for part in candidate.get("content", {}).get("parts", []):
                        if "inlineData" in part:
                            data = base64.b64decode(part["inlineData"]["data"])
                            return Image.open(BytesIO(data)).convert("RGB")
        except Exception as e:
            print(f"   {model} falhou: {e}")

    raise RuntimeError("Gemini: nenhum endpoint retornou imagem")


# ══════════════════════════════════════════════════════════
# FONTE 4: STABLE HORDE — crowdsourced, 100% gratis
# stablehorde.net/register → key gratis com prioridade
# Key anonima "0000000000" funciona sem registro (fila lenta)
# ══════════════════════════════════════════════════════════
def _stable_horde(prompt, attempt=1, **kw):
    headers = {
        "apikey":       STABLE_HORDE_KEY,
        "Content-Type": "application/json",
        "Client-Agent": "comfort-sounds-bot:1.0:github",
    }
    r = requests.post(
        "https://stablehorde.net/api/v2/generate/async",
        headers=headers,
        json={
            "prompt": prompt[:900] + " ### ugly, text, watermark, blurry, nsfw",
            "params": {
                "sampler_name": "k_euler_a",
                "cfg_scale": 7.5,
                "steps": 25,
                "width": 1024, "height": 1024,
                "n": 1, "karras": True,
            },
            # No fixed models — let Horde pick the best available worker
            "r2": True, "shared": False, "slow_workers": True,
        },
        timeout=30,
    )
    r.raise_for_status()
    job_id = r.json().get("id")
    if not job_id:
        raise RuntimeError("Stable Horde: sem job ID")

    print(f"   Job ID: {job_id} | Aguardando fila...")
    for _ in range(23):  # max ~3 min (23 x 8s)
        time.sleep(8)
        check = requests.get(
            f"https://stablehorde.net/api/v2/generate/check/{job_id}",
            headers=headers, timeout=20,
        )
        status = check.json()
        print(f"   Fila: {status.get('queue_position','?')} | Espera: {status.get('wait_time',0)}s")
        if status.get("done"):
            break
    else:
        try:
            requests.delete(f"https://stablehorde.net/api/v2/generate/status/{job_id}",
                            headers=headers, timeout=10)
        except:
            pass
        raise RuntimeError("Stable Horde: timeout")

    result = requests.get(
        f"https://stablehorde.net/api/v2/generate/status/{job_id}",
        headers=headers, timeout=30,
    )
    generations = result.json().get("generations", [])
    if not generations:
        raise RuntimeError("Stable Horde: sem imagens")
    img_str = generations[0].get("img", "")
    if img_str.startswith("http"):
        img_r = requests.get(img_str, timeout=60)
        return Image.open(BytesIO(img_r.content)).convert("RGB")
    elif img_str:
        return Image.open(BytesIO(base64.b64decode(img_str))).convert("RGB")
    raise RuntimeError("Stable Horde: formato inesperado")


# ══════════════════════════════════════════════════════════
# FONTE 5: POLLINATIONS — sem API key, gratuito
# ══════════════════════════════════════════════════════════
def _pollinations(prompt, attempt=1, **kw):
    # FIX: Pollinations becomes URL — long prompts cause 500 errors
    seed = int(time.time()) + attempt * 300
    encoded = urllib.parse.quote(prompt[:350])
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width=1920&height=1080&seed={seed}&nologo=true&enhance=true&model=flux"
    )
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    if "image" not in r.headers.get("content-type", ""):
        raise RuntimeError("Pollinations: nao retornou imagem")
    img = Image.open(BytesIO(r.content)).convert("RGB")
    if img.width < 100:
        raise RuntimeError("Pollinations: imagem invalida")
    return img


# ══════════════════════════════════════════════════════════
# FONTES 6A e 6B: PEXELS e PIXABAY — fotos reais, fallback final
# ══════════════════════════════════════════════════════════
def _pexels_photo(query):
    if not PEXELS_KEY:
        raise ValueError("PEXELS_API_KEY nao configurada")
    r = requests.get(
        "https://api.pexels.com/v1/search",
        headers={"Authorization": PEXELS_KEY},
        params={"query": query, "orientation": "landscape", "size": "large", "per_page": 5},
        timeout=30,
    )
    r.raise_for_status()
    photos = r.json().get("photos", [])
    if not photos:
        raise RuntimeError(f"Pexels: sem fotos para '{query}'")
    best = max(photos, key=lambda p: p["width"] * p["height"])
    img_r = requests.get(best["src"]["original"], timeout=60)
    return Image.open(BytesIO(img_r.content)).convert("RGB")

def _pixabay_photo(query):
    if not PIXABAY_KEY:
        raise ValueError("PIXABAY_API_KEY nao configurada")
    r = requests.get("https://pixabay.com/api/", params={
        "key": PIXABAY_KEY, "q": query, "image_type": "photo",
        "orientation": "horizontal", "min_width": 1920,
        "per_page": 5, "safesearch": "true",
    }, timeout=30)
    r.raise_for_status()
    hits = r.json().get("hits", [])
    if not hits:
        raise RuntimeError(f"Pixabay: sem imagens para '{query}'")
    best = max(hits, key=lambda h: h.get("imageWidth", 0))
    url = best.get("largeImageURL") or best.get("webformatURL")
    img_r = requests.get(url, timeout=60)
    return Image.open(BytesIO(img_r.content)).convert("RGB")


# ══════════════════════════════════════════════════════════
# PROCESSAMENTO
# ══════════════════════════════════════════════════════════
def make_background(img, output="background.jpg"):
    W, H = 1920, 1080
    ratio = max(W / img.width, H / img.height)
    nw, nh = int(img.width * ratio), int(img.height * ratio)
    img = img.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - W) // 2, (nh - H) // 2
    img = img.crop((left, top, left + W, top + H))
    img = ImageEnhance.Brightness(img).enhance(0.82)
    vig = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(vig)
    for i in range(180):
        d.rectangle([i, i, W - i, H - i], outline=(0, 0, 0, int(i / 180 * 100)))
    img = Image.alpha_composite(img.convert("RGBA"), vig).convert("RGB")
    img.save(output, "JPEG", quality=95)
    print(f"   Background: {output}")
    return img

def make_thumbnail(base_img, thumb_text, output="thumbnail.jpg"):
    W, H = 1280, 720
    img = base_img.resize((W, H), Image.LANCZOS)
    blur = img.filter(ImageFilter.GaussianBlur(radius=3))
    mask = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(mask)
    for i in range(60):
        d.rectangle([i, i, W - i, H - i], fill=int(255 * i / 60))
    img = Image.composite(img, blur, mask)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d2 = ImageDraw.Draw(ov)
    for i in range(H // 2):
        d2.rectangle([(0, H // 2 + i), (W, H // 2 + i + 1)],
                     fill=(0, 0, 0, int(i / (H // 2) * 190)))
    img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
    draw = ImageDraw.Draw(img)

    def get_font(size):
        for p in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        ]:
            if os.path.exists(p):
                try: return ImageFont.truetype(p, size)
                except: pass
        return ImageFont.load_default()

    fs = get_font(28)
    text = thumb_text.upper()
    # FIX: auto-fit font size so text never overflows thumbnail
    font_size = 72
    fm = get_font(font_size)
    while font_size > 24:
        try:
            bbox = draw.textbbox((0, 0), text, font=fm)
            text_w = bbox[2] - bbox[0]
        except Exception:
            text_w = len(text) * font_size * 0.6
        if text_w <= W * 0.80:
            break
        font_size -= 4
        fm = get_font(font_size)
    draw.text((W // 2 + 3, H - 160 + 3), text, font=fm, fill=(0, 0, 0, 200), anchor="mm")
    draw.text((W // 2, H - 160), text, font=fm, fill=(255, 255, 255), anchor="mm")
    draw.text((W - 24, H - 24), CHANNEL_NAME, font=fs, fill=(200, 200, 200), anchor="rb")
    draw.ellipse([(20, 20), (28, 28)], fill=(255, 180, 50))
    img.save(output, "JPEG", quality=93)
    print(f"   Thumbnail: {output} ({os.path.getsize(output)//1024}KB)")
    return img


# ══════════════════════════════════════════════════════════
# CASCADE — 6 fontes, 3 tentativas cada
# ══════════════════════════════════════════════════════════
def get_image(category, pexels_query):
    prompt = random.choice(CATEGORY_PROMPTS.get(category, CATEGORY_PROMPTS["cozy"]))

    ai_sources = [
        ("Together AI FLUX.1", _together),
        ("fal.ai FLUX",        _fal),
        ("Gemini Imagen",      _gemini),
        ("Stable Horde",       _stable_horde),
        ("Pollinations",       _pollinations),
    ]

    for name, fn in ai_sources:
        try:
            img = retry(fn, name, prompt)
            return img, name
        except Exception as e:
            print(f"   {name} esgotou tentativas: {e}")

    # Fallback fotos reais — sem retry (geralmente confiavel)
    print("   Todas as IAs falharam — usando foto real")
    for photo_name, photo_fn, photo_arg in [
        ("Pexels",   _pexels_photo,   pexels_query),
        ("Pixabay",  _pixabay_photo,  pexels_query),
    ]:
        try:
            print(f"   [{photo_name}] Buscando foto...")
            img = photo_fn(photo_arg)
            return img, photo_name
        except Exception as e:
            print(f"   {photo_name} falhou: {e}")

    raise RuntimeError("ERRO CRITICO: todas as 6 fontes de imagem falharam")


# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════
def main():
    meta_files = sorted(glob.glob("metadata_*.json"), key=os.path.getmtime, reverse=True)
    if not meta_files:
        raise FileNotFoundError("Execute step1_metadata.py primeiro")
    with open(meta_files[0]) as f:
        metadata = json.load(f)

    category   = metadata.get("category", "cozy")
    thumb_text = metadata.get("thumbnail_text", "Comfort Sounds")
    pexels_q   = metadata.get("theme_data", {}).get("pexels", metadata.get("theme", "cozy ambience"))

    print(f"\nGerando imagem: {category}")
    print(f"Thumbnail: {thumb_text}")

    img, source = get_image(category, pexels_q)
    print(f"\nFonte usada: {source} | Tamanho: {img.width}x{img.height}")

    bg = make_background(img, "background.jpg")
    make_thumbnail(bg, thumb_text, "thumbnail.jpg")
    print("\nEtapa 3 concluida!")


if __name__ == "__main__":
    main()
