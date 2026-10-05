"""Compare original SentenceTransformer BGE-M3 against the GenAI FP16 export."""
import os
os.environ['HF_HOME']='/mnt/xfs/AI_Models/huggingface'
import json
from pathlib import Path
import numpy as np
from transformers import AutoModel, AutoTokenizer
import torch
texts=['The Geekom serves coding models.', 'A Radeon card serves Hermes agents.', 'O computador traduz texto.', 'Die rekenaar vertaal teks.']
model=AutoModel.from_pretrained('BAAI/bge-m3',local_files_only=True).eval()
tokenizer=AutoTokenizer.from_pretrained('BAAI/bge-m3',local_files_only=True)
with torch.no_grad():
 v=model(**tokenizer(texts,padding=True,return_tensors='pt')).last_hidden_state[:,0]
 v=torch.nn.functional.normalize(v,p=2,dim=1).numpy()
results={}
for device in ['CPU','GPU']:
 x=np.load('intel/research/embedding-'+device+'.json.npy')
 cosine=np.sum(v*x,axis=1)/(np.linalg.norm(v,axis=1)*np.linalg.norm(x,axis=1))
 results[device]={'cosine_to_original':cosine.tolist(),'min_cosine':float(cosine.min()),'same_pairwise_ranking':bool(np.array_equal(np.argsort(v@v.T,axis=1),np.argsort(x@x.T,axis=1)))}
Path('intel/research/embedding-compatibility.json').write_text(json.dumps(results,indent=2)+'\n')
print(json.dumps(results))
assert min(x['min_cosine'] for x in results.values()) > .999
