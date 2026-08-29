#!/usr/bin/env python3
"""kanban.json 을 서버 없이 안전하게 고친다.

## 왜 필요한가

규약은 **에이전트가 kanban.json 을 직접 편집하는 것**을 기본 경로로 정한다. 서버는
편의 래퍼일 뿐이고 꺼져 있어도 정상이다. 그런데 그 기본 경로가 서버 경로보다 약했다.

- 서버 쓰기는 tmp + fsync + `os.replace` 로 원자적이다. 직접 편집은 truncate-then-write 라
  **읽는 쪽이 반쪽짜리 파일을 본다.** 실측 중 109,409B 로 파싱 실패했다가 곧 정상이 된
  적이 있다 — 손상이 아니라 부분 읽기였다.
- 원자성만으로는 부족하다. 두 에이전트가 각자 읽고 각자 쓰면 **나중에 쓴 쪽이 앞의 것을
  덮는다.** 같은 `next_id` 를 둘 다 집어 id 가 겹친다. impactbook 의 409·410 이 그 결과였고,
  git 은 파일의 다른 위치에 있는 두 태스크를 조용히 둘 다 머지한다.

그래서 필요한 것은 원자적 쓰기 **더하기** 읽기-수정-쓰기 전 구간의 잠금이다.

## 무엇을 재사용하는가

id 발급은 `server.py` 의 `_mint_id` 를 그대로 쓴다. 접두어 처리와 "next_id 가 실제
최대값보다 뒤처져 있으면 맞춘다"는 교정이 거기 있고, 여기서 다시 구현하면 두 경로가
조용히 갈라진다 — 이 레포가 이미 세 번 겪은 실패 방식이다.

## 한계 (숨기지 않는다)

`fcntl` 이 없는 환경(Windows)에서는 잠금이 no-op 이 된다. 원자적 교체는 그대로 동작하므로
**부분 읽기는 막지만 동시 편집의 갱신 유실은 막지 못한다.** `--require-lock` 을 주면
잠글 수 없을 때 진행하지 않고 실패한다.

    python3 scripts/kanban_edit.py add "제목" --category infra
    python3 scripts/kanban_edit.py set 42 --status done --details "..."
    python3 scripts/kanban_edit.py show 42
"""
import argparse
import contextlib
import importlib.util
import json
import os
import sys

try:
    import fcntl
    HAVE_FLOCK = True
except ImportError:  # Windows
    fcntl = None
    HAVE_FLOCK = False

HERE = os.path.dirname(os.path.abspath(__file__))
LOCK_NAME = "kanban.lock"


def _server():
    """server.py 를 모듈로 읽는다. id 발급·읽기·쓰기를 한 구현으로 유지한다."""
    sys.path.insert(0, HERE)
    spec = importlib.util.spec_from_file_location("vh_server_edit",
                                                  os.path.join(HERE, "server.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("vh_server_edit", mod)
    spec.loader.exec_module(mod)
    return mod


@contextlib.contextmanager
def kanban_lock(kanban_dir, require=False, timeout_note=True):
    """읽기-수정-쓰기 전 구간을 감싸는 프로세스 간 잠금.

    쓰기만 원자적으로 해서는 갱신 유실을 못 막는다. 읽은 뒤 쓰기까지가 한 구간이어야 한다.
    """
    os.makedirs(kanban_dir, exist_ok=True)
    path = os.path.join(kanban_dir, LOCK_NAME)
    if not HAVE_FLOCK:
        if require:
            raise SystemExit(
                "이 환경에는 fcntl 이 없어 파일 잠금을 걸 수 없다.\n"
                "  원자적 교체는 되지만 동시 편집의 갱신 유실은 막지 못한다.\n"
                "  --require-lock 없이 실행하면 잠금 없이 진행한다.")
        yield None
        return
    fh = open(path, "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield fh
    finally:
        # 예외로 빠져나가도 반드시 푼다. 안 그러면 다음 편집이 영영 막힌다.
        try:
            fcntl.flock(fh, fcntl.LOCK_UN)
        finally:
            fh.close()


def archived_ids(kanban_dir):
    """아카이브된 태스크 id. next_id 계산에 넣지 않으면 아카이브된 번호를 재사용한다."""
    adir = os.path.join(kanban_dir, "archive")
    out = []
    if not os.path.isdir(adir):
        return out
    for name in sorted(os.listdir(adir)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(adir, name), encoding="utf-8") as fh:
                doc = json.load(fh)
        except (ValueError, OSError):
            continue
        for t in doc.get("tasks") or []:
            out.append(t.get("id"))
    return out


def _numeric(ids):
    out = []
    for i in ids:
        try:
            out.append(int(i))
        except (TypeError, ValueError):
            continue
    return out


def add_task(kanban_dir, fields, require_lock=False):
    srv = _server()
    with kanban_lock(kanban_dir, require=require_lock):
        data = srv._read_kanban(kanban_dir)
        # 아카이브까지 본다. kanban 만 보면 아카이브된 id 를 다시 발급할 수 있다.
        arch = _numeric(archived_ids(kanban_dir))
        if arch:
            data["next_id"] = max(int(data.get("next_id") or 1), max(arch) + 1)
        data, task = srv._new_task(data, fields)
        srv._write_kanban(kanban_dir, data)
    return task


def set_task(kanban_dir, task_id, fields, require_lock=False):
    srv = _server()
    with kanban_lock(kanban_dir, require=require_lock):
        data = srv._read_kanban(kanban_dir)
        target = None
        for t in data.get("tasks") or []:
            if str(t.get("id")) == str(task_id):
                target = t
                break
        if target is None:
            raise SystemExit(f"태스크 {task_id} 없음")
        for k, v in fields.items():
            if v is not None:
                target[k] = v
        target["updated_at"] = srv._now()
        srv._write_kanban(kanban_dir, data)
    return target


def show_task(kanban_dir, task_id):
    srv = _server()
    for t in srv._read_kanban(kanban_dir).get("tasks") or []:
        if str(t.get("id")) == str(task_id):
            return t
    raise SystemExit(f"태스크 {task_id} 없음")


def _resolve_dir(arg):
    if arg:
        return os.path.abspath(arg)
    here = os.getcwd()
    for _ in range(6):
        cand = os.path.join(here, "vibe-harness")
        if os.path.isfile(os.path.join(cand, "kanban.json")):
            return cand
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    raise SystemExit("kanban.json 을 찾지 못했다 — --kanban-dir 로 지정한다")


def main(argv=None):
    ap = argparse.ArgumentParser(description="kanban.json 안전 편집 (서버 불필요)")
    ap.add_argument("--kanban-dir")
    ap.add_argument("--require-lock", action="store_true",
                    help="잠글 수 없으면 진행하지 않고 실패한다")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="태스크 추가")
    a.add_argument("title")
    for f in ("category", "status", "phase", "details", "assigned_to", "created_by", "priority"):
        a.add_argument("--" + f.replace("_", "-"), dest=f)

    s = sub.add_parser("set", help="태스크 수정")
    s.add_argument("task_id")
    for f in ("title", "category", "status", "phase", "details",
              "assigned_to", "priority", "lines_added", "lines_removed"):
        s.add_argument("--" + f.replace("_", "-"), dest=f)

    sh = sub.add_parser("show", help="태스크 출력")
    sh.add_argument("task_id")

    a_ = ap.parse_args(argv)
    kdir = _resolve_dir(a_.kanban_dir)

    if a_.cmd == "add":
        fields = {k: v for k, v in vars(a_).items()
                  if k not in ("cmd", "kanban_dir", "require_lock") and v is not None}
        task = add_task(kdir, fields, require_lock=a_.require_lock)
        print(json.dumps({"id": task["id"], "title": task["title"]}, ensure_ascii=False))
    elif a_.cmd == "set":
        fields = {k: v for k, v in vars(a_).items()
                  if k not in ("cmd", "kanban_dir", "require_lock", "task_id")}
        task = set_task(kdir, a_.task_id, fields, require_lock=a_.require_lock)
        print(json.dumps({"id": task["id"], "status": task.get("status")}, ensure_ascii=False))
    else:
        print(json.dumps(show_task(kdir, a_.task_id), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
