# 태스크 ID 접두어 (사람별)

**Last updated:** 2026-08-25
**Status:** 현행

여러 사람이 같은 `kanban.json` 을 각자 로컬에서 편집하면 **같은 번호가 서로 다른 태스크에 붙는다.** 접두어를 쓰면 구조적으로 겹치지 않는다.

---

## 왜 필요한가 — 조용히 실패하기 때문

ID 는 각자 로컬 파일의 `next_id` 로 발급된다. 두 사람이 동시에 태스크를 만들면 둘 다 같은 번호를 받는다.

**파일 충돌보다 나쁘다.** git 충돌은 멈춰 세워서 사람이 알아채지만, 두 태스크가 파일의 서로 다른 위치에 있으면 **git 이 조용히 둘 다 머지**한다. 대시보드는 같은 번호 중 하나만 보여주고, 나머지는 에러 없이 사라진다.

2026-08-25 codebook_vibe 에서 실제로 두 번 겹쳤고, 한 번은 머지 해소 과정에서 태스크 한 건이 유실될 뻔했다.

## 설정

`~/.claude/skills/vibe-harness/sync.json` 에 한 줄:

```json
{
  "machine": "mac-studio",
  "id_prefix": "hg"
}
```

설정 후 서버를 재시작하면 `hg431`, `hg432` … 형태로 발급된다.

### 접두어 정하기

**GitHub 사용자명 기반**을 권한다 — 유일성이 이미 보장되고, 이니셜은 동명이인·표기 차이로 겹칠 수 있다.

| 사람 | GitHub | 접두어 |
|---|---|---|
| 호건 | `hoarchi` | `hg` |
| 아름 | `areumjj` | `ar` |
| 지나 | `jina4066` | `ji` |

자동 추론하지 않고 **명시적으로 적는다.** 추론은 겹쳤을 때 조용히 틀리기 때문이다.

## 동작

| 상황 | 발급 |
|---|---|
| `id_prefix` 없음 | `431` (정수) — **기존과 완전히 동일** |
| `id_prefix: "hg"` | `"hg431"` (문자열) |

- **기존 정수 ID 는 변환하지 않는다.** 20 개 프로젝트에 950여 건이 있고, 커밋 메시지·PR 제목·문서에서 `#427` 로 참조된다. 섞여 있어도 동작한다.
- `next_id` 계산은 **정수 ID 만** 본다. 문자열이 섞여도 깨지지 않는다.
- URL 라우팅(`/api/{project}/tasks/{id}`)은 숫자면 정수, 아니면 문자열로 파싱한다.

## 함께 고친 것 — `next_id` 뒤처짐

`kanban.json` 을 손으로 편집하면(머지 해소 등) `next_id` 가 실제 최대값보다 뒤처져 **다음 발급이 기존 번호와 겹친다.** 실제로 `next_id=429` 인데 최대가 430 인 상태가 만들어졌다.

이제 발급 직전에 항상 실측 최대값과 맞춘다. 손으로 고쳐도 중복이 나지 않는다.

## 적용

각 머신에서:

```bash
cd <vibe-engineering 경로> && git pull
python3 scripts/setup.py          # ~/.claude/skills/vibe-harness/ 로 복사
# sync.json 에 id_prefix 추가 후
lsof -ti:4242 | xargs kill; python3 ~/.claude/skills/vibe-harness/server.py serve 4242 &
```

확인:
```bash
curl -s -X POST localhost:4242/api/<project>/tasks \
  -H 'Content-Type: application/json' -d '{"title":"확인","status":"todo"}'
# → {"id": "hg431", ...}
```
