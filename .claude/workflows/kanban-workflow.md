ultracode: Create a workflow that processes Kanban issues:
1. Analyzer agent: refines task description and acceptance criteria
2. Technical agent: proposes solution architecture (runs in parallel with analyzer)
3. Test agent: creates/maintains tests based on technical proposal
4. Developer agent: implements following project best practices

Each stage should wait for previous stages to complete, then pass their results to the next agent. Return a consolidated report with all findings.


