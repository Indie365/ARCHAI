# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Huggingface's Transformer-XL for ONNX.
"""

from collections import OrderedDict
from typing import Any, Dict, Mapping

from archai.nlp.models.config_base import OnnxConfig
from archai.nlp.models.mem_transformer.onnx_mem_transformer import MemTransformerLMOnnxModel as HfTransfoXLOnnxModel


class HfTransfoXLOnnxConfig(OnnxConfig):
    """Huggingface's Transformer-XL ONNX-based configuration.

    """

    def __init__(self, model_config: Dict[str, Any]) -> None:
        model_config['past_key_values'] = 0
        model_config['model_type'] = 'transfo-xl'

        super().__init__(model_config)

    @property
    def inputs(self) -> Mapping[str, Mapping[int, str]]:
        common_inputs = OrderedDict({'input_ids', {0: 'batch_size', 1: 'seq_len'}})

        return common_inputs

    @property
    def outputs(self) -> Mapping[str, Mapping[int, str]]:
        common_outputs = OrderedDict({'probs', {0: 'batch_size'}})

        return common_outputs
