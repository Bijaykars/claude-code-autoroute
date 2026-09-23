# FAQ

See also: [install.md](install.md) (setup) · [escalation.md](escalation.md) (the ESCALATE contract) · [self-tuning.md](self-tuning.md) (the retune loop).

## How does AutoRoute choose a model?

It does not intercept API calls. The session reads its own model tier from a routing table in `CLAUDE.md` and delegates to subagents whose model is pinned in their frontmatter: `locate`/`digest` on Haiku, `scaffold`/`implement`/`test-writer`/`reviewer` on Sonnet, `deep-debug` on Sonnet with self-escalation to Opus, and UI design work sent with `model: opus`. See [docs/escalation.md](escalation.md) for how an agent hands work up a rung when its tier cannot finish it.

## Does it require a proxy or gateway?

No. It is a `CLAUDE.md`, eight subagent definitions, four hook scripts and a small CLI; nothing sits between Claude Code and the API. Contrast that with gateway-style tools such as claude-code-router (musistudio), which route by rewriting requests to different providers — AutoRoute only decides which built-in subagent handles a task.

## Does it reduce API costs or subscription usage?

On API billing, the delegated work is priced at the cheaper tier's rate; the README's measured day shows the delegated tokens at 28% of the all-top-model price, estimated from reported token counts at an 80/20 input/output split, excluding the orchestrating session. On a subscription plan the effect depends on how the plan meters usage across models, which has not been measured here. A reproducible comparison is on the roadmap.

## Which Claude models does it use?

Haiku 4.5, Sonnet 5, Opus 5.5, with Fable 5.1 or Opus as the orchestrator. Tiers are names in frontmatter, not hardcoded model IDs, so they follow whatever the current generation is.

## What is the self-tuning, and can it make things worse?

Each agent keeps a ledger; the caller writes a `WRONG` row when a delegated answer proves wrong. `retune` moves an agent one rung at a time from those ledgers, and reverts a move that did not improve the next window. It writes a project-level agent override, never the global file, and it never demotes a code-writing agent below Sonnet. See [docs/self-tuning.md](self-tuning.md). It is experimental and has few rows of evidence so far.

## Does it work on Windows?

Yes. `install.py` writes each hook's absolute path into `settings.json` (forward slashes, quoted) instead of a `$HOME`/`$env:USERPROFILE` shell variable, so the same `command` string runs under any shell; it has been tested with Python 3.12 on Windows 11 via Git Bash. It needs `python` on `PATH`.

## Can I keep my own CLAUDE.md?

Yes. The installer merges only a marked routing block; `--full-claude-md` also adds the coding rules; uninstall removes the block. See [docs/install.md](install.md).

## Does it require Ponytail or the Karpathy rules?

No, both are optional. Attribution for the adapted sections is kept in the README's Credits.

## How do I turn it off?

Run `python install.py --uninstall`, or manually delete the marked block from `CLAUDE.md` and remove the three hook entries from `settings.json`.
