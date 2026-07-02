# Claude Code memory snippet — TokenConsumption

Paste the block below into a `CLAUDE.md` that Claude Code loads:

- **Global (all projects):** `~/.claude/CLAUDE.md`
- **Per-project:** `<repo>/CLAUDE.md`

Replace `<TOKENCONSUMPTION_DIR>` with your install path. The `scripts/tc-launcher.py`
entry point works without an activated virtualenv.

---

```markdown
<!-- BEGIN TokenConsumption -->
## TokenConsumption — preventive budget control

I use a local token/cost tracker at `<TOKENCONSUMPTION_DIR>`. Act **preventively,
not reactively** about cost.

**Before meaningful work** (multi-file edits, refactors, research, long generation),
prepend one line:

`Budget estimate: likely ≈ €X.XX, threshold €20.00, model: <model>, confidence: low/medium/high`

You may compute it with:
`python <TOKENCONSUMPTION_DIR>/scripts/tc-launcher.py estimate --task-type <type> --model <model>`

Then:
- **Below threshold** → proceed.
- **Near threshold** (≥ warn %) → warn me and suggest ways to reduce scope.
- **Above threshold** → STOP and ask for confirmation before doing expensive work.
  Do not auto-proceed even in auto mode.
- Recommend a **cheaper model** (e.g. Sonnet or Haiku) when it would suffice.
- Split large work into a cheap **planning/inspection phase** first, then execution.
- If the estimate is uncertain, say so and use **conservative** assumptions.
- Trivial replies (single-line answers, lookups) may skip the estimate.

**End of replies:** when the tracker is available, append its status line as the
last line:
`python <TOKENCONSUMPTION_DIR>/scripts/tc-launcher.py status --line`

**Honesty about cost:**
- The exact cost of the reply being written is **only known after the turn finishes**.
  Never fabricate an exact "current reply" cost.
- The status line shows the **previous** turn's actual cost plus session/day/month totals.
- Values marked `≈` or `est` are estimates; label them as such.

**Privacy:** the tracker stores only token/cost metadata. Do not store or log
prompt text, outputs, diffs, file contents, or secrets.
<!-- END TokenConsumption -->
```
