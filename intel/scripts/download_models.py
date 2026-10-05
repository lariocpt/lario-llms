#!/usr/bin/env python3
"""Download approved Intel models into the XFS model store."""
import os
os.environ['HF_HOME'] = '/mnt/xfs/AI_Models/huggingface'
from huggingface_hub import snapshot_download
snapshot_download('OpenVINO/whisper-large-v3-turbo-fp16-ov', local_dir='/mnt/xfs/AI_Models/openvino/asr/whisper-large-v3-turbo-fp16')
snapshot_download('OpenVINO/Qwen3-8B-int4-ov', local_dir='/mnt/xfs/AI_Models/openvino/translation/qwen3-8b-int4')
snapshot_download('OpenVINO/Kokoro-82M-int8-ov', local_dir='/mnt/xfs/AI_Models/openvino/tts/kokoro-82m-int8')
