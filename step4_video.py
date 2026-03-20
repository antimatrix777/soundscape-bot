"""
STEP 4 — Video Assembler (ffmpeg)
Combines background.jpg + output_audio.mp3 → final_video.mp4
Ken Burns effect: smooth zoom at 24fps (not 1fps).
"""
import subprocess, os, json, glob


def get_audio_duration(audio_file):
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
    ken_burns=True,
):
    if not os.path.exists(background):
        raise FileNotFoundError(f"Background not found: {background}")
    if not os.path.exists(audio):
        raise FileNotFoundError(f"Audio not found: {audio}")

    duration = get_audio_duration(audio)
    print(f"\nAssembling video...")
    print(f"   Background: {background}")
    print(f"   Audio: {audio} ({duration/3600:.1f}h)")

    if ken_burns:
        # FIX: 24fps for smooth zoom (was 1fps — looked choppy)
        fps          = 24
        total_frames = int(duration * fps)
        # Zoom from 1.0 to 1.03 over the entire video — smooth and subtle
        zoom_speed   = 0.03 / total_frames

        vf = (
            f"zoompan=z='min(zoom+{zoom_speed:.10f},1.03)':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={total_frames}:s=1920x1080:fps={fps}"
        )
    else:
        vf = "scale=1920:1080"

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", background,
        "-i", audio,
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "stillimage",
        "-crf", "23",              # FIX: was 28 — better visual quality
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output,
    ]

    print("   Processing (this takes 10-20 minutes)...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"ffmpeg error:\n{result.stderr[-2000:]}")
        raise RuntimeError("ffmpeg failed")

    size_mb = os.path.getsize(output) / (1024 * 1024)
    print(f"   Done: {output} ({size_mb:.0f}MB)")
    return output


def main():
    meta_files = sorted(glob.glob("metadata_*.json"), key=os.path.getmtime, reverse=True)
    if not meta_files:
        raise FileNotFoundError("Run step1_metadata.py first")

    with open(meta_files[0]) as f:
        metadata = json.load(f)

    theme_slug  = metadata["theme"][:30].replace(" ", "_")
    output_name = f"video_{theme_slug}.mp4"
    build_video(output=output_name)
    print(f"\nDone: {output_name}")


if __name__ == "__main__":
    main()
