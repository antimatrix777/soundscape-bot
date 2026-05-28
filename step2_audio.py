```python
# ─────────────────────────────────────────────────────────
# STEREO PROCESSING
# ─────────────────────────────────────────────────────────

def mono_to_stereo_immersive(seg):
    """
    Convert mono to immersive pseudo-stereo.
    Stable for long renders and GitHub Actions.
    """

    if seg.channels == 2:
        return seg

    mono = seg.set_channels(1)

    delay_ms = 15

    left = mono.apply_gain(0.5)
    right = mono.apply_gain(-0.5)

    if len(right) > delay_ms:
        silence = AudioSegment.silent(
            duration=delay_ms,
            frame_rate=mono.frame_rate
        )

        right = silence + right[:-delay_ms]

    # FIX CHANNEL ALIGNMENT
    min_len = min(len(left), len(right))

    left = left[:min_len]
    right = right[:min_len]

    return AudioSegment.from_mono_audiosegments(left, right)


def ensure_stereo(seg):
    if seg.channels == 2:
        return seg

    return mono_to_stereo_immersive(seg)


def fit_audio_length(seg, target_ms):
    """
    Guarantees exact segment duration.
    Prevents drift and append instability.
    """

    if len(seg) > target_ms:
        seg = seg[:target_ms]

    elif len(seg) < target_ms:
        seg += AudioSegment.silent(
            duration=target_ms - len(seg)
        )

    return seg


# ─────────────────────────────────────────────────────────
# IMPROVED PROCEDURAL RAIN
# ─────────────────────────────────────────────────────────

def _rain_phrase(duration_ms=90000):
    """
    True stereo procedural rain with aligned channels.
    """

    bed_l = _noise_layer(
        duration_ms,
        -31,
        hp=620,
        lp=5400
    )

    bed_r = _noise_layer(
        duration_ms,
        -31,
        hp=680,
        lp=5000
    )

    near_l = _noise_layer(
        duration_ms,
        -38,
        hp=1700,
        lp=9000
    )

    near_r = _noise_layer(
        duration_ms,
        -39,
        hp=1950,
        lp=8500
    )

    room = _noise_layer(
        duration_ms,
        -46,
        lp=900
    )

    left = bed_l.overlay(near_l).overlay(room)
    right = bed_r.overlay(near_r).overlay(room)

    for at_ms in range(18000, duration_ms, 30000):

        t_l = _tone(
            52,
            8000,
            gain_db=-37,
            fade_ms=2500
        ).low_pass_filter(180)

        t_r = _tone(
            49,
            8000,
            gain_db=-37,
            fade_ms=2500
        ).low_pass_filter(180)

        left = left.overlay(
            t_l,
            position=at_ms
        )

        right = right.overlay(
            t_r,
            position=at_ms
        )

    left = _amplitude_swell(
        left,
        period_ms=28000,
        depth_db=1.5
    )

    right = _amplitude_swell(
        right,
        period_ms=32000,
        depth_db=1.5
    )

    # FIX CHANNEL ALIGNMENT
    min_len = min(len(left), len(right))

    left = left[:min_len]
    right = right[:min_len]

    stereo = AudioSegment.from_mono_audiosegments(
        left,
        right
    )

    return stereo.fade_in(2500).fade_out(2500)


# ─────────────────────────────────────────────────────────
# ORIGINAL AUDIO FALLBACK
# ─────────────────────────────────────────────────────────

def build_original_audio(category, hours, report):

    target = hours * 3600 * 1000

    print(
        f"  Original fallback: generating "
        f"copyright-safe stereo {category} bed"
    )

    if category == "rain":

        phrase = _rain_phrase()

    elif category in {"jazz", "lofi"}:

        roots = (
            [196.00, 220.00, 174.61, 246.94]
            if category == "lofi"
            else [146.83, 164.81, 130.81, 196.00]
        )

        bar_fn = (
            _lofi_bar
            if category == "lofi"
            else _jazz_bar
        )

        bar_ms = (
            8000
            if category == "lofi"
            else 9000
        )

        phrase = AudioSegment.silent(duration=0)

        for root in roots:

            bar = fit_audio_length(
                bar_fn(root, bar_ms),
                bar_ms
            )

            phrase = phrase.append(
                bar,
                crossfade=min(1200, bar_ms // 4)
            )

    else:
        raise RuntimeError(
            f"No original fallback for category '{category}'"
        )

    phrase = normalize_segment(phrase)

    phrase = ensure_stereo(phrase)

    audio = phrase

    while len(audio) < target + CROSSFADE_MS:

        audio = audio.append(
            phrase,
            crossfade=CROSSFADE_MS
        )

    audio = audio[:target]

    audio = audio.fade_in(3000).fade_out(8000)

    reasons, stats = _audio_quality(
        audio[:min(len(audio), 20 * 60 * 1000)],
        category
    )

    if reasons:
        raise RuntimeError(
            f"Original {category} fallback failed QA: "
            f"{'; '.join(reasons)}"
        )

    report["accepted"].append({
        "source": "original_synthesis",
        "license": "original - no third-party audio",
        "stats": {
            **stats,
            "channels_out": 2
        },
        "notes": (
            "Procedural stereo ambient bed "
            "generated by the pipeline."
        ),
    })

    report["warnings"].append(
        "Used original procedural audio because "
        "not enough CC0 third-party sources were available."
    )

    return audio


# ─────────────────────────────────────────────────────────
# LOOP AUDIO
# ─────────────────────────────────────────────────────────

def loop_audio(segs, hours):

    target = hours * 3600 * 1000

    out = fit_audio_length(
        segs[0],
        len(segs[0])
    ).fade_in(2500)

    i = 1

    while len(out) < target + CROSSFADE_MS:

        next_seg = fit_audio_length(
            segs[i % len(segs)],
            len(segs[i % len(segs)])
        )

        fade_ms = min(
            CROSSFADE_MS,
            len(out) // 3,
            len(next_seg) // 3
        )

        out = out.append(
            next_seg,
            crossfade=fade_ms
        )

        i += 1

    return out[:target].fade_out(8000)


# ─────────────────────────────────────────────────────────
# MAIN FINALIZER
# ─────────────────────────────────────────────────────────

finally:

    _save_report(report)

    try:
        import shutil

        shutil.rmtree(
            "audio_tmp",
            ignore_errors=True
        )

    except Exception as cleanup_error:

        print(
            f"Cleanup warning: {cleanup_error}"
        )

    print(
        f"Audio QA report saved: "
        f"{QUALITY_REPORT}"
    )

    print("DONE")
```
