"""Public-domain LibriSpeech test sample, prepared at Whisper's 16kHz rate."""
import urllib.request
from pathlib import Path
p=Path('/tmp/lario-asr.flac')
url='https://huggingface.co/datasets/Narsil/asr_dummy/resolve/main/1.flac'
with urllib.request.urlopen(url, timeout=60) as response:
 p.write_bytes(response.read())
import subprocess
subprocess.run(['ffmpeg','-y','-v','error','-i',str(p),'-ar','16000','-ac','1','/tmp/lario-asr.wav'],check=True)
