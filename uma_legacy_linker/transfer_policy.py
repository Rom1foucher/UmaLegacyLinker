"""Transfer-only policy. Other optimizers retain their own scoring contract."""
from copy import deepcopy
from typing import Any


def transfer_scoring_config(source: dict[str, Any]) -> dict[str, Any]:
    config = deepcopy(source)
    helper = config.setdefault('transfer_helper', {})
    # Explicit transfer weights; never infer a local pair composition.
    modes = config.setdefault('mode_weights', {})
    modes['parent_branch'] = dict(helper.get('branch_weights') or {
        'distance_s': .29, 'surface_aptitude': .05, 'pink_other': .02,
        'white_skill': .35, 'race_scenario': .04, 'blue': .20, 'unique': .05,
    })
    modes['future_grandparent'] = dict(helper.get('grandparent_weights') or {
        'g1_potential': .17, 'blue': .25, 'pink': .35, 'white_skill': .20,
        'unique': .03,
    })
    # Unknown future compatibility and old ancestry cannot create GP value.
    modes['future_grandparent']['affinity'] = 0.0
    modes['future_grandparent']['white_generation'] = 0.0
    return config


def restrict_heritage(heritage: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Keep ordinary Whites in score/diagnostics, not in hard coverage guards."""
    result = deepcopy(heritage)
    critical = set(policy.get('build_defining_skill_keys', ['straight_descent']))
    for key, skill in result.get('skills', {}).items():
        if key not in critical:
            skill['protection_signals'] = []
    # A generic multi-White package is not an independent retention obligation.
    result['packages'] = []
    return result
