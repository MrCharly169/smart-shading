# Development

## Local validation

Run from the repository root:

```bash
python -m unittest discover -s tests -v
python -m compileall custom_components/smart_shading
node --check custom_components/smart_shading/frontend/smart-shading-card.js
node tests/test_card_runtime.js
python scripts/build_release.py --check
```

## Branches

- `main`: reviewed baseline and releases
- `develop`: integration branch when used
- `fix/<topic>`: focused bug fixes
- `feature/<topic>`: new behavior

## Pull requests

A pull request should describe:

1. the observed behavior;
2. the intended behavior;
3. affected regression cases;
4. validation performed;
5. migration impact.

Do not remove a regression test merely to make a change pass.
