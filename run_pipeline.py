"""
PIPELINE COMPLETO — Orquestrador Principal
Roda todas as 5 etapas em sequência.
"""
import os, sys, glob, argparse, subprocess, json
from datetime import datetime

def run(script, extra_args=None):
    cmd = [sys.executable, script] + (extra_args or [])
    print(f"\n{'='*55}\nRodando: {' '.join(cmd)}\n{'='*55}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"{script} falhou com codigo {result.returncode}")

def cleanup():
    print("\nLimpando arquivos temporarios...")
    for pat in ["output_audio.mp3","background.jpg","thumbnail.jpg",
                "video_*.mp4","sounds_tmp/*.mp3","metadata_*.json"]:
        for f in glob.glob(pat):
            try: os.remove(f); print(f"   Removido: {f}")
            except Exception as e: print(f"   Nao removeu {f}: {e}")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--category", choices=["rain","nature","cozy","jazz","focus_noise","study","urban"])
    p.add_argument("--duration", type=int, choices=[2,3,4])
    p.add_argument("--skip-upload", action="store_true")
    p.add_argument("--no-cleanup",  action="store_true")
    args = p.parse_args()

    start = datetime.now()
    print(f"\nSOUNDSCAPE BOT — {start.strftime('%Y-%m-%d %H:%M')}")
    print(f"   Categoria: {args.category or 'aleatorio'}")
    print(f"   Duracao:   {args.duration or 'aleatorio'}h")

    try:
        step1_args = []
        if args.category: step1_args += ["--category", args.category]
        if args.duration:  step1_args += ["--duration", str(args.duration)]
        run("step1_metadata.py", step1_args)
        run("step2_audio.py")
        run("step3_image.py")
        run("step4_video.py")
        if not args.skip_upload:
            run("step5_upload.py")
        else:
            print("\nUpload pulado")

        elapsed = int((datetime.now()-start).total_seconds()//60)
        print(f"\nPIPELINE CONCLUIDO em {elapsed} minutos!")
        if os.path.exists("last_upload.json"):
            with open("last_upload.json") as f:
                info = json.load(f)
            print(f"Video: {info.get('url','')}")

    except RuntimeError as e:
        print(f"\n{e}")
        sys.exit(1)
    finally:
        if not args.no_cleanup:
            cleanup()

if __name__ == "__main__":
    main()
