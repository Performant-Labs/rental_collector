#!/usr/bin/env python3
"""
Step 5: Local web viewer for rental listings.
Serves rentals.json + media files at http://localhost:9090
"""

import http.server, json, os, mimetypes, webbrowser
from pathlib import Path
from urllib.parse import urlparse, unquote

BASE     = Path(__file__).parent
RENTALS  = BASE / "output" / "rentals.json"
MEDIA    = BASE / "output" / "media"
PORT     = 9090

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Todos Santos · Rental Listings</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#0d0f14;--surface:#161a23;--card:#1c2133;--border:#252d3e;
    --accent:#4f9eff;--accent2:#7c5cfc;--green:#22c55e;--amber:#f59e0b;
    --text:#e8eaf0;--muted:#6b7a99;--tag:#1e2d4a;--tag-text:#60a5fa;
    --radius:14px;--shadow:0 4px 24px rgba(0,0,0,.4);
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
  header{
    background:linear-gradient(135deg,#0d1829 0%,#101428 50%,#130d20 100%);
    border-bottom:1px solid var(--border);
    padding:24px 32px 20px;position:sticky;top:0;z-index:100;
    backdrop-filter:blur(12px);
  }
  .header-top{display:flex;align-items:center;gap:16px;margin-bottom:18px}
  .logo{font-size:22px;font-weight:700;background:linear-gradient(90deg,var(--accent),var(--accent2));
        -webkit-background-clip:text;-webkit-text-fill-color:transparent}
  .subtitle{color:var(--muted);font-size:13px;margin-top:2px}
  .stats-pill{margin-left:auto;background:var(--tag);color:var(--tag-text);
               border-radius:999px;padding:4px 14px;font-size:12px;font-weight:500}
  .controls{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
  .search-wrap{flex:1;min-width:240px;position:relative}
  .search-wrap svg{position:absolute;left:14px;top:50%;transform:translateY(-50%);
                    color:var(--muted);width:16px;height:16px}
  input[type=search]{width:100%;background:var(--card);border:1px solid var(--border);
                      color:var(--text);border-radius:10px;padding:10px 14px 10px 40px;
                      font-size:14px;outline:none;transition:.2s}
  input[type=search]::placeholder{color:var(--muted)}
  input[type=search]:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(79,158,255,.15)}
  select{background:var(--card);border:1px solid var(--border);color:var(--text);
          border-radius:10px;padding:10px 14px;font-size:14px;outline:none;cursor:pointer;
          appearance:none;-webkit-appearance:none}
  select:focus{border-color:var(--accent)}
  .sort-label{color:var(--muted);font-size:13px;white-space:nowrap}
  main{padding:28px 32px;max-width:1400px;margin:0 auto}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(380px,1fr));gap:20px}
  .no-results{text-align:center;padding:80px 20px;color:var(--muted)}
  .card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
         overflow:hidden;display:flex;flex-direction:column;
         transition:transform .18s,box-shadow .18s,border-color .18s}
  .card:hover{transform:translateY(-3px);box-shadow:var(--shadow);border-color:#324060}
  .card-header{padding:14px 16px 10px;display:flex;align-items:flex-start;gap:10px}
  .avatar{width:38px;height:38px;border-radius:50%;
           display:flex;align-items:center;justify-content:center;font-weight:700;font-size:15px;flex-shrink:0}
  .sender-info{flex:1;min-width:0}
  .sender-name{font-weight:600;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .sender-phone{font-size:11px;color:var(--muted);margin-top:1px;font-family:monospace}
  .score-badge{background:linear-gradient(135deg,var(--accent),var(--accent2));
                color:#fff;border-radius:999px;padding:2px 10px;font-size:11px;font-weight:600;
                white-space:nowrap;align-self:flex-start}
  .card-date{padding:0 16px 8px;font-size:11px;color:var(--muted)}
  .card-images{padding:0 12px 12px;display:flex;gap:8px;flex-wrap:wrap}
  .thumb{width:100px;height:100px;border-radius:8px;object-fit:cover;cursor:pointer;
          border:2px solid transparent;transition:.15s;background:var(--surface)}
  .thumb:hover{border-color:var(--accent);transform:scale(1.04)}
  .card-body{padding:0 16px 12px;font-size:14px;line-height:1.6;color:#c8cfe0;flex:1;
              white-space:pre-wrap;word-break:break-word}
  .card-body mark{background:rgba(79,158,255,.25);color:var(--accent);border-radius:3px;padding:0 2px}
  .card-tags{padding:0 16px 14px;display:flex;gap:6px;flex-wrap:wrap}
  .tag{background:var(--tag);color:var(--tag-text);border-radius:6px;
        padding:2px 8px;font-size:11px;font-weight:500}
  #lightbox{display:none;position:fixed;inset:0;background:rgba(0,0,0,.92);
             z-index:1000;align-items:center;justify-content:center;
             cursor:zoom-out;padding:20px;backdrop-filter:blur(6px)}
  #lightbox.open{display:flex}
  #lb-img{max-width:92vw;max-height:92vh;border-radius:10px;object-fit:contain;
           box-shadow:0 8px 60px rgba(0,0,0,.8)}
  #lb-close{position:absolute;top:20px;right:24px;color:#fff;font-size:32px;
             cursor:pointer;line-height:1;opacity:.7;transition:.15s}
  #lb-close:hover{opacity:1}
  ::-webkit-scrollbar{width:6px}
  ::-webkit-scrollbar-track{background:var(--bg)}
  ::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
</style>
</head>
<body>
<header>
  <div class="header-top">
    <div>
      <div class="logo">🏠 Todos Santos Rentals</div>
      <div class="subtitle">Extracted from WhatsApp group · all time</div>
    </div>
    <div class="stats-pill" id="count-pill">Loading…</div>
  </div>
  <div class="controls">
    <div class="search-wrap">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
      </svg>
      <input type="search" id="search" placeholder="Search text, sender, keywords…" autofocus>
    </div>
    <span class="sort-label">Sort:</span>
    <select id="sort">
      <option value="score">Best match</option>
      <option value="newest">Newest first</option>
      <option value="oldest">Oldest first</option>
    </select>
    <select id="year-filter">
      <option value="">All years</option>
    </select>
  </div>
</header>
<main>
  <div class="grid" id="grid"></div>
  <div class="no-results" id="no-results" style="display:none">No listings match your search.</div>
</main>
<div id="lightbox">
  <span id="lb-close">&#215;</span>
  <img id="lb-img" src="" alt="">
</div>
<script>
let ALL=[], filtered=[];
async function init(){
  const res=await fetch('/api/rentals'); ALL=await res.json(); filtered=[...ALL];
  const years=[...new Set(ALL.map(m=>m.timestamp&&m.timestamp.slice(0,4)).filter(Boolean))].sort().reverse();
  const sel=document.getElementById('year-filter');
  years.forEach(y=>{const o=document.createElement('option');o.value=y;o.text=y;sel.append(o);});
  render();
}
function avatarLetter(n){return(n||'?').trim()[0].toUpperCase();}
function avatarBg(n){
  const c=[['#4f9eff','#7c5cfc'],['#22c55e','#0ea5e9'],['#f59e0b','#ef4444'],
            ['#ec4899','#8b5cf6'],['#06b6d4','#3b82f6'],['#84cc16','#22c55e']];
  let h=0; for(const ch of(n||''))h=(h*31+ch.charCodeAt(0))&0xffff;
  const[a,b]=c[h%c.length]; return`linear-gradient(135deg,${a},${b})`;
}
function esc(s){return(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function hi(text,q){
  if(!q||!text)return esc(text||'');
  const re=new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')})`,'gi');
  return esc(text).replace(re,'<mark>$1</mark>');
}
function fmtDate(iso){
  if(!iso)return'';
  return new Date(iso).toLocaleDateString('en-US',{year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
}
function render(){
  const q=document.getElementById('search').value.trim().toLowerCase();
  const sort=document.getElementById('sort').value;
  const year=document.getElementById('year-filter').value;
  filtered=ALL.filter(m=>{
    if(year&&!(m.timestamp||'').startsWith(year))return false;
    if(!q)return true;
    const h=[m.text,m.sender_name,m.phone,...(m.rental_keywords||[])].join(' ').toLowerCase();
    return q.split(/\s+/).every(w=>h.includes(w));
  });
  if(sort==='score') filtered.sort((a,b)=>(b.rental_score||0)-(a.rental_score||0));
  if(sort==='newest') filtered.sort((a,b)=>(b.timestamp||'')>(a.timestamp||'')?1:-1);
  if(sort==='oldest') filtered.sort((a,b)=>(a.timestamp||'')>(b.timestamp||'')?1:-1);
  document.getElementById('count-pill').textContent=`${filtered.length.toLocaleString()} listings`;
  const noRes=document.getElementById('no-results');
  noRes.style.display=filtered.length===0?'block':'none';
  document.getElementById('grid').innerHTML=filtered.map(m=>{
    const letter=avatarLetter(m.sender_name);
    const bg=avatarBg(m.sender_name);
    const img=m.media_file?`<div class="card-images"><img class="thumb" src="/media/${encodeURIComponent(m.media_file)}" loading="lazy" onclick="lb('${encodeURIComponent(m.media_file)}')" onerror="this.style.display='none'"></div>`:'';
    const tags=(m.rental_keywords||[]).slice(0,6).map(k=>`<span class="tag">${esc(k)}</span>`).join('');
    return`<div class="card">
      <div class="card-header">
        <div class="avatar" style="background:${bg}">${letter}</div>
        <div class="sender-info">
          <div class="sender-name">${hi(m.sender_name||'Unknown',q)}</div>
          <div class="sender-phone">${esc(m.phone||'')}</div>
        </div>
        <div class="score-badge">&#9733; ${m.rental_score}</div>
      </div>
      <div class="card-date">${fmtDate(m.timestamp)}</div>
      ${img}
      ${m.text?`<div class="card-body">${hi(m.text,q)}</div>`:''}
      ${tags?`<div class="card-tags">${tags}</div>`:''}
    </div>`;
  }).join('');
}
function lb(f){document.getElementById('lb-img').src='/media/'+f;document.getElementById('lightbox').classList.add('open');}
document.getElementById('lightbox').addEventListener('click',()=>{document.getElementById('lightbox').classList.remove('open');});
document.getElementById('lb-close').addEventListener('click',()=>{document.getElementById('lightbox').classList.remove('open');});
document.addEventListener('keydown',e=>{if(e.key==='Escape')document.getElementById('lightbox').classList.remove('open');});
document.getElementById('search').addEventListener('input',render);
document.getElementById('sort').addEventListener('change',render);
document.getElementById('year-filter').addEventListener('change',render);
init();
</script>
</body>
</html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html"):
            data = HTML.encode()
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
        elif path == "/api/rentals":
            data = RENTALS.read_bytes()
            self.send_response(200); self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
        elif path.startswith("/media/"):
            fp = MEDIA / path[len("/media/"):]
            if fp.exists():
                mime,_ = mimetypes.guess_type(str(fp)); data = fp.read_bytes()
                self.send_response(200); self.send_header("Content-Type",mime or "application/octet-stream")
                self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
            else:
                self.send_response(404); self.end_headers()
        else:
            self.send_response(404); self.end_headers()


if __name__ == "__main__":
    if not RENTALS.exists():
        print("❌  output/rentals.json not found — run 4_find_rentals.py first")
        raise SystemExit(1)
    addr = ("127.0.0.1", PORT)
    httpd = http.server.HTTPServer(addr, Handler)
    url = f"http://localhost:{PORT}"
    print(f"✅  Serving rental viewer at {url}")
    print("   Press Ctrl+C to stop.\n")
    webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
