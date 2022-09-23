from abc import ABCMeta, abstractmethod
from overrides.overrides import overrides

import random
from typing import Tuple, List, Dict, Union

import torch.nn as nn

from archai.common.common import logger
from archai.nas.arch_meta import ArchWithMetaData
from archai.search_spaces.discrete_search_spaces.base import EvolutionarySearchSpace
from archai.metrics.base import BaseMetric
from archai.nas.searcher import Searcher, SearchResult
from archai.common.config import Config


class EvolutionParetoSearch(Searcher):
    def __init__(self, search_space: EvolutionarySearchSpace, 
                 objectives: Union[List[BaseMetric], List[Tuple[BaseMetric, int]]]):
        assert isinstance(search_space, EvolutionarySearchSpace), \
            f'{str(search_space.__class__)} is not compatible with {str(self.__class__)}'
        self.search_space = search_space
        self.objectives = objectives

    def mutate_parents(self, parents:List[ArchWithMetaData], mutations_per_parent: int = 1) -> List[ArchWithMetaData]:
        ''' Using the nearest neighbors as mutations'''
        mutations = {}
        oversample_factor = (
            self.crowd_sorting['oversampling_factor'] if self.crowd_sorting['mutation']
            else 1
        )

        for p in tqdm(parents, desc='Mutating parents'):
            candidates = {}
            nb_tries = 0
            patience = 20

            if len(self._filter_population([p])) == 0:
                logger.info(
                    f'Model {p.metadata["archid"]} has latency {p.metadata["latency"]}'
                    f' or memory {p.metadata["memory"]} that is too high. Skipping mutation.'
                )

                continue

            while len(candidates) < (mutations_per_parent * oversample_factor) and nb_tries < patience:
                nbr = self.search_space.mutate(p)
                if nbr.metadata['archid'] not in self.eval_cache:
                    nbr.metadata['generation'] = self.iter_num
                    candidates[nbr.metadata['archid']] = nbr
                nb_tries += 1
            
            if candidates and self.crowd_sorting['mutation']:
                candidates_list = list(candidates.items())

                secondary_objs_proxy = np.array([
                    list(self._get_secondary_objectives_proxy(p).values()) for _, p in candidates_list
                ])

                crowd_dist = compute_crowding_distance(secondary_objs_proxy)
                
                # Deletes mutations that are not on the top k
                for idx in np.argsort(-crowd_dist, axis=None)[mutations_per_parent:]:
                    del candidates[candidates_list[idx][0]]

            mutations.update(candidates)

        return list(mutations.values())

    @abstractmethod
    def crossover_parents(self, parents:List[ArchWithMetaData], num_crossovers: int = 1) -> List[ArchWithMetaData]:
        pass

    @abstractmethod
    def update_pareto_frontier(self, population:List[ArchWithMetaData]) -> List[ArchWithMetaData]:
        pass

    @abstractmethod
    def plot_search_state(self, all_pop:List[ArchWithMetaData], pareto:List[ArchWithMetaData], iter_num:int) -> None:
        pass

    @abstractmethod
    def save_search_status(self, all_pop:List[ArchWithMetaData], pareto:List[ArchWithMetaData], iter_num:int) -> None:
        pass

    def _sample_init_population(self)->List[ArchWithMetaData]:
        init_pop:List[ArchWithMetaData] = []
        while len(init_pop) < self.init_num_models:
            init_pop.append(self.search_space.random_sample())  
        return init_pop

    def _sample_random_to_mix(self)->List[ArchWithMetaData]:
        mix_pop:List[ArchWithMetaData] = []
        while len(mix_pop) < self.num_random_mix:
            mix_pop.append(self.search_space.random_sample())
        return mix_pop

    def on_calc_task_accuracy_end(self, current_pop: List[ArchWithMetaData]) -> None:
        ''' Callback function called right after calc_task_accuracy()'''
        pass

    def on_search_iteration_start(self, current_pop: List[ArchWithMetaData]) -> None:
        ''' Callback function called right before each search iteration'''
        pass

    def select_next_population(self, current_pop: List[ArchWithMetaData]) -> List[ArchWithMetaData]:
        random.shuffle(current_pop)
        return current_pop[:self.max_unseen_population]

    @overrides
    def search(self, conf_search:Config):
        
        self.init_num_models = conf_search['init_num_models']
        self.num_iters = conf_search['num_iters']
        self.num_random_mix = conf_search['num_random_mix']
        self.max_unseen_population = conf_search['max_unseen_population']
        self.mutations_per_parent = conf_search.get('mutations_per_parent', 1)
        self.num_crossovers = conf_search.get('num_crossovers', 1)

        assert self.init_num_models > 0 
        assert self.num_iters > 0
        assert self.num_random_mix > 0
        assert self.max_unseen_population > 0

        self.search_space = self.get_search_space()
        assert isinstance(self.search_space, DiscreteSearchSpace)

        # sample the initial population
        self.iter_num = 0
        unseen_pop:List[ArchWithMetaData] = self._sample_init_population()

        self.all_pop = unseen_pop
        for i in range(self.num_iters):
            self.iter_num = i + 1

            logger.info(f'starting evolution pareto iter {i}')
            self.on_search_iteration_start(unseen_pop)
            
            # for the unseen population 
            # calculates the memory and latency
            # and inserts it into the meta data of each member
            logger.info(f'iter {i}: calculating memory latency for {len(unseen_pop)} models') 
            self.calc_secondary_objectives(unseen_pop)

            # calculate task accuracy proxy
            # could be anything from zero-cost proxy
            # to partial training
            logger.info(f'iter {i}: calculating task accuracy for {len(unseen_pop)} models')
            self.calc_task_accuracy(unseen_pop)  
            self.on_calc_task_accuracy_end(unseen_pop)

            # update the pareto frontier
            logger.info(f'iter {i}: updating the pareto')
            pareto:List[ArchWithMetaData] = self.update_pareto_frontier(self.all_pop)
            logger.info(f'iter {i}: found {len(pareto)} members')

            # select parents for the next iteration from 
            # the current estimate of the frontier while
            # giving more weight to newer parents
            # TODO
            parents = pareto # for now
            logger.info(f'iter {i}: chose {len(parents)} parents')

            # plot the state of search
            self.save_search_status(all_pop=self.all_pop, pareto=pareto, iter_num=i)
            self.plot_search_state(all_pop=self.all_pop, pareto=pareto, iter_num=i)

            # mutate random 'k' subsets of the parents
            # while ensuring the mutations fall within 
            # desired constraint limits
            mutated = self.mutate_parents(parents, self.mutations_per_parent)
            logger.info(f'iter {i}: mutation yielded {len(mutated)} new models')

            # crossover random 'k' subsets of the parents
            # while ensuring the mutations fall within 
            # desired constraint limits
            crossovered = self.crossover_parents(parents, self.num_crossovers)
            logger.info(f'iter {i}: crossover yielded {len(crossovered)} new models')

            # sample some random samples to add to the parent mix 
            # to mitigage local minima
            rand_mix = self._sample_random_to_mix()

            unseen_pop = crossovered + mutated + rand_mix
            # shuffle before we pick a smaller population for the next stage
            logger.info(f'iter {i}: total unseen population before restriction {len(unseen_pop)}')
            unseen_pop = self.select_next_population(unseen_pop)
            logger.info(f'iter {i}: total unseen population after restriction {len(unseen_pop)}')

            # update the set of architectures ever visited
            self.all_pop.extend(unseen_pop)
