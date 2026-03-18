"""
ETAPA 3 — Gerador de Imagem + Thumbnail (Pexels API + Pillow — GRÁTIS)
Baixa foto temática, cria background 1920x1080 e thumbnail 1280x720.
"""
import os, json, glob, requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance
from io import BytesIO
from dotenv import load_dotenv

load_dotenv()
PEXELS_KEY = os.environ["PEXELS_API_KEY"]


def search_pexels(query, orientation="landscape"):
    """Busca foto no Pexels e retorna URL da melhor imagem."""
    print(f"🖼  Buscando foto: '{query}'...")
    r = requests.get("https://api.pexels.com/v1/search", headers={
        "Authorization": PEXELS_KEY
    }, params={
        "query": query,
        "orientation": orientation,
        "size": "large",
        "per_page": 5,
    }, timeout=30)
    r.raise_for_status()
    photos = r.json().get("photos", [])
    if not photos:
        raise RuntimeError(f"Nenhuma foto encontrada para '{query}'")
    # Pega a foto com maior resolução
    best = max(photos, key=lambda p: p["width"] * p["height"])
    url = best["src"]["original"]
    print(f"   → Foto encontrada: {best['width']}x{best['height']}")
    return url, best


def download_image(url):
    """Baixa e retorna PIL Image."""
    r = requests.get(url, timeout=60)
    return Image.open(BytesIO(r.content)).convert("RGB")


def make_background(img, output="background.jpg"):
    """Cria background 1920x1080 com leve darken."""
    # Redimensiona mantendo proporção, depois crop central
    target_w, target_h = 1920, 1080
    ratio = max(target_w / img.width, target_h / img.height)
    new_w = int(img.width * ratio)
    new_h = int(img.height * ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)

    # Crop central
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    img = img.crop((left, top, left + target_w, top + target_h))

    # Escurece levemente para contraste com texto
    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(0.75)

    # Overlay gradiente escuro na parte inferior (para texto)
    overlay = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for i in range(300):
        alpha = int((i / 300) * 120)
        draw.rectangle([(0, target_h - 300 + i), (target_w, target_h - 300 + i + 1)],
                       fill=(0, 0, 0, alpha))
    img = img.convert("RGBA")
    img = Image.alpha_composite(img, overlay).convert("RGB")

    img.save(output, "JPEG", quality=95)
    print(f"✅ Background salvo: {output}")
    return img


def make_thumbnail(base_img, thumb_text, channel_name="Soundscapes", output="thumbnail.jpg"):
    """
    Cria thumbnail 1280x720 com:
    - Foto de fundo com blur suave nas bordas
    - Overlay escuro central
    - Texto grande centralizado
    - Tag do canal no canto
    """
    W, H = 1280, 720
    img = base_img.resize((W, H), Image.LANCZOS)

    # Blur suave nas bordas
    blur = img.filter(ImageFilter.GaussianBlur(radius=4))
    mask = Image.new("L", (W, H), 0)
    draw_mask = ImageDraw.Draw(mask)
    border = 80
    for i in range(border):
        alpha = int(255 * (1 - i / border))
        draw_mask.rectangle([i, i, W - i, H - i], fill=alpha)
    img = Image.composite(img, blur, mask)

    # Overlay escuro no centro
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rectangle([(0, H//2 - 160), (W, H//2 + 160)], fill=(0, 0, 0, 140))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(img)

    # Tenta carregar fonte, usa default se não encontrar
    def get_font(size, bold=False):
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "C:/Windows/Fonts/arialbd.ttf",
        ]
        for path in font_paths:
            if os.path.exists(path):
                try: return ImageFont.truetype(path, size)
                except: pass
        return ImageFont.load_default()

    # Texto principal (thumb_text)
    lines = thumb_text.upper().split(" • ") if " • " in thumb_text else [thumb_text.upper()]
    font_big = get_font(90, bold=True)
    font_small = get_font(36)

    y_start = H // 2 - 60 * len(lines)
    for line in lines:
        # Sombra
        draw.text((W//2 + 3, y_start + 3), line, font=font_big,
                  fill=(0, 0, 0, 180), anchor="mm")
        # Texto principal branco
        draw.text((W//2, y_start), line, font=font_big,
                  fill=(255, 255, 255), anchor="mm")
        y_start += 100

    # Tag do canal no canto inferior direito
    draw.text((W - 20, H - 20), channel_name,
              font=font_small, fill=(220, 220, 220), anchor="rb")

    img.save(output, "JPEG", quality=92)
    size_kb = os.path.getsize(output) / 1024
    print(f"✅ Thumbnail salvo: {output} ({size_kb:.0f}KB)")
    return img


def main():
    # Lê metadata
    meta_files = sorted(glob.glob("metadata_*.json"), key=os.path.getmtime, reverse=True)
    if not meta_files:
        raise FileNotFoundError("Rode step1_metadata.py primeiro")

    with open(meta_files[0]) as f:
        metadata = json.load(f)

    query = metadata["background_image_query"]
    thumb_text = metadata["thumbnail_text"]
    print(f"📋 Usando metadata: {meta_files[0]}")

    # Baixa imagem
    url, photo_data = search_pexels(query)
    img = download_image(url)
    print(f"   ⬇ Imagem baixada ({img.width}x{img.height})")

    # Gera background e thumbnail
    bg = make_background(img, "background.jpg")
    make_thumbnail(bg, thumb_text, output="thumbnail.jpg")


if __name__ == "__main__":
    main()
