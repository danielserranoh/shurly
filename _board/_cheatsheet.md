# CLAUDE KANBAN | COMMANDS

## Setup & health
/kanban:init-kanban          Initialize _board/ (idempotent)
/kanban:board-doctor         Diagnose and repair board incoherences

## Dashboard
/kanban:get-status           Full board dashboard

## Planning
/kanban:create-epic X        New epic in backlog/
/kanban:create-chore X       Quick plan straight into todo/
/kanban:plan-epic X          Epic -> executable plan with task blocks

## Execution
/kanban:start-plan X         Readiness gate, claim, move to WIP
/kanban:work-plan X          Run the plan across parallel agents
/kanban:check-plan X         Verify against the repo with real evidence
/kanban:close-plan X         Release, archive to done/

## Flow
create-epic -> backlog/ -> plan-epic -> todo/ -> start-plan -> WIP -> close-plan -> done/
                            create-chore -> todo/ ↗      work-plan / check-plan ↺

## Columns
backlog/  epic_*.md      todo/  plan_*.md
_board/   plan_*.md (WIP)        done/  plan_*.md + archived epic_*.md

## Task blocks (what makes parallel execution possible)
### T2 — Title
files: src/a.jsx, src/b.css     <- the concurrency contract; list everything
depends_on: T1
verify: npm test -- A           <- a real command, or `none` if there is no way
- [ ] step

## Reading `waves`
tasks in a GROUP  -> disjoint  -> in parallel, one agent per task
groups in a WAVE  -> share files -> in sequence
waves             -> in order

## Under the hood
scripts/board.sh help        Every deterministic operation
  status | new | move | claim | release | progress | tasks | waves
  validate | conflicts | readiness | log
