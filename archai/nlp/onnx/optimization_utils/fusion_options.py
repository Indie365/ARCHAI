# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Options that enables nodes' fusion.
"""

from typing import Optional


class AttentionMaskFormat:
    """Enumerator for attention mask shape."""

    MaskIndexEnd = 0
    MaskIndexEndAndStart = 1
    AttentionMask = 2
    NoMask = 3


class FusionOptions:
    """Operators that should be fused in the ONNX graph."""

    def __init__(self, model_type: str) -> None:
        """Defines an initialization method.

        Args:
            model_type: Type of model.

        """

        self.enable_shape_inference = True
        self.enable_qordered_matmul = True

        self.enable_gelu = True
        self.enable_bias_gelu = True
        self.enable_gelu_approximation = False
        self.enable_gemm_fast_gelu = False

        self.enable_layer_norm = True
        self.enable_embed_layer_norm = True
        self.enable_skip_layer_norm = True
        self.enable_bias_skip_layer_norm = True

        if model_type in ["gpt2", "gpt2_flex"]:
            self.enable_embed_layer_norm = False
            self.enable_skip_layer_norm = False

        self.enable_attention = True
        self.attention_mask_format = AttentionMaskFormat.AttentionMask

    def use_raw_attention_mask(self, use_raw_mask: Optional[bool] = True) -> None:
        """Enables the usage of raw attention mask.

        Args:
            use_raw_mask: Whether raw mask should be used or not.

        """

        if use_raw_mask:
            self.attention_mask_format = AttentionMaskFormat.AttentionMask
        else:
            self.attention_mask_format = AttentionMaskFormat.MaskIndexEnd

    def disable_attention_mask(self) -> None:
        """Disables the usage of attention mask."""

        self.attention_mask_format = AttentionMaskFormat.NoMask
