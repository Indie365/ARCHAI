from typing import Dict, Any, List
from copy import deepcopy
from random import Random

from archai.discrete_search.search_spaces.config.discrete_choice import DiscreteChoice


def repeat_config(config_dict: Dict[str, Any], repeat_times: List[int],
                  share_arch: bool = False) -> Dict[str, Any]:
    return {
        '_config_type': 'config_list',
        '_share_arch': share_arch,
        '_repeat_times': DiscreteChoice(repeat_times),
        '_configs': {
            str(i): (config_dict if share_arch else deepcopy(config_dict))
            for i in range(max(repeat_times))
        }
    }

