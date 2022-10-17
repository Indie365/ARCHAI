# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from typing import Optional, Callable, Type
import os

import torch
from torch.utils.data import DataLoader
from torch import nn, Tensor
from torch.optim.optimizer import Optimizer
from torch.optim.lr_scheduler import _LRScheduler

from overrides import overrides, EnforceOverrides

from archai.common.config import Config
from archai.common import common, utils
from archai.common.common import logger
from archai.nas.model import Model
from archai.nas.model_desc import ModelDesc
from archai.nas.arch_trainer import ArchTrainer
from archai.common.trainer import Trainer
from archai.nas.vis_model_desc import draw_model_desc
from archai.common.checkpoint import CheckPoint
from archai.common.ml_utils import set_optim_lr

TFreezeTrainer = Optional[Type['FreezeTrainer']]


class FreezeTrainer(ArchTrainer, EnforceOverrides):
    def __init__(self, conf_train: Config, model: nn.Module,
                 checkpoint:Optional[CheckPoint]) -> None:
        super().__init__(conf_train, model, checkpoint) 


    @overrides
    def pre_fit(self, train_dl: DataLoader, val_dl: Optional[DataLoader]) -> None:
        super().pre_fit(train_dl, val_dl)

        # freeze everything other than the last layer
        self._freeze_but_last_layer()


    def _freeze_but_last_layer(self) -> None:
        
        # Freezing via module names
        for module in self.model.modules():
            module.requires_grad = False
        
        # Unfreeze only some
        for name, module in self.model.named_modules():
            for identifier in self.conf_train['identifiers_to_unfreeze']:
                if identifier in name:
                    module.requires_grad = True

        for name, module in self.model.named_modules():
            if module.requires_grad:
                logger.info(f'{name} requires grad')

        # NOTE: freezing via named_parameters() doesn't expose all parameters? Check with Shital.    
        # for name, param in self.model.named_parameters():
        #     param.requires_grad = False
        
        # for name, param in self.model.named_parameters():
        #     # TODO: Make the layer names to be updated a config value
        #     # 'fc' for resnet18
        #     # 'logits_op._op' for darts search space
        #     for identifier in self.conf_train['proxynas']['identifiers_to_unfreeze']:
        #         if identifier in name:
        #             param.requires_grad = True

        # for name, param in self.model.named_parameters():
        #     if param.requires_grad:
        #         logger.info(f'{name} requires grad')

            