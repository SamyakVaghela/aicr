# Changelog

All notable changes to `aicr` are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-08-26

Initial version.

### Core review engine
- Pre-push git hook: reviews the diff about to be pushed and blocks it when a
  finding meets or exceeds `fail_on` (default `high`).
- Providers: Anthropic, OpenAI, Gemini, Ollama (local), and a stdlib-only
  `mock` regex reviewer for offline development and CI-free testing.
- Diff chunking and bin-packing for large pushes, per-provider concurrency,
  and response caching (`.aicr-cache/`) so an unchanged diff isn't re-billed.
- Layered config: built-in defaults → `~/.config/aicr/config.toml` → repo
  `.aicr.toml` (committed) → `.aicr.local.toml` (gitignored) → `AICR_*`
  env vars.
- Terminal and Markdown report renderers; JSON output for scripting.

### CLI
- `aicr review` (`--staged` / `--working` / `--range` / `--files`), `aicr repo`,
  `aicr doctor`, `aicr init`, `aicr install-hook` / `uninstall-hook`,
  `aicr pre-push` (hook entry point).
- `aicr install-hook --shared`: writes the hook to a committed `.githooks/`
  directory and sets this clone's `core.hooksPath`, so a teammate needs one
  generic `git config` command instead of an aicr-specific install step.

### IDE and CI integration
- `aicr cursor-init` / `aicr cursor-hook`: gates `git push` run by the Cursor
  agent, plus `/aicr-review` and `/aicr-fix` slash commands.
- `aicr github-init`: GitHub Actions workflow that reviews every PR push and
  posts (or updates) a single findings comment on the PR.

### Admin visibility (telemetry)
- Local review history at `~/.config/aicr/history.jsonl`, written on every
  review regardless of webhook configuration.
- Opt-in outbound webhook (`[telemetry]` in `.aicr.toml`, or
  `AICR_TELEMETRY_WEBHOOK`) reporting who/what/where/outcome per review.
- `telemetry.format = "card"` (or `AICR_TELEMETRY_FORMAT=card`): sends a
  ready-to-render Microsoft Adaptive Card instead of plain JSON, for Teams
  setups whose only available action requires one.
- Events enriched with git identity (`user`, `user_name`) and, when the
  remote is GitHub, `github_owner`, `repo_url`, `branch_url` for clickable
  links and an avatar in the rendered card.
- `aicr doctor --test-webhook`: sends one synthetic event and reports
  delivery success/failure before a team relies on it.
- `include_findings` (default off): opt-in to sending finding titles/details
  over the webhook, not just severity counts.

### Documentation
- `README.md`, `docs/ROLLOUT.md` (team rollout playbook), `docs/TOOL-COMPARISON.md`
  (market comparison), `docs/ADMIN-VISIBILITY.md` (manager-facing explainer).
