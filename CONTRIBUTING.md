# Contributing to pipewise

Thanks for your interest! Pipewise is pre-alpha and moving fast toward v1.0. This file is a stub; full guidelines land at v1.0.

## What's welcome right now

- **Bug reports.** Open an issue with a minimal reproduction.
- **Adapter contributions.** If you write a pipewise adapter for an open-source pipeline, link it from `examples/README.md` via a PR.
- **Schema feedback.** If `PipelineRun` / `StepExecution` doesn't fit your pipeline shape, that's exactly the kind of feedback I want before v1.0 locks the schema.

## What to discuss first

- **Large feature PRs.** Open an issue or discussion before sending code — pipewise is opinionated about staying focused (see `README.md` "What it is *not*"), and unsolicited big PRs are at risk of being rejected for scope.
- **New built-in scorers.** Often better as a third-party package; only the most universal scorers ship in core.

## Local dev

```bash
git clone https://github.com/isthatamullet/pipewise
cd pipewise
uv sync
uv run pytest
uv run ruff check .
uv run mypy pipewise/
```

## Code of conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold it. Report unacceptable behavior to [tyler.gohr@gmail.com](mailto:tyler.gohr@gmail.com).

## License

By contributing, you agree your contributions are licensed under [Apache 2.0](LICENSE).
