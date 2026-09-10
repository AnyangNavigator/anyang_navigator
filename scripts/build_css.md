# Tailwind CSS 다시 빌드하기

`app/static/app.css`는 **템플릿에서 실제로 쓰는 클래스만 담아 미리 빌드한** Tailwind CSS입니다.
`base.html`이 이 파일을 링크합니다.

## 왜 CDN을 안 쓰나 (#60)

예전에는 `<script src="https://cdn.tailwindcss.com">`(Play CDN)을 썼습니다. 이건 브라우저가
**런타임에 CSS를 생성**하는 방식이라

- 모든 페이지 콘솔에 `cdn.tailwindcss.com should not be used in production` 경고가 뜨고
- 초기 렌더가 그만큼 늦습니다.

미리 빌드하면 경고가 사라지고, 파일도 **약 12KB**로 작습니다.

## 언제 다시 빌드해야 하나

**템플릿(`app/templates/*.html`)에 지금까지 안 쓰던 Tailwind 유틸리티 클래스를 새로 추가했을 때**입니다.
빌드된 CSS에는 그 시점에 쓰인 클래스만 들어 있어서, 새 클래스는 다시 빌드하지 않으면 **스타일이 안 먹습니다.**

> 기존 클래스만 조합해 쓰는 변경(대부분의 UI 수정)은 다시 빌드할 필요가 없습니다.

## 방법 — Node 불필요

Tailwind는 Node 없이 도는 **독립 실행 바이너리**를 배포합니다. 이 저장소의 "Node 없는 단일 파이썬 스택"
원칙을 그대로 지킬 수 있습니다.

1. 바이너리 내려받기 (**v3.x를 쓸 것** — v4는 기본 스타일이 달라 현재 UI가 틀어집니다)

   - Windows: <https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.19/tailwindcss-windows-x64.exe>
   - Linux: <https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.19/tailwindcss-linux-x64>

2. 설정과 입력 파일을 임시 폴더에 만들기

   `tw.config.js`
   ```js
   module.exports = {
     content: ["./app/templates/**/*.html"],
     theme: { extend: {} },
     plugins: [],
   };
   ```

   `tw.in.css`
   ```css
   @tailwind base;
   @tailwind components;
   @tailwind utilities;
   ```

3. 저장소 루트에서 빌드

   ```bash
   tailwindcss build -c tw.config.js -i tw.in.css -o app/static/app.css --minify
   ```

4. 브라우저에서 `/dashboard`·`/simulator`·`/about`을 열어 레이아웃이 깨지지 않았는지 눈으로 확인하고
   `app/static/app.css`를 커밋합니다.

## 주의

- 바이너리(약 40MB)는 **커밋하지 않습니다.** 빌드 결과물인 `app/static/app.css`만 커밋합니다.
- CI에 빌드 단계를 넣지 않았습니다. 마감이 가까워 파이프라인을 늘리는 것보다, 결과물을 커밋하고
  필요할 때만 다시 만드는 쪽이 안전하다고 판단했습니다.
