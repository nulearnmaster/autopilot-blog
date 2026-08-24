import csv
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import tomllib

from . import llmauth

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))
CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"

PROMPT = """당신은 한국 최고의 리뷰 블로거입니다. 키워드 "{keyword}" (카테고리: {category})로
구매 전환율이 높은 블로그 글을 마크다운으로 작성하세요.

규칙:
- 첫 줄은 "# " 로 시작하는 제목 하나만, 본문은 ## 과 ### 소제목 사용
- 추천 제품마다 반드시 "### 1. 제품명" 형식의 소제목으로 시작 (3~5개)
- 각 제품 아래 특징/장단점/이런 분께 추천 을 "- " 리스트로 작성
- 표(table)와 일반 링크는 절대 사용 금지 (광고 링크는 시스템이 자동 삽입함)
- 구매 가이드 섹션과 FAQ(질문-답변 3개) 포함
- 자연스러운 한국어, 실사용자 어조, 1500자 이상
- 마크다운 코드펜스 없이 순수 마크다운만 출력"""


def load_config():
    with open(ROOT / "config.toml", "rb") as f:
        return tomllib.load(f)


def load_keywords(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_keywords(path, rows):
    fieldnames = ["keyword", "category", "priority", "status"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def pick_keywords(rows, n):
    pending = [r for r in rows if not r["status"].strip()]
    pending.sort(key=lambda r: -int(r["priority"]))
    return pending[:n]


def mark_done(rows, keyword):
    for r in rows:
        if r["keyword"] == keyword:
            r["status"] = datetime.now(KST).strftime("%Y-%m-%d")


def slug_for(keyword):
    digest = hashlib.md5(keyword.encode("utf-8")).hexdigest()[:10]
    return f"{datetime.now(KST):%Y%m%d}-{digest}"


def _extract_text(data, deltas=""):
    parts = []
    for item in data.get("output") or []:
        for c in item.get("content") or []:
            if c.get("type") in ("output_text", "text"):
                parts.append(c.get("text", ""))
    text = "\n".join(p for p in parts if p).strip()
    if not text and deltas:
        return deltas.strip()
    if not text:
        try:
            return data["choices"][0]["message"]["content"].strip()
        except Exception:
            return ""
    return text


def _parse_body(raw):
    raw = raw.strip()
    if raw.startswith("{"):
        try:
            return json.loads(raw), ""
        except Exception:
            return {}, ""
    data = {}
    deltas = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if not chunk or chunk == "[DONE]":
            continue
        try:
            j = json.loads(chunk)
        except Exception:
            continue
        t = j.get("type", "")
        if t == "response.output_text.delta":
            deltas.append(j.get("delta", ""))
        elif t == "response.completed" and isinstance(j.get("response"), dict):
            data = j["response"]
        elif j.get("output"):
            data = j
    return data, "".join(deltas)


def _via_codex(prompt, llm):
    token, account = llmauth.codex_tokens()
    if not token:
        return None
    payload = json.dumps({
        "model": llm.get("codex_model") or llmauth.get_codex_model(),
        "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        "store": False,
        "stream": True,
    }).encode("utf-8")
    req = urllib.request.Request(
        CODEX_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "chatgpt-account-id": account,
            "User-Agent": "codex_cli_rs",
            "Accept": "text/event-stream",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data, deltas = _parse_body(resp.read().decode("utf-8", "ignore"))
            return _extract_text(data, deltas)
    except urllib.error.HTTPError as e:
        print(f"codex 백엔드 HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:200]}")
        return None
    except Exception as e:
        print(f"codex 백엔드 오류: {e}")
        return None


def call_llm(cfg, keyword, category):
    llm = cfg["llm"]
    prompt = PROMPT.format(keyword=keyword, category=category)
    mode = llmauth.get_mode()
    text = None
    if mode == "codex":
        text = _via_codex(prompt, llm)
        source = "llm"
    elif mode == "api_key":
        api_key = llmauth.api_key()
        payload = json.dumps({
            "model": llm["model"],
            "temperature": llm["temperature"],
            "max_tokens": llm["max_tokens"],
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{llm['api_base'].rstrip('/')}/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            text = body["choices"][0]["message"]["content"].strip()
        except Exception:
            text = None
        source = "llm"
    else:
        return None
    if not text:
        return None
    text = re.sub(r"^```(?:markdown)?\s*|\s*```$", "", text.strip())
    return text if text.startswith("# ") else None


def fallback_article(keyword, category):
    today = datetime.now(KST).strftime("%Y년 %m월 %d일")
    base = re.sub(r"\s*추천\s*$", "", keyword)
    products = [f"{base} 인기 A형", f"{base} 가성비 B형", f"{base} 프리미엄 C형", f"{base} 신상 D형"]
    lines = [
        f"# {today} 기준 {keyword} 베스트 4 총정리",
        "",
        f"최근 {base} 검색량이 꾸준히 늘고 있습니다. 저도 직접 사용해 보고 후기들을 비교해 가면서 정리한 결과를 공유합니다. 오늘은 {category} 카테고리에서 가장 많이 팔리는 제품 위주로 골라봤습니다.",
        "",
        f"## {keyword} 고르기 전 확인할 것",
        "",
        f"- 예산: 가격대별로 성격이 확실히 다릅니다",
        "- 용도: 어디에 얼마나 자주 쓸지 먼저 정하세요",
        "- 유지비: 소모품과 A/S 정책도 함께 확인하세요",
        "",
    ]
    for i, name in enumerate(products, 1):
        lines += [
            f"### {i}. {name}",
            "",
            f"- 특징: {base} 중에서도 균형이 좋은 선택지입니다",
            f"- 장점: 초기 진입 장벽이 낮고 만족도 후기가 꾸준합니다",
            f"- 단점: 대량 사용 시에는 상위 모델 대비 성능 여유가 부족할 수 있습니다",
            f"- 이런 분께 추천: 처음 구매를 고민하는 분",
            "",
        ]
    lines += [
        f"## {keyword} 구매 가이드",
        "",
        "- 스펙만 보지 말고 실사용 후기를 함께 확인하세요",
        "- 시즌 세일 기간을 노리면 같은 제품을 더 저렴하게 살 수 있습니다",
        "- 배송/반품 조건을 미리 확인하면 실패 확률이 크게 줄어듭니다",
        "",
        "## FAQ",
        "",
        f"### Q. 평균적으로 얼마나 쓸 수 있나요?",
        "평균적인 사용 빈도 기준 2~5년 사용 사례가 많습니다.",
        "",
        f"### Q. 처음 산다면 어떤 걸 사야 하나요?",
        "검증된 인기 모델이나 가성비 모델부터 시작하는 것을 권합니다.",
        "",
        f"### Q. 오프라인에서 사는 게 나은가요?",
        "온라인 최저가와 비교해 10% 이상 차이가 없다면 편한 온라인 구매가 좋습니다.",
        "",
        f"오늘 정리한 {base} 정보가 구매 결정에 도움이 되셨길 바랍니다.",
    ]
    return "\n".join(lines)


PRODUCT_HEADING = re.compile(r"^(#{2,4}\s*\d+\.\s*)(.+?)\s*$", re.MULTILINE)
GENERIC_WORDS = {"추천", "베스트", "가격", "비교", "순위", "할인"}


def insert_affiliate(md_text, cfg, keyword):
    aff = cfg["affiliate"]
    if not aff.get("enabled"):
        return md_text
    template = aff["search_url_template"]
    cta_text = aff["cta_text"]

    def make_link(query):
        url = template.format(query=urllib.parse.quote_plus(query))
        label = cta_text.format(product=query)
        return f"> 🔗 **[{label}]({url})**"

    count = 0

    def repl(m):
        nonlocal count
        product = m.group(2).strip()
        block = m.group(0) + "\n\n"
        if count < int(aff["max_links_per_article"]):
            base = " ".join(w for w in keyword.split() if w not in GENERIC_WORDS)
            query = product if base and base in product else f"{keyword} {product}".strip()
            block += make_link(query) + "\n"
            count += 1
        return block

    md_text = PRODUCT_HEADING.sub(repl, md_text)
    disclosure = f"> ⚠️ {aff['partner_note']}"
    lines = md_text.split("\n")
    insert_at = next((i for i, l in enumerate(lines) if l.startswith("# ")), -1) + 1
    while insert_at < len(lines) and not lines[insert_at].strip():
        insert_at += 1
    lines.insert(insert_at, "\n" + disclosure + "\n")
    return "\n".join(lines)


def save_article(cfg, title_md, body_md, keyword, category, source="template"):
    posts_dir = ROOT / cfg["build"]["posts_dir"]
    posts_dir.mkdir(exist_ok=True)
    slug = slug_for(keyword)
    date = datetime.now(KST).strftime("%Y-%m-%d")
    title = title_md.lstrip("# ").strip()
    frontmatter = (
        "---\n"
        f"title: {title}\n"
        f"date: {date}\n"
        f"category: {category}\n"
        f"keyword: {keyword}\n"
        f"slug: {slug}\n"
        f"source: {source}\n"
        "---\n"
    )
    path = posts_dir / f"{slug}.md"
    path.write_text(frontmatter + body_md.strip() + "\n", encoding="utf-8")
    return path


def generate_one(cfg, row):
    keyword, category = row["keyword"], row["category"]
    md = call_llm(cfg, keyword, category)
    source = "llm"
    if md is None:
        md = fallback_article(keyword, category)
        source = "template"
    md = insert_affiliate(md, cfg, keyword)
    path = save_article(cfg, md.split("\n", 1)[0], md, keyword, category, source)
    return {"path": str(path), "source": source, "keyword": keyword}


def run():
    cfg = load_config()
    kw_path = ROOT / "keywords.csv"
    rows = load_keywords(kw_path)
    picks = pick_keywords(rows, int(cfg["build"]["articles_per_run"]))
    if not picks:
        print("생성할 키워드가 없습니다. keywords.csv 에 새 키워드를 추가하세요.")
        return []
    results = []
    for row in picks:
        result = generate_one(cfg, row)
        mark_done(rows, row["keyword"])
        results.append(result)
        print(f"[{result['source']}] {result['path']}")
    save_keywords(kw_path, rows)
    return results


if __name__ == "__main__":
    run()
