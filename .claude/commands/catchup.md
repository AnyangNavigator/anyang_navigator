---
description: 최신 main을 pull하고 내 담당 이슈·리뷰 요청을 파악해 가장 급한 일부터 처리
---

너는 이 저장소(AnyangNavigator/anyang_navigator)의 팀원 **$ARGUMENTS** (GitHub 아이디)로 작업한다.
`$ARGUMENTS`가 비어 있으면 실행 전에 어떤 GitHub 아이디로 작업할지 먼저 물어봐라.

다음 순서로 진행해라:

1. `git checkout main && git pull origin main` 으로 최신화하고, `README.md`·`CONTRIBUTING.md`를 훑어 이번 라운드에 바뀐 게 있는지 확인해라.
2. `gh pr list --search "review-requested:$ARGUMENTS"` 으로 내게 온 리뷰 요청을 확인해라.
3. `gh issue list --assignee $ARGUMENTS --state open` 으로 내게 할당된 이슈를 확인해라.
4. **리뷰 요청이 있으면 먼저 처리한다.** PR 설명을 그대로 믿지 말고:
   - 실제 diff를 읽어라 (`gh pr diff <번호>`)
   - 프런트(템플릿의 JS)가 API를 호출한다면, `app/main.py`의 실제 응답 필드명·상태 코드를 직접 열어 대조해라
   - 로컬에서 `pytest`를 돌려 확인해라
   - `gh pr checks <번호>`로 CI 상태를 확인해라
   - 리뷰는 body(JSON 파일)를 만들어 `gh api repos/AnyangNavigator/anyang_navigator/pulls/<번호>/reviews -X POST --input <file>`로 게시해라 (APPROVE/REQUEST_CHANGES/COMMENT)
5. 리뷰가 없거나 끝났으면, 할당된 이슈 중 **가장 먼저 해야 할 것 하나**를 골라 착수해라.
   - 다른 사람과 같이 할당된 이슈라면, 착수 전에 이슈에 "지금 착수합니다" 코멘트를 남겨 중복 작업을 줄여라.
   - 작업 브랜치는 `main`에서 분기하고, 이미 진행 중인 다른 PR에 의존한다면 그 브랜치 위에 스택해라 — 이 경우 PR 설명에 스택 체인과 "Create a merge commit" 경고를 반드시 넣어라.
   - 로컬 `pytest` 통과를 확인한 뒤 커밋·푸시·PR을 생성해라.
6. 리뷰어가 변경을 요청했다면(CHANGES_REQUESTED), 지적을 코드로 직접 재현/검증한 뒤 고치고, 무엇을 어떻게 고쳤는지 코멘트로 남겨라.
7. 마지막에: 이번 라운드에 한 일(리뷰 게시, PR 생성, 발견한 문제)을 한국어로 간결히 요약해서 알려줘. 아무것도 새로 할 게 없으면 "새로 할 일 없음"이라고 짧게 말해라 — 매번 장황하게 설명하지 마라.
