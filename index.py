"""FITLOG - personal fitness and nutrition tracker for Vercel.

Stateless: it never stores personal data. The browser keeps everything in
LocalStorage and calls this endpoint for calculations and the food database.

  GET  /                            the app (HTML + JavaScript; styles come from /style.css)
  GET  /api/index?action=meta       activities, MET values, goals, activity levels
  GET  /api/index?action=foods      offline food database (per 100 g)
  POST /api/index?action=targets    BMI, BMR, TDEE and calorie/macro targets
  POST /api/index?action=calories   MET-based exercise calorie estimate
"""
import json
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

# MET values (approximate, based on the Compendium of Physical Activities).
ACTIVITIES = {
    "walking":   {"label": "Walking",       "levels": {"slow": 2.8, "moderate": 3.5, "brisk": 4.3}},
    "running":   {"label": "Running",       "levels": {"light": 8.0, "moderate": 9.8, "fast": 11.5}},
    "cycling":   {"label": "Cycling",       "levels": {"light": 4.0, "moderate": 8.0, "vigorous": 10.0}},
    "strength":  {"label": "Strength training", "levels": {"light": 3.0, "moderate": 4.5, "vigorous": 6.0}},
    "swimming":  {"label": "Swimming",      "levels": {"light": 6.0, "moderate": 8.0, "vigorous": 10.0}},
    "football":  {"label": "Football",      "levels": {"light": 7.0, "moderate": 8.5, "vigorous": 10.0}},
    "basketball": {"label": "Basketball",   "levels": {"light": 4.5, "moderate": 6.5, "vigorous": 8.0}},
    "badminton": {"label": "Badminton",     "levels": {"light": 4.5, "moderate": 5.5, "vigorous": 7.0}},
    "jumprope":  {"label": "Jump rope",     "levels": {"light": 8.8, "moderate": 11.8, "vigorous": 12.3}},
    "custom":    {"label": "Other activity", "levels": {"light": 3.0, "moderate": 5.0, "vigorous": 7.0}},
}
GOALS = {"bulk": "Lean Bulk", "cut": "Cut", "maintain": "Maintain Weight"}
ACTIVITY_LEVELS = {
    "sedentary": (1.2, "Sedentary (desk job, little exercise)"),
    "light": (1.375, "Lightly active (light exercise 1-3 days/week)"),
    "moderate": (1.55, "Moderately active (exercise 3-5 days/week)"),
    "very": (1.725, "Very active (hard exercise 6-7 days/week)"),
}

# Food database, per 100 g: [name, category, kcal, protein, carbs, fat, serving_g, serving_label, note]
# Add your own foods by appending rows here.
FOOD_ROWS = [
    ["Paneer", "Indian dairy", 285, 18, 3.5, 22, 50, "2 cubes (50 g)", "Full-fat paneer. Low-fat versions are roughly 200 kcal."],
    ["Milk, full cream", "Dairy", 67, 3.4, 4.8, 4.0, 250, "1 glass (250 ml)", ""],
    ["Curd (dahi)", "Indian dairy", 61, 3.5, 4.7, 3.3, 100, "1 katori (100 g)", "Made from whole milk."],
    ["Buttermilk (chaas)", "Indian dairy", 18, 1.0, 2.2, 0.5, 200, "1 glass (200 ml)", ""],
    ["Greek yogurt, plain low-fat", "Dairy", 73, 10, 3.6, 2.0, 150, "1 bowl (150 g)", ""],
    ["Cheese, cheddar", "Dairy", 400, 25, 1.3, 33, 20, "1 slice (20 g)", ""],
    ["Ghee", "Fats", 900, 0, 0, 100, 5, "1 tsp (5 g)", ""],
    ["Whole egg, boiled", "Protein", 155, 13, 1.1, 11, 50, "1 egg (50 g)", ""],
    ["Egg whites", "Protein", 52, 11, 0.7, 0.2, 33, "1 white (33 g)", ""],
    ["Soy chunks, dry", "Protein", 345, 52, 33, 0.5, 30, "30 g dry", "Weight is DRY. Soaked/cooked chunks are about 3x heavier with roughly a third of the calories per 100 g."],
    ["Soybeans, cooked", "Protein", 173, 17, 10, 9, 100, "100 g cooked", ""],
    ["Tofu, firm", "Protein", 144, 15.8, 2.8, 8.7, 100, "100 g", ""],
    ["Dal, cooked (with tadka)", "Indian meals", 110, 6, 15, 3, 150, "1 katori (150 g)", "Home-style toor/moong dal. Extra ghee or oil adds calories."],
    ["Chickpeas (chana), boiled", "Protein", 164, 8.9, 27, 2.6, 100, "100 g cooked", "Boiled, no oil. Chole curry has more fat."],
    ["Rajma, boiled", "Protein", 127, 8.7, 22.8, 0.5, 100, "100 g cooked", "Boiled, no oil. Rajma curry has more fat."],
    ["Peanuts, raw", "Nuts", 567, 25.8, 16.1, 49.2, 30, "1 handful (30 g)", ""],
    ["Roti (phulka, no ghee)", "Indian meals", 270, 9, 52, 2.5, 40, "1 roti (40 g)", ""],
    ["Chapati (with a little oil)", "Indian meals", 300, 8.5, 50, 7.5, 45, "1 chapati (45 g)", ""],
    ["Rice, white, cooked", "Grains", 130, 2.7, 28, 0.3, 150, "1 katori (150 g)", "Cooked weight."],
    ["Brown rice, cooked", "Grains", 123, 2.7, 26, 1.0, 150, "1 katori (150 g)", "Cooked weight."],
    ["Oats, dry", "Grains", 389, 16.9, 66, 6.9, 40, "1 serving (40 g)", "Dry weight, before cooking."],
    ["Bread, whole wheat", "Grains", 265, 9, 49, 3.2, 30, "1 slice (30 g)", ""],
    ["Poha, cooked", "Indian meals", 130, 2.5, 23, 3, 150, "1 plate (150 g)", "Made with a little oil and vegetables."],
    ["Upma, cooked", "Indian meals", 150, 3.5, 22, 5.5, 200, "1 bowl (200 g)", ""],
    ["Khichdi", "Indian meals", 120, 4.5, 19, 3, 250, "1 bowl (250 g)", "Rice and moong dal with a little ghee."],
    ["Thepla", "Indian meals", 300, 8, 42, 11, 40, "1 thepla (40 g)", "Cooked with oil. Varies by recipe."],
    ["Dhokla", "Indian meals", 150, 6, 24, 3.5, 60, "2 pieces (60 g)", ""],
    ["Idli", "Indian meals", 140, 4, 29, 0.5, 40, "1 idli (40 g)", ""],
    ["Dosa, plain", "Indian meals", 168, 3.9, 28, 4.5, 100, "1 dosa (100 g)", "Made with a little oil. Masala filling adds calories."],
    ["Vegetable pulao", "Indian meals", 140, 3, 23, 4, 200, "1 plate (200 g)", ""],
    ["Dal rice", "Indian meals", 125, 4, 22, 2, 300, "1 plate (300 g)", "Cooked dal mixed with rice."],
    ["Bajra rotla", "Indian meals", 270, 8, 50, 4, 60, "1 rotla (60 g)", ""],
    ["Pav bhaji", "Indian meals", 150, 4, 21, 5.5, 300, "1 plate (bhaji + 2 pav)", "Butter-heavy versions are higher."],
    ["Moong sprouts", "Protein", 30, 3, 6, 0.2, 100, "100 g", "Raw sprouts."],
    ["Banana", "Fruits", 89, 1.1, 23, 0.3, 118, "1 medium (118 g)", ""],
    ["Apple", "Fruits", 52, 0.3, 14, 0.2, 180, "1 medium (180 g)", ""],
    ["Orange", "Fruits", 47, 0.9, 12, 0.1, 130, "1 medium (130 g)", ""],
    ["Papaya", "Fruits", 43, 0.5, 11, 0.3, 150, "1 cup (150 g)", ""],
    ["Mango", "Fruits", 60, 0.8, 15, 0.4, 200, "1 medium (200 g)", ""],
    ["Almonds", "Nuts", 579, 21, 22, 50, 28, "1 handful (28 g)", ""],
    ["Cashews", "Nuts", 553, 18, 30, 44, 28, "1 handful (28 g)", ""],
    ["Walnuts", "Nuts", 654, 15, 14, 65, 28, "1 handful (28 g)", ""],
    ["Peanut butter", "Nuts", 588, 25, 20, 50, 16, "1 tbsp (16 g)", ""],
    ["Whey protein", "Supplements", 400, 80, 10, 5, 30, "1 scoop (30 g)", "Check your product label."],
    ["Chicken breast, cooked", "Non-veg", 165, 31, 0, 3.6, 100, "100 g cooked", ""]
]

_foods_cache = None


def _num(d, key, lo, hi):
    try:
        v = float(d.get(key))
    except (TypeError, ValueError):
        raise ValueError("%s must be a number" % key)
    if not (lo <= v <= hi):
        raise ValueError("%s must be between %s and %s" % (key, lo, hi))
    return v


def calc_targets(p):
    """Mifflin-St Jeor BMR -> TDEE -> goal-adjusted calories and macros."""
    age = _num(p, "age", 10, 100)
    height = _num(p, "height", 100, 250)
    weight = _num(p, "weight", 25, 300)
    goal, act, gender = p.get("goal"), p.get("activity"), p.get("gender", "other")
    if goal not in GOALS:
        raise ValueError("Unknown fitness goal")
    if act not in ACTIVITY_LEVELS:
        raise ValueError("Unknown activity level")

    sex_const = {"male": 5, "female": -161}.get(gender, -78)  # 'other' = midpoint
    bmr = 10 * weight + 6.25 * height - 5 * age + sex_const
    tdee = bmr * ACTIVITY_LEVELS[act][0]
    adjust = {"bulk": 250, "cut": -400, "maintain": 0}[goal]
    kcal = max(1200.0, tdee + adjust)
    protein = {"bulk": 1.8, "cut": 2.0, "maintain": 1.6}[goal] * weight
    fat = 0.8 * weight
    carbs = max(0.0, (kcal - protein * 4 - fat * 9) / 4)
    bmi = weight / ((height / 100) ** 2)
    cat = "Underweight" if bmi < 18.5 else "Healthy range" if bmi < 25 else "Overweight" if bmi < 30 else "Obese range"
    return {
        "bmi": round(bmi, 1), "bmiCategory": cat,
        "bmr": round(bmr), "tdee": round(tdee), "adjustment": adjust,
        "kcal": round(kcal), "protein": round(protein), "carbs": round(carbs), "fat": round(fat),
        "note": "Estimates only - not a medical measurement.",
    }


def calc_calories(p):
    """kcal = MET x 3.5 x weight(kg) / 200 x minutes."""
    act = p.get("activity")
    if act not in ACTIVITIES:
        raise ValueError("Unknown activity")
    level = p.get("level")
    if level not in ACTIVITIES[act]["levels"]:
        raise ValueError("Unknown intensity")
    minutes = _num(p, "minutes", 1, 1440)
    weight = _num(p, "weight", 25, 300)
    met = ACTIVITIES[act]["levels"][level]
    return {"met": met, "kcal": round(met * 3.5 * weight / 200 * minutes, 1), "estimate": True}


def load_foods():
    global _foods_cache
    if _foods_cache is None:
        keys = ["name", "cat", "kcal", "protein", "carbs", "fat", "serving_g", "serving_label", "note"]
        _foods_cache = [dict(zip(keys, r)) for r in FOOD_ROWS]
    return _foods_cache


PAGE = r"""<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0c0d0f">
<title>FITLOG - Fitness &amp; Nutrition Tracker</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400..800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/style.css">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
</head>
<body>
<div id="root"><p class="boot">Loading…</p></div>
<div id="toast" role="status" aria-live="polite"></div>
<div id="modal" class="modal hidden"></div>
<script>
'use strict';
/* ================= helpers ================= */
const KEY = 'pulse.v1', VER = 1;
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pad = n => String(n).padStart(2, '0');
const fmtD = d => d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
const today = () => fmtD(new Date());
const parseD = s => new Date(s + 'T00:00:00');
const addDays = (s, n) => { const d = parseD(s); d.setDate(d.getDate() + n); return fmtD(d); };
const nowTime = () => { const d = new Date(); return pad(d.getHours()) + ':' + pad(d.getMinutes()); };
const nice = d => parseD(d).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
const R = (n, p = 0) => { const m = 10 ** p; return Math.round((+n || 0) * m) / m; };
const N = v => { const n = parseFloat(v); return Number.isFinite(n) ? n : NaN; };
const sum = (a, k) => a.reduce((s, x) => s + (+x[k] || 0), 0);
const cap = s => s ? s[0].toUpperCase() + s.slice(1) : '';
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const byDate = (a, b) => (a.date + (a.time || '')).localeCompare(b.date + (b.time || ''));
const MEALS = ['Breakfast', 'Lunch', 'Evening Snacks', 'Dinner'];
const MUSCLES = {
  Chest: ['Bench Press', 'Incline Dumbbell Press', 'Chest Fly', 'Push-ups'],
  Back: ['Lat Pulldown', 'Seated Cable Row', 'Pull-ups', 'Dumbbell Row'],
  Shoulders: ['Shoulder Press', 'Lateral Raises', 'Front Raises', 'Rear Delt Fly'],
  Arms: ['Bicep Curls', 'Hammer Curls', 'Tricep Pushdowns', 'Overhead Tricep Extensions'],
  Legs: ['Squats', 'Leg Press', 'Leg Extensions', 'Leg Curls', 'Calf Raises'],
  Other: []
};
const ICONS = {
  dashboard: '<path d="M3 3h8v8H3zM13 3h8v5h-8zM13 11h8v10h-8zM3 14h8v7H3z"/>',
  workouts: '<path d="M6.5 6.5v11M17.5 6.5v11M3 9v6M21 9v6M6.5 12h11"/>',
  nutrition: '<path d="M7 3v7a2 2 0 0 0 4 0V3M9 12v9M17 3c-2 1.5-3 4-3 7h3v11"/>',
  weight: '<rect x="4" y="4" width="16" height="16" rx="4"/><path d="M8.5 9.5a3.5 3.5 0 0 1 7 0M12 9.5l2-2"/>',
  analytics: '<path d="M4 20V11M10 20V4M16 20v-7M22 20H2"/>',
  settings: '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>'
};
const ic = n => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n]}</svg>`;
const NAV = [['dashboard', 'Dashboard', 'Home'], ['workouts', 'Workouts', 'Train'], ['nutrition', 'Nutrition', 'Food'], ['weight', 'Weight & Goals', 'Weight'], ['analytics', 'Progress & Analytics', 'Stats'], ['settings', 'Settings', 'Settings']];

function toast(m, err) { const t = $('#toast'); t.textContent = m; t.className = 'show' + (err ? ' err' : ''); clearTimeout(toast.h); toast.h = setTimeout(() => t.className = '', 2800); }
function openModal(html) { const m = $('#modal'); m.innerHTML = `<div class="sheet">${html}</div>`; m.classList.remove('hidden'); m.onclick = e => { if (e.target === m) closeModal(); }; }
function closeModal() { $('#modal').classList.add('hidden'); }

/* ================= storage ================= */
let S, META, FOODS, V = { date: today() }, charts = [];
const blank = () => ({ version: VER, profile: null, targets: null, weights: [], workouts: [], foods: [], customFoods: [], favorites: [], meals: [], exercises: [], settings: { theme: 'dark' } });
function normalize(o) {
  if (!o || typeof o !== 'object' || Array.isArray(o)) throw new Error('Not a valid backup file');
  const b = blank();
  for (const k of Object.keys(b)) {
    if (Array.isArray(b[k])) b[k] = Array.isArray(o[k]) ? o[k].filter(x => x && typeof x === 'object' || typeof x === 'string') : [];
    else if (k === 'version') b[k] = VER;
    else if (k === 'settings') b[k] = { ...b.settings, ...(o.settings && typeof o.settings === 'object' ? o.settings : {}) };
    else b[k] = o[k] && typeof o[k] === 'object' ? o[k] : null;
  }
  if (b.profile && !b.targets) b.targets = null;
  return b;
}
function load() {
  let raw = null;
  try { raw = localStorage.getItem(KEY); return raw ? normalize(JSON.parse(raw)) : blank(); }
  catch (e) { try { if (raw) localStorage.setItem(KEY + '.corrupt', raw); } catch (_) { } return blank(); }
}
function save() { try { S.version = VER; localStorage.setItem(KEY, JSON.stringify(S)); return true; } catch (e) { toast('Could not save: browser storage is full or blocked', 1); return false; } }
const applyTheme = () => { document.documentElement.dataset.theme = S.settings.theme === 'light' ? 'light' : 'dark'; };

async function api(action, body) {
  const r = await fetch('/api/index?action=' + action, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : undefined);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || 'Server error');
  return j;
}

/* ================= data helpers ================= */
const weightOn = d => { const w = S.weights.filter(x => x.date <= d); return w.length ? w[w.length - 1].kg : (S.profile?.weight || 70); };
const latestWeight = () => S.weights.length ? S.weights[S.weights.length - 1].kg : S.profile?.weight;
const dayFood = d => S.foods.filter(f => f.date === d);
function upsertWeight(date, kg) {
  const i = S.weights.findIndex(w => w.date === date);
  if (i >= 0) S.weights[i].kg = kg; else S.weights.push({ id: uid(), date, kg });
  S.weights.sort((a, b) => a.date.localeCompare(b.date));
  S.profile.weight = S.weights[S.weights.length - 1].kg;
}
const allFoods = () => [...S.customFoods.map(c => ({ ...c, custom: true })), ...FOODS];
const foodByName = n => allFoods().find(f => f.name === n);
const calcFood = (f, g) => ({ kcal: R(f.kcal * g / 100, 1), protein: R(f.protein * g / 100, 1), carbs: R(f.carbs * g / 100, 1), fat: R(f.fat * g / 100, 1) });
const exMap = () => { const m = {}; for (const [g, l] of Object.entries(MUSCLES)) l.forEach(n => m[n] = g); S.exercises.forEach(e => m[e.name] = e.muscle); return m; };
const guessMeal = () => { const h = new Date().getHours(); return h < 11 ? 'Breakfast' : h < 16 ? 'Lunch' : h < 19 ? 'Evening Snacks' : 'Dinner'; };

/* ================= UI pieces ================= */
const ring = (pct, color, big, small, sz = 120) => { const r = 46, c = 2 * Math.PI * r, p = Math.max(0, Math.min(1, pct || 0)); return `<div class="ring" style="width:${sz}px;height:${sz}px"><svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="${r}" class="rt"/><circle cx="50" cy="50" r="${r}" class="rf" style="stroke:${color};stroke-dasharray:${c};stroke-dashoffset:${c * (1 - p)}"/></svg><div class="rc"><b>${big}</b><span>${small}</span></div></div>`; };
const bar = (l, v, t, u, c) => `<div class="mb"><div class="mbh"><span>${l}</span><span>${R(v)} / ${R(t)} ${u}</span></div><div class="track"><i style="width:${Math.min(100, t ? v / t * 100 : 0)}%;background:${c}"></i></div></div>`;
const head = (t, extra = '') => `<header class="head"><h1>${t}</h1>${extra}</header>`;
const dateBar = () => `<div class="datebar"><button class="ib" aria-label="Previous day" onclick="shiftDate(-1)">‹</button><input type="date" value="${V.date}" onchange="setDate(this.value)" aria-label="Date"><button class="ib" aria-label="Next day" onclick="shiftDate(1)">›</button>${V.date !== today() ? '<button class="btn ghost sm" onclick="setDate(today())">Today</button>' : ''}</div>`;
const empty = (t, s) => `<div class="empty"><b>${t}</b>${s}</div>`;
function setDate(v) { if (v) { V.date = v; render(); } }
function shiftDate(n) { V.date = addDays(V.date, n); render(); }

function chart(id, type, labels, sets, zero, scales) {
  const el = document.getElementById(id); if (!el) return;
  if (typeof Chart === 'undefined') { el.parentNode.innerHTML = '<p class="mut">The chart library could not load. Check your connection and reload.</p>'; return; }
  const css = getComputedStyle(document.documentElement);
  Chart.defaults.color = css.getPropertyValue('--mut').trim(); Chart.defaults.borderColor = css.getPropertyValue('--line').trim();
  charts.push(new Chart(el, { type, data: { labels, datasets: sets.map(s => ({ tension: .3, borderWidth: 2, pointRadius: labels.length > 40 ? 0 : 3, borderRadius: 6, spanGaps: true, ...s })) }, options: { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false }, plugins: { legend: { display: sets.length > 1, labels: { boxWidth: 10 } } }, scales: { x: { grid: { display: false } }, y: { beginAtZero: !!zero }, ...(scales || {}) } } }));
}
const col = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

/* ================= profile / setup ================= */
function profileFields(p = {}) {
  const opts = (o, cur) => Object.entries(o).map(([k, v]) => `<option value="${k}" ${cur === k ? 'selected' : ''}>${esc(v)}</option>`).join('');
  return `<label>Name (optional)<input name="name" maxlength="40" value="${esc(p.name || '')}"></label>
<div class="row2"><label>Age<input name="age" type="number" min="10" max="100" step="1" required value="${p.age ?? ''}"></label>
<label>Gender<select name="gender">${opts({ male: 'Male', female: 'Female', other: 'Other' }, p.gender || 'male')}</select></label></div>
<div class="row2"><label>Height (cm)<input name="height" type="number" min="100" max="250" step="0.1" required value="${p.height ?? ''}"></label>
<label>Current weight (kg)<input name="weight" type="number" min="25" max="300" step="0.1" required value="${p.weight ?? ''}"></label></div>
<div class="row2"><label>Target weight (kg)<input name="target" type="number" min="25" max="300" step="0.1" required value="${p.target ?? ''}"></label>
<label>Gym sessions / week<input name="sessions" type="number" min="0" max="14" step="1" required value="${p.sessions ?? ''}"></label></div>
<label>Fitness goal<select name="goal">${opts(META.goals, p.goal || 'maintain')}</select></label>
<label>Activity level<select name="activity">${opts(META.activityLevels, p.activity || 'moderate')}</select></label>`;
}
function readProfile(form) {
  const g = n => form.elements[n].value;
  const num = (n, lo, hi, label) => { const v = N(g(n)); if (!(v >= lo && v <= hi)) throw new Error(`${label} must be between ${lo} and ${hi}`); return v; };
  return { name: g('name').trim(), age: num('age', 10, 100, 'Age'), gender: g('gender'), height: num('height', 100, 250, 'Height'), weight: num('weight', 25, 300, 'Current weight'), target: num('target', 25, 300, 'Target weight'), goal: g('goal'), activity: g('activity'), sessions: num('sessions', 0, 14, 'Gym sessions') };
}
const setupHTML = () => `<div class="setup"><h1>Welcome to <span class="acc">FITLOG</span></h1><p class="mut" style="margin-bottom:1.2rem">Tell us a bit about you to set daily calorie and macro targets. Everything stays in this browser.</p>
<form class="card" onsubmit="submitSetup(event)">${profileFields()}<p class="note">Targets are estimates (Mifflin-St Jeor equation), not medical measurements. You can edit them anytime.</p><button class="btn block">Create my plan</button></form></div>`;
async function submitSetup(e) {
  e.preventDefault();
  try {
    const p = readProfile(e.target), t = await api('targets', p);
    S.profile = p; S.targets = { kcal: t.kcal, protein: t.protein, carbs: t.carbs, fat: t.fat };
    upsertWeight(today(), p.weight); save(); location.hash = 'dashboard'; render();
  } catch (err) { toast(err.message, 1); }
}
async function recommend(reason) {
  try {
    const t = await api('targets', S.profile), c = S.targets || {};
    if (t.kcal === c.kcal && t.protein === c.protein && t.carbs === c.carbs && t.fat === c.fat) return;
    window._rec = t;
    const row = (l, a, b, u) => `<tr><td>${l}</td><td>${a} ${u}</td><td><b>${b} ${u}</b></td></tr>`;
    openModal(`<h3>New target recommendation</h3><p class="mut small" style="margin:.3rem 0 .8rem">${esc(reason)} Your targets have not changed yet.</p>
<table><tr><th></th><th>Current</th><th>Recommended</th></tr>${row('Calories', c.kcal, t.kcal, 'kcal')}${row('Protein', c.protein, t.protein, 'g')}${row('Carbs', c.carbs, t.carbs, 'g')}${row('Fat', c.fat, t.fat, 'g')}</table>
<p class="note">Estimated BMR ${t.bmr} kcal, TDEE ${t.tdee} kcal. These are estimates.</p>
<div class="btns"><button class="btn ghost" onclick="closeModal()">Keep current</button><button class="btn" onclick="applyRec()">Apply recommendation</button></div>`);
  } catch (e) { toast(e.message, 1); }
}
function applyRec() { const t = window._rec; S.targets = { kcal: t.kcal, protein: t.protein, carbs: t.carbs, fat: t.fat }; save(); closeModal(); render(); toast('Targets updated'); }

/* ================= router ================= */
const PAGES = { dashboard: pgDashboard, workouts: pgWorkouts, nutrition: pgNutrition, weight: pgWeight, analytics: pgAnalytics, settings: pgSettings };
function render() {
  charts.forEach(c => c.destroy()); charts = [];
  const y = window.scrollY, root = $('#root');
  if (!S.profile) { root.innerHTML = setupHTML(); return; }
  if (!S.weights.length) upsertWeight(today(), S.profile.weight);
  const cur = PAGES[location.hash.slice(1)] ? location.hash.slice(1) : 'dashboard';
  root.innerHTML = `<aside class="side"><div class="logo">FITLOG<b>.</b></div>${NAV.map(([k, l]) => `<a href="#${k}" class="${k === cur ? 'on' : ''}">${ic(k)}${l}</a>`).join('')}</aside>
<main class="main" id="main"></main><nav class="bottom">${NAV.map(([k, , s]) => `<a href="#${k}" class="${k === cur ? 'on' : ''}">${ic(k)}${s}</a>`).join('')}</nav>`;
  PAGES[cur](); window.scrollTo(0, y);
}

/* ================= dashboard ================= */
function pgDashboard() {
  const d = V.date, f = dayFood(d), w = S.workouts.filter(x => x.date === d), T = S.targets;
  const eat = sum(f, 'kcal'), burn = sum(w, 'kcal'), of = t => sum(w.filter(x => x.type === t), 'kcal');
  const other = sum(w.filter(x => !['walking', 'running', 'strength'].includes(x.type)), 'kcal');
  const lw = latestWeight(), tw = S.profile.target, diff = R(lw - tw, 1);
  const exCount = w.reduce((a, x) => a + (x.type === 'strength' ? (x.exercises || []).length : 1), 0);
  const dist = t => R(sum(w.filter(x => x.type === t), 'distance'), 2);
  const remain = T.kcal - eat;
  $('#main').innerHTML = `${head(S.profile.name ? `Hi, ${esc(S.profile.name)}` : 'Dashboard', dateBar())}
${!f.length && !w.length ? `<div class="card">${empty('Nothing logged for ' + nice(d), 'Log a meal or a workout to see your day here.')}<div class="btns" style="justify-content:center"><a class="btn" href="#nutrition" style="text-decoration:none">Log food</a><a class="btn ghost" href="#workouts" style="text-decoration:none">Log workout</a></div></div>` : ''}
<div class="grid">
<section class="card"><h2>Calories consumed</h2><div class="ringwrap">${ring(eat / T.kcal, 'var(--acc)', R(eat), 'of ' + T.kcal + ' kcal')}<div><div class="big">${R(Math.abs(remain))}</div><div class="mut small">kcal ${remain >= 0 ? 'remaining' : 'over target'}</div></div></div></section>
<section class="card"><h2>Calories burned <span class="pill">estimate</span></h2><div class="big">${R(burn)} <span class="mut small">kcal</span></div>
<div style="margin-top:.7rem"><div class="kv"><span>Walking</span><span>${R(of('walking'))} kcal</span></div><div class="kv"><span>Running</span><span>${R(of('running'))} kcal</span></div><div class="kv"><span>Strength training</span><span>${R(of('strength'))} kcal</span></div><div class="kv"><span>Other activity</span><span>${R(other)} kcal</span></div></div></section>
<section class="card"><h2>Macronutrients</h2>${bar('Protein', sum(f, 'protein'), T.protein, 'g', 'var(--acc)')}${bar('Carbohydrates', sum(f, 'carbs'), T.carbs, 'g', 'var(--blue)')}${bar('Fat', sum(f, 'fat'), T.fat, 'g', 'var(--amber)')}</section>
<section class="card"><h2>Body weight</h2><div class="big">${R(lw, 1)} <span class="mut small">kg</span></div><div class="kv"><span>Target</span><span>${tw} kg</span></div><div class="kv"><span>Difference</span><span>${diff === 0 ? 'At target' : (diff > 0 ? '+' : '') + diff + ' kg'}</span></div></section>
<section class="card"><h2>Activity summary</h2><div class="kv"><span>Walking distance</span><span>${dist('walking')} km</span></div><div class="kv"><span>Running distance</span><span>${dist('running')} km</span></div><div class="kv"><span>Workout duration</span><span>${R(sum(w, 'duration'))} min</span></div><div class="kv"><span>Exercises completed</span><span>${exCount}</span></div></section>
<section class="card"><h2>Daily calorie balance</h2><div class="kv"><span>Net intake (eaten - burned)</span><span><b>${R(eat - burn)} kcal</b></span></div><div class="kv"><span>Remaining vs food target</span><span><b>${R(remain)} kcal</b></span></div>
<p class="note">Your food target already accounts for your usual activity, so exercise calories are not added back. This avoids double-counting.</p></section>
</div><p class="mut small" style="margin-top:1rem">Calorie targets and exercise burn are estimates, not medical measurements.</p>`;
}

/* ================= workouts ================= */
let WF = null;
const newRow = () => ({ name: '', muscle: 'Chest', sets: 3, reps: 10, kg: 0 });
const wfNew = () => ({ id: null, type: 'walking', sub: 'swimming', custom: '', date: V.date, time: nowTime(), duration: '', distance: '', speed: '', pace: '', level: 'moderate', auto: true, notes: '', rest: '', rows: [newRow()] });
const metKey = f => f.type === 'other' ? f.sub : f.type;
const AUTO = { walking: [4, 5.5], running: [9, 11], cycling: [16, 22] };
function effDist(f) {
  const d = N(f.distance); if (d > 0) return d;
  const m = N(f.duration); if (!(m > 0)) return 0;
  if (f.type === 'walking' && N(f.speed) > 0) return N(f.speed) * m / 60;
  if (f.type === 'running' && N(f.pace) > 0) return m / N(f.pace);
  return 0;
}
function wfHTML() {
  const f = WF, lv = META.activities[metKey(f)].levels, dist = ['walking', 'running', 'cycling'].includes(f.type);
  const types = [['walking', 'Walking'], ['running', 'Running'], ['cycling', 'Cycling'], ['strength', 'Strength'], ['other', 'Other']];
  const subs = ['swimming', 'football', 'basketball', 'badminton', 'jumprope', 'custom'];
  let h = `<div class="seg">${types.map(([t, l]) => `<button type="button" class="${f.type === t ? 'on' : ''}" onclick="wfType('${t}')">${l}</button>`).join('')}</div>
<div class="row2"><label>Date<input type="date" data-k="date" required value="${f.date}"></label><label>Time<input type="time" data-k="time" required value="${f.time}"></label></div>`;
  if (f.type === 'other') h += `<div class="row2"><label>Activity<select data-k="sub" onchange="wfSub()">${subs.map(s => `<option value="${s}" ${f.sub === s ? 'selected' : ''}>${META.activities[s].label}</option>`).join('')}</select></label>${f.sub === 'custom' ? `<label>Name<input data-k="custom" maxlength="40" required value="${esc(f.custom)}"></label>` : '<span></span>'}</div>`;
  h += `<div class="row2"><label>Duration (min)<input type="number" data-k="duration" min="1" max="1440" step="1" required value="${f.duration}"></label>
<label>Intensity<select data-k="level">${Object.entries(lv).map(([k, m]) => `<option value="${k}" ${f.level === k ? 'selected' : ''}>${cap(k)} (${m} MET)</option>`).join('')}</select></label></div>`;
  if (dist) h += `<div class="row2"><label>Distance (km)<input type="number" data-k="distance" min="0" max="500" step="0.01" value="${f.distance}"></label>${f.type === 'walking' ? `<label>Avg speed (km/h, optional)<input type="number" data-k="speed" min="0" max="12" step="0.1" value="${f.speed}"></label>` : f.type === 'running' ? `<label>Pace (min/km, optional)<input type="number" data-k="pace" min="0" max="30" step="0.1" value="${f.pace}"></label>` : '<span></span>'}</div><p class="small mut" id="whint"></p>`;
  if (f.type === 'strength') {
    const known = exMap();
    h += `<datalist id="exlist">${Object.keys(known).map(n => `<option value="${esc(n)}">`).join('')}</datalist><div class="exlab"><span>Muscle</span><span>Sets</span><span>Reps</span><span>Kg</span><span></span></div>${f.rows.map((r, i) => `<div class="exrow"><input class="nm" list="exlist" placeholder="Exercise name" data-r="${i}" data-k="name" required value="${esc(r.name)}"><select data-r="${i}" data-k="muscle">${Object.keys(MUSCLES).map(m => `<option ${r.muscle === m ? 'selected' : ''}>${m}</option>`).join('')}</select><input type="number" min="1" max="50" data-r="${i}" data-k="sets" value="${r.sets}"><input type="number" min="1" max="200" data-r="${i}" data-k="reps" value="${r.reps}"><input type="number" min="0" max="1000" step="0.5" data-r="${i}" data-k="kg" value="${r.kg}"><button type="button" class="ib" aria-label="Remove exercise" onclick="wfDel(${i})">✕</button></div>`).join('')}
<button type="button" class="btn ghost sm" onclick="wfAddRow()">+ Add exercise</button><label style="margin-top:.8rem">Rest between sets (sec, optional)<input type="number" data-k="rest" min="0" max="1200" value="${f.rest}"></label><p class="small" id="wtot"></p>`;
  }
  h += `<label>Notes<textarea rows="2" data-k="notes" maxlength="300">${esc(f.notes)}</textarea></label><p class="small mut" id="wprev"></p>
<div class="btns"><button class="btn">${f.id ? 'Update workout' : 'Save workout'}</button>${f.id ? '<button type="button" class="btn ghost" onclick="wfCancel()">Cancel edit</button>' : ''}</div>`;
  return h;
}
function wfType(t) { WF.type = t; WF.level = 'moderate'; WF.auto = true; $('#wform').innerHTML = wfHTML(); wfRefresh(); }
function wfSub() { WF.sub = $('#wform [data-k=sub]').value; WF.custom = WF.custom || ''; WF.level = 'moderate'; $('#wform').innerHTML = wfHTML(); wfRefresh(); }
function wfAddRow() { WF.rows.push(newRow()); $('#wform').innerHTML = wfHTML(); wfRefresh(); }
function wfDel(i) { WF.rows.splice(i, 1); if (!WF.rows.length) WF.rows.push(newRow()); $('#wform').innerHTML = wfHTML(); wfRefresh(); }
function wfCancel() { WF = wfNew(); render(); }
function wfIn(e) {
  const t = e.target, k = t.dataset.k; if (!k) return;
  if (t.dataset.r !== undefined) {
    const r = WF.rows[+t.dataset.r]; r[k] = t.value;
    if (k === 'name') { const m = exMap()[t.value]; if (m) { r.muscle = m; t.nextElementSibling.value = m; } }
  } else { WF[k] = t.value; if (k === 'level') WF.auto = false; if (k === 'date') V.date = t.value; }
  wfRefresh();
}
function wfRefresh() {
  const f = WF; if (!f || !$('#wform')) return;
  const dur = N(f.duration), dist = effDist(f), hint = $('#whint');
  if (AUTO[f.type] && dur > 0 && dist > 0) {
    const sp = dist / (dur / 60);
    if (hint) hint.textContent = `Average speed ${R(sp, 1)} km/h · pace ${R(dur / dist, 1)} min/km`;
    if (f.auto) { const keys = Object.keys(META.activities[metKey(f)].levels), t = AUTO[f.type]; f.level = keys[sp < t[0] ? 0 : sp < t[1] ? 1 : 2]; const sel = $('#wform [data-k=level]'); if (sel) sel.value = f.level; }
  } else if (hint) hint.textContent = '';
  if (f.type === 'strength') {
    let s = 0, rp = 0, vol = 0; f.rows.forEach(r => { const a = N(r.sets) || 0, b = N(r.reps) || 0, c = N(r.kg) || 0; s += a; rp += a * b; vol += a * b * c; });
    $('#wtot').innerHTML = `Total sets <b>${s}</b> · reps <b>${rp}</b> · volume <b>${R(vol)} kg</b>`;
  }
  wfPreview();
}
const wfPreview = debounce(async () => {
  const f = WF, el = $('#wprev'); if (!el) return;
  const dur = N(f.duration); if (!(dur >= 1 && dur <= 1440)) { el.textContent = ''; return; }
  try { const c = await api('calories', { activity: metKey(f), level: f.level, minutes: dur, weight: weightOn(f.date || today()) }); if ($('#wprev')) $('#wprev').textContent = `Estimated burn: about ${R(c.kcal)} kcal (MET ${c.met}, ${R(weightOn(f.date), 1)} kg)`; } catch (e) { el.textContent = ''; }
}, 250);
async function wfSave(e) {
  e.preventDefault(); const f = WF;
  try {
    const dur = N(f.duration); if (!(dur >= 1 && dur <= 1440)) throw new Error('Enter a duration between 1 and 1440 minutes');
    if (!f.date) throw new Error('Choose a date');
    const rec = { id: f.id || uid(), date: f.date, time: f.time || nowTime(), type: f.type, duration: dur, notes: f.notes.trim(), level: f.level };
    if (f.type === 'strength') {
      const known = exMap(); const rows = [];
      for (const r of f.rows) {
        const name = r.name.trim(), sets = N(r.sets), reps = N(r.reps), kg = N(r.kg) || 0;
        if (!name) continue;
        if (!(sets >= 1 && Number.isInteger(sets)) || !(reps >= 1 && Number.isInteger(reps)) || kg < 0) throw new Error(`Check sets, reps and weight for "${name}"`);
        rows.push({ name, muscle: r.muscle, sets, reps, kg });
        if (!known[name]) { S.exercises.push({ name, muscle: r.muscle }); known[name] = r.muscle; }
      }
      if (!rows.length) throw new Error('Add at least one exercise');
      rec.name = 'Strength training'; rec.exercises = rows; rec.sets = sum(rows, 'sets'); rec.reps = rows.reduce((a, r) => a + r.sets * r.reps, 0); rec.volume = R(rows.reduce((a, r) => a + r.sets * r.reps * r.kg, 0), 1); rec.rest = N(f.rest) || 0;
    } else {
      rec.distance = R(effDist(f), 2);
      if (f.type === 'other') { rec.sub = f.sub; rec.name = f.sub === 'custom' ? f.custom.trim() : META.activities[f.sub].label; if (!rec.name) throw new Error('Enter an activity name'); }
      else rec.name = META.activities[f.type].label;
    }
    const c = await api('calories', { activity: metKey(f), level: f.level, minutes: dur, weight: weightOn(f.date) });
    rec.met = c.met; rec.kcal = c.kcal;
    const i = S.workouts.findIndex(x => x.id === rec.id); if (i >= 0) S.workouts[i] = rec; else S.workouts.push(rec);
    S.workouts.sort(byDate); save(); V.date = rec.date; WF = wfNew(); toast(i >= 0 ? 'Workout updated' : 'Workout saved'); render();
  } catch (err) { toast(err.message, 1); }
}
function wfEdit(id) {
  const w = S.workouts.find(x => x.id === id); if (!w) return;
  WF = { ...wfNew(), id: w.id, type: w.type, sub: w.sub || 'swimming', custom: w.sub === 'custom' ? w.name : '', date: w.date, time: w.time, duration: w.duration, distance: w.distance || '', level: w.level || 'moderate', auto: false, notes: w.notes || '', rest: w.rest || '', rows: w.exercises ? w.exercises.map(r => ({ ...r })) : [newRow()] };
  render(); window.scrollTo({ top: 0, behavior: 'smooth' });
}
function wfRemove(id) { if (!confirm('Delete this workout?')) return; S.workouts = S.workouts.filter(x => x.id !== id); if (WF.id === id) WF = wfNew(); save(); render(); toast('Workout deleted'); }
const workoutItem = w => `<div class="li"><div><div class="t">${esc(w.name)}</div><div class="s">${nice(w.date)} · ${esc(w.time)} · ${R(w.duration)} min${w.distance ? ' · ' + w.distance + ' km' : ''}${w.type === 'strength' ? ` · ${w.sets} sets · ${R(w.volume)} kg volume` : ''}</div>
${w.exercises ? `<div class="s">${w.exercises.map(r => `${esc(r.name)} ${r.sets}×${r.reps}${r.kg ? ' @ ' + r.kg + 'kg' : ''}`).join(', ')}</div>` : ''}${w.notes ? `<div class="s">“${esc(w.notes)}”</div>` : ''}</div>
<div class="r"><span class="pill">≈ ${R(w.kcal)} kcal</span><button class="ib" aria-label="Edit" onclick="wfEdit('${w.id}')">✎</button><button class="ib" aria-label="Delete" onclick="wfRemove('${w.id}')">🗑</button></div></div>`;
function pgWorkouts() {
  if (!WF) WF = wfNew();
  const day = S.workouts.filter(x => x.date === V.date), recent = [...S.workouts].sort((a, b) => byDate(b, a)).filter(x => x.date !== V.date).slice(0, 15);
  $('#main').innerHTML = `${head('Workouts', dateBar())}<div class="grid2"><section class="card"><h2>${WF.id ? 'Edit workout' : 'Log a workout'}</h2><form id="wform" oninput="wfIn(event)" onchange="wfIn(event)" onsubmit="wfSave(event)">${wfHTML()}</form><p class="note">Calories are MET-based estimates: MET × 3.5 × weight (kg) ÷ 200 × minutes.</p></section>
<div><section class="card"><h2>${nice(V.date)}</h2>${day.length ? day.map(workoutItem).join('') + `<p class="small mut" style="margin-top:.6rem">Total ≈ ${R(sum(day, 'kcal'))} kcal (estimate)</p>` : empty('No workouts on this day', 'Use the form to add one.')}</section>
${recent.length ? `<section class="card"><h2>Recent workouts</h2>${recent.map(workoutItem).join('')}</section>` : ''}</div></div>`;
  wfRefresh();
}

/* ================= nutrition ================= */
let NT = { tab: 'search', q: '', res: [], sel: null, qty: 100, unit: 'g', meal: guessMeal() };
function mealCard(m, items) {
  return `<section class="card"><div class="ch"><h2>${m}</h2><span class="small mut">${R(sum(items, 'kcal'))} kcal${items.length ? ` <button class="btn ghost sm" onclick="saveMeal('${m}')">Save as meal</button>` : ''}</span></div>
${items.length ? items.map(x => `<div class="li"><div><div class="t">${esc(x.name)}</div><div class="s">${R(x.kcal)} kcal · P ${R(x.protein, 1)} · C ${R(x.carbs, 1)} · F ${R(x.fat, 1)}</div></div><div class="r"><input class="q" type="number" min="1" max="5000" step="1" value="${R(x.grams, 1)}" aria-label="Grams" onchange="editGrams('${x.id}',this.value)"><span class="small mut">g</span><button class="ib" aria-label="Delete" onclick="delFood('${x.id}')">🗑</button></div></div>`).join('') : '<p class="small mut">Nothing logged yet.</p>'}</section>`;
}
function pgNutrition() {
  const f = dayFood(V.date), T = S.targets;
  $('#main').innerHTML = `${head('Nutrition', dateBar())}<div class="grid2"><div>
<section class="card"><h2>${nice(V.date)}</h2>${bar('Calories', sum(f, 'kcal'), T.kcal, 'kcal', 'var(--acc)')}${bar('Protein', sum(f, 'protein'), T.protein, 'g', 'var(--acc)')}${bar('Carbs', sum(f, 'carbs'), T.carbs, 'g', 'var(--blue)')}${bar('Fat', sum(f, 'fat'), T.fat, 'g', 'var(--amber)')}</section>
${MEALS.map(m => mealCard(m, f.filter(x => x.meal === m))).join('')}</div>
<section class="card sticky"><div class="seg">${[['search', 'Search'], ['favs', 'Favourites'], ['meals', 'My meals'], ['custom', 'Custom food']].map(([k, l]) => `<button class="${NT.tab === k ? 'on' : ''}" onclick="NT.tab='${k}';renderNT();">${l}</button>`).join('')}</div><div id="ntab"></div></section></div>`;
  renderNT();
}
function renderNT() {
  const el = $('#ntab'); if (!el) return;
  document.querySelectorAll('.seg button').forEach(b => { if (b.parentNode.parentNode.classList.contains('sticky')) b.classList.toggle('on', b.textContent === { search: 'Search', favs: 'Favourites', meals: 'My meals', custom: 'Custom food' }[NT.tab]); });
  const mealSel = `<select id="smeal" onchange="NT.meal=this.value">${MEALS.map(m => `<option ${NT.meal === m ? 'selected' : ''}>${m}</option>`).join('')}</select>`;
  if (NT.tab === 'search' || NT.tab === 'favs') {
    el.innerHTML = `${NT.tab === 'search' ? `<input id="q" type="search" placeholder="Search foods, e.g. paneer, dal, roti" value="${esc(NT.q)}" oninput="NT.q=this.value;renderRes()" autocomplete="off">` : ''}<div class="res" id="res"></div><div id="addbox"></div>`;
    renderRes(); renderAdd();
  } else if (NT.tab === 'meals') {
    el.innerHTML = `<label>Add to meal${mealSel}</label>${S.meals.length ? S.meals.map(m => `<div class="li"><div><div class="t">${esc(m.name)}</div><div class="s">${m.items.length} items · ${R(sum(m.items, 'kcal'))} kcal · P ${R(sum(m.items, 'protein'))}g</div></div><div class="r"><button class="btn sm" onclick="addSavedMeal('${m.id}')">Add</button><button class="ib" aria-label="Delete meal" onclick="delSavedMeal('${m.id}')">🗑</button></div></div>`).join('') : empty('No saved meals yet', 'Log foods, then press “Save as meal” on any meal.')}`;
  } else {
    el.innerHTML = `<form onsubmit="addCustomFood(event)"><label>Food name<input name="name" required maxlength="60"></label><p class="small mut" style="margin-bottom:.5rem">Nutrition per 100 g</p><div class="row2"><label>Calories<input name="kcal" type="number" min="0" max="900" step="0.1" required></label><label>Protein (g)<input name="protein" type="number" min="0" max="100" step="0.1" required></label></div><div class="row2"><label>Carbs (g)<input name="carbs" type="number" min="0" max="100" step="0.1" required></label><label>Fat (g)<input name="fat" type="number" min="0" max="100" step="0.1" required></label></div><label>Typical serving in grams (optional)<input name="serving" type="number" min="1" max="2000"></label><button class="btn block">Save custom food</button></form>
${S.customFoods.length ? `<h3 style="margin:1rem 0 .3rem">Your foods</h3>${S.customFoods.map(c => `<div class="li"><div><div class="t">${esc(c.name)}</div><div class="s">${c.kcal} kcal/100 g</div></div><button class="ib" aria-label="Delete" onclick="delCustom('${c.id}')">🗑</button></div>`).join('')}` : ''}`;
  }
}
function renderRes() {
  const el = $('#res'); if (!el) return;
  const terms = NT.q.toLowerCase().split(/\s+/).filter(Boolean);
  let list = allFoods().filter(f => terms.every(t => (f.name + ' ' + f.cat).toLowerCase().includes(t)));
  if (NT.tab === 'favs') list = list.filter(f => S.favorites.includes(f.name));
  list.sort((a, b) => S.favorites.includes(b.name) - S.favorites.includes(a.name) || (b.custom ? 1 : 0) - (a.custom ? 1 : 0));
  NT.res = list;
  el.innerHTML = list.length ? list.map((f, i) => `<div class="li"><div style="cursor:pointer;flex:1" onclick="pickFood(${i})"><div class="t">${esc(f.name)}</div><div class="s">${f.kcal} kcal · P ${f.protein} · C ${f.carbs} · F ${f.fat} per 100 g</div></div><button class="ib ${S.favorites.includes(f.name) ? 'on' : ''}" aria-label="Favourite" onclick="toggleFav(${i})">${S.favorites.includes(f.name) ? '★' : '☆'}</button></div>`).join('') : empty(NT.tab === 'favs' ? 'No favourites yet' : 'No matches', NT.tab === 'favs' ? 'Tap the star on any food to save it here.' : 'Try another name or add a custom food.');
}
function toggleFav(i) { const n = NT.res[i].name, j = S.favorites.indexOf(n); if (j >= 0) S.favorites.splice(j, 1); else S.favorites.push(n); save(); renderRes(); }
function pickFood(i) { NT.sel = NT.res[i]; NT.unit = 'g'; NT.qty = 100; renderAdd(); }
function renderAdd() {
  const el = $('#addbox'); if (!el) return;
  const f = NT.sel; if (!f) { el.innerHTML = '<p class="small mut">Select a food to set the quantity and add it to a meal.</p>'; return; }
  el.innerHTML = `<div class="card" style="margin:.6rem 0 0;background:var(--card2)"><h3>${esc(f.name)}</h3>${f.note ? `<p class="small mut">${esc(f.note)}</p>` : ''}
<div class="row2" style="margin-top:.6rem"><label>Quantity<input type="number" id="fq" min="0.1" max="5000" step="0.1" value="${NT.qty}" oninput="NT.qty=this.value;renderPrev()"></label><label>Unit<select onchange="NT.unit=this.value;NT.qty=this.value==='g'?100:1;renderAdd()"><option value="g" ${NT.unit === 'g' ? 'selected' : ''}>grams</option>${f.serving_g ? `<option value="s" ${NT.unit === 's' ? 'selected' : ''}>servings (${esc(f.serving_label)})</option>` : ''}</select></label></div>
<label>Meal<select onchange="NT.meal=this.value">${MEALS.map(m => `<option ${NT.meal === m ? 'selected' : ''}>${m}</option>`).join('')}</select></label><div id="fprev" class="note"></div><button class="btn block" onclick="addFood()">Add to ${esc(V.date === today() ? 'today' : nice(V.date))}</button></div>`;
  renderPrev();
}
const gramsNow = () => NT.unit === 's' ? N(NT.qty) * NT.sel.serving_g : N(NT.qty);
function renderPrev() { const g = gramsNow(), el = $('#fprev'); if (!el) return; if (!(g > 0)) { el.textContent = 'Enter a quantity'; return; } const c = calcFood(NT.sel, g); el.innerHTML = `<b>${R(g, 1)} g</b> → ${c.kcal} kcal · Protein ${c.protein} g · Carbs ${c.carbs} g · Fat ${c.fat} g`; }
function addFood() {
  const g = gramsNow(); if (!(g > 0 && g <= 5000)) return toast('Enter a quantity between 0 and 5000 g', 1);
  const f = NT.sel, c = calcFood(f, g);
  S.foods.push({ id: uid(), date: V.date, meal: NT.meal, name: f.name, grams: R(g, 1), ...c, per: [f.kcal, f.protein, f.carbs, f.fat] });
  save(); toast(`Added ${f.name}`); NT.sel = null; render();
}
function editGrams(id, v) {
  const g = N(v), x = S.foods.find(f => f.id === id); if (!x) return;
  if (!(g > 0 && g <= 5000)) { toast('Enter 1-5000 g', 1); return render(); }
  x.grams = g; x.kcal = R(x.per[0] * g / 100, 1); x.protein = R(x.per[1] * g / 100, 1); x.carbs = R(x.per[2] * g / 100, 1); x.fat = R(x.per[3] * g / 100, 1); save(); render();
}
function delFood(id) { S.foods = S.foods.filter(f => f.id !== id); save(); render(); }
function saveMeal(m) {
  const name = (prompt('Name this meal (e.g. Post-workout breakfast)') || '').trim(); if (!name) return;
  S.meals.push({ id: uid(), name: name.slice(0, 50), items: dayFood(V.date).filter(x => x.meal === m).map(({ name, grams, kcal, protein, carbs, fat, per }) => ({ name, grams, kcal, protein, carbs, fat, per })) });
  save(); toast('Meal saved'); NT.tab = 'meals'; render();
}
function addSavedMeal(id) { const m = S.meals.find(x => x.id === id); if (!m) return; m.items.forEach(i => S.foods.push({ ...i, id: uid(), date: V.date, meal: NT.meal })); save(); toast(`Added ${m.name}`); render(); }
function delSavedMeal(id) { if (!confirm('Delete this saved meal?')) return; S.meals = S.meals.filter(m => m.id !== id); save(); renderNT(); }
function addCustomFood(e) {
  e.preventDefault(); const g = n => e.target.elements[n].value;
  const c = { id: uid(), name: g('name').trim(), cat: 'Custom', kcal: N(g('kcal')), protein: N(g('protein')), carbs: N(g('carbs')), fat: N(g('fat')), serving_g: N(g('serving')) || 0, serving_label: (N(g('serving')) || 0) + ' g serving', note: 'Custom food' };
  if (!c.name) return toast('Enter a name', 1);
  if ([c.kcal, c.protein, c.carbs, c.fat].some(v => !(v >= 0))) return toast('Enter valid numbers', 1);
  if (c.protein + c.carbs + c.fat > 100) return toast('Protein + carbs + fat cannot exceed 100 g per 100 g', 1);
  S.customFoods.push(c); save(); toast('Custom food saved'); NT.tab = 'search'; NT.q = c.name; render();
}
function delCustom(id) { if (!confirm('Delete this custom food? Logged entries stay.')) return; S.customFoods = S.customFoods.filter(c => c.id !== id); save(); renderNT(); }

/* ================= weight & goals ================= */
function weeklyAvgs() {
  const m = {}; S.weights.forEach(w => { const k = addDays(w.date, -((parseD(w.date).getDay() + 6) % 7)); (m[k] = m[k] || []).push(w.kg); });
  return Object.entries(m).sort().map(([k, a]) => ({ week: k, avg: a.reduce((x, y) => x + y, 0) / a.length, n: a.length }));
}
function pgWeight() {
  const P = S.profile, ws = S.weights, lw = latestWeight(), first = ws[0], wk = weeklyAvgs().reverse();
  const last7 = ws.filter(w => w.date > addDays(today(), -7)), avg7 = last7.length ? last7.reduce((a, w) => a + w.kg, 0) / last7.length : null;
  $('#main').innerHTML = `${head('Weight & Goals')}<div class="stats"><div class="stat"><b>${R(lw, 1)} kg</b><span>Latest</span></div><div class="stat"><b>${P.target} kg</b><span>Target</span></div><div class="stat"><b>${R(lw - first.kg, 1) > 0 ? '+' : ''}${R(lw - first.kg, 1)} kg</b><span>Change since first entry</span></div><div class="stat"><b>${avg7 ? R(avg7, 1) + ' kg' : '–'}</b><span>7-day average</span></div></div>
<div class="grid2"><div><section class="card"><h2>Weight over time</h2>${ws.length > 1 ? '<div class="chart"><canvas id="cw"></canvas></div>' : empty('Add more weigh-ins', 'A chart appears once you have two or more entries.')}</section>
<section class="card"><h2>History</h2>${[...ws].reverse().map(w => `<div class="li"><div><div class="t">${nice(w.date)}</div></div><div class="r"><input class="q" type="number" min="25" max="300" step="0.1" value="${w.kg}" aria-label="kg" onchange="editWeight('${w.id}',this.value)"><span class="small mut">kg</span><button class="ib" aria-label="Delete" onclick="delWeight('${w.id}')">🗑</button></div></div>`).join('')}</section></div>
<div><section class="card"><h2>Add weight</h2><form onsubmit="addWeight(event)"><div class="row2"><label>Date<input type="date" name="date" required value="${today()}"></label><label>Weight (kg)<input type="number" name="kg" min="25" max="300" step="0.1" required></label></div><button class="btn block">Save weight</button></form></section>
<section class="card"><h2>Goal</h2><form onsubmit="saveGoal(event)"><label>Fitness goal<select name="goal">${Object.entries(META.goals).map(([k, v]) => `<option value="${k}" ${P.goal === k ? 'selected' : ''}>${v}</option>`).join('')}</select></label><label>Target weight (kg)<input type="number" name="target" min="25" max="300" step="0.1" required value="${P.target}"></label><button class="btn block">Update goal</button></form><p class="note">Changing your goal or weight shows a new calorie recommendation first. Your targets only change if you accept it.</p></section>
<section class="card"><h2>Weekly averages</h2>${wk.length ? `<table><tr><th>Week of</th><th>Average</th><th>Entries</th></tr>${wk.slice(0, 8).map(w => `<tr><td>${nice(w.week)}</td><td>${R(w.avg, 1)} kg</td><td>${w.n}</td></tr>`).join('')}</table>` : empty('No data', '')}</section></div></div>`;
  if (ws.length > 1) chart('cw', 'line', ws.map(w => w.date.slice(5)), [{ label: 'Weight (kg)', data: ws.map(w => w.kg), borderColor: col('--acc'), backgroundColor: col('--acc') }, { label: 'Target', data: ws.map(() => P.target), borderColor: col('--mut'), borderDash: [6, 6], pointRadius: 0 }]);
}
function addWeight(e) {
  e.preventDefault(); const d = e.target.elements.date.value, kg = N(e.target.elements.kg.value);
  if (!d || !(kg >= 25 && kg <= 300)) return toast('Enter a weight between 25 and 300 kg', 1);
  upsertWeight(d, kg); save(); render(); toast('Weight saved'); recommend('Your weight changed.');
}
function editWeight(id, v) { const w = S.weights.find(x => x.id === id), kg = N(v); if (!w) return; if (!(kg >= 25 && kg <= 300)) { toast('Enter 25-300 kg', 1); return render(); } upsertWeight(w.date, kg); save(); render(); recommend('Your weight changed.'); }
function delWeight(id) { if (S.weights.length <= 1) return toast('Keep at least one weight entry', 1); if (!confirm('Delete this entry?')) return; S.weights = S.weights.filter(w => w.id !== id); S.profile.weight = S.weights[S.weights.length - 1].kg; save(); render(); }
function saveGoal(e) { e.preventDefault(); const t = N(e.target.elements.target.value); if (!(t >= 25 && t <= 300)) return toast('Enter a valid target weight', 1); S.profile.goal = e.target.elements.goal.value; S.profile.target = t; save(); render(); toast('Goal updated'); recommend('Your goal changed.'); }

/* ================= analytics ================= */
let AR = 30, AX = '';
function pgAnalytics() {
  const today_ = today(); let dates = [];
  if (AR > 0) for (let i = AR - 1; i >= 0; i--) dates.push(addDays(today_, -i));
  else { const all = [...S.weights, ...S.workouts, ...S.foods].map(x => x.date).sort(); let d = all[0] || today_; while (d <= today_ && dates.length < 800) { dates.push(d); d = addDays(d, 1); } }
  const set = new Set(dates), inR = x => set.has(x.date), T = S.targets;
  const day = Object.fromEntries(dates.map(d => [d, { k: 0, p: 0, c: 0, f: 0, n: 0, burn: 0 }]));
  S.foods.filter(inR).forEach(x => { const o = day[x.date]; o.k += x.kcal; o.p += x.protein; o.c += x.carbs; o.f += x.fat; o.n++; });
  const wk = S.workouts.filter(inR); wk.forEach(x => day[x.date].burn += x.kcal);
  const logged = dates.filter(d => day[d].n), avg = k => logged.length ? logged.reduce((a, d) => a + day[d][k], 0) / logged.length : 0;
  const ws = S.weights.filter(inR), lastW = S.weights[S.weights.length - 1];
  const prior = [...S.weights].reverse().find(w => w.date <= addDays(lastW.date, -30)) || S.weights[0];
  const l = dates.map(d => d.slice(5)), series = k => dates.map(d => day[d].n ? R(day[d][k]) : null);
  const strength = wk.filter(x => x.type === 'strength'), sess = {};
  S.workouts.filter(x => x.type === 'strength').forEach(w => (w.exercises || []).forEach(r => { (sess[r.name] = sess[r.name] || []).push({ date: w.date, kg: r.kg, reps: r.reps, vol: r.sets * r.reps * r.kg }); }));
  const names = Object.keys(sess).sort((a, b) => sess[b].length - sess[a].length); if (!sess[AX]) AX = names[0] || '';
  const pr = names.map(n => { const a = sess[n], m = a.reduce((x, y) => y.kg > x.kg ? y : x, a[0]); return { n, kg: m.kg, reps: m.reps, date: m.date, vol: Math.max(...a.map(x => x.vol)) }; });
  const exh = AX ? sess[AX].filter(x => set.has(x.date)).sort((a, b) => a.date.localeCompare(b.date)) : [];
  const sd = d => `<div class="stat"><b>${d[0]}</b><span>${d[1]}</span></div>`;
  $('#main').innerHTML = `${head('Progress & Analytics', `<div class="seg" style="margin:0">${[[7, '7 days'], [30, '30 days'], [90, '90 days'], [0, 'All time']].map(([v, t]) => `<button class="${AR === v ? 'on' : ''}" onclick="AR=${v};render()">${t}</button>`).join('')}</div>`)}
<h2 style="margin-bottom:.6rem">Weight</h2><div class="stats">${sd([R(lastW.kg, 1) + ' kg', 'Latest'])}${sd([(R(lastW.kg - prior.kg, 1) > 0 ? '+' : '') + R(lastW.kg - prior.kg, 1) + ' kg', 'Change over ~30 days'])}${sd([ws.length ? R(ws.reduce((a, w) => a + w.kg, 0) / ws.length, 1) + ' kg' : '–', 'Average in range'])}</div>
<section class="card">${ws.length > 1 ? '<div class="chart"><canvas id="a1"></canvas></div>' : empty('Not enough weight data in this range', 'Add weigh-ins on the Weight page.')}</section>
<h2 style="margin-bottom:.6rem">Nutrition</h2><div class="stats">${sd([R(avg('k')) + ' kcal', 'Average daily calories'])}${sd([R(avg('p')) + ' g', 'Average protein'])}${sd([R(avg('c')) + ' g', 'Average carbs'])}${sd([R(avg('f')) + ' g', 'Average fat'])}${sd([logged.filter(d => day[d].p >= T.protein * .9).length + ' / ' + logged.length, 'Days meeting protein (≥90%)'])}</div>
${logged.length ? `<div class="grid"><section class="card"><h3>Calories</h3><div class="chart"><canvas id="a2"></canvas></div></section><section class="card"><h3>Protein</h3><div class="chart"><canvas id="a3"></canvas></div></section><section class="card"><h3>Carbs &amp; fat</h3><div class="chart"><canvas id="a4"></canvas></div></section></div>` : `<section class="card">${empty('No food logged in this range', 'Log meals on the Nutrition page.')}</section>`}
<h2 style="margin:1rem 0 .6rem">Workouts</h2><div class="stats">${sd([wk.length, 'Total workouts'])}${sd([R(sum(wk, 'kcal')) + ' kcal', 'Exercise calories (est.)'])}${sd([R(sum(wk.filter(x => x.type === 'walking'), 'distance'), 1) + ' km', 'Walking distance'])}${sd([R(sum(wk.filter(x => x.type === 'running'), 'distance'), 1) + ' km', 'Running distance'])}${sd([strength.length, 'Strength sessions'])}${sd([R(sum(wk, 'duration')) + ' min', 'Total duration'])}</div>
${wk.length ? '<section class="card"><h3>Calories burned per day</h3><div class="chart"><canvas id="a5"></canvas></div></section>' : `<section class="card">${empty('No workouts in this range', 'Log one on the Workouts page.')}</section>`}
<h2 style="margin:1rem 0 .6rem">Strength</h2>${names.length ? `<div class="grid"><section class="card"><div class="ch"><h3>Progression</h3><select style="width:auto" onchange="AX=this.value;render()">${names.map(n => `<option ${n === AX ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></div>${exh.length ? '<div class="chart"><canvas id="a6"></canvas></div>' : empty('No sessions in this range', '')}</section>
<section class="card"><h3>Personal records (all time)</h3><table><tr><th>Exercise</th><th>Max weight</th><th>Best volume</th></tr>${pr.map(p => `<tr><td>${esc(p.n)}</td><td>${p.kg} kg × ${p.reps}<div class="small mut">${nice(p.date)}</div></td><td>${R(p.vol)} kg</td></tr>`).join('')}</table></section></div>` : `<section class="card">${empty('No strength history yet', 'Log a strength workout to track records and volume.')}</section>`}`;
  if (ws.length > 1) chart('a1', 'line', ws.map(w => w.date.slice(5)), [{ label: 'Weight (kg)', data: ws.map(w => w.kg), borderColor: col('--acc'), backgroundColor: col('--acc') }]);
  if (logged.length) {
    chart('a2', 'bar', l, [{ label: 'kcal', data: series('k'), backgroundColor: col('--acc') }, { type: 'line', label: 'Target', data: dates.map(() => T.kcal), borderColor: col('--mut'), borderDash: [6, 6], pointRadius: 0 }], true);
    chart('a3', 'bar', l, [{ label: 'Protein (g)', data: series('p'), backgroundColor: col('--blue') }, { type: 'line', label: 'Target', data: dates.map(() => T.protein), borderColor: col('--mut'), borderDash: [6, 6], pointRadius: 0 }], true);
    chart('a4', 'line', l, [{ label: 'Carbs (g)', data: series('c'), borderColor: col('--amber'), backgroundColor: col('--amber') }, { label: 'Fat (g)', data: series('f'), borderColor: col('--pink'), backgroundColor: col('--pink') }], true);
  }
  if (wk.length) chart('a5', 'bar', l, [{ label: 'kcal burned (est.)', data: dates.map(d => R(day[d].burn) || null), backgroundColor: col('--acc') }], true);
  if (exh.length) chart('a6', 'bar', exh.map(x => x.date.slice(5)), [{ label: 'Volume (kg)', data: exh.map(x => R(x.vol)), backgroundColor: col('--blue'), yAxisID: 'y' }, { type: 'line', label: 'Weight (kg)', data: exh.map(x => x.kg), borderColor: col('--acc'), yAxisID: 'y1' }], true, { y1: { position: 'right', beginAtZero: true, grid: { display: false } } });
}

/* ================= settings & data ================= */
function pgSettings() {
  const T = S.targets;
  $('#main').innerHTML = `${head('Settings')}<div class="grid2"><div>
<section class="card"><h2>Profile</h2><form onsubmit="saveProfile(event)">${profileFields(S.profile)}<button class="btn block">Save profile</button></form></section>
<section class="card"><h2>Daily targets</h2><form onsubmit="saveTargets(event)"><div class="row2"><label>Calories<input name="kcal" type="number" min="800" max="8000" required value="${T.kcal}"></label><label>Protein (g)<input name="protein" type="number" min="0" max="500" required value="${T.protein}"></label></div><div class="row2"><label>Carbs (g)<input name="carbs" type="number" min="0" max="1000" required value="${T.carbs}"></label><label>Fat (g)<input name="fat" type="number" min="0" max="400" required value="${T.fat}"></label></div><div class="btns"><button class="btn">Save targets</button><button type="button" class="btn ghost" onclick="recommendNow()">Use recommended</button></div></form><p class="note">Targets are estimates. Adjust them to match how your body responds over a few weeks.</p></section></div>
<div><section class="card"><h2>Appearance</h2><label>Theme<select onchange="S.settings.theme=this.value;save();applyTheme();render()"><option value="dark" ${S.settings.theme !== 'light' ? 'selected' : ''}>Dark</option><option value="light" ${S.settings.theme === 'light' ? 'selected' : ''}>Light</option></select></label></section>
<section class="card"><h2>Backup</h2><p class="small mut" style="margin-bottom:.7rem">Your data lives only in this browser. Export a backup regularly, especially before clearing browser data.</p><div class="btns"><button class="btn" onclick="exportJSON()">Export JSON</button><label class="btn ghost" style="margin:0;cursor:pointer;color:var(--txt)">Import JSON<input type="file" accept="application/json,.json" hidden onchange="importJSON(this)"></label></div>
<h3 style="margin:1rem 0 .5rem">CSV exports</h3><div class="btns"><button class="btn ghost sm" onclick="exportCSV('weight')">Weight</button><button class="btn ghost sm" onclick="exportCSV('workouts')">Workouts</button><button class="btn ghost sm" onclick="exportCSV('nutrition')">Nutrition</button></div></section>
<section class="card"><h2>Reset</h2><p class="small mut" style="margin-bottom:.7rem">Permanently deletes your profile and all logs from this browser.</p><button class="btn danger" onclick="resetAll()">Delete all data</button></section></div></div>`;
}
async function saveProfile(e) {
  e.preventDefault();
  try { const p = readProfile(e.target); S.profile = { ...S.profile, ...p }; if (p.weight !== latestWeight()) upsertWeight(today(), p.weight); save(); render(); toast('Profile saved'); recommend('Your profile changed.'); } catch (err) { toast(err.message, 1); }
}
function saveTargets(e) {
  e.preventDefault(); const g = n => N(e.target.elements[n].value);
  const t = { kcal: g('kcal'), protein: g('protein'), carbs: g('carbs'), fat: g('fat') };
  if (!(t.kcal >= 800 && t.kcal <= 8000) || [t.protein, t.carbs, t.fat].some(v => !(v >= 0))) return toast('Enter valid targets', 1);
  S.targets = t; save(); toast('Targets saved'); render();
}
async function recommendNow() { try { const t = await api('targets', S.profile); S.targets = { kcal: t.kcal, protein: t.protein, carbs: t.carbs, fat: t.fat }; save(); render(); toast('Recommended targets applied'); } catch (e) { toast(e.message, 1); } }
function download(name, text, type) { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type })); a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000); }
function exportJSON() { download(`fitlog-backup-${today()}.json`, JSON.stringify({ ...S, exportedAt: new Date().toISOString() }, null, 2), 'application/json'); toast('Backup downloaded'); }
function importJSON(inp) {
  const file = inp.files[0]; if (!file) return; const rd = new FileReader();
  rd.onload = () => {
    try {
      const o = JSON.parse(rd.result); if (o.version > VER) throw new Error('This backup is from a newer version of the app');
      const d = normalize(o); if (!d.profile || !d.targets) throw new Error('Backup has no profile data');
      if (!confirm('Replace ALL current data with this backup?')) return;
      S = d; save(); applyTheme(); render(); toast('Backup restored');
    } catch (e) { toast('Import failed: ' + e.message, 1); }
  };
  rd.onerror = () => toast('Could not read the file', 1); rd.readAsText(file); inp.value = '';
}
function exportCSV(kind) {
  const q = v => { v = String(v ?? ''); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
  const rows = kind === 'weight' ? [['date', 'weight_kg'], ...S.weights.map(w => [w.date, w.kg])]
    : kind === 'workouts' ? [['date', 'time', 'type', 'name', 'duration_min', 'distance_km', 'est_kcal', 'notes'], ...S.workouts.map(w => [w.date, w.time, w.type, w.name, w.duration, w.distance || '', R(w.kcal, 1), w.notes || ''])]
      : [['date', 'meal', 'food', 'grams', 'kcal', 'protein_g', 'carbs_g', 'fat_g'], ...S.foods.map(f => [f.date, f.meal, f.name, f.grams, f.kcal, f.protein, f.carbs, f.fat])];
  if (rows.length === 1) return toast('Nothing to export yet', 1);
  download(`fitlog-${kind}-${today()}.csv`, rows.map(r => r.map(q).join(',')).join('\n'), 'text/csv');
}
function resetAll() {
  if (!confirm('Delete ALL data? This cannot be undone. Export a backup first if unsure.')) return;
  try { localStorage.removeItem(KEY); } catch (e) { } S = blank(); WF = null; location.hash = ''; applyTheme(); render(); toast('All data deleted');
}

/* ================= boot ================= */
(async function boot() {
  S = load(); applyTheme();
  try { [META, FOODS] = await Promise.all([api('meta'), api('foods').then(r => r.foods)]); }
  catch (e) { $('#root').innerHTML = `<div class="center card"><h2>Can’t reach the FITLOG API</h2><p class="mut">${esc(e.message)}</p><p class="mut small" style="margin-top:.6rem">Deploy to Vercel, or run <code>vercel dev</code> locally, so <code>/api/index</code> is available.</p></div>`; return; }
  window.addEventListener('hashchange', render); render();
})();
</script>
</body>
</html>
"""


def meta():
    return {
        "activities": ACTIVITIES, "goals": GOALS,
        "activityLevels": {k: v[1] for k, v in ACTIVITY_LEVELS.items()},
    }


# FastAPI application detected automatically by Vercel from this root index.py.
app = FastAPI(title="FITLOG API")


@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(PAGE, headers={"Cache-Control": "no-cache"})


@app.get("/style.css")
async def stylesheet():
    css_path = Path(__file__).with_name("style.css")
    if not css_path.is_file():
        return JSONResponse({"error": "style.css was not found"}, status_code=404)
    return FileResponse(css_path, media_type="text/css", headers={"Cache-Control": "public, max-age=300"})


@app.get("/api/index")
async def get_api(action: str = "meta"):
    if action == "meta":
        return JSONResponse(meta(), headers={"Cache-Control": "public, max-age=300"})
    if action == "foods":
        return JSONResponse({"foods": load_foods()}, headers={"Cache-Control": "public, max-age=300"})
    if action == "health":
        return {"ok": True}
    return JSONResponse({"error": "Unknown action"}, status_code=404)


@app.post("/api/index")
async def post_api(request: Request, action: str = ""):
    try:
        data = await request.json()
        if not isinstance(data, dict):
            return JSONResponse({"error": "Body must be a JSON object"}, status_code=400)
        if action == "targets":
            return calc_targets(data)
        if action == "calories":
            return calc_calories(data)
        return JSONResponse({"error": "Unknown action"}, status_code=404)
    except (ValueError, TypeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception:
        return JSONResponse({"error": "Invalid request or internal server error"}, status_code=400)
