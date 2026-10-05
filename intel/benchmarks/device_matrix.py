#!/usr/bin/env python3
"""Run one real GenAI workload per process/device; write measurable evidence as JSON."""
import argparse
import json
import time
from pathlib import Path
import numpy as np
import openvino as ov
import openvino_genai as genai

p=argparse.ArgumentParser()
p.add_argument('task', choices=['embedding','asr','translation','tts'])
p.add_argument('device')
p.add_argument('model')
p.add_argument('--audio')
p.add_argument('--output', required=True)
a=p.parse_args()
r={'task':a.task,'device':a.device,'model':a.model,'openvino':ov.__version__,'genai':genai.get_version()}
t=time.perf_counter()
try:
 c=ov.Core()
 r['available_devices']={d:c.get_property(d,'FULL_DEVICE_NAME') for d in c.available_devices}
 if a.device not in r['available_devices']:
  raise RuntimeError('Requested device is not enumerated')
 if a.task=='embedding':
  cfg=genai.TextEmbeddingPipeline.Config()
  cfg.max_length=8192 if a.device!='NPU' else 512
  cfg.pooling_type=genai.TextEmbeddingPipeline.PoolingType.CLS
  cfg.normalize=True
  if a.device=='NPU':
   cfg.pad_to_max_length=True
   cfg.batch_size=1
  pipe=genai.TextEmbeddingPipeline(a.model,a.device,cfg)
 elif a.task=='asr':
  pipe=genai.WhisperPipeline(a.model,a.device)
 elif a.task=='translation':
  pipe=genai.LLMPipeline(a.model,a.device)
 else:
  pipe=genai.Text2SpeechPipeline(a.model,a.device)
 r['compile_seconds']=time.perf_counter()-t
 t=time.perf_counter()
 if a.task=='embedding':
  texts=['The Geekom serves coding models.', 'A Radeon card serves Hermes agents.', 'O computador traduz texto.', 'Die rekenaar vertaal teks.']
  v=np.array([pipe.embed_query(text) for text in texts])
  r['shape']=list(v.shape); r['norms']=np.linalg.norm(v,axis=1).tolist()
  np.save(a.output+'.npy',v)
 elif a.task=='asr':
  import soundfile as sf
  audio,sr=sf.read(a.audio,dtype='float32')
  assert sr==16000 and audio.ndim==1
  r['text']=''.join(pipe.generate(audio,max_new_tokens=128,language='<|en|>',task='transcribe').texts)
  r['audio_seconds']=len(audio)/sr
 elif a.task=='translation':
  messages=[{'role':'system','content':'Translate from English to Portuguese. Return only the translation.'}, {'role':'user','content':'The server is ready and the documents are stored safely.'}]
  prompt=pipe.get_tokenizer().apply_chat_template(messages,True,extra_context={'enable_thinking':False})
  r['text']=str(pipe.generate(prompt,max_new_tokens=128,do_sample=False,apply_chat_template=False))
  assert '<think>' not in r['text'] and 'servidor' in r['text'].lower(), 'Translation output failed smoke check'
 else:
  speaker=ov.Tensor(np.fromfile(Path(a.model)/'voices/af_heart.bin',dtype=np.float32).reshape(pipe.get_speaker_embedding_shape()))
  result=pipe.generate('The server is ready.',speaker,language='en-us')
  audio=np.concatenate([np.array(s.data).reshape(-1) for s in result.speeches])
  r['sample_rate']=result.output_sample_rate
  r['audio_seconds']=len(audio)/r['sample_rate']
  assert audio.size and np.isfinite(audio).all() and np.max(np.abs(audio))>0.001, 'Empty or silent speech'
  import soundfile as sf
  sf.write('/tmp/lario-tts-'+a.device.replace('.','-')+'.wav',audio,r['sample_rate'])
 r['inference_seconds']=time.perf_counter()-t
 r['status']='passed'
except Exception as e:
 r['status']='failed'; r['error']=str(e)
r['total_seconds']=time.perf_counter()-t if 'compile_seconds' not in r else r['compile_seconds']+r.get('inference_seconds',time.perf_counter()-t)
Path(a.output).write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps(r),flush=True)
