"""Native OpenVINO GenAI Kokoro speech, with explicit local voice embeddings."""
import base64
import io
import os
import threading
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Literal
import numpy as np
import openvino as ov
import openvino_genai as genai
import soundfile as sf
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

MODEL_DIR=Path(os.getenv('TTS_MODEL_DIR','/mnt/xfs/AI_Models/openvino/tts/kokoro-82m-int8'))
DEVICE=os.getenv('TTS_DEVICE','CPU')
LANGUAGES={'a':'en-us','b':'en-gb','e':'es','f':'fr-fr','h':'hi','i':'it','p':'pt-br'}
pipe=None
lock=threading.Lock()

@asynccontextmanager
async def lifespan(app):
 global pipe
 pipe=genai.Text2SpeechPipeline(str(MODEL_DIR),DEVICE)
 yield
app=FastAPI(title='Intel Kokoro speech',lifespan=lifespan)

class Request(BaseModel):
 text:str=Field(min_length=1,max_length=2000)
 voice:str=Field(default='af_heart',pattern=r'^[a-z][fm]_[a-z0-9]+$')
 format:Literal['wav']='wav'
 speed:float=Field(default=1.0,ge=0.5,le=2.0)

@app.post('/synthesize')
def synthesize(req:Request):
 if pipe is None:raise HTTPException(503,'Model is not ready')
 voice=MODEL_DIR/'voices'/f'{req.voice}.bin'
 language=LANGUAGES.get(req.voice[0])
 if not voice.is_file() or language is None:raise HTTPException(400,'Unsupported voice')
 with lock:
  speaker=ov.Tensor(np.fromfile(voice,dtype=np.float32).reshape(pipe.get_speaker_embedding_shape()))
  result=pipe.generate(req.text,speaker,language=language,speed=req.speed)
 audio=np.concatenate([np.asarray(s.data).reshape(-1) for s in result.speeches])
 buf=io.BytesIO();sf.write(buf,audio,result.output_sample_rate,format='WAV',subtype='PCM_16')
 return {'audio_base64':base64.b64encode(buf.getvalue()).decode(),'format':'wav','sample_rate':result.output_sample_rate,'voice':req.voice,'model':MODEL_DIR.name,'device':DEVICE}

@app.get('/voices')
def voices():
 return {'voices':[{'id':p.stem,'language':LANGUAGES[p.stem[0]]} for p in sorted((MODEL_DIR/'voices').glob('*.bin')) if p.stem[0] in LANGUAGES]}

@app.get('/health')
def health():return {'status':'healthy' if pipe else 'unavailable','model_loaded':pipe is not None,'model':MODEL_DIR.name,'device':DEVICE}

if __name__=='__main__':
 import uvicorn
 uvicorn.run(app,host=os.getenv('BIND_HOST','127.0.0.1'),port=8004)
