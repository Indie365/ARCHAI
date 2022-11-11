# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""GPT-2 ONNX configuration.
"""

from typing import Any, Mapping, Optional, Tuple

import torch
from transformers.configuration_utils import PretrainedConfig

from archai.nlp.onnx.config_utils.onnx_config_base import OnnxConfig, OnnxConfigWithPast


class GPT2OnnxConfig(OnnxConfigWithPast):
    """Implements a GPT-2 ONNX configuration (with past key/values support)."""

    def __init__(
        self, config: PretrainedConfig,
        batch_size: int = 2,
        seq_len: int = 8,
        task: Optional[str] = "causal-lm",
        use_past: Optional[bool] = False
    ) -> None:
        super().__init__(
            config, task=task,
            batch_size=batch_size,
            seq_len=seq_len,
            use_past=use_past, past_key_values=2
        )

    @property
    def num_layers(self) -> int:
        return self.config.n_layer

    @property
    def is_ort_graph_optimizable(self) -> bool:
        return True

    @property
    def ort_graph_optimizer_args(self) -> Tuple[Any, ...]:
        return (self.num_attention_heads, self.hidden_size)


class GPT2FlexOnnxConfig(OnnxConfigWithPast):
    """Implements a GPT-2 Flex ONNX configuration (with past key/values support)."""

    def __init__(
        self, config: PretrainedConfig,
        batch_size: int = 2,
        seq_len: int = 8,
        task: Optional[str] = "causal-lm",
        use_past: Optional[bool] = False
    ) -> None:
        super().__init__(
            config, task=task,
            batch_size=batch_size,
            seq_len=seq_len,
            use_past=use_past, past_key_values=2
        )

    @property
    def num_layers(self) -> int:
        return self.config.n_layer

    @property
    def is_ort_graph_optimizable(self) -> bool:
        return all(nh == self.num_attention_heads[0] for nh in self.num_attention_heads)

    @property
    def ort_graph_optimizer_args(self) -> Tuple[Any, ...]:
        return (self.num_attention_heads[0], self.hidden_size)

    def generate_dummy_inputs(self) -> Mapping[str, torch.Tensor]:
        dummy_inputs = OnnxConfig.generate_dummy_inputs(self)

        if self.use_past:
            # [past_key_values, batch_size, n_head[i], past_seq_len, d_head[i]]
            dummy_inputs["past_key_values"] = tuple(
                [
                    torch.zeros(
                        self.config.past_key_values,
                        self.batch_size,
                        self.num_attention_heads[i],
                        self.seq_len,
                        self.hidden_size // self.num_attention_heads[i],
                    )
                    for i in range(self.num_layers)
                ]
            )

        return dummy_inputs
