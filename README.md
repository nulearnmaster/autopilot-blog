# autopilot-blog

잠자는 동안 돌아가는 콘텐츠 + 애필리에이트 자동 수익 시스템.

키워드 큐에서 주제를 가져와 → AI로 리뷰 글 생성 → 쿠팡 파트너스 링크 자동 삽입 →
SEO 정적 사이트(HTML/sitemap/RSS/JSON-LD)까지 빌드하는 파이프라인.
GitHub Actions 무료 크론이 하루 4회 자동 실행합니다.

## 빠른 시작 (3분)

```bash
chmod +x run_daily.sh loop_forever.sh
./run_daily.sh          # 글 3개 생성 + 사이트 빌드 테스트
```

`docs/` 폴더에 완성된 웹사이트가 만들어집니다.

## 24시간 자동 운영 설정

1. GitHub에 이 폴더를 새 private/public 저장소로 push
2. Settings > Secrets > Actions 에 `OPENAI_API_KEY` 등록
   - 미등록 시 내장 템플릿으로 글 생성 (API 비용 0원)
3. Settings > Pages > Source: `main` 브랜치 `/docs` 선택
4. `config.toml`의 `base_url`을 실제 Pages 주소로 수정
5. 끝. 하루 4번(한국시간 아침 6시/납 12시/저녁 6시/밤 12시) 자동 발행

### 로컬에서 24시간 돌리기 (선택)

```bash
./loop_forever.sh 14400   # 4시간마다 무한 실행
```

## 수익화 체크리스트 (수익 극대화 순서)

1. **쿠팡 파트너스 가입** (partners.coupang.com) → 발급받은 트래킹 링크 형식을
   `config.toml`의 `search_url_template`에 넣으세요. 예:
   `https://link.coupang.com/a/?yourid={query}` 처럼 본인 추적 링크로 교체
2. **Google AdSense 승인** 후 client_id 입력 → 상하단 광고 자동 노출
3. **Search Console**에 sitemap.xml 제출 → 색인 속도 ↑
4. `keywords.csv`에 **고단가 키워드** 계속 추가 (보험/대출/카드 = CPC 최상,
   가전/디지털 = 전환율 최상)
5. 글이 30개+ 쌓이면 카테고리 내부링크 효과로 SEO 가중

## 파일 구조

```
config.toml            사이트·광고·LLM 설정 (여기만 고치면 됨)
keywords.csv           키워드 대기열 (priority 높은 순 자동 소진)
autopilot/generator.py 글 생성 (LLM API, 실패 시 템플릿)
autopilot/builder.py   SEO 정적 사이트 빌더
content/               생성된 원본 마크다운
docs/                  배포용 완성 사이트
.github/workflows/     하루 4회 자동 실행 크론
```

## 현실적인 기대치

- 수익은 트래픽 함수입니다: 보통 색인 후 2~3개월부터 유입 시작
- 키워드 품질이 곧 수익입니다. `keywords.csv` 관리가 핵심 운영 업무
- 쿠팡 파트너스는 반드시 "수수료 제공받습니다" 문구가 필요하며 본 시스템이 자동 삽입함
- AdSense 정책상 자동생성 콘텐츠는 가치가 있어야 함 — LLM 모드 사용 권장
