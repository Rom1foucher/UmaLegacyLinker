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
