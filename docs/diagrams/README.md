# docs/diagrams

Architecture diagrams, stored as Mermaid source (`.mmd`) plus a rendered PNG that the docs embed. The PNGs exist because many Markdown viewers (VS Code's built-in preview, Quick Look, some desktop apps) don't render Mermaid and show raw code instead. An image displays everywhere.

| Diagram | Source | Embedded in |
|---|---|---|
| ![](v3-overview.png) | [v3-overview.mmd](v3-overview.mmd) | [ARCHITECTURE.md §1](../../ARCHITECTURE.md#1-system-at-a-glance), [README.md](../../README.md#how-it-fits-together) |
| ![](pipeline-1-scan-to-passport.png) | [pipeline-1-scan-to-passport.mmd](pipeline-1-scan-to-passport.mmd) | [ARCHITECTURE.md §3](../../ARCHITECTURE.md#3-pipeline-1--scan-to-passport) |
| ![](pipeline-2-condition-vs-references.png) | [pipeline-2-condition-vs-references.mmd](pipeline-2-condition-vs-references.mmd) | [ARCHITECTURE.md §4](../../ARCHITECTURE.md#4-pipeline-2--condition-vs-references-the-core) |
| ![](pipeline-3-handover.png) | [pipeline-3-handover.mmd](pipeline-3-handover.mmd) | [ARCHITECTURE.md §5](../../ARCHITECTURE.md#5-pipeline-3--handover-check) |

## Changing a diagram

1. Edit the `.mmd` file. **Never edit the PNG by hand.**
2. Re-render it (needs Node; uses your installed Google Chrome):

```bash
npx -y @mermaid-js/mermaid-cli -i docs/diagrams/v3-overview.mmd -o docs/diagrams/v3-overview.png -b white -s 2
```

3. Commit the `.mmd` and `.png` together.

**Mermaid syntax gotchas we've already hit:**
- Put labels in quotes (`NODE["label"]`). An unquoted `{` starts a diamond shape and breaks the whole diagram.
- Never put `;` in a sequence-diagram message. Mermaid treats it as the end of a line.
