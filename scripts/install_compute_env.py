#!/usr/bin/env python3
"""Install an isolated pinned compute environment on XFS; never activate services."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--backend',choices=('rocm','xpu','openvino'),required=True)
    args=parser.parse_args()
    if subprocess.check_output(['findmnt','-n','-o','FSTYPE','-T',str(args.root)],text=True).strip()!='xfs':
        parser.error('runtime storage must be on mounted XFS')
    versions=json.loads((ROOT/'shared/runtime-versions.json').read_text())
    env={**os.environ,'UV_CACHE_DIR':str(args.root/'cache/uv'),
         'UV_PYTHON_INSTALL_DIR':str(args.root/'python')}
    if args.backend=='openvino':
        pins=versions['openvino']
        directory=args.root/('openvino/venv-'+pins['openvino'])
    else:
        pins=versions['pytorch_'+args.backend]
        suffix='rocm-'+pins['version'].split('+rocm')[1] if args.backend=='rocm' else 'xpu-'+pins['version']
        directory=args.root/'pytorch'/suffix
    def run(argv,**kwargs):
        return subprocess.run([str(x) for x in argv],env=env,check=True,**kwargs)
    if not (directory/'pyvenv.cfg').exists():
        run(['uv','venv','--python','3.12',directory])
    pip=['uv','pip','install','--python',directory/'bin/python']
    if args.backend=='openvino':
        with tempfile.NamedTemporaryFile(mode='w',suffix='.txt') as overrides:
            overrides.write('\n'.join(k+'=='+v for k,v in pins.items())+'\n');overrides.flush()
            run([*pip,'-r',ROOT/'intel/requirements.txt','--override',overrides.name])
    else:
        extra='['+','.join(pins['device_extras'])+']' if args.backend=='rocm' else ''
        run([*pip,'--index-url',pins['index'],'torch'+extra+'=='+pins['version']])
        run([*pip,'--index-url','https://pypi.org/simple','numpy=='+versions['numpy']])
    frozen=run(['uv','pip','freeze','--python',directory/'bin/python'],capture_output=True,text=True)
    (directory/'requirements.lock').write_text(frozen.stdout)
    print(json.dumps({'backend':args.backend,'environment':str(directory),
                      'status':'installed-isolated-not-serving'}))


if __name__=='__main__':
    main()
