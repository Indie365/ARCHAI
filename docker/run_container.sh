#!/bin/bash
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

# Runs an interactive bash within the container
docker run --rm \
    --gpus all \
    --name nvidia22.07-archai0.6.6 \
    --shm-size=10g \
    --ipc=host \
    --ulimit memlock=-1 \
    --ulimit stack=67108864 \
    -e NCCL_P2P_LEVEL=NVL \
    -it nvidia22.07-archai0.6.6:latest