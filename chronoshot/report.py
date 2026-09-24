"""Build the one-page HTML report."""

import base64
import io
import json
import os
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from . import config, shots
from .util import ensure_dirs, read_json, daemon_pid, in_range, log_days, resolve_range


def norm_session(s, running=False):
    st = datetime.fromisoformat(s["start"])
    en = datetime.fromisoformat(s["end"])
    base = datetime.combine(st.date(), datetime.min.time())
    end_label = en.strftime("%H:%M:%S")
    if en.date() != st.date():
        end_label += f" (+{(en.date() - st.date()).days}d)"
    return {
        "project": s.get("project", "Default"),
        "note": s.get("note", ""),
        "start": st.strftime("%H:%M:%S"),
        "end": end_label,
        "startSec": int((st - base).total_seconds()),
        "endSec": int((en - base).total_seconds()),
        "duration": round(float(s.get("duration", (en - st).total_seconds())), 1),
        "running": running,
    }


def embed_image(path):
    """Self-contained copy of a screenshot (JPEG, max 1600px when Pillow is available)."""
    try:
        from PIL import Image

        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((1600, 1600))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=80)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return (
            "data:image/png;base64,"
            + base64.b64encode(Path(path).read_bytes()).decode()
        )


def collect_report_data(d_from, d_to, project, embed, base_dir):
    days = {}

    def bucket(d):
        return days.setdefault(d, {"date": d, "sessions": [], "shots": []})

    def keep_project(p):
        return not project or p.lower() == project.lower()

    for day in log_days():
        if not in_range(day, d_from, d_to):
            continue
        for s in read_json(config.LOGS_DIR / f"{day}.json", []):
            try:
                n = norm_session(s)
            except (KeyError, ValueError):
                continue
            if keep_project(n["project"]):
                bucket(day)["sessions"].append(n)

    live = read_json(config.CURRENT_SESSION, None) if daemon_pid() else None
    if live:
        try:
            st = datetime.fromisoformat(live["start"])
            now = datetime.now()
            n = norm_session(
                {
                    "start": live["start"],
                    "end": now.isoformat(timespec="seconds"),
                    "duration": (now - st).total_seconds(),
                    "project": live.get("project", "Default"),
                    "note": live.get("note", ""),
                },
                running=True,
            )
            day = st.strftime("%Y-%m-%d")
            if in_range(day, d_from, d_to) and keep_project(n["project"]):
                bucket(day)["sessions"].append(n)
        except (KeyError, ValueError):
            pass

    for it in shots.list_shots(config.ACCEPTED_DIR):
        if not in_range(it["date"], d_from, d_to) or not keep_project(it["project"]):
            continue
        if embed:
            src = embed_image(it["path"])
        else:
            rel = os.path.relpath(it["path"], base_dir).replace(os.sep, "/")
            src = quote(rel, safe="/")
        bucket(it["date"])["shots"].append(
            {
                "name": it["name"],
                "time": it["time"],
                "sec": it["sec"],
                "project": it["project"],
                "src": src,
            }
        )

    out = []
    for day in sorted(days):
        b = days[day]
        b["sessions"].sort(key=lambda s: s["startSec"])
        b["shots"].sort(key=lambda s: s["sec"])
        if b["sessions"] or b["shots"]:
            out.append(b)
    projects = sorted(
        {s["project"] for d in out for s in d["sessions"]}
        | {x["project"] for d in out for x in d["shots"]}
    )
    return {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "days": out,
        "projects": projects,
        "minDate": out[0]["date"] if out else "",
        "maxDate": out[-1]["date"] if out else "",
    }


REPORT_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en" data-theme="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  color-scheme:light;
  --bg:#eceee9; --panel:#f8f9f6; --ink:#182126; --muted:#5b686e; --line:#d2d8d1;
  --accent:#2350d8; --accent-soft:#dbe4fa; --track:#dde2db;
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --thumb:260px;
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --bg:#11161a; --panel:#182027; --ink:#e6ebed; --muted:#93a1a8; --line:#28343b;
  --accent:#7ea0ff; --accent-soft:#233052; --track:#232d34;
}
@media (prefers-color-scheme:dark){
  :root[data-theme="auto"]{
    color-scheme:dark;
    --bg:#11161a; --panel:#182027; --ink:#e6ebed; --muted:#93a1a8; --line:#28343b;
    --accent:#7ea0ff; --accent-soft:#233052; --track:#232d34;
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 var(--sans);font-variant-numeric:tabular-nums}
button,input,select{font:inherit;color:inherit}
button{cursor:pointer}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.app{display:grid;grid-template-columns:290px minmax(0,1fr);gap:44px;max-width:1440px;margin:0 auto;padding:28px 28px 72px}
aside{position:sticky;top:20px;align-self:start;max-height:calc(100vh - 40px);overflow:auto;padding-right:8px}
.brand h1{font:600 30px/1.1 var(--serif);margin:0 0 4px}
.brand p{margin:0;color:var(--muted);font-size:13px}
.actions{display:flex;flex-wrap:wrap;gap:6px;margin-top:14px}
.btn{border:1px solid var(--line);background:var(--panel);border-radius:6px;padding:5px 11px;font-size:13px}
.btn:hover{border-color:var(--muted)}
.group{margin-top:24px}
.group h3{font:600 13px/1.2 var(--sans);margin:0 0 9px;color:var(--muted)}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chips button{border:1px solid var(--line);background:transparent;border-radius:999px;padding:4px 11px;font-size:13px}
.chips button[aria-pressed="true"]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}
label.f{display:flex;flex-direction:column;gap:3px;font-size:12px;color:var(--muted)}
input[type=date],input[type=search],select{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:6px 8px;width:100%}
input[type=range]{width:100%;accent-color:var(--accent)}
.check{display:flex;align-items:center;gap:8px;font-size:14px;margin-bottom:10px}
.proj{display:block;width:100%;text-align:left;background:transparent;border:0;border-radius:6px;padding:7px 8px;margin-bottom:2px}
.proj:hover{background:var(--panel)}
.proj.on{background:var(--accent-soft)}
.pl{display:flex;align-items:center;gap:8px}
.pn{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pt{color:var(--muted);font-size:13px}
.pbar{display:block;height:3px;background:var(--track);border-radius:2px;margin-top:5px;overflow:hidden}
.pbar i{display:block;height:100%}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;flex:none}
.lead{font:400 32px/1.2 var(--serif);margin:0 0 6px}
.sub{margin:0;color:var(--muted)}
.chart{margin:26px 0 10px;border:1px solid var(--line);border-radius:10px;background:var(--panel);padding:16px 18px 12px}
.chart h2{font:600 15px var(--sans);margin:0 0 12px}
.bars{display:flex;gap:10px;overflow-x:auto;padding-bottom:6px}
.col{flex:1 0 50px;max-width:96px;display:flex;flex-direction:column;align-items:center;gap:4px}
.val{font-size:11px;color:var(--muted);white-space:nowrap}
.barwrap{height:130px;width:100%;display:flex;align-items:flex-end}
.bar{width:100%;display:flex;flex-direction:column-reverse;min-height:2px;border-radius:4px 4px 0 0;overflow:hidden}
.bseg{min-height:1px}
.lbl{font-size:11px;color:var(--muted)}
.empty{color:var(--muted);margin:8px 0}
.day{border-top:1px solid var(--line);padding:18px 0 14px}
.day>summary{list-style:none;display:flex;align-items:center;gap:12px;cursor:pointer}
.day>summary::-webkit-details-marker{display:none}
.day>summary::before{content:"";flex:none;width:7px;height:7px;border-right:2px solid var(--muted);border-bottom:2px solid var(--muted);transform:rotate(-45deg);transition:transform .15s}
.day[open]>summary::before{transform:rotate(45deg)}
.dname{flex:1}
.dname b{font:600 22px var(--serif)}
.dname span{color:var(--muted);margin-left:8px;font-size:14px}
.dtot{font:600 20px var(--serif)}
.dchips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 0 19px}
.chip{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;border:1px solid var(--line);border-radius:999px;padding:1px 10px}
.stripwrap{position:relative;margin:20px 0 38px 19px}
.strip{position:relative;height:26px;background:var(--track);border-radius:6px}
.strip .seg{position:absolute;top:0;bottom:0;border-radius:4px;opacity:.93}
.strip .pin{position:absolute;top:-6px;width:10px;height:10px;margin-left:-5px;border-radius:50%;background:var(--ink);border:2px solid var(--panel);padding:0;cursor:pointer}
.tick{position:absolute;top:32px;transform:translateX(-50%);font-size:11px;color:var(--muted)}
.sessions{width:calc(100% - 19px);margin:0 0 18px 19px;border-collapse:collapse;font-size:14px}
.sessions td{padding:6px 12px 6px 0;border-bottom:1px solid var(--line);vertical-align:top}
.sessions .t{white-space:nowrap}
.sessions .n{width:100%;color:var(--muted)}
.live{margin-left:8px;color:var(--accent);font-size:12px}
.shots{display:grid;grid-template-columns:repeat(auto-fill,minmax(var(--thumb),1fr));gap:12px;margin-left:19px}
.shots figure{margin:0;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--panel);cursor:zoom-in}
.shots img{display:block;width:100%;aspect-ratio:16/10;object-fit:cover;background:var(--track)}
.shots figcaption{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:6px 9px;font-size:12px;color:var(--muted)}
.lb{position:fixed;inset:0;z-index:50;background:rgba(8,10,12,.93);display:flex;flex-direction:column;align-items:center;justify-content:center;padding:20px;gap:12px}
.lb[hidden]{display:none}
.lb img{max-width:100%;max-height:calc(100vh - 120px);object-fit:contain;border-radius:4px}
.lbbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:center;color:#dfe6e9;font-size:13px}
.lbbar button,.lbbar a{color:#dfe6e9;background:transparent;border:1px solid #4a565c;border-radius:6px;padding:4px 12px;text-decoration:none;font-size:13px}
.noscroll{overflow:hidden}
@media (max-width:900px){
  .app{grid-template-columns:1fr;gap:20px;padding:16px}
  aside{position:static;max-height:none}
  .lead{font-size:26px}
}
@media print{
  aside,.lb{display:none!important}
  .app{display:block;padding:0}
  body{background:#fff;color:#000}
  .shots{grid-template-columns:repeat(3,1fr)}
  .shots figure,.day>summary{break-inside:avoid}
}
</style>
</head>
<body>
<div class="app">
  <aside>
    <div class="brand">
      <h1>Time report</h1>
      <p id="gen"></p>
      <div class="actions">
        <button class="btn" id="btnTheme" type="button">Theme: auto</button>
        <button class="btn" id="btnCsv" type="button">Export CSV</button>
        <button class="btn" id="btnPrint" type="button">Print</button>
      </div>
    </div>

    <div class="group">
      <h3>Date range</h3>
      <div class="chips" id="ranges">
        <button type="button" data-r="today">Today</button>
        <button type="button" data-r="7">Last 7 days</button>
        <button type="button" data-r="30">Last 30 days</button>
        <button type="button" data-r="all">All time</button>
      </div>
      <div class="row2">
        <label class="f">From<input type="date" id="from"></label>
        <label class="f">To<input type="date" id="to"></label>
      </div>
    </div>

    <div class="group">
      <h3>Project</h3>
      <div id="projList"></div>
    </div>

    <div class="group">
      <h3>Search project or note</h3>
      <input type="search" id="q" placeholder="Type to filter">
    </div>

    <div class="group">
      <h3>Display</h3>
      <label class="check"><input type="checkbox" id="showShots" checked> Show screenshots</label>
      <label class="f">Screenshot size<input type="range" id="size" min="140" max="520" step="10" value="260"></label>
      <label class="f" style="margin-top:10px">Day order
        <select id="order"><option value="desc">Newest first</option><option value="asc">Oldest first</option></select>
      </label>
      <div class="actions">
        <button class="btn" id="expand" type="button">Expand all days</button>
        <button class="btn" id="collapse" type="button">Collapse all days</button>
      </div>
    </div>
  </aside>

  <main>
    <div id="summary"></div>
    <section class="chart" id="chartBox"><h2>Time per day</h2><div id="daily"></div></section>
    <div id="days"></div>
  </main>
</div>

<div class="lb" id="lb" hidden>
  <img id="lbImg" alt="Screenshot">
  <div class="lbbar">
    <button type="button" id="lbPrev">Previous</button>
    <span id="lbCap"></span>
    <button type="button" id="lbNext">Next</button>
    <a id="lbOpen" target="_blank" rel="noopener">Open original</a>
    <button type="button" id="lbClose">Close</button>
  </div>
</div>

<script>
(function () {
  'use strict';
  const D = __DATA__;
  const S = { range: 'all', from: '', to: '', project: '', q: '', shots: true, order: 'desc' };
  const VIS = [];
  const $ = (s) => document.querySelector(s);
  const pad = (n) => String(n).padStart(2, '0');

  function el(tag, props) {
    const e = document.createElement(tag);
    if (props) {
      for (const k in props) {
        const v = props[k];
        if (k === 'class') e.className = v;
        else if (k === 'style') e.style.cssText = v;
        else if (k.slice(0, 2) === 'on') e.addEventListener(k.slice(2), v);
        else if (v !== false && v !== null && v !== undefined) e.setAttribute(k, v === true ? '' : v);
      }
    }
    for (const c of Array.prototype.slice.call(arguments, 2).flat()) {
      if (c === null || c === undefined || c === false) continue;
      e.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return e;
  }
  function fmtDur(sec) {
    sec = Math.round(sec);
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    if (h) return h + 'h ' + pad(m) + 'm';
    if (m) return m + 'm ' + pad(s) + 's';
    return s + 's';
  }
  function color(name) {
    let h = 7;
    for (const c of name) h = (h * 131 + c.charCodeAt(0)) >>> 0;
    return 'hsl(' + (h % 360) + ' 60% 50%)';
  }
  function iso(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function niceDate(s) {
    const d = new Date(s + 'T00:00:00');
    return {
      dow: d.toLocaleDateString(undefined, { weekday: 'long' }),
      rest: d.toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' })
    };
  }
  const plural = (n, w) => n + ' ' + w + (n === 1 ? '' : 's');
  const total = (ss) => ss.reduce((a, s) => a + s.duration, 0);
  function byProject(ss) {
    const o = {};
    for (const s of ss) o[s.project] = (o[s.project] || 0) + s.duration;
    return o;
  }
  const chip = (p, extra) => el('span', { class: 'chip' }, el('i', { class: 'dot', style: 'background:' + color(p) }), p + (extra ? ' ' + extra : ''));

  function filtered(skipProject) {
    const q = S.q.trim().toLowerCase();
    const out = [];
    for (const day of D.days) {
      if (S.from && day.date < S.from) continue;
      if (S.to && day.date > S.to) continue;
      const okP = (p) => skipProject || !S.project || p === S.project;
      const sessions = day.sessions.filter((s) => okP(s.project) && (!q || (s.project + ' ' + (s.note || '')).toLowerCase().includes(q)));
      const shots = day.shots.filter((x) => okP(x.project) && (!q || x.project.toLowerCase().includes(q)));
      if (sessions.length || shots.length) out.push({ date: day.date, sessions: sessions, shots: shots });
    }
    out.sort((a, b) => (S.order === 'asc' ? a.date.localeCompare(b.date) : b.date.localeCompare(a.date)));
    return out;
  }

  function renderSummary(days) {
    const box = $('#summary');
    box.replaceChildren();
    if (!days.length) {
      box.append(el('p', { class: 'lead' }, 'Nothing matches these filters.'),
        el('p', { class: 'sub' }, D.days.length ? 'Widen the date range or choose All projects.' : 'No sessions or accepted screenshots yet. Run start, then stop, then report again.'));
      return;
    }
    const sess = days.flatMap((d) => d.sessions);
    const shots = days.reduce((a, d) => a + d.shots.length, 0);
    const tot = total(sess);
    const active = days.filter((d) => d.sessions.length).length;
    const projs = Object.keys(byProject(sess)).length;
    box.append(el('p', { class: 'lead' }, tot ? fmtDur(tot) + ' tracked over ' + plural(active, 'day') + ' on ' + plural(projs, 'project') + '.' : 'No sessions in this range.'));
    const bits = [plural(sess.length, 'session'), plural(shots, 'accepted screenshot')];
    if (active) {
      const longest = days.filter((d) => d.sessions.length).reduce((a, b) => (total(b.sessions) > total(a.sessions) ? b : a));
      bits.push('average ' + fmtDur(tot / active) + ' per active day');
      bits.push('longest day ' + longest.date + ' (' + fmtDur(total(longest.sessions)) + ')');
    }
    box.append(el('p', { class: 'sub' }, bits.join(', ') + '.'));
  }

  function renderDaily(days) {
    const box = $('#daily');
    box.replaceChildren();
    const asc = days.filter((d) => total(d.sessions) > 0).sort((a, b) => a.date.localeCompare(b.date));
    $('#chartBox').style.display = asc.length ? '' : 'none';
    if (!asc.length) return;
    const max = Math.max.apply(null, asc.map((d) => total(d.sessions)));
    box.append(el('div', { class: 'bars' }, asc.map((d) => {
      const tot = total(d.sessions);
      const segs = Object.entries(byProject(d.sessions)).sort((a, b) => b[1] - a[1]).map((e) =>
        el('span', { class: 'bseg', style: 'flex:' + e[1] + ' 1 0px;background:' + color(e[0]), title: e[0] + ': ' + fmtDur(e[1]) }));
      return el('div', { class: 'col' },
        el('div', { class: 'val' }, fmtDur(tot)),
        el('div', { class: 'barwrap' }, el('div', { class: 'bar', style: 'height:' + (tot / max * 100) + '%', title: d.date + ': ' + fmtDur(tot) }, segs)),
        el('div', { class: 'lbl' }, d.date.slice(5)));
    })));
  }

  function projBtn(value, label, secs, share, col) {
    return el('button', { class: 'proj' + (S.project === value ? ' on' : ''), type: 'button', 'aria-pressed': S.project === value ? 'true' : 'false',
      onclick: function () { S.project = value; update(); } },
      el('span', { class: 'pl' }, el('i', { class: 'dot', style: 'background:' + col }), el('span', { class: 'pn' }, label), el('span', { class: 'pt' }, fmtDur(secs))),
      el('span', { class: 'pbar' }, el('i', { style: 'width:' + (share * 100) + '%;background:' + col })));
  }
  function renderProjects() {
    const days = filtered(true);
    const by = byProject(days.flatMap((d) => d.sessions));
    for (const d of days) for (const x of d.shots) if (!(x.project in by)) by[x.project] = 0;
    if (S.project && !(S.project in by)) by[S.project] = 0;
    const tot = Object.values(by).reduce((a, b) => a + b, 0);
    const box = $('#projList');
    box.replaceChildren(projBtn('', 'All projects', tot, 1, 'var(--muted)'));
    Object.entries(by).sort((a, b) => b[1] - a[1]).forEach((e) => box.append(projBtn(e[0], e[0], e[1], tot ? e[1] / tot : 0, color(e[0]))));
  }

  function strip(day, base) {
    const pts = day.sessions.map((s) => [s.startSec, Math.min(s.endSec, 86400)]).concat(day.shots.map((x) => [x.sec, x.sec]));
    if (!pts.length) return null;
    let loH = Math.max(0, Math.floor(Math.min.apply(null, pts.map((p) => p[0])) / 3600));
    let hiH = Math.min(24, Math.ceil(Math.max.apply(null, pts.map((p) => p[1])) / 3600));
    if (hiH - loH < 2) { hiH = Math.min(24, loH + 2); loH = Math.max(0, hiH - 2); }
    const span = (hiH - loH) * 3600;
    const pos = (sec) => Math.max(0, Math.min(100, (sec - loH * 3600) / span * 100));
    const wrap = el('div', { class: 'stripwrap' });
    const bar = el('div', { class: 'strip' });
    day.sessions.forEach((s) => {
      const l = pos(s.startSec), w = Math.max(0.5, pos(Math.min(s.endSec, 86400)) - l);
      bar.append(el('div', { class: 'seg', style: 'left:' + l + '%;width:' + w + '%;background:' + color(s.project), title: s.project + ' ' + s.start + ' to ' + s.end + ' (' + fmtDur(s.duration) + ')' }));
    });
    day.shots.forEach((x, i) => {
      bar.append(el('button', { class: 'pin', type: 'button', style: 'left:' + pos(x.sec) + '%', title: 'Screenshot ' + x.time, 'aria-label': 'Open screenshot from ' + x.time, onclick: function () { openLB(base + i); } }));
    });
    wrap.append(bar);
    const hours = hiH - loH, step = hours <= 6 ? 1 : hours <= 12 ? 2 : 4;
    for (let h = loH; h <= hiH; h += step) wrap.append(el('span', { class: 'tick', style: 'left:' + pos(h * 3600) + '%' }, pad(h % 24) + ':00'));
    return wrap;
  }

  function renderDays(days) {
    const root = $('#days');
    root.replaceChildren();
    VIS.length = 0;
    for (const day of days) {
      const nd = niceDate(day.date);
      const tot = total(day.sessions);
      const base = VIS.length;
      day.shots.forEach((x) => VIS.push(Object.assign({ date: day.date }, x)));
      const det = el('details', { class: 'day', open: true });
      det.append(el('summary', null,
        el('span', { class: 'dname' }, el('b', null, nd.dow), el('span', null, nd.rest)),
        el('span', { class: 'dtot' }, tot ? fmtDur(tot) : 'no sessions')));
      const chips = Object.entries(byProject(day.sessions)).sort((a, b) => b[1] - a[1]).map((e) => chip(e[0], fmtDur(e[1])));
      if (chips.length) det.append(el('div', { class: 'dchips' }, chips));
      const st = strip(day, base);
      if (st) det.append(st);
      if (day.sessions.length) {
        det.append(el('table', { class: 'sessions' }, el('tbody', null, day.sessions.map((s) =>
          el('tr', null,
            el('td', { class: 't' }, s.start + ' to ' + s.end),
            el('td', { class: 't' }, fmtDur(s.duration)),
            el('td', { class: 't' }, chip(s.project)),
            el('td', { class: 'n' }, s.note || '', s.running ? el('span', { class: 'live' }, 'running now') : null))))));
      }
      if (S.shots && day.shots.length) {
        const grid = el('div', { class: 'shots' });
        day.shots.forEach((x, i) => {
          const idx = base + i;
          grid.append(el('figure', { tabindex: '0', onclick: function () { openLB(idx); }, onkeydown: function (e) { if (e.key === 'Enter') openLB(idx); } },
            el('img', { src: x.src, loading: 'lazy', decoding: 'async', alt: 'Screenshot at ' + x.time }),
            el('figcaption', null, el('span', null, x.time), chip(x.project))));
        });
        det.append(grid);
      }
      root.append(det);
    }
  }

  let LBI = -1;
  function openLB(i) {
    if (i < 0 || i >= VIS.length) return;
    LBI = i;
    const x = VIS[i];
    $('#lbImg').src = x.src;
    $('#lbCap').textContent = x.date + ' ' + x.time + ', ' + x.project + ', ' + x.name + ' (' + (i + 1) + '/' + VIS.length + ')';
    $('#lbOpen').href = x.src;
    $('#lb').hidden = false;
    document.body.classList.add('noscroll');
  }
  function closeLB() {
    $('#lb').hidden = true;
    $('#lbImg').removeAttribute('src');
    document.body.classList.remove('noscroll');
    LBI = -1;
  }

  function exportCsv() {
    const rows = [['date', 'start', 'end', 'duration_seconds', 'duration', 'project', 'note']];
    for (const d of filtered(false)) for (const s of d.sessions) rows.push([d.date, s.start, s.end, Math.round(s.duration), fmtDur(s.duration), s.project, s.note || '']);
    const csv = rows.map((r) => r.map((v) => '"' + String(v).replace(/"/g, '""') + '"').join(',')).join('\n');
    const a = el('a', { href: URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv' })), download: 'time-report.csv' });
    document.body.append(a); a.click(); a.remove();
  }

  function applyRange(r) {
    S.range = r;
    const t = new Date();
    if (r === 'all') { S.from = ''; S.to = ''; }
    else if (r === 'today') { S.from = S.to = iso(t); }
    else { const f = new Date(t); f.setDate(f.getDate() - (parseInt(r, 10) - 1)); S.from = iso(f); S.to = iso(t); }
    $('#from').value = S.from; $('#to').value = S.to;
    update();
  }

  function update() {
    const days = filtered(false);
    renderSummary(days);
    renderDaily(days);
    renderProjects();
    renderDays(days);
    document.querySelectorAll('#ranges button').forEach((b) => b.setAttribute('aria-pressed', b.dataset.r === S.range ? 'true' : 'false'));
  }

  // wiring
  $('#gen').textContent = 'Generated ' + D.generated;
  $('#from').min = $('#to').min = D.minDate; $('#from').max = $('#to').max = D.maxDate;
  document.querySelectorAll('#ranges button').forEach((b) => b.addEventListener('click', () => applyRange(b.dataset.r)));
  $('#from').addEventListener('input', (e) => { S.from = e.target.value; S.range = 'custom'; update(); });
  $('#to').addEventListener('input', (e) => { S.to = e.target.value; S.range = 'custom'; update(); });
  $('#q').addEventListener('input', (e) => { S.q = e.target.value; update(); });
  $('#showShots').addEventListener('change', (e) => { S.shots = e.target.checked; update(); });
  $('#order').addEventListener('change', (e) => { S.order = e.target.value; update(); });
  $('#size').addEventListener('input', (e) => document.documentElement.style.setProperty('--thumb', e.target.value + 'px'));
  $('#expand').addEventListener('click', () => document.querySelectorAll('details.day').forEach((d) => { d.open = true; }));
  $('#collapse').addEventListener('click', () => document.querySelectorAll('details.day').forEach((d) => { d.open = false; }));
  $('#btnCsv').addEventListener('click', exportCsv);
  $('#btnPrint').addEventListener('click', () => window.print());
  window.addEventListener('beforeprint', () => document.querySelectorAll('details.day').forEach((d) => { d.open = true; }));
  $('#lbPrev').addEventListener('click', () => openLB(LBI - 1));
  $('#lbNext').addEventListener('click', () => openLB(LBI + 1));
  $('#lbClose').addEventListener('click', closeLB);
  $('#lb').addEventListener('click', (e) => { if (e.target.id === 'lb') closeLB(); });
  document.addEventListener('keydown', (e) => {
    if ($('#lb').hidden) return;
    if (e.key === 'Escape') closeLB();
    else if (e.key === 'ArrowLeft') openLB(LBI - 1);
    else if (e.key === 'ArrowRight') openLB(LBI + 1);
  });

  const themes = ['auto', 'light', 'dark'];
  function setTheme(t) {
    document.documentElement.dataset.theme = t;
    $('#btnTheme').textContent = 'Theme: ' + t;
    try { localStorage.setItem('chronoshot-theme', t); } catch (e) { /* storage can be blocked */ }
  }
  let saved = 'auto';
  try { saved = localStorage.getItem('chronoshot-theme') || 'auto'; } catch (e) { /* ignore */ }
  setTheme(themes.indexOf(saved) >= 0 ? saved : 'auto');
  $('#btnTheme').addEventListener('click', () => setTheme(themes[(themes.indexOf(document.documentElement.dataset.theme) + 1) % 3]));

  update();
})();
</script>
</body>
</html>
"""


def cmd_report(args):
    ensure_dirs()
    d_from, d_to = resolve_range(args)
    out_path = Path(args.out).expanduser().resolve() if args.out else config.REPORT_FILE
    out_path.parent.mkdir(parents=True, exist_ok=True)

    data = collect_report_data(d_from, d_to, args.project, args.embed, out_path.parent)
    if not data["days"]:
        print("⚠️  No sessions or accepted screenshots found. The report will be empty.")
    payload = json.dumps(data).replace("<", "\\u003c")
    page = REPORT_TEMPLATE.replace("__TITLE__", "Time report").replace(
        "__DATA__", payload
    )
    out_path.write_text(page, encoding="utf-8")

    n_sessions = sum(len(d["sessions"]) for d in data["days"])
    n_shots = sum(len(d["shots"]) for d in data["days"])
    print(f"✅ Report generated: {out_path}")
    print(
        f"   {len(data['days'])} day(s), {n_sessions} session(s), {n_shots} screenshot(s)"
        + (f", {out_path.stat().st_size / 1e6:.1f} MB" if args.embed else "")
    )
    if not args.embed:
        print(
            "   Screenshots are linked, not copied. "
            "Use --embed for a single file you can send to someone."
        )
    if args.open:
        webbrowser.open(out_path.as_uri())
    else:
        print(f"   Open it: xdg-open {out_path}")
