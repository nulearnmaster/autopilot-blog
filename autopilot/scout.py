import csv
import json
import re
import urllib.parse
import urllib.request

from .generator import ROOT, load_keywords, save_keywords

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

INTENT_WEIGHTS = {
    "추천": 3, "최저가": 3, "비교": 2, "가격": 2, "후기": 2,
    "장단점": 2, "할인": 2, "순위": 1, "브랜드": 1,
}

NOISE_WORDS = (
    "클리앙", "더쿠", "펨코", "디씨", "디시", "뽐뿌", "인벤",
    "쿨엔", "오르비", "테라", "웹소설", "유튜브", "reddit",
)

CATEGORY_MAP = [
    (("청소기", "에어컨", "공기청정", "가습", "제습", "세탁", "냉장고", "TV"), "가전"),
    (("노트북", "폰", "이어폰", "아이패드", "태블릿", "시계", "모니터", "키보드", "마우스"), "디지털"),
    (("에어프라이어", "머신", "냄비", "프라이팬", "블렌더", "포트"), "주방"),
    (("홈트", "프로틴", "요가", "덤벨", "러닝", "운동"), "운동"),
    (("캠핑", "등산", "낚시", "텐트"), "레저"),
    (("카드", "대출", "보험", "적금", "투자", "재테크", "연금", "환전"), "금융"),
    (("젖병", "유모차", "아기", "육아", "매트"), "육아"),
    (("옷", "신발", "잡화", "장갑", "모자", "백팩", "코트"), "패션"),
    (("의자", "책상", "침구", "조명", "커튼", "수납"), "리빙"),
]


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read()
    try:
        return json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return json.loads(raw.decode("euc-kr"))


def google_suggest(seed):
    url = (
        "https://suggestqueries.google.com/complete/search?client=firefox&hl=ko"
        f"&ie=UTF-8&oe=UTF-8&q={urllib.parse.quote_plus(seed)}"
    )
    try:
        data = _fetch(url)
        return [s for s in data[1] if isinstance(s, str)]
    except Exception:
        return []


def naver_suggest(seed):
    url = (
        "https://ac.search.naver.com/nx/ac?q=" + urllib.parse.quote_plus(seed)
        + "&con=0&frm=nv&ans=2&r_format=json&r_enc=UTF-8"
    )
    try:
        data = _fetch(url)
        items = data.get("items") or []
        flat = []
        for group in items:
            for entry in group:
                if isinstance(entry, str):
                    flat.append(re.sub(r"<[^>]+>", "", entry))
                elif isinstance(entry, list) and entry:
                    flat.append(str(entry[0]))
        return list(dict.fromkeys(flat))
    except Exception:
        return []


def guess_category(keyword):
    low = keyword.lower()
    for words, cat in CATEGORY_MAP:
        if any(w in keyword or w in low for w in words):
            return cat
    return "리빙"


def intent_score(keyword):
    return max((w for m, w in INTENT_WEIGHTS.items() if m in keyword), default=0)


def scout(seed, max_add=10):
    seeds = [seed] + [f"{seed} {m}" for m in ("추천", "비교")]
    found = {}
    for s in seeds:
        for kw in google_suggest(s) + naver_suggest(s):
            kw = kw.strip()
            if any(n in kw.lower() for n in NOISE_WORDS):
                continue
            if 4 < len(kw) < 40 and seed.rstrip("추천 비교").split()[0] in kw.replace(" ", ""):
                found[kw] = max(found.get(kw, 0), intent_score(kw))
    kw_path = ROOT / "keywords.csv"
    rows = load_keywords(kw_path)
    existing = {r["keyword"] for r in rows}
    candidates = [(k, v) for k, v in found.items() if k not in existing]
    candidates.sort(key=lambda x: -x[1])
    added = 0
    today = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    for kw, score in candidates[:max_add]:
        rows.append({
            "keyword": kw,
            "category": guess_category(kw),
            "priority": str(max(score, 1)),
            "status": "",
        })
        added += 1
    save_keywords(kw_path, rows)
    return {"added": added, "candidates": [k for k, _ in candidates[:max_add]]}


if __name__ == "__main__":
    import sys
    result = scout(sys.argv[1] if len(sys.argv) > 1 else "공기청정기")
    print(json.dumps(result, ensure_ascii=False, indent=2))
