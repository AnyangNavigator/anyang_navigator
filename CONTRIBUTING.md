# 🤝 안양 균형발전 내비게이터 협업 매뉴얼 (CONTRIBUTING)

> 3인 팀이 Issues와 Pull Requests로 협업하기 위한 규칙입니다.
> **작업을 시작하기 전에 이 문서를 먼저 읽어주세요.**

---

## 1. 전체 개발 흐름

```
① 이슈 생성          "무엇을 할지" 정의 (기능/버그)
      ↓
② 작업 브랜치 생성    feat/xxx 또는 fix/xxx  (main에서 분기)
      ↓
③ 코드 작성 + 커밋    작은 단위로 자주 커밋
      ↓
④ PR 생성 → main     작업 브랜치를 main으로 병합 요청
      ↓
⑤ 코드 리뷰          팀원 1명 이상 승인(Approve) + CI 통과
      ↓
⑥ main 병합
```

**핵심 원칙**: 코드는 항상 `작업 브랜치 → main` 순서로만 올라갑니다. `main`에 직접 push하지 않습니다.
(3인 팀이라 `dev` 통합 브랜치는 생략했습니다. 나중에 인원이 늘거나 배포 전 통합 검증이 필요해지면 `dev`를 다시 넣을 수 있습니다.)

---

## 2. 브랜치 전략

| 브랜치 | 용도 | 병합 방향 |
|--------|------|-----------|
| `main` | 배포/제출용 안정 버전. 직접 작업 ❌ | — |
| `feat/*` | 새 기능 개발 | `feat/* → main` |
| `fix/*` | 버그 수정 | `fix/* → main` |

브랜치 이름: `<타입>/<영역>-<설명>` (예: `feat/simulator-ranking`, `fix/map-marker-color`)

| 영역 키워드 | 담당 파트 |
|---|---|
| `simulator` | 시뮬레이터 — 예산 대비 효과 다중 시나리오 순위화 (`app/simulator.py`, `app/templates/simulator.html`) |
| `map` | 지도 — 행정동 경계 GeoJSON choropleth 고도화 (`app/templates/dashboard.html`) |
| `core`/`api`/`report`/`chat` | 백엔드 코어 — 대시보드/데이터/리포트/챗봇 (`app/main.py`, `app/data.py`, `app/report.py`, `app/chatbot.py`) |

### 병합 방식 — 가장 중요한 규칙

| 상황 | 소스 브랜치가 병합 후에도 살아있나 | 병합 방식 |
|---|---|---|
| `feat/* → main` | ❌ 병합 후 삭제 | **Squash and merge** |
| **스택 PR** (base가 다른 feature 브랜치) | ✅ 위에 다른 PR이 매달려 있음 | 🚨 **Create a merge commit** |

**판단 기준: squash는 소스 브랜치를 버릴 때만.**
병합 후에도 그 브랜치를 계속 쓴다면(그 위에 다른 PR이 스택된 feature 브랜치) squash가 커밋 이력을 압축해 새 커밋 ID를 만들고, git이 원본과의 공통 조상을 못 찾아 다음 병합에서 "내용은 같은데 충돌"이 납니다.

**스택 PR**이란 PR의 base가 `main`이 아니라 다른 feature 브랜치인 경우입니다. 앞 작업이 끝나기 전에 이어서 작업할 때 생깁니다. PR 설명에 체인을 명시하고 병합 방식을 굵게 표시하세요:

```
⚠️ 스택 PR입니다: main ← feat/A (#12) ← feat/B (이 PR)
🚨 병합 시 Create a merge commit (squash 금지)
```

---

## 3. 이슈 사용법

**모든 작업은 이슈에서 시작합니다.**

- 제목: `[타입] 요약` (예: `[Feat] 예산 대비 효과 시나리오 순위화`)
- 담당자(Assignee)를 반드시 지정
- 템플릿은 `.github/ISSUE_TEMPLATE/`에 있음

---

## 4. 커밋 규칙

```
<타입>: <한 줄 요약> (#이슈번호)
```

`feat`/`fix`/`docs`/`style`/`refactor`/`test`/`chore` — 작은 단위로 자주 커밋하세요.

---

## 5. PR 규칙

- 제목: `[타입] 요약 (#이슈번호)`
- 템플릿은 `.github/PULL_REQUEST_TEMPLATE.md`가 자동으로 채워줍니다.
- 병합 후 작업 브랜치는 삭제합니다(단, 스택 PR의 base 브랜치는 위에 다른 PR이 있으면 삭제 금지).

---

## 6. 코드 리뷰 규칙

- PR이 올라오면 가능한 한 빨리(당일 목표) 확인합니다.
- **PR 설명을 그대로 믿지 말고, 실제 diff와 관련 코드를 대조해서 검증하세요.** 특히 프런트(템플릿의 JS)가 API를 호출한다면 `app/main.py`의 실제 응답 필드명·상태 코드를 확인할 것.
- 승인 기준: 이슈 요구사항 충족 / 다른 기능을 깨뜨리지 않음(로컬에서 `pytest` 통과) / 민감 정보 미포함.

---

## 7. 담당자별 작업 영역

| 영역 | 담당자 | 브랜치 접두어 | GitHub |
|------|--------|---------------|--------|
| PM & 백엔드 코어 (대시보드/데이터/리포트/챗봇) | 김규현 | `feat/core-*` | [@k2hop1213](https://github.com/k2hop1213) |
| 시뮬레이터 (예산 대비 효과 다중 시나리오 순위화) | 정준기 | `feat/simulator-*` | [@JK-hustler](https://github.com/JK-hustler) |
| 지도 (행정동 경계 GeoJSON choropleth 고도화) | 이상현 | `feat/map-*` | [@sangt633-art](https://github.com/sangt633-art) |

> 김규현(@k2hop1213)이 `main` 병합의 최종 관리자를 겸합니다.

---

## 8. 자주 하는 실수 & 주의사항

- **main에 직접 push 금지** → 반드시 PR로만
- **API 키, `.env`, 서비스 계정 키 커밋 금지** → `.gitignore`로 관리 (네이버 지도 Client ID는 도메인 화이트리스트로 보호되는 공개 키라 예외적으로 코드에 있음)
- **거대한 PR 금지** → 기능 단위로 잘게 나누기
- **오래된 브랜치로 작업 금지** → 작업 전 항상 `git pull origin main`
- **CI 체크가 비어 있는 것과 초록인 것은 다릅니다** — 비어 있으면 아무것도 검증 안 된 것

### 🔒 브랜치 보호 설정

Settings → Branches → Branch protection rules 에서 `main`에:
- ✅ Require a pull request before merging
- ✅ Require approvals (1명 이상)
- ✅ Require review from Code Owners
- ✅ Do not allow bypassing the above settings

(이미 설정 완료 — `setup-branch-protection.sh` 참고)

---

**질문이나 논의가 필요하면 Issues에 남겨주세요.**
