# Contributing

Contributions that keep the project small, self-hosted and human-operated are welcome.

## Development setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
python -m patchright install chromium
```

Run the complete local validation set before opening a pull request:

```bash
ruff check .
ruff format --check .
pytest --cov=headful_auth_tunnel --cov-report=term-missing
python -m build
shellcheck scripts/*.sh
```

## Pull requests

Keep changes focused and explain:

- the user problem;
- security or profile-persistence implications;
- compatibility changes;
- tests and manual validation performed.

Do not commit generated browser profiles, screenshots containing private data, tokens, cookies, certificates, `.env` files, runtime logs or machine-specific paths.

Changes to authentication, navigation filtering, profile ownership, browser lifecycle or secret handling should include regression tests.

## Bug reports

Use the bug-report template and include the version/commit, Python version, OS/container environment and reproduction steps. Sanitise logs before posting them.

Do not disclose a vulnerability in a public issue. Follow `SECURITY.md` and use GitHub private vulnerability reporting.

## Scope

The project is a remote human-control bridge, not an anti-bot or access-control bypass tool. Contributions intended to solve CAPTCHAs, evade protections, bypass paywalls or circumvent account restrictions are out of scope.
