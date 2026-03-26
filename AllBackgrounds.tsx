import React from 'react';

interface Props { frame: number; totalFrames: number }

function seeded(s: number) {
  const x = Math.sin(s + 1) * 43758.5453;
  return x - Math.floor(x);
}

// ══════════════════════════════════════════════════════════════
// STUDY BG — luz de desk lamp com poeira flutuando no feixe
// ══════════════════════════════════════════════════════════════
export const StudyBg: React.FC<Props> = ({ frame }) => {
  const W = 1080, H = 1920;
  const fps = 30;

  // Oscilação suave da lâmpada (como se houvesse corrente de ar)
  const lampFlicker = 1 + 0.03 * Math.sin(frame / 11) + 0.015 * Math.sin(frame / 4.3);

  // Partículas de poeira no feixe de luz
  const numDust = 25;
  const dust = Array.from({ length: numDust }, (_, i) => {
    const period = fps * (8 + seeded(i * 7) * 10);
    const t      = ((frame * 0.4 + i * period * seeded(i * 11)) % period) / period;
    // Poeira flutua dentro do cone de luz
    const coneLeft  = W * 0.30 + t * 50;
    const coneRight = W * 0.70 - t * 50;
    const x = coneLeft + seeded(i * 13) * (coneRight - coneLeft);
    const y = H * 0.28 + t * H * 0.45 + Math.sin(t * 12 + i * 1.7) * 30;
    const opacity = t < 0.1 ? t / 0.1 * 0.5
                 : t > 0.8  ? (1-t) / 0.2 * 0.5
                 : 0.3 + seeded(i * 17) * 0.2;
    const r = 1.5 + seeded(i * 19) * 2;
    return { x, y, r, opacity };
  });

  // Chuva suave fora da janela (desfocada)
  const numRain = 20;
  const rain = Array.from({ length: numRain }, (_, i) => {
    const speed = 3 + seeded(i * 23) * 4;
    const y = ((frame * speed + seeded(i * 29) * H) % (H + 100)) - 50;
    const x = seeded(i * 31) * W;
    return { x, y };
  });

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
      <defs>
        <radialGradient id="studyRoom" cx="50%" cy="30%" r="70%">
          <stop offset="0%"   stopColor="#100e08" />
          <stop offset="100%" stopColor="#050403" />
        </radialGradient>
        <radialGradient id="lampBeam" cx="50%" cy="0%" r="100%">
          <stop offset="0%"   stopColor="#c8920a" stopOpacity={0.45 * lampFlicker} />
          <stop offset="100%" stopColor="transparent" stopOpacity="0" />
        </radialGradient>
        <filter id="sb_blur20"><feGaussianBlur stdDeviation="20" /></filter>
        <filter id="sb_blur8"> <feGaussianBlur stdDeviation="8"  /></filter>
        <filter id="sb_blur40"><feGaussianBlur stdDeviation="40" /></filter>
      </defs>

      <rect width={W} height={H} fill="url(#studyRoom)" />

      {/* Janela com chuva leve fora */}
      <rect x={W*0.55} y={H*0.05} width={W*0.38} height={H*0.38} rx={4} fill="#08101a" opacity="0.8" />
      {/* Chuva fora da janela */}
      <g opacity="0.15" clipPath="">
        {rain.map((r, i) => (
          <line key={i} x1={W*0.55 + (r.x % (W*0.38))} y1={H*0.05 + (r.y % (H*0.38))}
            x2={W*0.55 + (r.x % (W*0.38)) + 5} y2={H*0.05 + (r.y % (H*0.38)) + 20}
            stroke="rgba(150,180,220,0.6)" strokeWidth="1"
          />
        ))}
      </g>
      {/* Moldura da janela */}
      <rect x={W*0.55} y={H*0.05}  width={W*0.38} height={H*0.38} rx={4} fill="none" stroke="#1a1410" strokeWidth="12" />
      <line x1={W*0.74} y1={H*0.05} x2={W*0.74} y2={H*0.43} stroke="#1a1410" strokeWidth="8" />
      <line x1={W*0.55} y1={H*0.24} x2={W*0.93} y2={H*0.24} stroke="#1a1410" strokeWidth="8" />

      {/* Cone de luz da lâmpada */}
      <polygon
        points={`${W*0.42},${H*0.28} ${W*0.58},${H*0.28} ${W*0.78},${H*0.78} ${W*0.22},${H*0.78}`}
        fill="url(#lampBeam)"
        filter="url(#sb_blur20)"
      />
      {/* Núcleo do feixe */}
      <ellipse cx={W*0.5} cy={H*0.52} rx={130*lampFlicker} ry={200*lampFlicker}
        fill="rgba(200,150,40,0.08)" filter="url(#sb_blur40)" />

      {/* Lâmpada de mesa */}
      <circle cx={W*0.5} cy={H*0.26} r={35*lampFlicker}
        fill={`rgba(240,190,60,${0.7*lampFlicker})`} filter="url(#sb_blur8)" />
      <circle cx={W*0.5} cy={H*0.26} r={18}
        fill={`rgba(255,230,120,${0.9*lampFlicker})`} />
      {/* Suporte da lâmpada */}
      <line x1={W*0.5} y1={H*0.28} x2={W*0.5} y2={H*0.42}
        stroke="#1a1308" strokeWidth="6" />

      {/* Mesa */}
      <rect x={0} y={H*0.74} width={W} height={H*0.26} fill="#0d0a07" />
      <rect x={0} y={H*0.74} width={W} height={8} fill="#1a1510" />

      {/* Livros empilhados */}
      <rect x={W*0.06} y={H*0.72} width={W*0.12} height={H*0.03} rx={3} fill="#1a0e0a" />
      <rect x={W*0.06} y={H*0.69} width={W*0.12} height={H*0.03} rx={3} fill="#0e1a0a" />
      <rect x={W*0.06} y={H*0.66} width={W*0.11} height={H*0.03} rx={3} fill="#0a0e1a" />

      {/* Caderno aberto */}
      <rect x={W*0.28} y={H*0.72} width={W*0.25} height={H*0.04} rx={3} fill="#f5f0e8" opacity="0.6" />
      <line x1={W*0.405} y1={H*0.72} x2={W*0.405} y2={H*0.76} stroke="#d0c8b8" strokeWidth="2" />

      {/* Caneca */}
      <ellipse cx={W*0.72} cy={H*0.74} rx={28} ry={12} fill="#180f0a" />
      <rect x={W*0.72-24} y={H*0.72} width={48} height={38} rx={5} fill="#180f0a" />

      {/* Partículas de poeira */}
      {dust.map((d, i) => (
        <circle key={i} cx={d.x} cy={d.y} r={d.r}
          fill="rgba(220,190,130,1)" opacity={d.opacity}
        />
      ))}

      <rect width={W} height={H} fill="rgba(5,3,2,0.12)" />
    </svg>
  );
};

// ══════════════════════════════════════════════════════════════
// JAZZ BG — vinil girando, ondas de luz pulsantes
// ══════════════════════════════════════════════════════════════
export const JazzBg: React.FC<Props> = ({ frame }) => {
  const W = 1080, H = 1920;
  const fps = 30;

  const rpm = 33.3;
  const angle = (frame / fps) * (rpm / 60) * 360;

  // Ondas de som expandindo do vinil
  const numWaves = 5;
  const waves = Array.from({ length: numWaves }, (_, i) => {
    const period = fps * 3;
    const t      = ((frame + i * (period / numWaves)) % period) / period;
    const r      = 160 + t * 500;
    const opacity = (1 - t) * 0.3;
    return { r, opacity };
  });

  // Partículas de "notas musicais" flutuando
  const numNotes = 12;
  const notes = Array.from({ length: numNotes }, (_, i) => {
    const period = fps * (6 + seeded(i * 7) * 8);
    const t      = ((frame * 0.8 + i * period * seeded(i * 11)) % period) / period;
    const x      = W * 0.3 + seeded(i * 13) * W * 0.4;
    const y      = H * 0.5  - t * H * 0.35;
    const opacity = t < 0.15 ? t/0.15 * 0.5 : t > 0.7 ? (1-t)/0.3 * 0.5 : 0.5;
    return { x, y, opacity };
  });

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
      <defs>
        <radialGradient id="jazzRoom" cx="50%" cy="60%" r="70%">
          <stop offset="0%"   stopColor="#120a05" />
          <stop offset="100%" stopColor="#060304" />
        </radialGradient>
        <radialGradient id="vinylGlow" cx="50%" cy="50%" r="50%">
          <stop offset="0%"   stopColor="#c87020" stopOpacity="0.5" />
          <stop offset="100%" stopColor="transparent" />
        </radialGradient>
        <filter id="jz_blur30"><feGaussianBlur stdDeviation="30" /></filter>
        <filter id="jz_blur8"> <feGaussianBlur stdDeviation="8"  /></filter>
        <filter id="jz_blur5"> <feGaussianBlur stdDeviation="5"  /></filter>
      </defs>

      <rect width={W} height={H} fill="url(#jazzRoom)" />

      {/* Glow de neon no fundo */}
      <ellipse cx={W*0.2}  cy={H*0.4} rx={200} ry={80}
        fill="rgba(180,20,60,0.15)" filter="url(#jz_blur30)" />
      <ellipse cx={W*0.85} cy={H*0.3} rx={160} ry={70}
        fill="rgba(20,60,200,0.12)" filter="url(#jz_blur30)" />

      {/* Ondas expandindo */}
      {waves.map((w, i) => (
        <circle key={i} cx={W*0.5} cy={H*0.42}
          r={w.r} fill="none"
          stroke="rgba(200,140,40,1)"
          strokeWidth="1.5"
          opacity={w.opacity}
        />
      ))}

      {/* Disco de vinil */}
      <g transform={`rotate(${angle}, ${W*0.5}, ${H*0.42})`}>
        {/* Base preta */}
        <circle cx={W*0.5} cy={H*0.42} r={160} fill="#0d0a08" />
        {/* Sulcos */}
        {[140, 120, 100, 80, 60].map((r, i) => (
          <circle key={i} cx={W*0.5} cy={H*0.42} r={r}
            fill="none" stroke="#1a1614" strokeWidth="1.5" />
        ))}
        {/* Label central */}
        <circle cx={W*0.5} cy={H*0.42} r={42} fill="#8b1c1c" />
        <circle cx={W*0.5} cy={H*0.42} r={38} fill="#6e1515" />
        {/* Furo central */}
        <circle cx={W*0.5} cy={H*0.42} r={6} fill="#0d0a08" />
      </g>

      {/* Glow do vinil */}
      <circle cx={W*0.5} cy={H*0.42} r={180}
        fill="url(#vinylGlow)" filter="url(#jz_blur30)" />

      {/* Base do toca-discos */}
      <rect x={W*0.15} y={H*0.60} width={W*0.70} height={H*0.06} rx={8} fill="#100c08" />

      {/* Notas musicais */}
      {notes.map((n, i) => (
        <text key={i} x={n.x} y={n.y}
          fontSize="28" fill="rgba(200,150,60,1)"
          opacity={n.opacity} fontFamily="serif"
        >
          {i % 2 === 0 ? '♪' : '♫'}
        </text>
      ))}

      {/* Mesa de madeira */}
      <rect x={0} y={H*0.76} width={W} height={H*0.24} fill="#0e0a06" />
      <rect x={0} y={H*0.76} width={W} height={6} fill="#1c1510" />

      {/* Taça */}
      <ellipse cx={W*0.8} cy={H*0.76} rx={20} ry={8} fill="#18120a" />
      <path d={`M ${W*0.78} ${H*0.76} Q ${W*0.8} ${H*0.68} ${W*0.82} ${H*0.76}`}
        fill="#1e180e" />

      <rect width={W} height={H} fill="rgba(5,3,2,0.10)" />
    </svg>
  );
};

// ══════════════════════════════════════════════════════════════
// URBAN BG — luzes da cidade, chuva, reflexos no asfalto
// ══════════════════════════════════════════════════════════════
export const UrbanBg: React.FC<Props> = ({ frame }) => {
  const W = 1080, H = 1920;
  const fps = 30;

  const numDrops = 50;
  const drops = Array.from({ length: numDrops }, (_, i) => {
    const speed  = 5 + seeded(i * 7) * 8;
    const y      = ((frame * speed + seeded(i * 11) * H) % (H + 80)) - 40;
    const x      = seeded(i * 13) * W;
    const length = 15 + seeded(i * 17) * 40;
    const opacity = 0.2 + seeded(i * 19) * 0.35;
    return { x, y, length, opacity };
  });

  // Neóns piscando
  const neons = [
    { x: W*0.08, y: H*0.30, w: 180, color: '#ff2060', period: 7, phase: 0    },
    { x: W*0.60, y: H*0.22, w: 140, color: '#00aaff', period: 11, phase: 2.1 },
    { x: W*0.20, y: H*0.45, w: 100, color: '#ffaa00', period: 13, phase: 1.4 },
    { x: W*0.70, y: H*0.38, w: 160, color: '#aa00ff', period: 9,  phase: 3.0 },
  ];

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
      <defs>
        <linearGradient id="urbanSky" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%"   stopColor="#050810" />
          <stop offset="50%"  stopColor="#0a1020" />
          <stop offset="100%" stopColor="#14101a" />
        </linearGradient>
        <filter id="ub_blur25"><feGaussianBlur stdDeviation="25" /></filter>
        <filter id="ub_blur8"> <feGaussianBlur stdDeviation="8"  /></filter>
        <filter id="ub_blur15"><feGaussianBlur stdDeviation="15" /></filter>
      </defs>

      <rect width={W} height={H} fill="url(#urbanSky)" />

      {/* Prédios escuros com janelas */}
      <g>
        {[
          [0,    H*0.25, 160, H*0.75],
          [140,  H*0.15, 130, H*0.85],
          [250,  H*0.30, 100, H*0.70],
          [330,  H*0.20, 140, H*0.80],
          [450,  H*0.10, 120, H*0.90],
          [550,  H*0.25, 110, H*0.75],
          [640,  H*0.18, 150, H*0.82],
          [770,  H*0.28, 100, H*0.72],
          [850,  H*0.12, 140, H*0.88],
          [970,  H*0.22, 110, H*0.78],
        ].map(([x, y, w, h], i) => (
          <rect key={i} x={x} y={y} width={w} height={h} fill="#070810" />
        ))}
      </g>

      {/* Janelas dos prédios */}
      {Array.from({ length: 120 }, (_, i) => {
        const bx = seeded(i * 53) * W;
        const by = H * 0.12 + seeded(i * 59) * H * 0.55;
        const lit = seeded(i * 61) > 0.45;
        if (!lit) return null;
        const flicker = seeded(i*67) > 0.9
          ? (Math.sin(frame / 6 + i) > 0.3 ? 1 : 0)
          : 1;
        const hue = seeded(i * 71) > 0.6 ? 45 : seeded(i * 71) > 0.3 ? 200 : 280;
        return (
          <rect key={i} x={bx} y={by} width={7} height={11}
            fill={`hsl(${hue}, 60%, ${45*flicker}%)`}
            opacity={0.6 * flicker}
          />
        );
      })}

      {/* Neóns */}
      {neons.map((n, i) => {
        const blink = 0.6 + 0.4 * Math.abs(Math.sin(frame / n.period + n.phase));
        return (
          <g key={i}>
            <rect x={n.x} y={n.y} width={n.w} height={8} rx={4}
              fill={n.color} opacity={blink} filter="url(#ub_blur8)"
            />
            <rect x={n.x} y={n.y} width={n.w} height={8} rx={4}
              fill={n.color} opacity={blink * 0.4}
            />
          </g>
        );
      })}

      {/* Reflexos dos neóns no asfalto molhado */}
      <g filter="url(#ub_blur25)" opacity="0.4">
        {neons.map((n, i) => {
          const blink = 0.6 + 0.4 * Math.abs(Math.sin(frame / n.period + n.phase));
          return (
            <rect key={i}
              x={n.x} y={H - (H - n.y) + (H*0.5 - n.y) * 0.15}
              width={n.w} height={60} rx={4}
              fill={n.color} opacity={blink * 0.5}
            />
          );
        })}
      </g>

      {/* Asfalto molhado */}
      <rect x={0} y={H*0.72} width={W} height={H*0.28} fill="#0a0c12" />
      <rect x={0} y={H*0.72} width={W} height={4} fill="#141820" />

      {/* Poças d'água (reflexo) */}
      {[W*0.2, W*0.5, W*0.78].map((cx, i) => (
        <ellipse key={i} cx={cx} cy={H*0.82} rx={80+i*30} ry={15}
          fill="rgba(60,80,120,0.3)" filter="url(#ub_blur15)"
        />
      ))}

      {/* Chuva */}
      <g opacity="0.5">
        {drops.map((d, i) => (
          <line key={i}
            x1={d.x} y1={d.y}
            x2={d.x + d.length*0.12} y2={d.y + d.length}
            stroke="rgba(150,180,220,0.7)"
            strokeWidth="1"
            opacity={d.opacity}
          />
        ))}
      </g>

      <rect width={W} height={H} fill="rgba(3,4,10,0.15)" />
    </svg>
  );
};

// ══════════════════════════════════════════════════════════════
// FOCUS BG — ondas geométricas minimalistas expandindo
// ══════════════════════════════════════════════════════════════
export const FocusBg: React.FC<Props> = ({ frame }) => {
  const W = 1080, H = 1920;
  const fps = 30;

  const numRings = 8;
  const rings = Array.from({ length: numRings }, (_, i) => {
    const period = fps * 6;
    const t      = ((frame + i * (period / numRings)) % period) / period;
    const maxR   = Math.sqrt(W*W + H*H) * 0.6;
    const r      = t * maxR;
    const opacity = (1 - t) * 0.18;
    return { r, opacity };
  });

  // Linhas de grade suaves
  const gridOpacity = 0.04 + 0.02 * Math.sin(frame / (fps * 8));

  // Ponto central pulsando
  const pulse = 1 + 0.15 * Math.sin(frame / (fps * 1.5));

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
      <defs>
        <radialGradient id="focusBg" cx="50%" cy="55%" r="70%">
          <stop offset="0%"   stopColor="#0c0e18" />
          <stop offset="100%" stopColor="#06070f" />
        </radialGradient>
        <filter id="fc_blur4"><feGaussianBlur stdDeviation="4" /></filter>
        <filter id="fc_blur20"><feGaussianBlur stdDeviation="20" /></filter>
      </defs>

      <rect width={W} height={H} fill="url(#focusBg)" />

      {/* Grade de fundo */}
      <g opacity={gridOpacity} stroke="rgba(100,120,200,1)" strokeWidth="1">
        {Array.from({ length: 20 }, (_, i) => (
          <line key={`v${i}`} x1={i*60} y1={0} x2={i*60} y2={H} />
        ))}
        {Array.from({ length: 35 }, (_, i) => (
          <line key={`h${i}`} x1={0} y1={i*60} x2={W} y2={i*60} />
        ))}
      </g>

      {/* Ondas circulares */}
      {rings.map((ring, i) => (
        <circle key={i}
          cx={W*0.5} cy={H*0.5}
          r={ring.r}
          fill="none"
          stroke="rgba(80,120,255,1)"
          strokeWidth="1.5"
          opacity={ring.opacity}
        />
      ))}

      {/* Ponto central */}
      <circle cx={W*0.5} cy={H*0.5} r={40*pulse}
        fill="rgba(80,120,255,0.08)" filter="url(#fc_blur20)" />
      <circle cx={W*0.5} cy={H*0.5} r={8*pulse}
        fill="rgba(120,160,255,0.6)" filter="url(#fc_blur4)" />
      <circle cx={W*0.5} cy={H*0.5} r={3} fill="rgba(180,210,255,0.9)" />

      {/* Linhas diagonais sutis */}
      <g opacity="0.025" stroke="rgba(100,140,220,1)" strokeWidth="1">
        {Array.from({ length: 12 }, (_, i) => {
          const a = (i / 12) * Math.PI;
          return (
            <line key={i}
              x1={W*0.5} y1={H*0.5}
              x2={W*0.5 + Math.cos(a) * W}
              y2={H*0.5 + Math.sin(a) * H}
            />
          );
        })}
      </g>

      {/* Texto minimalista */}
      <text x={W*0.5} y={H*0.75}
        textAnchor="middle"
        fontSize="20"
        fill="rgba(80,120,255,0.15)"
        letterSpacing="8"
        fontFamily="monospace"
      >
        NOCTURNE NOISE
      </text>

      <rect width={W} height={H} fill="rgba(4,5,10,0.12)" />
    </svg>
  );
};
