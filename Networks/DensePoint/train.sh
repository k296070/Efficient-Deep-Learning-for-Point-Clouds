#!/usr/bin/env sh
mkdir -p log
now=$(date +"%Y%m%d_%H%M%S")
log_name="Cls_LOG_"$now""
export CUDA_VISIBLE_DEVICES=0
python -u train.py \
--config cfgs/config_cls.yaml \
2>&1|tee log/$log_name.log &
