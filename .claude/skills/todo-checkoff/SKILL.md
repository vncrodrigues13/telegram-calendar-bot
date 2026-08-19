---
name: todo-checkoff
description: Keep Markdown TODO checklists synchronized with implementation progress. Use when Claude is working from any Markdown task list, implementation checklist, plan, spec, README, or issue body containing checkbox items like `- [ ]` and completed work should be marked as `- [X]`.
---

# TODO Checkoff

## Core Rule

When a task is completed and it corresponds to a Markdown checklist item, update that item from:

```md
- [ ] Task text
```

to:

```md
- [X] Task text
```

Do this during the same work session, not only in the final response.

## Workflow

1. Before starting checklist-driven work, identify the relevant Markdown checklist file and the subset of TODO items in scope.
2. As each item is genuinely completed, patch the checklist file and mark only that item as `- [X]`.
3. Keep unfinished, blocked, partially complete, or merely-started items as `- [ ]`.
4. If an item is completed by previous work discovered during inspection, mark it checked only after verifying the result in the repo.
5. After updating checklist state, continue with the next unchecked item.
6. In the final response, summarize which checklist file was updated and mention any TODO items intentionally left unchecked.

## Matching Guidance

- Preserve the original task text unless the checklist item is factually wrong or stale.
- Match completed work to the most specific checklist item available.
- If one implementation step satisfies multiple checklist items, mark each verified completed item.
- If no checklist item exactly matches the completed work, do not invent a new item unless the user asked to maintain the checklist structure.
- Use uppercase `X` for checked items: `- [X]`.

## Safety

- Never mark a TODO checked based only on intent, plan, or generated code that has not been applied.
- Never mark verification items checked unless the named command or manual check actually ran successfully.
- If a command could not be run, leave the item unchecked and document the gap.
- Do not check off unrelated tasks outside the current user request.
