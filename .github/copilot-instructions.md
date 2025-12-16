## Copilot Instructions for ReOS

- **Project shape**: This repo currently only contains the product charter in [ReOS_charter.md](../ReOS_charter.md). There is no codebase yet; ask for confirmation before assuming a tech stack or creating scaffolding.
- **Core purpose**: ReOS protects, reflects, and returns human attention; it treats attention as labor and avoids gamification, productivity scoring, or moral language.
- **Local-first & privacy**: Prefer designs that run locally on Linux, keep data user-owned, avoid cloud dependencies and telemetry, and do not capture content by default. Make privacy choices explicit and auditable.
- **Tone of output**: When generating user-facing text, avoid shame/optimization framing. Reflect patterns with neutral, compassionate language.
- **Attention modeling**: If implementing features, focus on observing context switching, fragmentation vs coherence, revolution vs evolution states, and “frayed mind” detection. Provide explainable classifications instead of prescriptive commands.
- **Integrations**: Planned integration is Thunderbird for relational attention (frequency/metadata), without reading message bodies by default. Any email-related code must default to minimal, consented data use.
- **Non-goals**: Do not build task managers, streaks/quotas, gamified habit trackers, or engagement loops. If a request moves in that direction, flag it and align with the charter.
- **Language principles**: Avoid “good/bad day” scoring. Prefer reflective summaries: timelines, patterns, depth vs fragmentation, and gentle observations like “this looks like strain”.
- **Architecture bias**: Favor local, inspectable pipelines (e.g., event collectors -> classifiers -> reflective summaries). Keep models/heuristics explainable and parameterized.
- **Data boundaries**: No hidden data exfiltration. Require explicit consent for any network calls or external storage. Default to zero-trust; document what is collected and why.
- **Future work prompts**: Before adding components (UI, storage, ML), confirm desired stack, storage location, and observability expectations consistent with the charter.
- **Testing & telemetry**: If adding instrumentation, keep it local and user-visible. Avoid third-party analytics unless explicitly approved.
- **Docs first**: Update the charter or adjacent docs when adding features so they stay aligned with the principles above.

When in doubt, re-read the charter and ask for clarification before proceeding.