from typing import Dict, Any, List
from copy import deepcopy
from random import Random

from archai.discrete_search.search_spaces.builder.discrete_choice import DiscreteChoice
from archai.discrete_search.search_spaces.builder.arch_config import ArchConfig, ArchConfigList
from archai.discrete_search.search_spaces.builder.arch_param_tree import ArchParamTree


class RepeatConfig(ArchParamTree):
    def __init__(self, config_dict: Dict[str, Any], repeat_times: List[int], share_arch: bool = False):
        self.repeat_times = repeat_times
        self.share_arch = share_arch

        config_dict = deepcopy(config_dict)

        # If arch params should be shared between blocks, re-uses the same reference to `config_dict`
        # instead of creating a new copy
        config_dict = {
            '_repeat_times': DiscreteChoice(repeat_times),
            '_configs': {
                i: config_dict if self.share_arch else deepcopy(config_dict)
                for i in range(max(repeat_times))
            },
            '_share_arch': share_arch,
        }

        super().__init__(config_dict)

    def _sample_config(self, rng: Random, ref_map: Dict[int, Any]):
        config = super()._sample_config(rng, ref_map)
        return ArchConfigList(config.config_tree)