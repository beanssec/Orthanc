# Contributing to Orthanc

Thanks for your interest in contributing to Orthanc.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/Orthanc.git`
3. Create a branch: `git checkout -b feature/your-feature`
4. Make your changes
5. Test locally with `docker compose up -d`
6. Commit and push to your fork
7. Open a Pull Request

## Development Setup

```bash
cp .env.example .env
docker compose up -d
```

Frontend: http://localhost:3001
Backend: http://localhost:8000
API docs: http://localhost:8000/docs

## Guidelines

- **Open an issue first** for large changes or new features
- Keep the dark theme consistent (see `frontend/src/styles/globals.css` for the colour palette)
- No inline styles except for truly dynamic values — use CSS files with CSS variables
- No external chart/graph libraries — raw SVG/Canvas only
- No Tailwind or CSS-in-JS
- Backend must be fully async
- Collector errors must never crash post ingestion
- Don't commit credentials or API keys

## Adding a New Collector

1. Create `backend/app/collectors/your_collector.py`
2. Follow the pattern of existing collectors (start/stop, async polling, dedup, broadcast)
3. Wire it into `backend/app/collectors/orchestrator.py`
4. Add the source type to `frontend/src/components/settings/SourcesPage.tsx`
5. Add the credential provider to `frontend/src/components/settings/CredentialsPage.tsx` if auth is needed

## Reporting Issues

Include:
- What you expected vs what happened
- Browser and OS
- Relevant error messages or screenshots

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
