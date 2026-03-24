## Skill boundaries

The orchestrator (`review-assistant/SKILL.md`) must stay thin. Flag any change that adds implementation details, diff analysis, finding presentation, or user interaction to the orchestrator — these belong in the sub-skills.

Instructions in skills should be directive ("Call: `Skill(...)`"), not descriptive ("The skill will fetch the diff and..."). Descriptive instructions cause Claude to inline the work instead of invoking the skill.

## Session file contract

The session file is the interface between `reading-pr-context` and `interactive-diff-review`. Changes to its format (headers, finding format, section names) must be compatible across both skills.

## Skill descriptions

Skill `description` fields should start with "Use when..." and describe only triggering conditions — never summarize the skill's workflow. Claude may follow the description instead of reading the full skill.
