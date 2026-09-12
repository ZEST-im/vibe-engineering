# Contributing

## Before you push

```bash
python3 scripts/check.py
```

It runs what CI runs — compile, tests, a run without `private/`, lint, coverage — and prints
what it could **not** check. Read that part.

## What gets merged

- A new check must catch an injected violation. A check that passes from the first commit
  has not been shown to work.
- Claims in Markdown are compared against the code (`tests/test_skill_claims.py`). If you
  document behaviour, make it true first.
- Coverage floor only goes up (`tests/test_skills.py` fails if it drops).
