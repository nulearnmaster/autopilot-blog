import base64
import html
import json
import re
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .generator import load_config, ROOT
from .markdown import to_html, parse_frontmatter

KST = timezone(timedelta(hours=9))

CSS = """
:root{--accent:#e5322d;--bg:#fafafa;--card:#fff;--text:#222}
*{box-sizing:border-box}body{margin:0;font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif;background:var(--bg);color:var(--text);line-height:1.8}
a{color:var(--accent)}header.site{background:var(--accent);color:#fff;padding:1.2rem 1rem;text-align:center}
header.site a{color:#fff;text-decoration:none;font-size:1.4rem;font-weight:700}
main{max-width:720px;margin:0 auto;padding:1.5rem 1rem}
.post-card{background:var(--card);border-radius:10px;padding:1.2rem 1.4rem;margin-bottom:1rem;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.post-card h2{margin:.2rem 0;font-size:1.15rem}.post-card h2 a{text-decoration:none;color:var(--text)}
.meta{color:#888;font-size:.85rem;margin-bottom:.5rem}
blockquote{background:#fff6d5;border-left:4px solid #f0b400;margin:1.2rem 0;padding:.7rem 1rem;border-radius:0 8px 8px 0}
blockquote a{display:inline-block;background:var(--accent);color:#fff;padding:.45rem 1.1rem;border-radius:24px;text-decoration:none;font-weight:600;margin-top:.3rem}
h1{font-size:1.5rem}footer{text-align:center;color:#999;font-size:.8rem;padding:2rem 0}
.ad-slot{margin:1.5rem 0;min-height:90px}
"""


def esc(s):
    return html.escape(str(s), quote=True)


def strip_tags(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def track_links(body_html, slug):
    def repl(m):
        url = html.unescape(m.group(1))
        if "coupang.com" not in url:
            return m.group(0)
        token = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
        return f'href="/go/?t={slug}&u={token}"'
    return re.sub(r'href="(https://[^"]*coupang\.com[^"]*)"', repl, body_html)


def decode_token(token):
    token += "=" * (-len(token) % 4)
    try:
        return base64.urlsafe_b64decode(token.encode()).decode()
    except Exception:
        return ""


def adsense_block(cfg, slot_key):
    client = cfg["adsense"].get("client_id", "")
    if not client:
        return ""
    return f'<ins class="adsbygoogle" style="display:block" data-ad-client="{esc(client)}" data-ad-slot="{esc(cfg["adsense"].get(slot_key, ""))}" data-ad-format="auto" data-full-width-responsive="true"></ins>'


def render_post_page(cfg, meta, body_html, related_html=""):
    url = f"{cfg['site']['base_url'].rstrip('/')}/posts/{meta['slug']}.html"
    title = meta["title"]
    description = esc(strip_tags(body_html)[:147] + "...")
    noindex = '<meta name="robots" content="noindex,follow">' if meta.get("source", "template") == "template" else ""
    schema = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": title,
        "datePublished": meta["date"],
        "author": {"@type": "Organization", "name": cfg["site"]["author"]},
        "url": url,
        "inLanguage": cfg["site"]["lang"],
    }
    adsense_script = ""
    if cfg["adsense"].get("client_id"):
        adsense_script = (
            '<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client='
            + esc(cfg["adsense"]["client_id"]) + '" crossorigin="anonymous"></script>'
            '<script>(adsbygoogle=window.adsbygoogle||[]).push({});(adsbygoogle=window.adsbygoogle||[]).push({});</script>'
        )
    return f"""<!DOCTYPE html>
<html lang="{cfg['site']['lang']}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{noindex}
<title>{esc(title)} | {esc(cfg['site']['title'])}</title>
<meta name="description" content="{description}">
<meta property="og:type" content="article">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="{esc(url)}">
<link rel="alternate" type="application/rss+xml" href="/rss.xml" title="RSS">
<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False)}</script>
<style>{CSS}</style>
{adsense_script}
</head>
<body>
<header class="site"><a href="/index.html">{esc(cfg['site']['title'])}</a></header>
<main>
<article>
<div class="meta">{esc(meta['date'])} · {esc(meta['category'])}</div>
<h1>{esc(title)}</h1>
{adsense_block(cfg, 'slot_top')}
{body_html}
{adsense_block(cfg, 'slot_bottom')}
</article>
<section><h2>함께 보면 좋은 글</h2>{related_html}</section>
</main>
<footer>© {datetime.now(KST):%Y} {esc(cfg['site']['title'])}</footer>
</body>
</html>"""


def post_card(meta):
    return (f'<div class="post-card"><div class="meta">{esc(meta["date"])} · {esc(meta["category"])}</div>'
            f'<h2><a href="/posts/{esc(meta["slug"])}.html">{esc(meta["title"])}</a></h2></div>')


def build_site():
    cfg = load_config()
    posts_dir = ROOT / cfg["build"]["posts_dir"]
    site_dir = ROOT / cfg["build"]["site_dir"]
    posts = []
    for md_path in sorted(posts_dir.glob("*.md")):
        text = md_path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        meta, body = parse_frontmatter(text)
        if not all(k in meta for k in ("title", "date", "slug")):
            continue
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", meta["date"]):
            continue
        posts.append((meta, to_html(body)))
    posts.sort(key=lambda p: p[0]["date"], reverse=True)

    (site_dir / "posts").mkdir(parents=True, exist_ok=True)
    base = cfg["site"]["base_url"].rstrip("/")

    for idx, (meta, raw_html) in enumerate(posts):
        body_html = re.sub(r"^\s*<h1>.*?</h1>", "", raw_html, count=1)
        body_html = track_links(body_html, meta["slug"])
        same_cat = [posts[j] for j in range(len(posts))
                    if j != idx and posts[j][0].get("category") == meta.get("category")]
        rest = [posts[j] for j in range(len(posts)) if j != idx and posts[j] not in same_cat]
        pool = (same_cat + rest)[:3]
        related = "".join(post_card(m) for m, _ in pool)
        page = render_post_page(cfg, meta, body_html, related)
        (site_dir / "posts" / f"{meta['slug']}.html").write_text(page, encoding="utf-8")

    cards = "".join(post_card(m) for m, _ in posts) or "<p>아직 글이 없습니다.</p>"
    index_page = f"""<!DOCTYPE html>
<html lang="{cfg['site']['lang']}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(cfg['site']['title'])}</title>
<meta name="description" content="{esc(cfg['site']['description'])}">
<link rel="alternate" type="application/rss+xml" href="/rss.xml" title="RSS">
<style>{CSS}</style>
</head>
<body>
<header class="site"><a href="/index.html">{esc(cfg['site']['title'])}</a></header>
<main>
<p>{esc(cfg['site']['description'])}</p>
{adsense_block(cfg, 'slot_top')}
{cards}
</main>
<footer>© {datetime.now(KST):%Y} {esc(cfg['site']['title'])}</footer>
</body>
</html>"""
    (site_dir / "index.html").write_text(index_page, encoding="utf-8")

    urls = [f"{base}/"] + [f"{base}/posts/{m['slug']}.html" for m, _ in posts]
    today = datetime.now(KST).strftime("%Y-%m-%d")
    sitemap_items = "\n".join(
        f"<url><loc>{esc(u)}</loc><lastmod>{today}</lastmod><changefreq>daily</changefreq></url>"
        for u in urls
    )
    (site_dir / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{sitemap_items}\n</urlset>',
        encoding="utf-8",
    )
    (site_dir / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n", encoding="utf-8"
    )

    rss_items = "\n".join(
        f"<item><title>{esc(m['title'])}</title><link>{base}/posts/{esc(m['slug'])}.html</link>"
        f"<pubDate>{datetime.strptime(m['date'], '%Y-%m-%d').strftime('%a, %d %b %Y 09:00:00 +0900')}</pubDate></item>"
        for m, _ in posts[:20]
    )
    (site_dir / "rss.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
        f"<title>{esc(cfg['site']['title'])}</title><link>{base}/</link>"
        f"<description>{esc(cfg['site']['description'])}</description>{rss_items}</channel></rss>",
        encoding="utf-8",
    )

    key = (cfg.get("indexnow") or {}).get("key", "")
    if key:
        (site_dir / f"{key}.txt").write_text(key, encoding="utf-8")
        host = urllib.parse.urlparse(base).netloc
        payload = json.dumps({
            "host": host,
            "key": key,
            "keyLocation": f"{base}/{key}.txt",
            "urlList": urls[:30],
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.indexnow.org/indexnow",
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                print(f"IndexNow 제출: HTTP {resp.status} ({len(urls[:30])} URLs)")
        except Exception as e:
            print(f"IndexNow 실패: {e}")

    print(f"빌드 완료: {len(posts)}개 글 -> {site_dir}")


if __name__ == "__main__":
    build_site()
