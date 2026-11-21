#!/usr/bin/env python3
"""SNIFF policy-trace console: turns the engine's --debug output into one static HTML page.

It never decides anything. It only displays what system/run already decided, with the
policy trace the engine attached (principle, exact POLICY.md sentence, facts, resolution path).

Usage:
  system/run ../dev /tmp/debug.jsonl --debug
  python3 console/trace.py --debug /tmp/debug.jsonl --data ../dev \
      [--labels ../dev/practice_labels.jsonl] [--harness /tmp/hdemo/demo_report.json] \
      [--out console/trace.html]

The generated HTML contains dev data, so it is gitignored. Only this script is committed.
Python 3 standard library only. No server: open the HTML file in a browser.
"""
import argparse
import html
import json
import os
from collections import Counter

DEMO_HITS = ["H-58A39C", "H-91AC66", "H-6C7985"]


def read_jsonl(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def find_file(folder, key):
    if not folder or not os.path.isdir(folder):
        return None
    for root, _, files in os.walk(folder):
        for fn in sorted(files):
            if fn.endswith(".jsonl") and key in fn.lower():
                return os.path.join(root, fn)
    return None


def screened_name(alert):
    if not alert:
        return None
    if alert.get("customer_name"):
        return alert["customer_name"]
    c = alert.get("customer")
    if isinstance(c, dict):
        return c.get("name") or c.get("customer_name") or c.get("full_name")
    return None


def build(args):
    rows = read_jsonl(args.debug)
    alerts, hits = {}, {}
    if args.data:
        ap, hp = find_file(args.data, "alert"), find_file(args.data, "hit")
        if ap:
            alerts = {a.get("alert_id"): a for a in read_jsonl(ap)}
        if hp:
            hits = {h.get("hit_id"): h for h in read_jsonl(hp)}

    items = []
    for r in rows:
        h = hits.get(r.get("hit_id"), {})
        a = alerts.get(r.get("alert_id"), {})
        t = r.get("trace") or {}
        items.append({
            "id": r.get("hit_id"), "alert": r.get("alert_id"), "decision": r.get("decision"),
            "code": r.get("reason_code"), "cust": r.get("customer_record_id"),
            "reason": r.get("reason"), "evidence": r.get("evidence") or [],
            "path": t.get("resolution") or r.get("path") or [],
            "principle": t.get("principle"), "rule": t.get("rule"),
            "facts": t.get("facts") or [], "fragile": bool(t.get("fragile_guard")),
            "screened": screened_name(a), "hitName": h.get("name"),
            "category": h.get("primary_category") or h.get("categories"),
            "type": h.get("entity_type"),
        })
    items.sort(key=lambda x: (x["id"] not in DEMO_HITS,
                              DEMO_HITS.index(x["id"]) if x["id"] in DEMO_HITS else 0, x["id"] or ""))

    counts = Counter(i["decision"] for i in items)
    stats = {"total": len(items), "different": counts.get("DIFFERENT_ENTITY", 0),
             "same": counts.get("SAME_ENTITY", 0), "review": counts.get("REVIEW", 0)}
    stats["auto"] = round(100 * (stats["different"] + stats["same"]) / max(1, stats["total"]))

    if args.labels and os.path.exists(args.labels):
        labels = read_jsonl(args.labels)
        by = {i["id"]: i for i in items}
        right = unsafe = 0
        for lab in labels:
            o = by.get(lab.get("hit_id"))
            if not o:
                continue
            right += o["decision"] == lab.get("decision")
            unsafe += o["decision"] == "DIFFERENT_ENTITY" and lab.get("decision") != "DIFFERENT_ENTITY"
        stats["practice"] = f"{right}/{len(labels)}"
        stats["unsafe"] = unsafe

    harness = None
    if args.harness and os.path.exists(args.harness):
        hj = json.load(open(args.harness, encoding="utf-8"))
        s = hj.get("summary", {})
        harness = {
            "seeds": s.get("n_seeds"), "cases": s.get("n_cases"),
            "same": s.get("stayed_SAME", 0), "review": s.get("moved_to_REVIEW", 0),
            "different": s.get("became_DIFFERENT", 0), "unsafe": s.get("safety_violations", 0),
            "results": [{"hit": x.get("hit_id"), "mutation": x.get("mutation"),
                         "before": x.get("original_decision"), "after": x.get("mutated_decision"),
                         "safe": not x.get("safety_violation")} for x in hj.get("results", [])],
        }

    payload = json.dumps({"items": items, "stats": stats, "harness": harness, "demo": DEMO_HITS},
                         ensure_ascii=False).replace("</", "<\\/")
    page = TEMPLATE.replace("__DATA__", payload).replace("__TITLE__", html.escape(args.title))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"wrote {args.out}  ({len(items)} hits)")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --bg:#FFFFFF; --paper:#F6F6F6; --tint:#EEEEEE; --line:#E4E4E4;
  --accent:#111111; --accent2:#2A2A2A; --deep:#000000; --ink:#111111; --muted:#6B6B6B;
  --clear:#13A45C; --match:#E5484D; --review:#F2A30F;
  --shadow:0 1px 2px rgba(0,0,0,.06),0 12px 32px -12px rgba(0,0,0,.18);
  --spring:cubic-bezier(.2,.9,.25,1.15);
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.5 ui-sans-serif,-apple-system,"Segoe UI",Inter,Roboto,"Helvetica Neue",Arial,sans-serif}
.wrap{max-width:1280px;margin:0 auto;padding:0 28px}
/* ---------- hero ---------- */
.hero{position:relative;overflow:hidden;background:
  radial-gradient(900px 420px at 85% -10%,#E8E8E8 0%,rgba(232,232,232,0) 60%),
  radial-gradient(700px 380px at -10% 110%,#F0F0F0 0%,rgba(240,240,240,0) 60%),var(--paper);
  border-bottom:1px solid var(--line)}
.hero .wrap{display:grid;grid-template-columns:1.1fr .9fr;gap:32px;align-items:center;padding-top:44px;padding-bottom:40px}
.brand{display:flex;align-items:center;font-weight:800;letter-spacing:.08em;color:var(--deep);font-size:18px}
h1{font-size:46px;line-height:1.05;margin:18px 0 12px;letter-spacing:-.02em}
h1 em{font-style:normal;color:var(--deep)}
.sub{color:var(--muted);font-size:17px;max-width:560px}
.pill{display:inline-flex;align-items:center;gap:8px;padding:6px 12px;border-radius:999px;background:#fff;border:1px solid var(--line);font-size:13px;color:var(--muted);margin-top:18px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--clear);box-shadow:0 0 0 4px rgba(19,164,92,.15)}
/* 3D scene */
.scene{height:330px;perspective:1100px;display:grid;place-items:center}
.stack{position:relative;width:340px;height:300px;transform-style:preserve-3d;transform:rotateX(14deg) rotateY(-22deg);transition:transform .25s ease-out}
.card3{position:absolute;left:0;top:0;width:250px;height:132px;border-radius:20px;background:#fff;border:1px solid var(--line);box-shadow:var(--shadow);padding:18px;
  transform-style:preserve-3d;animation:bob 6s ease-in-out infinite}
.card3 .k{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted)}
.card3 .v{font-weight:700;font-size:18px;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.card3 .row{height:8px;border-radius:6px;background:var(--tint);margin-top:12px}
.c1{transform:translate3d(-10px,0,-60px);animation-delay:-1s}
.c2{transform:translate3d(45px,84px,0);animation-delay:-2s}
.c3{transform:translate3d(100px,168px,60px);background:linear-gradient(140deg,#fff 0%,#F3F3F3 100%);border-color:#CCCCCC;animation-delay:-3s}
@keyframes bob{0%,100%{translate:0 0}50%{translate:0 -10px}}
.badge{display:inline-flex;align-items:center;gap:6px;font-weight:700;font-size:12px;padding:5px 10px;border-radius:999px;letter-spacing:.02em}
.b-DIFFERENT_ENTITY{background:rgba(19,164,92,.12);color:var(--clear)}
.b-SAME_ENTITY{background:rgba(229,72,77,.12);color:var(--match)}
.b-REVIEW{background:rgba(242,163,15,.16);color:#B97800}
/* stats */
.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin:-28px auto 8px;position:relative;z-index:2}
.stat{background:#fff;border:1px solid var(--line);border-radius:18px;padding:16px 18px;box-shadow:var(--shadow);transform-style:preserve-3d;transition:transform .2s ease-out}
.stat .n{font-size:30px;font-weight:800;letter-spacing:-.02em}
.stat .l{color:var(--muted);font-size:13px}
.stat.hot .n{color:var(--accent)}
/* explorer */
.section-title{display:flex;align-items:end;justify-content:space-between;margin:40px 0 14px}
.section-title h2{margin:0;font-size:24px;letter-spacing:-.01em}
.section-title p{margin:0;color:var(--muted)}
.explorer{display:grid;grid-template-columns:340px 1fr;gap:20px;align-items:start}
.side{position:sticky;top:16px;background:#fff;border:1px solid var(--line);border-radius:18px;box-shadow:var(--shadow);overflow:hidden}
.search{padding:14px;border-bottom:1px solid var(--line);background:var(--paper)}
.search input{width:100%;padding:10px 12px;border-radius:12px;border:1px solid var(--line);font:inherit;outline:none;background:#fff}
.search input:focus{border-color:var(--accent);box-shadow:0 0 0 4px rgba(0,0,0,.08)}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
.chip{border:1px solid var(--line);background:#fff;border-radius:999px;padding:5px 10px;font-size:12px;cursor:pointer;color:var(--muted)}
.chip.on{background:var(--accent);border-color:var(--accent);color:#fff}
.list{max-height:640px;overflow:auto}
.li{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:11px 14px;border-bottom:1px solid #F0F0F0;cursor:pointer;transition:background .15s}
.li:hover{background:var(--paper)}
.li.sel{background:var(--tint)}
.li .id{font-weight:700;font-size:13px}
.li .nm{color:var(--muted);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:170px}
.star{color:var(--accent);font-size:11px;margin-left:4px}
.dotd{width:10px;height:10px;border-radius:50%;flex:none}
.d-DIFFERENT_ENTITY{background:var(--clear)} .d-SAME_ENTITY{background:var(--match)} .d-REVIEW{background:var(--review)}
/* detail */
.detail{min-height:600px}
.vs{display:grid;grid-template-columns:1fr auto 1fr;gap:14px;align-items:stretch;margin-bottom:18px}
.who{background:#fff;border:1px solid var(--line);border-radius:18px;padding:16px 18px;box-shadow:var(--shadow)}
.who .k{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.who .v{font-size:20px;font-weight:800;margin-top:2px}
.who .m{color:var(--muted);font-size:13px}
.vsx{display:grid;place-items:center;font-weight:900;color:#fff;width:52px;border-radius:16px;background:linear-gradient(160deg,var(--accent2),var(--deep));box-shadow:var(--shadow)}
.pipe{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;perspective:1200px}
.step{position:relative;background:#fff;border:1px solid var(--line);border-radius:20px;padding:16px;box-shadow:var(--shadow);
  transform-style:preserve-3d;opacity:0;transform:translateY(26px) rotateX(18deg) scale(.96);min-height:220px}
.step.in{animation:springIn .7s var(--spring) forwards}
@keyframes springIn{to{opacity:1;transform:translateY(0) rotateX(0) scale(1)}}
.step .num{width:28px;height:28px;border-radius:9px;display:grid;place-items:center;font-weight:800;font-size:13px;background:var(--tint);color:var(--deep)}
.step h3{margin:10px 0 8px;font-size:15px}
.step:not(:last-child)::after{content:"";position:absolute;right:-12px;top:50%;width:10px;height:10px;border-top:2px solid var(--accent2);border-right:2px solid var(--accent2);transform:translateY(-50%) rotate(45deg);z-index:3}
.step.final{background:linear-gradient(150deg,#fff 0%,#F3F3F3 100%);border-color:#CCCCCC}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px}
.path{margin:0;padding-left:16px;color:var(--ink);font-size:12.5px}
.path li{margin:4px 0}
.ev{display:flex;flex-wrap:wrap;gap:6px}
.ev span{background:var(--paper);border:1px solid var(--line);border-radius:8px;padding:3px 7px}
.quote{border-left:3px solid var(--accent);padding:4px 0 4px 10px;color:#2a2a2a;font-size:13px;font-style:italic}
.code{display:inline-block;margin-top:8px;font-weight:700;color:var(--deep)}
.verdict{font-size:22px;font-weight:900;letter-spacing:-.01em;margin:6px 0}
.v-DIFFERENT_ENTITY{color:var(--clear)} .v-SAME_ENTITY{color:var(--match)} .v-REVIEW{color:#C48100}
.guard{margin-top:8px;font-size:12px;color:#9A5B00;background:#FFF4D6;border:1px solid #F6DA92;border-radius:10px;padding:6px 8px}
.facts{margin-top:16px;background:#fff;border:1px solid var(--line);border-radius:18px;padding:16px 18px;box-shadow:var(--shadow)}
.facts h4{margin:0 0 8px;font-size:13px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.facts p{margin:6px 0}
/* harness */
.harness{margin:44px 0 30px;display:grid;grid-template-columns:.85fr 1.15fr;gap:20px}
.hcard{background:#fff;border:1px solid var(--line);border-radius:22px;padding:22px;box-shadow:var(--shadow)}
.big{font-size:84px;font-weight:900;line-height:1;letter-spacing:-.04em;color:var(--deep)}
.bar{display:flex;height:22px;border-radius:999px;overflow:hidden;background:var(--paper);margin:16px 0 8px}
.bar div{width:0;transition:width 1.2s var(--spring)}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:13px;color:var(--muted)}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--muted);font-weight:600;padding:8px;border-bottom:1px solid var(--line)}
td{padding:7px 8px;border-bottom:1px solid #F0F0F0}
.ok{color:var(--clear);font-weight:700} .bad{color:var(--match);font-weight:700}
.tbl{max-height:360px;overflow:auto}
footer{border-top:1px solid var(--line);background:var(--paper);color:var(--muted);font-size:13px;padding:22px 0;margin-top:20px}
.reveal{opacity:0;transform:translateY(18px);transition:opacity .7s ease,transform .7s var(--spring)}
.reveal.show{opacity:1;transform:none}
@media (max-width:1000px){.hero .wrap,.explorer,.harness{grid-template-columns:1fr}.stats{grid-template-columns:repeat(2,1fr)}.pipe{grid-template-columns:1fr 1fr}.side{position:static}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}.step{opacity:1;transform:none}}
</style>
</head>
<body>
<header class="hero">
  <div class="wrap">
    <div>
      <div class="brand">SNIFF</div>
      <h1>Is this watchlist hit <em>really</em> our customer?</h1>
      <div class="sub">Sanctions Name &amp; Identity Fact Finder. SNIFF resolves the customer across six bank systems, gathers the listed person's facts, and follows the screening SOP to the letter: clear only on a contradiction, confirm only on agreement, otherwise send it to a person.</div>
      <div class="pill"><span class="dot"></span>Deterministic: no model, no randomness, same answer every run</div>
    </div>
    <div class="scene" id="scene">
      <div class="stack" id="stack">
        <div class="card3 c1"><div class="k">Customer (verified ID)</div><div class="v" id="h-cust">Resolving…</div><div class="row" style="width:80%"></div><div class="row" style="width:55%"></div></div>
        <div class="card3 c2"><div class="k">Watchlist hit</div><div class="v" id="h-hit">Gathering facts…</div><div class="row" style="width:70%"></div><div class="row" style="width:40%"></div></div>
        <div class="card3 c3"><div class="k">SOP verdict</div><div class="v" id="h-verdict">…</div><div class="row" style="width:62%;background:#DDDDDD"></div><div class="mono" id="h-code" style="margin-top:12px;color:var(--deep)"></div></div>
      </div>
    </div>
  </div>
</header>

<div class="wrap">
  <div class="stats" id="stats"></div>

  <div class="section-title reveal"><div><h2>Policy trace</h2><p>Every decision, from the customer we found to the exact POLICY.md sentence it rests on.</p></div></div>
  <div class="explorer reveal">
    <aside class="side">
      <div class="search">
        <input id="q" placeholder="Search hit ID, name or reason code…">
        <div class="chips" id="chips"></div>
      </div>
      <div class="list" id="list"></div>
    </aside>
    <section class="detail" id="detail"></section>
  </div>

  <div id="harnessWrap"></div>
</div>
<footer><div class="wrap">SNIFF · Track 2, Grok Bot London Financial Crime Hackathon · This page only displays what <span class="mono">system/run --debug</span> decided; it makes no decisions of its own.</div></footer>

<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const LABEL = {DIFFERENT_ENTITY:'Cleared · different person', SAME_ENTITY:'Match · same person', REVIEW:'Review · send to analyst'};
const SHORT = {DIFFERENT_ENTITY:'Cleared', SAME_ENTITY:'Match', REVIEW:'Review'};
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

/* ---- stats with count-up ---- */
const S = D.stats;
const statDefs = [
  {n:S.total, l:'hits decided', hot:false},
  {n:S.auto, l:'resolved automatically', suf:'%', hot:true},
  {n:S.different, l:'cleared (different person)'},
  {n:S.same, l:'confirmed matches'},
  S.practice ? {t:S.practice, l:'practice labels · '+S.unsafe+' unsafe clears', hot:true} : {n:S.review, l:'sent to review'}
];
document.getElementById('stats').innerHTML = statDefs.map(s =>
  `<div class="stat tilt ${s.hot?'hot':''}"><div class="n" data-n="${s.n ?? ''}" data-suf="${s.suf||''}">${s.t ? esc(s.t) : '0'}</div><div class="l">${esc(s.l)}</div></div>`).join('');
document.querySelectorAll('.stat .n[data-n]').forEach(el => {
  const target = +el.dataset.n; if (!el.dataset.n) return; const t0 = performance.now(); const dur = 1100;
  const step = t => { const p = Math.min(1, (t - t0) / dur); const e = 1 - Math.pow(1 - p, 3);
    el.textContent = Math.round(target * e) + el.dataset.suf; if (p < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
});

/* ---- list + filters ---- */
let filter = 'ALL', query = '', selected = null;
const chipDefs = [['ALL','All'],['DIFFERENT_ENTITY','Cleared'],['SAME_ENTITY','Match'],['REVIEW','Review']];
const chips = document.getElementById('chips');
chips.innerHTML = chipDefs.map(([k,l]) => `<button class="chip ${k==='ALL'?'on':''}" data-k="${k}">${l}</button>`).join('');
chips.onclick = e => { const b = e.target.closest('.chip'); if (!b) return; filter = b.dataset.k;
  chips.querySelectorAll('.chip').forEach(c => c.classList.toggle('on', c === b)); renderList(); };
document.getElementById('q').oninput = e => { query = e.target.value.toLowerCase(); renderList(); };

function visible() {
  return D.items.filter(i => (filter === 'ALL' || i.decision === filter) &&
    (!query || [i.id, i.code, i.hitName, i.screened, i.cust].join(' ').toLowerCase().includes(query)));
}
function renderList() {
  const v = visible().slice(0, 400);
  document.getElementById('list').innerHTML = v.map(i => `
    <div class="li ${i.id===selected?'sel':''}" data-id="${esc(i.id)}">
      <div><div class="id">${esc(i.id)}${D.demo.includes(i.id)?'<span class="star">★ demo</span>':''}</div>
      <div class="nm">${esc(i.hitName || i.code)}</div></div>
      <span class="dotd d-${esc(i.decision)}" title="${esc(SHORT[i.decision])}"></span>
    </div>`).join('') || '<div class="li">No hits match.</div>';
}
document.getElementById('list').onclick = e => { const r = e.target.closest('.li[data-id]'); if (r) select(r.dataset.id); };

/* ---- detail pipeline ---- */
function select(id) {
  selected = id; renderList();
  const i = D.items.find(x => x.id === id); if (!i) return;
  document.getElementById('h-cust').textContent = i.screened || i.cust || '—';
  document.getElementById('h-hit').textContent = i.hitName || i.id;
  const hv = document.getElementById('h-verdict'); hv.textContent = SHORT[i.decision]; hv.className = 'v v-' + i.decision;
  document.getElementById('h-code').textContent = i.code;
  const path = (i.path || []).map(p => `<li class="mono">${esc(p)}</li>`).join('') || '<li>No link or fit found.</li>';
  const ev = (i.evidence || []).map(e => `<span class="mono">${esc(e)}</span>`).join('') || '<span>none</span>';
  const facts = (i.facts && i.facts.length ? i.facts : [i.reason]).map(f => `<p>${esc(f)}</p>`).join('');
  document.getElementById('detail').innerHTML = `
    <div class="vs">
      <div class="who tilt"><div class="k">Customer as screened</div><div class="v">${esc(i.screened || '—')}</div>
        <div class="m">Resolved record: <span class="mono">${esc(i.cust ?? 'none')}</span></div></div>
      <div class="vsx">VS</div>
      <div class="who tilt"><div class="k">Watchlist hit · ${esc(i.category || i.type || '')}</div><div class="v">${esc(i.hitName || '—')}</div>
        <div class="m"><span class="mono">${esc(i.id)}</span> · alert <span class="mono">${esc(i.alert)}</span></div></div>
    </div>
    <div class="pipe">
      <div class="step tilt"><div class="num">1</div><h3>Find the customer</h3><ol class="path">${path}</ol></div>
      <div class="step tilt"><div class="num">2</div><h3>Evidence that decided it</h3><div class="ev">${ev}</div></div>
      <div class="step tilt"><div class="num">3</div><h3>SOP rule · principle ${esc(i.principle || '—')}</h3>
        <div class="quote">${esc(i.rule || 'See POLICY.md')}</div><span class="code mono">${esc(i.code)}</span></div>
      <div class="step final tilt"><div class="num">4</div><h3>Decision</h3>
        <div class="verdict v-${esc(i.decision)}">${esc(SHORT[i.decision])}</div>
        <span class="badge b-${esc(i.decision)}">${esc(LABEL[i.decision])}</span>
        ${i.fragile ? '<div class="guard">Free-text guard fired: unsure note reading, so we sent it to a person instead of guessing.</div>' : ''}
      </div>
    </div>
    <div class="facts"><h4>Facts the engine relied on</h4>${facts}</div>`;
  document.querySelectorAll('#detail .step').forEach((s, k) => setTimeout(() => s.classList.add('in'), 120 * k));
  bindTilt();
}

/* ---- harness ---- */
if (D.harness) {
  const H = D.harness, tot = Math.max(1, H.same + H.review + H.different);
  const rows = H.results.map(r => `<tr><td class="mono">${esc(r.hit)}</td><td>${esc(r.mutation.replace(/_/g,' '))}</td>
    <td><span class="badge b-${esc(r.before)}">${esc(SHORT[r.before]||r.before)}</span></td>
    <td><span class="badge b-${esc(r.after)}">${esc(SHORT[r.after]||r.after)}</span></td>
    <td class="${r.safe?'ok':'bad'}">${r.safe?'safe':'UNSAFE'}</td></tr>`).join('');
  document.getElementById('harnessWrap').innerHTML = `
    <div class="section-title reveal"><div><h2>Test to fail</h2><p>We take real matches, corrupt a copy of the data on purpose, and rerun. A real match must never come out cleared.</p></div></div>
    <div class="harness reveal">
      <div class="hcard tilt"><div class="k" style="color:var(--muted);font-size:12px;letter-spacing:.12em;text-transform:uppercase">Unsafe clears</div>
        <div class="big" id="bigzero">${H.unsafe}</div>
        <div style="font-weight:700;margin-top:6px">${H.cases} mutations from ${H.seeds} true matches</div>
        <div class="bar"><div id="b1" style="background:var(--accent)"></div><div id="b2" style="background:var(--review)"></div><div id="b3" style="background:var(--clear)"></div></div>
        <div class="legend"><span><i style="background:var(--accent)"></i>${H.same} still caught as a match</span><span><i style="background:var(--review)"></i>${H.review} moved to review</span><span><i style="background:var(--clear)"></i>${H.different} became cleared</span></div>
        <p style="color:var(--muted);font-size:13px;margin-top:12px">Mutations include name variants, hidden dates of birth, look-alike customers, rejected ID checks, duplicate records and cut account links.</p>
      </div>
      <div class="hcard"><div class="tbl"><table><thead><tr><th>Hit</th><th>Trick</th><th>Before</th><th>After</th><th>Safety</th></tr></thead><tbody>${rows}</tbody></table></div></div>
    </div>`;
  const grow = () => { b1.style.width = (100*H.same/tot)+'%'; b2.style.width = (100*H.review/tot)+'%'; b3.style.width = (100*H.different/tot)+'%'; };
  window.__grow = grow;
}

/* ---- 3D tilt (Framer-style spring feel, vanilla JS) ---- */
function bindTilt() {
  document.querySelectorAll('.tilt').forEach(el => {
    if (el.__t) return; el.__t = 1;
    el.addEventListener('mousemove', e => { const r = el.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
      el.style.transform = `perspective(900px) rotateY(${x*8}deg) rotateX(${-y*8}deg) translateZ(6px)`; });
    el.addEventListener('mouseleave', () => { el.style.transition = 'transform .5s cubic-bezier(.2,.9,.25,1.15)'; el.style.transform = '';
      setTimeout(() => el.style.transition = '', 500); });
  });
}
const scene = document.getElementById('scene'), stack = document.getElementById('stack');
scene.addEventListener('mousemove', e => { const r = scene.getBoundingClientRect();
  const x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
  stack.style.transform = `rotateX(${14 - y*16}deg) rotateY(${-22 + x*26}deg)`; });
scene.addEventListener('mouseleave', () => stack.style.transform = '');

/* ---- scroll reveal ---- */
const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add('show');
  if (e.target.classList.contains('harness') && window.__grow) setTimeout(window.__grow, 250); } }), {threshold:.15});
document.querySelectorAll('.reveal').forEach(el => io.observe(el));

renderList(); bindTilt();
if (D.items.length) select(D.items[0].id);
</script>
</body>
</html>"""


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="SNIFF policy-trace console (static HTML)")
    p.add_argument("--debug", required=True, help="output of: system/run <data> <out> --debug")
    p.add_argument("--data", help="dev data folder, to show screened and hit names")
    p.add_argument("--labels", help="practice_labels.jsonl, to show the practice score")
    p.add_argument("--harness", help="harness demo_report.json, to show the test-to-fail section")
    p.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "trace.html"))
    p.add_argument("--title", default="SNIFF · Policy trace")
    build(p.parse_args())
