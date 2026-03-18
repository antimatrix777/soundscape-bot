def main():
    import random
    meta_files = sorted(glob.glob("metadata_*.json"), key=os.path.getmtime, reverse=True)
    if not meta_files:
        raise FileNotFoundError("Execute step1_metadata.py primeiro")

    with open(meta_files[0]) as f:
        metadata = json.load(f)

    category   = metadata.get("category", "cozy")
    thumb_text = metadata.get("thumbnail_text", "Comfort Sounds")
    pexels_q   = metadata.get("theme_data", {}).get("pexels", metadata.get("theme", "cozy ambience"))

    print(f"\nGerando imagem: categoria={category}")
    print(f"Thumbnail text: {thumb_text}")

    img, source = get_image(category, pexels_q)
    print(f"   Fonte usada: {source}")

    bg = make_background(img, "background.jpg")
    make_thumbnail(bg, thumb_text, "thumbnail.jpg")
    print("\nEtapa 3 concluida!")


if __name__ == "__main__":
    main()
