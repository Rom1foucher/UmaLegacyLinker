# White Skill priority JSON

The White Skill priority file assigns the strategic value of individual White
Sparks for each target profile. It is separate from
`parent_scoring_overrides.json`, which controls structural weights, probability
curves, thresholds and the relative importance of the White component itself.

The selectors shown in the shared **Search** workspace and in
**Weights → Individual White Skill priorities** edit the same persisted setting for local and
uma.moe searches. Leaving the path empty uses `default_skill_priorities.json`.

## Merge and output pipeline

A selected file may be a complete profile or a minimal override:

1. the application loads `default_skill_priorities.json`;
2. it recursively merges the selected JSON on top;
3. it validates the resulting complete profile;
4. it writes the effective result to `output/active_skill_priorities.json`;
5. that effective profile generates `manual_skill_weights.json` and, when a
   course file is active, `course_skill_weights.json`.

Objects are merged recursively. Arrays, including `profiles`, replace the
complete default array at that path.

## Minimal override

Only the values that differ from the bundled profile need to be present:

```json
{
  "description": "Kyoto 2200 m lucky Pace profile",
  "skills": {
    "groundwork": {
      "style": {
        "pace_chaser": 1.28
      }
    },
    "ramp_up": {
      "style": {
        "pace_chaser": 0.0
      }
    },
    "slipstream": {
      "style": {
        "pace_chaser": 0.0
      }
    },
    "nimble_navigator": {
      "style": {
        "pace_chaser": 0.0
      }
    }
  }
}
```

For these existing `catalog_key` entries, omitted fields such as `base` and
other styles remain inherited from `default_skill_priorities.json`.

## Root object

| Field | Type | Meaning |
| --- | --- | --- |
| `description` | string | Optional documentation; it does not affect scoring. |
| `default_weight` | non-negative number | Fallback for a White Spark not explicitly configured. Optional in a partial override. |
| `skills` | object | Entries indexed by stable White Spark `catalog_key`. |

`schema_version` may be retained in a complete profile, but a partial override
does not need it.

## Skill entry

```json
{
  "base": 0.1,
  "surface": {
    "turf": 0.2,
    "dirt": 0.0
  },
  "distance": {
    "sprint": 0.1,
    "mile": 0.4,
    "medium": 0.8,
    "long": 1.0
  },
  "style": {
    "front_runner": 0.0,
    "pace_chaser": 1.1,
    "late_surger": 0.0,
    "end_closer": 0.0
  },
  "profiles": [
    {
      "match": {
        "surface": "turf",
        "distance": "medium",
        "style": "pace_chaser"
      },
      "operation": "cap",
      "value": 0.9,
      "reason": "Optional explanation"
    }
  ],
  "notes": "Optional general explanation"
}
```

| Field | Required in a complete new entry | Meaning |
| --- | --- | --- |
| `base` | yes | Generic priority before matching dimensions. |
| `surface` | no | Overrides for `turf` and/or `dirt`. |
| `distance` | no | Overrides for `sprint`, `mile`, `medium` and/or `long`. |
| `style` | no | Overrides for `front_runner`, `pace_chaser`, `late_surger` and/or `end_closer`. |
| `profiles` | no | Ordered exact-profile rules applied after dimension values. |
| `notes` | no | Documentation only. |

Every numeric priority must be finite and non-negative. An explicit `0.0` in
any matching dimension is a hard incompatibility.

If one dimension matches, its value replaces `base`. If several non-zero
dimensions match, their arithmetic mean is used. Matching `profiles` rules are
then applied in array order, and the final value is clamped to `0.0…1.35`.
An incompatibility derived from the MDB still forces the generated value to
zero.

## Exact-profile rules

`match` accepts `surface`, `distance` and `style`. Each value may be one
canonical string or an array of canonical strings.

| Operation | Effect |
| --- | --- |
| `override` | Replace the current value. |
| `floor` | Raise it to at least `value`. |
| `cap` | Lower it to at most `value`. |
| `multiplier` | Multiply it by `value`. |
| `bonus` | Add `value`. |

`reason` is optional documentation. Misspelled dimensions, values or
operations are rejected during profile materialisation instead of being
silently ignored.

## Choosing identifiers

Use the `catalog_key` values from `default_skill_priorities.json` or from the
generated `manual_skill_weights.json`. A key that is not present in the bundled
defaults must provide at least `base`; it only affects scoring when the current
MDB skill catalogue contains the same key.

The numbers represent the value of obtaining a skill as a White Spark for
parent farming. They deliberately combine race usefulness, practical scarcity
in common support decks and lineage differentiation; they are not raw
in-race skill-strength ratings.
