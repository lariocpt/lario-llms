"""Run the pinned production engine with the exact registered context/identity."""
import json, os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from arcB70.vllm.prepare import command
from shared.serving.catalog import profiles
from shared.serving.state import off_marker
reg=json.loads((ROOT/'arcB70/models.json').read_text())
if reg.get('serving_engine')!='vllm' or off_marker(reg).exists():raise SystemExit('vLLM is not enabled')
key,profile=next(iter(profiles(reg).items()))
argv=command()
argv=[('lario-b70-vllm' if v=='lario-b70-vllm-candidate' else
       f'127.0.0.1:{reg["backend_port"]}:8000' if v=='127.0.0.1:11458:8000' else
       f'MAX_MODEL_LEN={profile["context"]}' if v.startswith('MAX_MODEL_LEN=') else
       'SERVED_NAME='+key if v.startswith('SERVED_NAME=') else v) for v in argv]
# Pass the credential through the inherited environment, never a process argument.
os.environ['VLLM_API_KEY']=os.environ['LARIO_BACKEND_KEY']
argv[2:2]=['-e','VLLM_API_KEY']
os.execvp(argv[0],argv)
