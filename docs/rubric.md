# Rubric Notes

## Code Quality Ladder

### Level 4

- Naming convention is consistent.
- Comments are present for complex parts.
- File size is reasonable, around 200 lines per module.
- Includes 1-2 reusable utilities.

### Level 4 to 5

- Clean code follows basic principles: small functions, DRY, clear naming.
- Public functions have docstring or JSDoc coverage.
- File structure is modular and easy to navigate.
- Unit tests cover core logic, with a few passing test cases.
- Git commit messages are clear.
- Code review happens within the team before merge.
- Linter setup exists, such as ESLint, Prettier, or Black, with auto-formatting.
- The review process is clear.
- A basic CONTRIBUTING.md exists.
- The folder structure is easy to navigate.
- Integration tests cover the main flow, such as auth or the key feature.
- Pre-commit hooks exist for lint and format.
- Git history shows real refactoring, not only "fix bug" commits.
- Test coverage is above 50%.
- Code is documented fully with JSDoc or docstrings.
- CONTRIBUTING.md and ARCHITECTURE.md are present.
- Team code mentoring is visible.
- The code architecture is extensible.

### Level 5

- Production-quality code that is ready for open source.
- Includes examples, tutorials, and API docs.
- External contributors can fork and contribute right away.
- Changelog, semantic versioning, and release tags are present.
- The AI agent can maintain the codebase independently.

## 5 RUBRIC Dimensions

- The product should solve a real user pain point.
- Overall architecture, data flow, and scalability belong here, not code details.
- UI should be attractive, easy to use, and friendly, not user testing.
- Deploy, monitoring, CI/CD, and security belong here, not architecture.
- Clean code, naming, comments, and tests require the team to show source code or self-check the GitHub repository.