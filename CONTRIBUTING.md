# Contributing to permyt-mcp

Thank you for your interest in contributing to permyt-mcp.

## Development Setup

```bash
python -m venv env
source env/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver 9020
```

## Running Tests

```bash
pytest                              # all tests
pytest app/core/requests/tests/     # specific module
pytest -v -k "test_login"           # by keyword
```

## Code Style

This project uses:

- **black** (line length 100) for formatting
- **pylint** with django plugin for linting

Both are enforced in CI and checked by the test suite. Run before committing:

```bash
black app/
pylint app/
```

## Pull Requests

1. Fork the repository and create a feature branch
2. Write tests for new functionality
3. Ensure all tests pass (`pytest`)
4. Ensure code is formatted (`black --check app/`)
5. Open a PR with a clear description of the change

## Security

If you discover a security vulnerability, please follow the process in [SECURITY.md](SECURITY.md). Do not open a public issue.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
