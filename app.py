import csv
import io
import json
import re
import threading
import time
import webbrowser
from contextlib import redirect_stdout
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from autopilot.generator import (
    ROOT,
    load_config,
    load_keywords,
    save_keywords,
    pick_keywords,
    mark_done,
    call_llm,
    insert_affiliate,
    save_article,
)
from autopilot.builder import build_site, decode_token
from autopilot.scout import scout as run_scout

KST = timezone(timedelta(hours=9))
PORT = 8321

LOCK = threading.Lock()
STATE = {
    "busy": False,
    "auto": False,
    "last_build": None,
    "generated_total": 0,
    "logs": [],
}


def log(msg):
    stamp = datetime.now(KST).strftime("%H:%M:%S")
    STATE["logs"].append(f"[{stamp}] {msg}")
    STATE["logs"] = STATE["logs"][-200:]


class LogTee(io.TextIOBase):
    def write(self, s):
        s = s.strip()
        if s:
            log(s)
        return len(s)


def run_job(kind="full", count=None):
    if STATE["busy"]:
        return False
    STATE["busy"] = True

    def worker():
        try:
            cfg = load_config()
            n = count or int(cfg["build"]["articles_per_run"])
            kw_path = ROOT / "keywords.csv"
            rows = load_keywords(kw_path)
            picks = pick_keywords(rows, n)
            if picks:
                tee = LogTee()
                for row in picks:
                    md = call_llm(cfg, row["keyword"], row["category"])
                    source = "llm"
                    if md is None:
                        from autopilot.generator import fallback_article
                        md = fallback_article(row["keyword"], row["category"])
                        source = "template"
                    md = insert_affiliate(md, cfg, row["keyword"])
                    path = save_article(cfg, md.split("\n", 1)[0], md, row["keyword"], row["category"], source)
                    mark_done(rows, row["keyword"])
                    STATE["generated_total"] += 1
                    log(f"{source} 생성: {Path(path).name}")
                save_keywords(kw_path, rows)
            else:
                log("생성할 키워드 없음")
            if kind in ("full", "build"):
                import os
                os.environ["AUTOPILOT_TRACK"] = "1"
                with redirect_stdout(LogTee()):
                    build_site()
                STATE["last_build"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            log(f"오류: {e}")
        finally:
            STATE["busy"] = False

    threading.Thread(target=worker, daemon=True).start()
    return True


def auto_loop(interval):
    log(f"24시간 자동화 시작 ({interval}초 간격)")
    while STATE["auto"]:
        if not STATE["busy"]:
            run_job("full")
            wait = 0
            while wait < interval and STATE["auto"]:
                time.sleep(2)
                wait += 2
        else:
            time.sleep(5)


def start_auto(interval):
    if STATE["auto"]:
        return
    STATE["auto"] = True
    threading.Thread(target=auto_loop, args=(interval,), daemon=True).start()


def stop_auto():
    STATE["auto"] = False
    log("24시간 자동화 정지")


def get_click_stats():
    path = ROOT / "data" / "clicks.csv"
    if not path.exists():
        return {"total": 0, "week": 0, "top": []}
    import datetime as _dt
    rows = list(csv.reader(open(path, encoding="utf-8")))[1:]
    week_ago = (_dt.datetime.now() - _dt.timedelta(days=7)).strftime("%Y-%m-%d")
    per_post = {}
    total = 0
    week = 0
    for r in rows:
        if len(r) < 2:
            continue
        total += 1
        if r[0][:10] >= week_ago:
            week += 1
        per_post[r[1]] = per_post.get(r[1], 0) + 1
    titles = {}
    from autopilot.markdown import parse_frontmatter
    for p in (ROOT / load_config()["build"]["posts_dir"]).glob("*.md"):
        meta, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
        if meta.get("slug") in per_post and meta.get("title"):
            titles[meta["slug"]] = meta["title"]
    top = sorted(per_post.items(), key=lambda x: -x[1])[:5]
    return {
        "total": total,
        "week": week,
        "top": [{"slug": s, "title": titles.get(s, s), "clicks": n} for s, n in top],
    }


def log_click(slug, target):
    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    path = data_dir / "clicks.csv"
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "post", "target"])
        w.writerow([datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"), slug, target])


def get_status():
    cfg = load_config()
    posts = list((ROOT / cfg["build"]["posts_dir"]).glob("*.md"))
    rows = load_keywords(ROOT / "keywords.csv")
    pending = sum(1 for r in rows if not r["status"].strip())
    links = 0
    for p in posts:
        text = p.read_text(encoding="utf-8")
        links += text.count("coupang.com") + text.count("link.coupang.com")
    return {
        "articles": len(posts),
        "pending_keywords": pending,
        "total_keywords": len(rows),
        "affiliate_links": links,
        "busy": STATE["busy"],
        "auto": STATE["auto"],
        "generated_total": STATE["generated_total"],
        "last_build": STATE["last_build"],
        "logs": STATE["logs"][-30:],
        "site_url": cfg["site"]["base_url"],
    }


CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".xml": "application/xml",
    ".txt": "text/plain; charset=utf-8",
    ".css": "text/css",
    ".js": "application/javascript",
    ".png": "image/png",
    ".jpg": "image/jpeg",
}

PAGE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Autopilot 블로그 대시보드</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif;background:#111318;color:#e8eaf0;line-height:1.6}
.wrap{max-width:1080px;margin:0 auto;padding:24px 16px}
header{display:flex;justify-content:space-between;align-items:center;padding:18px 22px;background:#1a1d25;border-radius:14px;margin-bottom:20px;border:1px solid #262a35}
header h1{font-size:1.25rem}.brand b{color:#ff5a52}
.badge{padding:.35rem .9rem;border-radius:20px;font-size:.8rem;font-weight:700;margin-left:.5rem}
.on{background:#123c22;color:#4ade80}.off{background:#3a2020;color:#f87171}
.work{background:#3a3417;color:#facc15}.idle{background:#22283a;color:#93b4ff}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px}
.stat{background:#1a1d25;border:1px solid #262a35;border-radius:12px;padding:14px 16px}
.stat .num{font-size:1.7rem;font-weight:800;color:#fff}
.stat .lbl{font-size:.78rem;color:#8b93a7}
.panel{background:#1a1d25;border:1px solid #262a35;border-radius:14px;padding:18px 20px;margin-bottom:20px}
.panel h2{font-size:.95rem;margin-bottom:12px;color:#aab3c8;text-transform:uppercase;letter-spacing:.05em}
button{border:none;border-radius:10px;padding:.7rem 1.3rem;font-weight:700;font-size:.92rem;cursor:pointer;color:#fff;margin-right:.5rem;margin-bottom:.5rem;transition:.15s}
button:hover{filter:brightness(1.15)}button:disabled{opacity:.4;cursor:not-allowed}
.red{background:#e5322d}.green{background:#16a34a}.gray{background:#374151}.blue{background:#2563eb}
input,select{background:#111318;border:1px solid #333a4a;color:#e8eaf0;border-radius:8px;padding:.55rem .8rem;font-size:.9rem}
table{width:100%;border-collapse:collapse;font-size:.88rem}
th{text-align:left;color:#8b93a7;font-weight:600;padding:.45rem .5rem;border-bottom:1px solid #262a35}
td{padding:.42rem .5rem;border-bottom:1px solid #20242f}
.done{color:#4ade80}.wait{color:#facc15}
pre#log{background:#0c0e13;border-radius:10px;padding:12px 14px;font-size:.78rem;max-height:220px;overflow:auto;color:#9fb3c8;white-space:pre-wrap}
iframe{width:100%;height:640px;border:none;border-radius:10px;background:#fafafa}
.row{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center;margin-bottom:10px}
a.openbtn{color:#93b4ff;font-size:.85rem;text-decoration:none}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="brand">🚀 <b>Autopilot</b> 블로그 머니 엔진</div>
  <div><span id="autoBadge" class="badge off">자동화 OFF</span><span id="busyBadge" class="badge idle">유휴</span></div>
</header>

<div class="grid">
  <div class="stat"><div class="num" id="stArticles">0</div><div class="lbl">발행된 글</div></div>
  <div class="stat"><div class="num" id="stPending">0</div><div class="lbl">대기 키워드</div></div>
  <div class="stat"><div class="num" id="stLinks">0</div><div class="lbl">삽입된 링크</div></div>
  <div class="stat"><div class="num" id="stTotal">0</div><div class="lbl">누적 생성</div></div>
  <div class="stat"><div class="num" style="font-size:1rem" id="stBuild">-</div><div class="lbl">마지막 빌드</div></div>
</div>

<div class="panel">
  <h2>컨트롤</h2>
  <button class="red" id="btnGen" onclick="act('/api/generate')">✍️ 글 생성하기</button>
  <button class="blue" id="btnBuild" onclick="act('/api/build')">🔨 사이트 빌드</button>
  <button class="green" id="btnAuto" onclick="toggleAuto()">▶️ 24시간 자동화 시작</button>
  <span style="font-size:.8rem;color:#8b93a7;margin-left:8px">간격</span>
  <select id="interval">
    <option value="3600">1시간</option>
    <option value="14400" selected>4시간</option>
    <option value="21600">6시간</option>
    <option value="43200">12시간</option>
  </select>
</div>

<div class="panel">
  <h2>키워드 큐 (priority 높은 순 자동 소진)</h2>
  <div class="row">
    <input id="kwInput" placeholder="새 키워드 입력 (예: 무선 이어폰 추천)" size="34">
    <select id="kwCat"><option>가전</option><option>디지털</option><option>주방</option><option>운동</option><option>레저</option><option>금융</option><option>육아</option><option>패션</option><option>리빙</option></select>
    <input id="kwPri" type="number" min="1" max="10" value="7" style="width:64px" title="priority">
    <button class="green" onclick="addKeyword()">추가</button>
    <button class="gray" onclick="resetDone()">완료 초기화</button>
  </div>
  <div style="max-height:260px;overflow:auto"><table id="kwTable"></table></div>
</div>

<div class="panel">
  <h2>키워드 발굴 (구글 자동완성 실시간 수집)</h2>
  <div class="row">
    <input id="scoutSeed" placeholder="씨앗 키워드 (예: 무선청소기)" size="30">
    <button class="blue" onclick="doScout()">🔎 발굴</button>
    <span id="scoutResult" style="font-size:.82rem;color:#8b93a7"></span>
  </div>
</div>

<div class="panel">
  <h2>수익 클릭 통계 (/go/ 실측) <a href="#" onclick="resetClicks();return false" style="color:#8b93a7;font-size:.75rem">초기화</a></h2>
  <div class="row" style="gap:1.5rem">
    <span>전체 <b id="ckTotal" style="font-size:1.3rem">0</b></span>
    <span>최근 7일 <b id="ckWeek" style="font-size:1.3rem">0</b></span>
  </div>
  <table id="ckTable"></table>
</div>

<div class="panel">
  <h2>로그</h2>
  <pre id="log"></pre>
</div>

<div class="panel">
  <h2>완성 사이트 미리보기 <a class="openbtn" href="/site/index.html" target="_blank">↗ 새 창에서 열기</a></h2>
  <iframe src="/site/index.html"></iframe>
</div>
</div>

<script>
async function api(url, body){
  const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body||{})});
  return r.json();
}
async function act(u){ await api(u); setTimeout(refresh, 400); }
async function toggleAuto(){
  const s = document.getElementById('interval').value;
  const st = window._status;
  if(st && st.auto){ await act('/api/auto-stop'); }
  else { await act('/api/auto-start', {interval:+s}); }
  setTimeout(refresh, 500);
}
async function addKeyword(){
  const k = document.getElementById('kwInput').value.trim();
  if(!k) return;
  await api('/api/keywords-add', {keyword:k, category:document.getElementById('kwCat').value, priority:+document.getElementById('kwPri').value});
  document.getElementById('kwInput').value='';
  refresh();
}
async function resetDone(){ await api('/api/keywords-reset'); refresh(); }
async function doScout(){
  const seed = document.getElementById('scoutSeed').value.trim();
  if(!seed) return;
  const el = document.getElementById('scoutResult');
  el.textContent = '수집중...';
  const r = await api('/api/scout', {seed});
  el.textContent = r.ok ? `${r.added}개 추가됨` : '실패';
  refresh();
}
async function resetClicks(){ await api('/api/clicks-reset'); loadClicks(); }
async function loadClicks(){
  try{
    const r = await fetch('/api/clicks');
    const d = await r.json();
    document.getElementById('ckTotal').textContent = d.total;
    document.getElementById('ckWeek').textContent = d.week;
    let html = '<tr><th>글</th><th>클릭</th></tr>';
    for(const t of d.top||[]){
      html += `<tr><td>${t.title.slice(0,40)}</td><td>${t.clicks}</td></tr>`;
    }
    document.getElementById('ckTable').innerHTML = html;
  }catch(e){}
}

function render(status){
  window._status = status;
  document.getElementById('stArticles').textContent = status.articles;
  document.getElementById('stPending').textContent = status.pending_keywords;
  document.getElementById('stLinks').textContent = status.affiliate_links;
  document.getElementById('stTotal').textContent = status.generated_total;
  document.getElementById('stBuild').textContent = status.last_build || '-';
  const ab = document.getElementById('autoBadge');
  ab.textContent = status.auto ? '자동화 ON' : '자동화 OFF';
  ab.className = 'badge ' + (status.auto ? 'on' : 'off');
  const btn = document.getElementById('btnAuto');
  btn.textContent = status.auto ? '⏹ 자동화 정지' : '▶️ 24시간 자동화 시작';
  btn.className = 'btn ' + (status.auto ? 'gray' : 'green');
  const bb = document.getElementById('busyBadge');
  bb.textContent = status.busy ? '작업중' : '유휴';
  bb.className = 'badge ' + (status.busy ? 'work' : 'idle');
  document.getElementById('btnGen').disabled = status.busy;
  document.getElementById('btnBuild').disabled = status.busy;
  document.getElementById('log').textContent = status.logs.join('\\n');
  let html = '<tr><th>키워드</th><th>카테고리</th><th>PRI</th><th>상태</th></tr>';
  for(const k of status.keywords||[]){
    html += `<tr><td>${k.keyword}</td><td>${k.category}</td><td>${k.priority}</td>`+
            `<td class="${k.status?'done':'wait'}">${k.status?'✓ '+k.status:'대기'}</td></tr>`;
  }
  document.getElementById('kwTable').innerHTML = html;
}

async function refresh(){
  try{
    const r = await fetch('/api/status');
    render(await r.json());
  }catch(e){}
}
refresh();
setInterval(refresh, 3000);
loadClicks();
setInterval(loadClicks, 10000);
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj):
        self._send(200, "application/json", json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/go/":
            qs = parse_qs(parsed.query)
            slug = (qs.get("t") or ["?"])[0]
            target = decode_token((qs.get("u") or [""])[0])
            if not target.startswith("http"):
                self.send_error(400)
                return
            log_click(slug, target)
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()
            return
        if path == "/":
            self._send(200, CONTENT_TYPES[".html"], PAGE.encode("utf-8"))
        elif path == "/api/status":
            cfg = load_config()
            data = get_status()
            data["keywords"] = load_keywords(ROOT / "keywords.csv")
            data["site_url"] = cfg["site"]["base_url"]
            self._json(data)
        elif path == "/api/clicks":
            self._json(get_click_stats())
        elif path.startswith("/site/"):
            self.serve_static(path[len("/site/"):])
        else:
            self.serve_static(path.lstrip("/"))

    def serve_static(self, rel):
        base = (ROOT / load_config()["build"]["site_dir"]).resolve()
        target = (base / rel).resolve()
        if base not in target.parents and target != base:
            self.send_error(403)
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.exists():
            if target.name == "index.html":
                self._send(200, "text/html; charset=utf-8", "<meta charset=utf-8>아직 빌드된 사이트가 없습니다".encode())
            else:
                self.send_error(404)
            return
        ctype = CONTENT_TYPES.get(target.suffix, "application/octet-stream")
        self._send(200, ctype, target.read_bytes())

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = {}
        if length:
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                body = {}
        if path == "/api/generate":
            ok = run_job("full", body.get("count"))
            self._json({"ok": ok})
        elif path == "/api/build":
            ok = run_job("build")
            self._json({"ok": ok})
        elif path == "/api/auto-start":
            start_auto(int(body.get("interval", 14400)))
            self._json({"ok": True})
        elif path == "/api/auto-stop":
            stop_auto()
            self._json({"ok": True})
        elif path == "/api/keywords-add":
            kw_path = ROOT / "keywords.csv"
            rows = load_keywords(kw_path)
            new_kw = str(body.get("keyword", "")).strip()
            if not new_kw:
                self._json({"ok": False, "error": "empty"})
                return
            if any(r["keyword"] == new_kw for r in rows):
                log(f"키워드 추가 실패(중복): {new_kw}")
                self._json({"ok": False, "error": "duplicate"})
                return
            rows.append({
                "keyword": new_kw,
                "category": str(body.get("category", "리빙")),
                "priority": str(int(body.get("priority", 7))),
                "status": "",
            })
            save_keywords(kw_path, rows)
            log(f"키워드 추가: {body.get('keyword')}")
            self._json({"ok": True})
        elif path == "/api/keywords-reset":
            kw_path = ROOT / "keywords.csv"
            rows = load_keywords(kw_path)
            for r in rows:
                r["status"] = ""
            save_keywords(kw_path, rows)
            log("모든 키워드 상태 초기화")
            self._json({"ok": True})
        elif path == "/api/scout":
            seed = str(body.get("seed", "")).strip()
            if not seed:
                self._json({"ok": False, "error": "empty"})
                return
            cfg = load_config()
            result = run_scout(seed, int(cfg.get("scout", {}).get("max_add", 10)))
            log(f"키워드 발굴 '{seed}': {result['added']}개 추가")
            self._json({"ok": True, **result})
        elif path == "/api/clicks-reset":
            (ROOT / "data" / "clicks.csv").unlink(missing_ok=True)
            log("클릭 통계 초기화")
            self._json({"ok": True})
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Autopilot 대시보드: http://localhost:{PORT}")
    webbrowser.open(f"http://localhost:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
