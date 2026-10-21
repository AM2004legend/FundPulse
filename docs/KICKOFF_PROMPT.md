# Paste these into Claude Code, one at a time

## Prompt 1 — first message (planning only)

Read CLAUDE.md and docs/PRD.md fully. Don't write any code yet.

Then give me:
1. A one-paragraph summary of what we're building, in your own words.
2. The plan for Phase 1 (Setup): every file you'll create and every package you'll install and
   why, in a short table.
3. Anything in the PRD that looks unclear or contradictory.
4. What I need on my Windows laptop first (Python 3.12, Docker Desktop, etc.) and the
   PowerShell commands to check each.

Wait for my "go" before writing anything.

## Prompt 2 — after checking the plan

Go ahead with Phase 1 only. When done:
- run ruff and pytest and show me the output,
- show me how to start Postgres and confirm the schema was applied,
- explain what you built, the key concepts, and 2 interview questions about this phase.
Then stop.

## Prompt 3 — Phase 2 (don't skip this one)

Do Phase 2: download the real AMFI file once, show me its first ~40 lines, and explain its exact
format — separator, columns, how section headings look, date format, and any odd values you see.
Save a trimmed sample as tests/fixtures/navall_sample.txt with a few headings, a blank line, an
"N.A." value if any exist, and one duplicate row added by hand. Don't write the parser yet.

## Prompt for every later phase

Do Phase N from CLAUDE.md. Plan first (files + why), wait for my go, then build it with tests,
run them, and explain it the same way as before. Then stop.

## Handy prompts while building

- "Explain this SQL view line by line. What would break if I removed PARTITION BY?"
- "Run the load twice and prove to me the row count didn't change."
- "Quiz me with 5 questions on this phase. Don't give answers until I reply."
- "This failed: <paste error>. Explain the cause before fixing it."
- "Review this phase like a senior data engineer. What would they criticise?"
- "Write a short bug-diary entry about what just went wrong and how we fixed it."
