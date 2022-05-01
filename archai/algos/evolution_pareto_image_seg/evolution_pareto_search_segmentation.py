import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from overrides.overrides import overrides
from typing import List, Tuple, Optional, Dict
import pandas as pd
import ray

import torch

import numpy as np
import plotly.graph_objects as go
from tqdm import tqdm

from archai.common.common import get_conf, get_conf_common
from archai.common.common import get_expdir
from archai.nas.discrete_search_space import DiscreteSearchSpace
from archai.nas.searcher import Searcher, SearchResult
from archai.common.common import logger
from archai.common.config import Config
from archai.common.trainer import Trainer
from archai.algos.evolution_pareto.evolution_pareto_search import EvolutionParetoSearch
from archai.nas.arch_meta import ArchWithMetaData
from archai.common import utils
from archai.search_spaces.discrete_search_spaces.segmentation_search_spaces.discrete_search_space_segmentation import DiscreteSearchSpaceSegmentation

from archai.algos.evolution_pareto_image_seg.segmentation_trainer import SegmentationTrainer, get_custom_overall_metrics
from archai.algos.evolution_pareto_image_seg.utils import get_onnx_latency, to_onnx, get_utc_date
from archai.algos.evolution_pareto_image_seg.remote_benchmark import RemoteAzureBenchmark

from archai.nas.constraints.torch_constraints import measure_torch_inference_latency, measure_torch_peak_memory
from archai.nas.constraints.pareto_frontier import find_pareto_frontier_points

class EvolutionParetoSearchSegmentation(EvolutionParetoSearch):

    @overrides
    def search(self, conf_search:Config)->SearchResult:

        self.dataroot = utils.full_path(conf_search['loader']['dataset']['dataroot'])
        self.dataset_name = conf_search['loader']['dataset']['name']
        self.conf_train = conf_search['trainer']
        self.conf_loader = conf_search['loader']
        self.min_mac = conf_search['min_mac']
        self.max_mac = conf_search['max_mac']
        self.min_layers = conf_search['min_layers']
        self.max_layers = conf_search['max_layers']
        self.max_downsample_factor = conf_search['max_downsample_factor']
        self.skip_connections = conf_search['skip_connections']
        self.max_skip_connection_length = conf_search['max_skip_connection_length']
        self.max_scale_delta = conf_search['max_scale_delta']
        self.max_post_upsample_layers = conf_search['max_post_upsample_layers']
        self.min_base_channels = conf_search['min_base_channels']
        self.max_base_channels = conf_search['max_base_channels']
        self.base_channels_binwidth = conf_search['base_channels_binwidth']
        self.min_delta_channels = conf_search['min_delta_channels']
        self.max_delta_channels = conf_search['max_delta_channels']
        self.delta_channels_binwidth = conf_search['delta_channels_binwidth']

        self.init_architectures_from_dir = conf_search['init_architectures_from_dir']
        self.use_remote_benchmark = conf_search['use_remote_benchmark']

        if self.use_remote_benchmark:
            remote_config = conf_search['remote_benchmark_config']
            assert 'connection_string_env_var_name' in remote_config
            assert remote_config['connection_string_env_var_name'] in os.environ

            con_string = os.environ[remote_config['connection_string_env_var_name']]

            self.remote_benchmark = RemoteAzureBenchmark(
                connection_string=con_string, 
                blob_container_name=remote_config['blob_container_name'],
                table_name=remote_config['table_name'],
                partition_key=remote_config['partition_key'],
                overwrite=remote_config['overwrite']
            )

        # eval cache so that if search visits
        # a network already evaluated then we don't
        # evaluate it again. 
        self.eval_cache = dict()

        # init ray
        ray.init()

        super().search(conf_search)


    @overrides
    def get_search_space(self)->DiscreteSearchSpaceSegmentation:
        return DiscreteSearchSpaceSegmentation(self.dataset_name, 
                                               min_mac=self.min_mac, 
                                               max_mac=self.max_mac)

    @overrides
    def _sample_init_population(self) -> List[ArchWithMetaData]:
        if self.init_architectures_from_dir:
            arch_dir = Path(self.init_architectures_from_dir)
            arch_files = list(arch_dir.glob('*.yaml'))
            search_space = self.get_search_space()
            logger.info(f'Loading {len(arch_files)} seed models for first iteration.')

            return [search_space.load_from_file(arch_file) for arch_file in arch_files]
        return super()._sample_init_population()

    @overrides
    def calc_memory_latency(self, population:List[ArchWithMetaData])->None:
        # computes memory and latency of each model
        cache_misses = 0
        for p in tqdm(population):
            latency_ms = get_onnx_latency(p.arch, img_size=p.arch.img_size)

            # TODO: get peak memory of the onnx model
            # instead of the torch model
            peak_mem_mb = measure_torch_peak_memory(p.arch,
                                                    use_quantization=False,
                                                    input_dims=(1, 3, p.arch.img_size, p.arch.img_size),
                                                    n_threads=1,
                                                    device='cpu')

            if not self.use_remote_benchmark:
                p.metadata['latency'], p.metadata['memory'] = latency_ms, peak_mem_mb
            else:
                p.metadata['proxy_latency'], p.metadata['proxy_memory'] = latency_ms, peak_mem_mb
                
                # Checks if this architecture was already benchmarked before
                if p.metadata['archid'] not in self.remote_benchmark:
                    cache_misses += 1
                    self.remote_benchmark.send_model(p)
        if self.use_remote_benchmark:
            logger.info(f'{len(population) - cache_misses} benchmark cache hits')

    @overrides
    def calc_task_accuracy(self, population:List[ArchWithMetaData])->None:
        # computes task accuracy of each model
        # and updates the meta data

        # folder where to store training logs of each model
        exp_dir = utils.full_path(get_expdir())
        save_folder = os.path.join(exp_dir, f'arch_eval_logs_iter_{self.iter_num}')
        os.makedirs(save_folder, exist_ok=True)

        fit_refs = []

        pop_to_eval = [
            p for p in population
            if p.metadata['archid'] not in self.eval_cache
        ]

        if len(pop_to_eval) < len(population):
            logger.info(
                f'{len(population) - len(pop_to_eval)} evaluation cache hits'
            )

        for p in pop_to_eval:
            # create a ray actor per model to be trained
            actor_ref = self._create_training_job(p)
            # create a folder name for the model training logs
            run_path = os.path.join(save_folder, str(p.metadata['archid']))
            os.makedirs(run_path, exist_ok=True)
            # fit and validate the model 
            fit_refs.append(actor_ref.fit_and_validate.remote(run_path=run_path))
        
        # gather all results for all models
        results = ray.get(fit_refs)

        # Cached results
        for p in population:
            if p.metadata['archid'] in self.eval_cache:
                p.metadata['f1'] = self.eval_cache[p.metadata['archid']]

        # Evaluation results
        for r, p in zip(results, pop_to_eval):
            p.metadata['f1'] = r
            self.eval_cache[p.metadata['archid']] = r

    @overrides
    def on_calc_task_accuracy_end(self, current_pop: List[ArchWithMetaData]) -> None:
        if self.use_remote_benchmark:
            evaluated = set()
            logger.info('Gathering remote benchmark results...')
            pbar = tqdm(total=len(current_pop), desc='Gathering remote benchmark results...')

            while len(evaluated) < len(current_pop):
                for i, p in enumerate(current_pop):
                    # Gets the metrics for all the models in `current_pop``.
                    # we don't need to worry about the cost of checking the same model
                    # more than once since the cost of `get_entity` is infimal
                    # and we may get better estimates for the latency mean when we 
                    # check the same model again (given how the pipeline is constructed)

                    metrics = self.remote_benchmark.get_entity(
                        str(p.metadata['archid'])
                    )

                    # Updates the metadata with the remote benchmark metrics
                    if 'mean' in metrics and metrics['mean']:
                        if 'memory_usage' in metrics and metrics['memory_usage']:
                            p.metadata['latency'] = metrics['mean']
                            p.metadata['memory'] = metrics['memory_usage']
                            
                            if i not in evaluated:
                                evaluated.add(i)
                                pbar.update()

                if len(evaluated) < len(current_pop):
                    pbar.set_description('Sleeping...')
                    logger.info(
                        'Waiting remote benchmark results for '
                        f'{len(current_pop) - len(evaluated)} models...'
                    )
                    time.sleep(120)

            logger.info('Finished gathering remote benchmark results.')


    def _create_training_job(self, arch:ArchWithMetaData)->List:
        ''' Creates a ray actor that will train a single architecture '''
        # region config
        self.evaluate_for_steps = self.conf_train['evaluate_for_steps']  
        self.val_check_interval = self.conf_train['val_check_interval']  
        self.val_size = self.conf_train['val_size']
        self.gpus = self.conf_train['gpus']
        self.img_size = self.conf_train['img_size']
        self.augmentation = self.conf_train['augmentation']
        self.lr = self.conf_train['lr']
        self.lr_exp_decay_gamma = self.conf_train['lr_exp_decay_gamma']
        self.criterion_name = self.conf_train['criterion_name']
        self.batch_size = self.conf_loader['batch_size']
        self.seed = get_conf_common()['seed']
        # region

        # train
        dataset_dir = os.path.join(self.dataroot, 'face_synthetics')
        ref = SegmentationTrainer.remote(arch.arch, 
                                      dataset_dir=dataset_dir, 
                                      max_steps=self.evaluate_for_steps,
                                      val_check_interval=self.val_check_interval,
                                      val_size=self.val_size,
                                      img_size=self.img_size,
                                      augmentation=self.augmentation,
                                      batch_size=self.batch_size,
                                      lr=self.lr,
                                      lr_exp_decay_gamma=self.lr_exp_decay_gamma,
                                      criterion_name=self.criterion_name, 
                                      gpus=self.gpus,
                                      seed=self.seed)
        return ref

    @overrides
    def update_pareto_frontier(self, population:List[ArchWithMetaData])->List[ArchWithMetaData]:
        # need all decreasing or increasing quantities 
        all_errors = [1.0 - p.metadata['f1'] for p in population]
        all_latencies = [p.metadata['latency']  for p in population]
        all_memories = [p.metadata['memory']  for p in population]

        xs = np.array(all_errors).reshape(-1, 1)
        ys = np.array(all_latencies).reshape(-1, 1)
        zs = np.array(all_memories).reshape(-1, 1)
        
        points = np.concatenate((xs, ys, zs), axis=1)
        points_idx = find_pareto_frontier_points(points, is_decreasing=True)
        pareto_points = [population[idx] for idx in points_idx]

        # save all the pareto points
        self._save_yaml(pareto_points, basename='pareto')

        return pareto_points


    def _save_yaml(self, points:List[ArchWithMetaData], basename='pareto')->None:
        exp_dir = utils.full_path(get_expdir())
        save_folder = os.path.join(exp_dir, f'{basename}_iter_{self.iter_num}')
        os.makedirs(save_folder, exist_ok=True)
        for p in points:
            this_name = os.path.join(save_folder, str(p.metadata['archid']) + '.yaml')
            p.arch.to_file(this_name)


    @overrides
    def mutate_parents(self, parents:List[ArchWithMetaData], mutations_per_parent: int = 1)->List[ArchWithMetaData]:
        ''' Using the nearest neighbors as mutations'''
        mutations = {}

        for p in parents:
            candidates = {}
            nb_tries = 0
            patience = 20

            while len(candidates) < mutations_per_parent and nb_tries < patience:
                for nbr in self.search_space.get_neighbors(p):
                    if nbr.metadata['archid'] not in self.eval_cache:
                        candidates[nbr.metadata['archid']] = nbr
                nb_tries += 1

            mutations.update(candidates)

        # TODO: there will be a lot of neighbors
        # so might want to downsample them
        return list(mutations.values())


    @overrides
    def crossover_parents(self, parents:List[ArchWithMetaData])->List[ArchWithMetaData]:
        '''TODO: Returning empty for now '''
        return []

    @overrides
    def plot_search_state(self, all_pop:List[ArchWithMetaData], pareto:List[ArchWithMetaData], iter_num:int) -> None:
        # TODO: refactor this function to use a dataframe instead of the model list
        all_data, pareto_data = [
            {k: [p.metadata[k] for p in pop] for k in ['f1', 'latency', 'memory', 'archid'] }
            for pop in [all_pop, pareto]
        ]

        # Converts archids to str
        all_data['archid'] = list(map(str, all_data['archid']))

        fig = go.Figure()
        fig.add_trace(go.Scatter3d(x=all_data['f1'], 
                                   y=all_data['latency'], 
                                   z=all_data['memory'],
                                   text=all_data['archid'],
                                   mode='markers',
                                   marker_color='blue',
                                   showlegend=True,
                                   name='All visited architectures'))

        fig.add_trace(go.Scatter3d(x=pareto_data['f1'], 
                                   y=pareto_data['latency'], 
                                   z=pareto_data['memory'],
                                   text=pareto_data['archid'],
                                   mode='markers',
                                   marker_color='red',
                                   showlegend=True,
                                   name='Pareto architectures'))

        title_text = f'Search State Iter {iter_num}'
        xaxis_title = 'Accuracy (validation f1)'
        yaxis_title = 'Latency (ms)'
        zaxis_title = 'Memory (mb)'

        fig.update_layout(title_text=title_text,
                          scene=dict(xaxis_title=xaxis_title,
                                     yaxis_title=yaxis_title,
                                     zaxis_title=zaxis_title))

        expdir = get_expdir()
        html_path = os.path.join(expdir, f'search_state_{iter_num}.html')
        fig.write_html(html_path)

        png_path = os.path.join(expdir, f'search_state_{iter_num}.png')
        fig.write_image(png_path, engine='kaleido', width=1500, height=1500, scale=1) 

    @overrides
    def save_search_status(self, all_pop:List[ArchWithMetaData], pareto:List[ArchWithMetaData], iter_num:int) -> None:
        all_data = {
            k: [p.metadata[k] if k in p.metadata else None for p in all_pop]
            for k in ['archid', 'f1', 'latency', 'memory', 'proxy_latency', 'proxy_memory', 'parent']
        }
        pareto_ids = [p.metadata['archid'] for p in pareto]

        status_df = pd.DataFrame(all_data)
        status_df['nb_iterations'] = iter_num
        status_df['is_pareto'] = False
        status_df.loc[status_df['archid'].isin(pareto_ids), 'is_pareto'] = True

        # Saves the status
        expdir = get_expdir()
        status_df.to_csv(os.path.join(expdir, f'search_status_{iter_num}.csv'))
