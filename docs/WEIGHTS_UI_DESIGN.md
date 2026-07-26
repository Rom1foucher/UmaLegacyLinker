# Weights editor redesign notes

## Why preview 3 still felt technical

Preview 3 solved the most visible data-editor problems: JSON paths disappeared,
settings gained categories, and values received controls matching their type. The
remaining friction came from the information architecture:

- three side-by-side panes competed for width at the 1120 px minimum window size;
- the table answered “what is the current value?” but not “what does it change?”;
- the selected setting had no explanation of direction, scope, normalisation or
  trade-offs;
- category navigation consumed permanent space while each setting’s useful context
  was compressed;
- help would have been undiscoverable if it existed only as a hover tooltip;
- the White Skill priority-file controls occupied prime vertical space even though
  they are a secondary workflow.

## Comparable settings editors

The redesign borrows interaction patterns, not visual copies:

- [Visual Studio Code Settings](https://code.visualstudio.com/docs/configure/settings)
  combines search, grouped navigation, a visible modified state, per-setting reset,
  human descriptions and a separate raw JSON escape hatch.
- [JetBrains Settings](https://www.jetbrains.com/help/idea/settings-preferences-dialog.html)
  keeps search and hierarchical categories together, with the selected settings in
  a larger content area.
- [Apple’s slider guidance](https://developer.apple.com/design/human-interface-guidelines/sliders)
  recommends pairing sliders with an exact numeric field and labelling their range.
- [Microsoft’s slider guidance](https://learn.microsoft.com/windows/apps/design/controls/slider)
  reserves sliders for relative quantities, uses switches for booleans, and asks for
  visible units, endpoints and feedback.

## Target interaction model

The page is now a two-pane settings editor:

1. **Find** — search, category and modified-only filters sit above one readable list.
2. **Understand** — selecting a setting always shows a plain-language summary,
   affected workflow, control type, increase/decrease effect and default value.
3. **Adjust** — common values use a purpose-built control. Percentage sliders retain
   precise spin-box input and receive meaningful endpoint labels.
4. **Verify** — the draft/default state and reset action remain beside the control.
5. **Discover quickly** — hovering a list row shows the same summary and impact in a
   tooltip, but no essential information exists only on hover.
6. **Keep focus** — White Skill priority-file management moves into a collapsed
   secondary section.

## Preview 5: make weight semantics visible

The previous slider still used a percentage-shaped display for several different
mathematical concepts. That made `120%` look like an invalid allocation even when
the engine treated it as a perfectly valid `×1.2` coefficient. The editor now
separates three control families:

- **probabilities and bounded thresholds** remain absolute percentages;
- **independent coefficients** use `×` notation, with `×1` shown as the reference;
- **normalised mixes** expose the effective share of a 100% budget rather than the
  raw stored coefficient.

Nine mixes (42 settings) are normalised by the scoring engine: the three global
scoring roles, both aptitude-dimension roles, parent-branch partial scoring, both
uma.moe ranking stages and Transfer Helper utility. Selecting one of these settings
reveals a live donut chart and legend of the effective 100% distribution. Changing
a coefficient updates only that stored value; the preview recalculates every
effective share without rewriting untouched siblings.

The broad gameplay categories are complemented by 50 ordered subcategories. They
group settings that contribute to the same calculation (for example final-pair
score, Long Blue stats, White proc rates or Transfer Helper utility) and replace
the historical JSON insertion order in navigation.

The raw scoring profile remains importable and exportable for advanced users, while
the main interface avoids exposing implementation keys.
