"""테스트를 개발자 홈에서 격리한다.

reconcile 이 Codex 세션까지 모으게 되면서, 테스트가 실제 ~/.codex/sessions 를 스캔해
57초까지 느려지고 결과가 머신마다 달라졌다. 빈 디렉토리로 고정한다.
"""

import os
import tempfile

import pytest


@pytest.fixture(autouse=True, scope="session")
def _isolate_codex_sessions():
    empty = tempfile.mkdtemp(prefix="vibe-codex-empty-")
    old = os.environ.get("VIBE_CODEX_SESSIONS")
    os.environ["VIBE_CODEX_SESSIONS"] = empty
    yield
    if old is None:
        os.environ.pop("VIBE_CODEX_SESSIONS", None)
    else:
        os.environ["VIBE_CODEX_SESSIONS"] = old
