/**
 * render-short.mjs
 * Chamado pelo step6_shorts.py via subprocess.
 * Lê inputProps.json, builda e renderiza o Short.
 */
import { bundle }             from '@remotion/bundler';
import { renderMedia, selectComposition, getCompositions } from '@remotion/renderer';
import { createRequire }      from 'module';
import { fileURLToPath }      from 'url';
import path                   from 'path';
import fs                     from 'fs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const propsPath = path.join(__dirname, 'inputProps.json');
const outPath   = path.join(__dirname, '..', 'short_final.mp4');

// Lê props geradas pelo Python
const props = JSON.parse(fs.readFileSync(propsPath, 'utf8'));
const {
  title,
  category,
  audioPath,
  durationSeconds = 59,
  fps             = 30,
} = props;

const durationInFrames = durationSeconds * fps;

console.log(`\n🎬 Remotion Render`);
console.log(`   Title:    ${title}`);
console.log(`   Category: ${category}`);
console.log(`   Duration: ${durationSeconds}s (${durationInFrames} frames @ ${fps}fps)`);
console.log(`   Audio:    ${audioPath}`);

// Entry point do React
const entryPoint = path.join(__dirname, 'src', 'index.tsx');

console.log('\n   Bundling...');
const bundleLocation = await bundle({
  entryPoint,
  webpackOverride: (config) => config,
});
console.log('   Bundle OK');

// Seleciona composição
const compositions = await getCompositions(bundleLocation, {
  inputProps: { title, category, audioPath, durationInFrames, fps },
});

const composition = compositions.find(c => c.id === 'ComfortShort');
if (!composition) {
  throw new Error(`Composição "ComfortShort" não encontrada. Disponíveis: ${compositions.map(c=>c.id).join(', ')}`);
}

console.log('\n   Renderizando...');
await renderMedia({
  composition: {
    ...composition,
    durationInFrames,
    fps,
    width:  1080,
    height: 1920,
  },
  serveUrl:       bundleLocation,
  codec:          'h264',
  outputLocation: outPath,
  inputProps: { title, category, audioPath, durationInFrames, fps },
  concurrency:    2,
  onProgress: ({ progress }) => {
    const pct = Math.round(progress * 100);
    if (pct % 10 === 0) process.stdout.write(`\r   Progresso: ${pct}%`);
  },
});

console.log(`\n\n   ✓ Short renderizado: ${outPath}`);
const size = (fs.statSync(outPath).size / 1024 / 1024).toFixed(1);
console.log(`   Tamanho: ${size}MB`);
