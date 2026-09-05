#!/usr/bin/env bash
# main 브랜치 보호 규칙을 gh CLI로 한 번에 설정.
# 사용법: `bash setup-branch-protection.sh` 실행.
# (저장소 관리자 권한 필요, gh auth login 되어 있어야 함)

set -euo pipefail

REPO="AnyangNavigator/anyang_navigator"
BRANCHES=("main")
REQUIRED_APPROVALS=1

PAYLOAD_FILE="$(mktemp)"
trap 'rm -f "$PAYLOAD_FILE"' EXIT

cat > "$PAYLOAD_FILE" <<EOF
{
  "required_status_checks": null,
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": ${REQUIRED_APPROVALS},
    "require_code_owner_reviews": true
  },
  "restrictions": null
}
EOF

for BRANCH in "${BRANCHES[@]}"; do
  echo "Setting protection on $REPO:$BRANCH ..."
  # -f/-F는 null을 표현할 수 없어서(문자열 "null"이 되어버림) JSON 파일을 --input으로 넘긴다.
  gh api \
    --method PUT \
    -H "Accept: application/vnd.github+json" \
    "repos/${REPO}/branches/${BRANCH}/protection" \
    --input "$PAYLOAD_FILE"
  echo "  done."
done

echo
echo "완료. GitHub 웹 UI(Settings → Branches)에서 결과를 확인하세요."
echo "CI가 초록으로 몇 번 돈 뒤에는 Settings → Branches → 해당 룰 편집에서"
echo "'Require status checks to pass before merging' → 'backend' 잡도 추가로 켜는 걸 권장합니다."
