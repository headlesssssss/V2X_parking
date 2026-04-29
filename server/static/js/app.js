'use strict';

const SENSORS  = { 12: 'C2', 16: 'C4', 17: 'C1', 22: 'C3' };
const CLS      = { FREE: 'free', OCCUPIED: 'occupied', ANOMALY: 'anomaly' };
const LBL      = { FREE: 'LIBRE', OCCUPIED: 'OCCUPÉE', ANOMALY: 'ANOMALIE' };
const ARROWS   = { '0,1': '→', '0,-1': '←', '1,0': '↓', '-1,0': '↑' };

let mapem = null, socket = null, denmN = 0;
let prevSnapshot = {};  // pour détecter les places qui se libèrent
let soundEnabled = true;

const $ = id => document.getElementById(id);

/* ── Son notification ───────────────────────────── */
function playNotifSound() {
  if (!soundEnabled) return;
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    // Son doux type "ding" — 2 notes
    [520, 660].forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.15, ctx.currentTime + i * 0.15);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + i * 0.15 + 0.4);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(ctx.currentTime + i * 0.15);
      osc.stop(ctx.currentTime + i * 0.15 + 0.4);
    });
  } catch {}
}

function checkFreedSpot(spotId, newEtat) {
  const prev = prevSnapshot[spotId];
  if (prev && prev !== 'FREE' && newEtat === 'FREE') {
    playNotifSound();
    showToast(`Place ${spotId} libérée !`);
  }
  prevSnapshot[spotId] = newEtat;
}

function showToast(msg) {
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();
  
  const t = document.createElement('div');
  t.className = 'toast';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.classList.add('show'), 10);
  setTimeout(() => { t.classList.remove('show'); setTimeout(() => t.remove(), 300); }, 3000);
}

/* ── Grid ───────────────────────────────────────── */
function buildGrid(data) {
  const g = $('parking-grid');
  g.innerHTML = '';
  const rows = data.grid.length, cols = data.grid[0].length;
  g.style.gridTemplateColumns = `repeat(${cols}, minmax(44px,1fr))`;
  g.style.gridTemplateRows    = `repeat(${rows}, 52px)`;

  data.grid.forEach((row, r) => row.forEach((v, c) => {
    const d = document.createElement('div');
    d.dataset.r = r; d.dataset.c = c; d.dataset.v = v;

    if (v === 1) {
      d.className = 'cell c-wall';
    } else if (v === 0) {
      d.className = 'cell c-road';
    } else if (v === 98) {
      d.className = 'cell c-entry';
      d.innerHTML = '<span style="font-size:.85rem">↑</span><span style="font-size:.48rem;letter-spacing:.04em">ENTRÉE</span>';
    } else if (v === 99) {
      d.className = 'cell c-hall';
      d.innerHTML = '<span style="writing-mode:vertical-rl;font-size:.45rem;letter-spacing:.06em;opacity:.7">HALL</span>';
    } else if (v >= 10 && v <= 90) {
      const sp = data.spots[String(v)];
      const et = sp ? sp.etat : 'FREE';
      const lb = SENSORS[v] || '';
      d.id = `s${v}`;
      d.className = `cell c-spot ${CLS[et]||'free'}`;
      if (lb) d.classList.add('has-sensor');
      d.innerHTML = `<span class="spot-id">${v}</span>${lb ? `<span class="spot-lbl">${lb}</span>` : ''}`;
      d.onclick = () => reqGuide(v);
    }
    g.appendChild(d);
  }));
}

/* ── Update spot ────────────────────────────────── */
function updSpot(id, et) {
  const el = $(`s${id}`);
  if (!el) return;
  el.classList.remove('free','occupied','anomaly');
  el.classList.add(CLS[et]||'free');
}

/* ── Stats ──────────────────────────────────────── */
function updStats(f, o, a) {
  $('stat-free').innerHTML  = `<span class="stat-n">${f}</span><span class="stat-l">libres</span>`;
  $('stat-occ').innerHTML   = `<span class="stat-n">${o}</span><span class="stat-l">occupées</span>`;
  $('stat-anom').innerHTML   = `<span class="stat-n">${a}</span><span class="stat-l">anomalies</span>`;
}

function calcStats(spots) {
  const v = Object.values(spots);
  return { f: v.filter(x=>x==='FREE').length, o: v.filter(x=>x==='OCCUPIED').length, a: v.filter(x=>x==='ANOMALY').length };
}

/* ── Path (Waze) ────────────────────────────────── */
function clearPath() {
  document.querySelectorAll('.on-path').forEach(e => {
    e.classList.remove('on-path');
    const a = e.querySelector('.path-arrow'); if (a) a.remove();
  });
  document.querySelectorAll('.is-dest').forEach(e => e.classList.remove('is-dest'));
}

function drawPath(path, dest) {
  clearPath();
  if (!path || !path.length) return;

  path.forEach(([r,c], i) => {
    const el = document.querySelector(`[data-r="${r}"][data-c="${c}"]`);
    if (!el) return;

    if (i === path.length - 1) {
      setTimeout(() => el.classList.add('is-dest'), i * 80);
    } else if (i > 0) {
      setTimeout(() => {
        el.classList.add('on-path');
        if (i < path.length - 1) {
          const dr = path[i+1][0]-r, dc = path[i+1][1]-c;
          const ch = ARROWS[`${dr},${dc}`];
          if (ch) {
            const s = document.createElement('span');
            s.className = 'path-arrow'; s.textContent = ch;
            el.appendChild(s);
          }
        }
      }, i * 80);
    }
  });

  const gd = $('guide-dest'), gi = $('guide-dist'), gp = $('guide-panel');
  if (dest && gd) {
    gd.textContent = `Place ${dest}`;
    gi.textContent = `${path.length - 1} pas`;
    gp.className = 'guide-panel'; gp.hidden = false;
  }
}

/* ── Guidance request ───────────────────────────── */
async function reqGuide(spotId) {
  const btn = $('btn-guide'), gp = $('guide-panel');
  btn.disabled = true; btn.textContent = 'Calcul…'; clearPath();

  try {
    const body = spotId != null ? { spot_id: spotId } : {};
    const res = await fetch('/api/guidance', {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)
    });
    const data = await res.json();

    if (data.error) {
      $('guide-dest').textContent = '—';
      $('guide-dist').textContent = data.error;
      gp.className = 'guide-panel error'; gp.hidden = false;
    } else {
      drawPath(data.path, data.spot_id);
    }
  } catch {
    $('guide-dest').textContent = '—';
    $('guide-dist').textContent = 'Erreur réseau';
    gp.className = 'guide-panel error'; gp.hidden = false;
  } finally {
    btn.disabled = false; btn.textContent = 'Trouver une place libre';
  }
}

/* ── DENM ───────────────────────────────────────── */
function addDenm(d) {
  denmN++;
  const b = $('denm-badge'); b.textContent = denmN; b.hidden = false;
  const list = $('denm-list');
  const emp = list.querySelector('.empty'); if (emp) emp.remove();

  const div = document.createElement('div');
  div.className = 'alert-item';
  div.innerHTML = `<span class="a-head">⚠ Capteur C${d.hw_id}${d.spot_id ? ` — Place ${d.spot_id}` : ''}</span>
    <span class="a-body">${esc(d.reason)}</span><span class="a-time">${fmtT(d.ts)}</span>`;
  list.prepend(div);
  while (list.children.length > 12) list.lastChild.remove();
}

/* ── Log ────────────────────────────────────────── */
function addLog(d) {
  const list = $('log-list');
  const emp = list.querySelector('.empty'); if (emp) emp.remove();
  const c = CLS[d.etat]||'free', l = LBL[d.etat]||d.etat;
  const dist = d.distance_cm != null ? ` (${Number(d.distance_cm).toFixed(1)}cm)` : '';

  const div = document.createElement('div');
  div.className = `log-row l-${c}`;
  div.innerHTML = `<span class="log-time">${fmtT(d.ts)}</span><span class="log-msg">C${d.hw_id} → P${d.spot_id} : ${l}${dist}</span>`;
  list.prepend(div);
  while (list.children.length > 30) list.lastChild.remove();
}

/* ── Socket ─────────────────────────────────────── */
function initIO() {
  socket = io({ transports: ['websocket','polling'] });

  socket.on('connect', () => {
    $('conn-dot').className = 'conn-indicator connected';
    reqGuide(null);
  });
  socket.on('disconnect', () => {
    $('conn-dot').className = 'conn-indicator disconnected';
  });

  socket.on('spatem', d => {
    checkFreedSpot(d.spot_id, d.etat);  // notification sonore si place libérée
    updSpot(d.spot_id, d.etat);
    updStats(d.free, d.occupied, d.anomaly_count);
    addLog(d);
  });

  socket.on('guidance_update', d => {
    if (d.spot_id) { drawPath(d.path, d.spot_id); }
    else {
      clearPath();
      $('guide-dest').textContent = '—';
      $('guide-dist').textContent = 'Parking complet';
      $('guide-panel').className = 'guide-panel error';
      $('guide-panel').hidden = false;
    }
  });

  socket.on('denm', addDenm);
}

/* ── Util ───────────────────────────────────────── */
function fmtT(s) {
  try { return new Date(s).toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit',second:'2-digit'}); }
  catch { return ''; }
}
function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

/* ── Init ───────────────────────────────────────── */
async function init() {
  try {
    const r = await fetch('/api/mapem');
    mapem = await r.json();
    buildGrid(mapem);
    const st = calcStats(Object.fromEntries(Object.entries(mapem.spots).map(([k,v])=>[k,v.etat])));
    updStats(st.f, st.o, st.a);
  } catch(e) {
    console.error('[APP]', e);
    $('parking-grid').innerHTML = '<p class="empty" style="color:var(--occ)">Impossible de charger la carte</p>';
  }

  $('btn-guide').onclick = () => reqGuide(null);
  $('btn-sound').onclick = () => {
    soundEnabled = !soundEnabled;
    $('btn-sound').textContent = soundEnabled ? '🔔' : '🔕';
    $('btn-sound').title = soundEnabled ? 'Notifications activées' : 'Notifications désactivées';
  };

  // Initialiser le snapshot pour tracker les changements
  if (mapem && mapem.spots) {
    Object.entries(mapem.spots).forEach(([k, v]) => { prevSnapshot[parseInt(k)] = v.etat; });
  }

  initIO();

  try { const r = await fetch('/api/denm'); (await r.json()).slice(0,5).reverse().forEach(addDenm); } catch {}
}

document.addEventListener('DOMContentLoaded', init);
