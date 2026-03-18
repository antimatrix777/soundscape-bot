"""
ETAPA 4 — Montador de Vídeo (ffmpeg direto — GRÁTIS)
Combina background.jpg + output_audio.mp3 → final_video.mp4
Usa ffmpeg diretamente (mais rápido que MoviePy para imagem estática + áudio longo).
Ken Burns (slow zoom) via filtro de vídeo do ffmpeg.
"""
import subprocess, os, json, glob


def get_audio_duration(audio_file):
    """Retorna duração do áudio em segundos via ffprobe."""
    result = subprocess.run([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", audio_file
    ], capture_output=True, text=True)
    info = json.loads(result.stdout)
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "audio":
            return float(stream["duration"])
    return 0


def build_video(
    background="background.jpg",
    audio="output_audio.mp3",
    output="final_video.mp4",
    ken_burns=True
):
    """
    Monta o vídeo final com ffmpeg.
    Ken Burns: zoom suave de 1.0x → 1.03x ao longo do vídeo.
    """
    if not os.path.exists(background):
        raise FileNotFoundError(f"Background não encontrado: {background}")
    if not os.path.exists(audio):
        raise FileNotFoundError(f"Áudio não encontrado: {audio}")

    duration = get_audio_duration(audio)
    print(f"\n🎬 Montando vídeo...")
    print(f"   📷 Background: {background}")
    print(f"   🎵 Áudio: {audio} ({duration/3600:.1f}h)")

    if ken_burns:
        # Zoom suave: começa em 1.0x, termina em 1.03x
        # zoompan: zoom de 1.0 a 1.03 ao longo de toda a duração
        fps = 1  # 1 fps para imagem estática — economiza espaço
        total_frames = int(duration * fps)
        zoom_speed = 0.03 / total_frames  # incremento por frame

        vf = (
            f"zoompan=z='min(zoom+{zoom_speed:.8f},1.03)':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={total_frames}:s=1920x1080:fps={fps}"
        )
    else:
        vf = "scale=1920:1080"

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",              # imagem estática em loop
        "-i", background,
        "-i", audio,
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "ultrafast",    # prioriza velocidade no GitHub Actions
        "-tune", "stillimage",     # otimizado para imagem estática
        "-crf", "28",              # qualidade (18=lossless, 28=boa/compacta)
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",               # para quando o áudio terminar
        "-pix_fmt", "yuv420p",     # compatibilidade máxima
        "-movflags", "+faststart", # permite streaming antes do download completo
        output
    ]

    print(f"   ⚙️  Processando (pode levar 5-15 minutos)...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"❌ Erro no ffmpeg:\n{result.stderr[-2000:]}")
        raise RuntimeError("ffmpeg falhou")

    size_mb = os.path.getsize(output) / (1024 * 1024)
    print(f"✅ Vídeo gerado: {output} ({size_mb:.0f}MB)")
    return output


def main():
    meta_files = sorted(glob.glob("metadata_*.json"), key=os.path.getmtime, reverse=True)
    if not meta_files:
        raise FileNotFoundError("Rode step1_metadata.py primeiro")

    with open(meta_files[0]) as f:
        metadata = json.load(f)

    theme_slug = metadata["theme"][:30].replace(" ", "_")
    output_name = f"video_{theme_slug}.mp4"

    build_video(output=output_name)
    print(f"\n🎉 Pronto! Arquivo: {output_name}")


if __name__ == "__main__":
    main()
