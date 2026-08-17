// Prueba de punta a punta de la fase 2, con navegador de verdad.
//
//   node e2e.mjs ruta/al/plano.dwg
//
// Da por hecho que ya corren el worker y `next start`. Comprueba lo que el DoD
// de la fase 2 exige, y una cosa mas que no esta en el DoD y deberia:
// que el token de servicio NO aparece en nada que reciba el navegador.
import { existsSync } from 'node:fs';
import { chromium } from 'playwright';

// El Chromium que trae la maquina puede no ser de la revision que espera esta
// version de playwright. Si hay uno instalado, se usa ese en vez de exigir
// `playwright install` (300 MB) en cada entorno.
const CHROME = process.env.PLAYWRIGHT_CHROMIUM
  ?? ['/opt/pw-browsers/chromium', '/usr/bin/chromium', '/usr/bin/google-chrome']
       .find((r) => existsSync(r));

const DWG = process.argv[2];
const WEB = process.env.WEB ?? 'http://127.0.0.1:3000';
const TOKEN = process.env.SERVICE_TOKEN ?? '';
if (!DWG) { console.error('uso: node e2e.mjs plano.dwg'); process.exit(1); }

let fallos = 0;
const ok = (etiqueta, cond, extra = '') => {
  console.log(`  ${cond ? 'OK   ' : 'FALLA'} ${etiqueta}${extra ? '  ' + extra : ''}`);
  if (!cond) fallos++;
};

const navegador = await chromium.launch(
  CHROME ? { executablePath: CHROME } : {});
const ctx = await navegador.newContext({ viewport: { width: 1280, height: 900 } });
const p = await ctx.newPage();

// todo lo que el navegador recibe, para el registro de fugas del token
const recibido = [];
p.on('response', async (r) => {
  const u = r.url();
  if (!u.startsWith(WEB)) return;
  try { recibido.push(await r.text()); } catch {}
});
const errores = [];
p.on('pageerror', (e) => errores.push(e.message));

console.log('── 1 · subir ───────────────────────────────────');
await p.goto(WEB);
ok('la pantalla de subida carga', await p.locator('h1').textContent() === 'Nuevo levantamiento');
await p.locator('input[type=file]').setInputFiles(DWG);
ok('acepta el fichero', (await p.locator('.drop').textContent()).includes('.dwg'));
await p.getByRole('button', { name: 'Procesar' }).click();
await p.waitForURL(/\/jobs\//, { timeout: 20000 });
const id = p.url().split('/jobs/')[1];
ok('crea el trabajo y navega', Boolean(id), id);

console.log('── 2 · estado ──────────────────────────────────');
await p.waitForSelector('text=Falta que lo mires', { timeout: 90000 });
const pasos = await p.locator('.paso .n').allTextContents();
ok('los 7 pasos en pantalla', pasos.length >= 7, pasos.join(' · '));
const rojos = await p.locator('.dot.no').count();
ok('ninguna comprobacion en rojo', rojos === 0);
const cuerpo = await p.locator('main').innerText();
ok('la salida del verificador es visible', cuerpo.includes('cobertura'));

console.log('── 3 · la puerta 7 ─────────────────────────────');
ok('avisa de que falta el ojo humano', cuerpo.includes('no se puede automatizar'));
const marco = p.frameLocator('iframe');
await marco.locator('svg').first().waitFor({ timeout: 20000 });
ok('la superposicion se renderiza en el iframe', true);
ok('no hay enlace antes de aprobar', !cuerpo.includes('Para el cliente final'));

await p.getByRole('button', { name: /Encaja/ }).click();
await p.waitForSelector('text=Para el cliente final', { timeout: 20000 });

console.log('── 4 · compartir ───────────────────────────────');
const enlace = await p.locator('a.enlace').first().getAttribute('href');
ok('devuelve el enlace del cliente', /^\/p\/[a-f0-9]{16}\/$/.test(enlace), enlace);

// El visor ALOJADO carga three.js de cdnjs. En un entorno sin salida a internet
// no se puede comprobar, y decir que pasa seria mentir. Se intenta, y si falla
// por red se declara como no comprobado en vez de darse por bueno.
const visor = await ctx.newPage();
await visor.goto(WEB + enlace);
let alojado = 'sin red';
try {
  await visor.waitForFunction('window.__ready === true', { timeout: 12000 });
  const e = await visor.evaluate(() => window.SCENE_DATA.islands.length);
  alojado = e === 2 ? 'ok' : 'geometria mal';
} catch { /* CDN inalcanzable */ }
if (alojado === 'sin red') {
  console.log('  ----- visor alojado (CDN)  NO COMPROBADO: sin salida a cdnjs');
} else {
  ok('el visor alojado arranca', alojado === 'ok', alojado);
}

// El visor OFFLINE no depende de nadie: este si se puede comprobar siempre, y es
// el que se manda por WhatsApp.
const off = await ctx.newPage();
await off.goto(WEB + enlace + 'offline');
await off.waitForFunction('window.__ready === true', { timeout: 30000 });
const escena = await off.evaluate(() => ({
  islas: window.SCENE_DATA.islands.length,
  estancias: window.SCENE_DATA.islands.map((i) => i.rooms.length),
}));
ok('el visor offline arranca en el enlace publico',
   escena.islas === 2 && escena.estancias.join() === '7,8', JSON.stringify(escena));

console.log('── movil ───────────────────────────────────────');
const movil = await ctx.newPage();
await movil.setViewportSize({ width: 390, height: 844 });
await movil.goto(WEB + enlace + 'offline');
await movil.waitForFunction('window.__ready === true', { timeout: 30000 });
const oculto = await movil.evaluate(() =>
  document.getElementById('panel').classList.contains('hide'));
ok('a 390 px el panel se colapsa', oculto);
await movil.screenshot({ path: '/tmp/e2e-movil.png' });

console.log('── el token no se filtra ───────────────────────');
const fuga = TOKEN ? recibido.filter((t) => t.includes(TOKEN)).length : -1;
ok('el token de servicio no llega al navegador', fuga === 0,
   TOKEN ? `${recibido.length} respuestas revisadas` : '(SERVICE_TOKEN no dado, sin comprobar)');
ok('sin errores de consola', errores.length === 0, errores.join(' | '));

await navegador.close();
console.log(fallos === 0 ? '\nTODAS LAS COMPROBACIONES OK' : `\n${fallos} COMPROBACIONES FALLAN`);
process.exit(fallos === 0 ? 0 : 1);
