## OACS Project Policy

Use the globally installed `oacs` Skill for persistent project context and the
`proof-loop` Skill for evidence-backed delivery. Current user instructions
override stale checkpoints and historical memory.

Project-specific requirements:

- Do not commit `.agent/tasks`, raw local proof artifacts, `.oacs`, local
  databases, passphrases, or other private agent state.
- Verifiers must judge current code and current command results.
- Keep this root file lean. Put longer repository guidance in `@path` imports
  or `.claude/rules/*.md`.
