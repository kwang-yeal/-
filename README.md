# ✈️ 김포→제주 좌석 모니터

GitHub Actions로 자동 조회하고 GitHub Pages로 결과를 보여주는 무료 항공 좌석 모니터입니다.

## 설정 방법 (5분)

### 1. 이 저장소를 fork 또는 새 저장소 생성

- GitHub에서 **New repository** 클릭
- 이 파일들을 업로드

### 2. GitHub Pages 활성화

- 저장소 **Settings** → **Pages**
- **Source**: `Deploy from a branch`
- **Branch**: `main` / `/ (root)`
- **Save** 클릭
- 잠시 후 `https://[username].github.io/[repo-name]` 주소로 접속 가능

### 3. 조회 날짜 설정

저장소 **Settings** → **Variables** → **Actions** → **New repository variable**

| Variable | 값 | 설명 |
|---|---|---|
| `TARGET_DATES` | `20260501,20260502,20260503` | 조회할 날짜 (YYYYMMDD, 쉼표로 구분) |
| `ADULT_COUNT` | `1` | 성인 인원 |

> **날짜를 설정 안 하면** 오늘부터 7일치를 자동으로 조회합니다.

### 4. Actions 활성화

- 저장소 **Actions** 탭 → **"I understand my workflows, enable them"** 클릭

### 5. 첫 실행 (선택)

- **Actions** → **항공 좌석 조회** → **Run workflow** 클릭
- 수동으로 즉시 실행해서 데이터 생성 가능

---

## 구조

```
.
├── .github/
│   └── workflows/
│       └── check-flights.yml   # 스케줄러 (매 5분)
├── data/
│   └── flights.json            # 조회 결과 (자동 생성)
├── fetch_flights.py             # 항공사 API 조회 스크립트
└── index.html                   # 결과 표시 페이지
```

## 지원 항공사

| 항공사 | 방식 | 비고 |
|---|---|---|
| 진에어 | API 직접 호출 | 편명·시간·잔여석·가격 |
| 제주항공 | HTML 파싱 | 편명·시간·잔여석·가격 |
| 티웨이 | HTML 파싱 | 서버사이드 렌더링 여부에 따라 변동 |

## 알림

GitHub Pages 페이지에서 **🔔 알림 받기** 버튼을 클릭하면 브라우저 알림을 받을 수 있습니다.  
(페이지가 열려 있는 동안 30초마다 새로고침하며 새 잔여석 발견 시 알림)

## 주의사항

- GitHub Actions 무료 플랜: 월 2,000분 사용 가능
- 5분마다 1회 실행 시 월 약 420분 사용 → 여유 있음
- `data/flights.json`이 자동으로 커밋되므로 저장소 history에 기록됨
