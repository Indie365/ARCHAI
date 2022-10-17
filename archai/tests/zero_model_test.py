# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import torch
from archai.nas.model import Model
from archai.nas.model_desc_builder import ModelDescBuilder
from archai.common.common import common_init

def test_darts_zero_model():
    conf = common_init(config_filepath='confs/algos/darts.yaml')
    conf_search = conf['nas']['search']
    model_desc = conf_search['model_desc']

    model_desc_builder = ModelDescBuilder()
    model_desc = model_desc_builder.build(model_desc)
    m = Model(model_desc, False, True)
    y, aux = m(torch.rand((1, 3, 32, 32)))
    assert isinstance(y, torch.Tensor) and y.shape==(1,10) and aux is None

def test_petridish_zero_model():
    conf = common_init(config_filepath='confs/petridish_cifar.yaml')
    conf_search = conf['nas']['search']
    model_desc = conf_search['model_desc']

    model_desc_builder = ModelDescBuilder()
    model_desc = model_desc_builder.build(model_desc)
    m = Model(model_desc, False, True)
    y, aux = m(torch.rand((1, 3, 32, 32)))
    assert isinstance(y, torch.Tensor) and y.shape==(1,10) and aux is None
