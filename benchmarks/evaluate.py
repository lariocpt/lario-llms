"""Bounded pure-function evaluation. Run only as an isolated benchmark subprocess."""
import ast
from collections import Counter
from types import SimpleNamespace
import json
import resource
import sys

payload=json.load(sys.stdin)
resource.setrlimit(resource.RLIMIT_CPU,(2,2))
resource.setrlimit(resource.RLIMIT_AS,(128*1024*1024,128*1024*1024))
resource.setrlimit(resource.RLIMIT_FSIZE,(0,0))
source=payload['source']
tree=ast.parse(source)
allowed_attributes={'setdefault','Counter','fromkeys','add','count','append','extend','lower','isalnum','strip','split','join','get','items','values','keys','pop','sort','replace','sub','findall','match','fullmatch'}
for node in ast.walk(tree):
    if isinstance(node,ast.Import) and any(alias.name not in ('re','collections') for alias in node.names):
        raise ValueError('only re and collections.Counter imports supported')
    if isinstance(node,ast.ImportFrom) and (node.level or node.module not in ('re','collections') or node.module=='collections' and any(alias.name!='Counter' for alias in node.names)):
        raise ValueError('only re and collections.Counter imports supported')
    if isinstance(node,(ast.Global,ast.Nonlocal,ast.ClassDef)):
        raise ValueError('unsupported code in pure fixture')
    if isinstance(node,ast.Name) and '__' in node.id:raise ValueError('dunder forbidden')
    if isinstance(node,ast.Attribute) and node.attr not in allowed_attributes:raise ValueError('unsupported attribute')
safe={name:getattr(__import__('builtins'),name) for name in
      ['len','sorted','set','list','dict','tuple','range','enumerate','zip','min','max','sum','abs','all','any','int','float','str','bool','reversed','ValueError','isinstance']}
scope={'__builtins__':safe}
def safe_import(name,*args,**kwargs):
    if name=='collections':return SimpleNamespace(Counter=Counter)
    if name!='re':raise ValueError('unsupported import')
    return __import__('re')
safe['__import__']=safe_import
exec(compile(tree,'solution.py','exec'),scope)
checks=[]
for arguments,expected in payload['checks']:
    if payload.get('integer_dict_keys'):
        expected={int(key):value for key,value in expected.items()}
    try:actual=scope['solve'](*arguments) if payload['two_args'] else scope['solve'](arguments)
    except Exception:checks.append(False)
    else:checks.append(actual==expected)
if payload.get('invalid_chunk_size'):
    try:scope['solve']([1],0)
    except ValueError:checks.append(True)
    except Exception:checks.append(False)
    else:checks.append(False)
print(json.dumps({'checks':checks,'passed':all(checks)}))
