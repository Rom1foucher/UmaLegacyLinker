# White skill weights format

`white_skill_weights_template.json` is regenerated from the selected `master.mdb`.
It contains one entry per white skill Spark group.

## Stable matching across game updates

The main key is `catalog_key`, derived from the English Spark name. Current IDs are
kept under `current_mdb` only as diagnostics and must not be treated as permanent.
After a game update, regenerate the catalog from the new MDB and merge weights by
`catalog_key` / `spark_name`.

## Weight scale

Recommended convention:

- `0.0`: useless for this profile;
- `0.25`: very situational or weak;
- `0.5`: useful but non-priority;
- `0.75`: strong;
- `1.0`: top priority;
- values above `1.0`: exceptional / build-defining.

Each skill has:

- `default_weight`: fallback when no profile cell is filled;
- `weight_matrix[surface][distance][style]`: exact relevance for an Ace profile;
- `notes`: free-form explanation.

A `null` cell falls back to `default_weight`. A `null` default falls back to `0.0`.

## Dynamic conditions

The MDB conditions only describe engine activation checks. They do not express all
strategic context. For example, Nimble Navigator checks whether the runner is blocked
in the last spurt, but the MDB does not say that blocking is unlikely for Front Runner
or more common in longer races. That strategic judgment belongs in the manual matrix.

## Race Sparks granting green skills

`race_factor_skill_catalog.json` identifies race Sparks that grant a skill hint. Race
Sparks should otherwise receive a low base value. When a race Spark grants a useful
green skill for the target course, reuse the corresponding skill relevance weight as
a separate bonus rather than inflating all race Sparks.

## Manual parent-Spark priority semantics

`default_skill_priorities.json` does **not** score raw in-race performance alone.
Its values combine:

1. strategic usefulness for the selected Ace profile;
2. practical scarcity in commonly played support decks;
3. how much obtaining the skill as a white Spark differentiates a lineage.

Consequently, a strong but ubiquitous hint such as a matching distance/style corner
should remain modest, while rare and build-defining Sparks such as Uma Stan, Nimble
Navigator, Groundwork or a course-valid Straightaway Spurt may exceed `1.0`.

### Combining surface, distance and style

For a profile cell, `manual_weights._profile_weight` applies these rules:

- if no matching dimension override exists, use `base`;
- if one override exists, use that value;
- if several non-zero overrides exist, use their arithmetic mean;
- if any matching override is exactly `0.0`, the result is a hard incompatibility (`0.0`);
- matching `profiles` rules are then applied, allowing an exact `override`, `floor`,
  `cap`, `multiplier` or `bonus`.

Use an explicit zero for impossible distance/style/surface combinations. Use a
`profiles` cap or override when a dimension is technically possible but should stay
low regardless of another dimension's positive bonus; Nimble Navigator on Front
Runner is the canonical example.