# Privacy Policy

**Default mode: `metadata_only`**

The following is **never** stored in the database by default:

- Message content (prompts, assistant replies)
- File contents read or written by Claude Code tools
- Git diffs or patches
- Tool inputs or outputs
- API keys, secrets, or credentials
- Shell command output content

The following **is** stored:

- Token counts (input, output, cache read/write)
- Model name
- Session ID (opaque UUID)
- Project slug (derived from directory name — no full path)
- Approximate working directory (encoded path, used for grouping)
- Timestamps
- Computed costs (if pricing is configured)

The database is local to your machine at `data/usage.sqlite`.
It is gitignored and never uploaded anywhere.
