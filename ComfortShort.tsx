import React from 'react';
import {
  AbsoluteFill, useCurrentFrame, useVideoConfig,
  interpolate, Easing, Audio, staticFile,
} from 'remotion';
import { RainBg }       from './backgrounds/RainBg';
import { CozyBg }       from './backgrounds/CozyBg';
import { NatureBg }     from './backgrounds/NatureBg';
import { StudyBg }      from './backgrounds/StudyBg';
import { JazzBg }       from './backgrounds/JazzBg';
import { UrbanBg }      from './backgrounds/UrbanBg';
import { FocusBg }      from './backgrounds/FocusBg';

// ─── Types ────────────────────────────────────────────────
export interface ShortProps {
  title:            string;
  category:         string;
  audioPath:        string;
  durationInFrames: number;
  fps:              number;
}

// ─── Background selector ──────────────────────────────────
const BG_MAP: Record<string, React.FC<{ frame: number; totalFrames: number }>> = {
  rain:        RainBg,
  cozy:        CozyBg,
  nature:      NatureBg,
  study:       StudyBg,
  jazz:        JazzBg,
  urban:       UrbanBg,
  focus_noise: FocusBg,
};

// ─── Main composition ─────────────────────────────────────
export const ComfortShort: React.FC<ShortProps> = ({
  title,
  category,
  audioPath,
  durationInFrames,
  fps,
}) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();

  const BgComponent = BG_MAP[category] ?? CozyBg;

  // ── Global fade in/out para loop seamless ──────────────
  const fadeInEnd   = fps * 1.2;    // 1.2s fade in
  const fadeOutStart = durationInFrames - fps * 1.5; // 1.5s fade out

  const globalOpacity = interpolate(
    frame,
    [0, fadeInEnd, fadeOutStart, durationInFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  );

  // ── Título: aparece aos 0.8s, flutua suavemente ─────────
  const titleStart = Math.floor(fps * 0.8);

  const titleOpacity = interpolate(
    frame,
    [titleStart, titleStart + fps, fadeOutStart - fps * 0.5, fadeOutStart + fps * 0.3],
    [0, 1, 1, 0],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic) }
  );

  // Float suave: sobe e desce levemente
  const floatY = Math.sin(frame / (fps * 2.5)) * 6;

  // ── Vinheta lateral ─────────────────────────────────────
  const vignetteStyle: React.CSSProperties = {
    position: 'absolute',
    inset: 0,
    background: 'radial-gradient(ellipse at center, transparent 40%, rgba(0,0,0,0.55) 100%)',
    pointerEvents: 'none',
  };

  // ── Linha decorativa acima do título ────────────────────
  const lineWidth = interpolate(
    frame,
    [titleStart, titleStart + fps * 1.5],
    [0, 120],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic) }
  );

  return (
    <AbsoluteFill style={{ background: '#080810', overflow: 'hidden' }}>

      {/* Background animado */}
      <AbsoluteFill style={{ opacity: globalOpacity }}>
        <BgComponent frame={frame} totalFrames={durationInFrames} />
      </AbsoluteFill>

      {/* Vinheta */}
      <div style={vignetteStyle} />

      {/* Gradiente escuro no topo (área do título) */}
      <AbsoluteFill style={{
        background: 'linear-gradient(to bottom, rgba(0,0,0,0.65) 0%, rgba(0,0,0,0.2) 35%, transparent 55%)',
        pointerEvents: 'none',
      }} />

      {/* Título — terço superior, flutuando */}
      <AbsoluteFill style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'flex-start',
        paddingTop: Math.floor(height * 0.10),
        opacity: titleOpacity,
        transform: `translateY(${floatY}px)`,
      }}>
        {/* Linha decorativa */}
        <div style={{
          width: lineWidth,
          height: 1,
          background: 'rgba(200, 160, 80, 0.6)',
          marginBottom: 22,
          borderRadius: 1,
        }} />

        {/* Título */}
        <div style={{
          fontFamily:    '"Georgia", "Times New Roman", serif',
          fontSize:      72,
          fontWeight:    400,
          color:         '#f0e8d0',
          textAlign:     'center',
          lineHeight:    1.25,
          letterSpacing: '0.02em',
          paddingLeft:   60,
          paddingRight:  60,
          textShadow:    '0 2px 30px rgba(0,0,0,0.9), 0 0 80px rgba(180,120,40,0.25)',
          maxWidth:      960,
          fontStyle:     'italic',
        }}>
          {title}
        </div>

        {/* Canal */}
        <div style={{
          marginTop:     20,
          fontFamily:    '"Georgia", serif',
          fontSize:      26,
          fontWeight:    300,
          color:         'rgba(200, 170, 100, 0.55)',
          letterSpacing: '0.18em',
          textTransform: 'uppercase',
        }}>
          Nocturne Noise
        </div>
      </AbsoluteFill>

      {/* Áudio */}
      {audioPath && (
        <Audio src={audioPath} />
      )}

    </AbsoluteFill>
  );
};
