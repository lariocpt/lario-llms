#!/usr/bin/env python3
"""Build a pinned llama.cpp release in a new runtime directory outside XFS; never activate it."""
import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def build(root, backend, jobs, rocm_root=None, gpu_targets='gfx1151,gfx1100', sycl_root=Path('/opt/intel/oneapi/compiler/latest'), mkl_root=None):
    pins = json.loads((ROOT/'shared/runtime-versions.json').read_text())
    pin = pins['llama_cpp_arc_sycl' if backend=='sycl' else 'llama_cpp']
    if not re.fullmatch(r'[0-9a-f]{40}',pin['commit']):
        raise ValueError('expected exact upstream commit')
    directory = root/'llama.cpp'/pin['release']/backend
    source, output = directory/'src', directory/'build'
    directory.mkdir(parents=True,exist_ok=True)
    def run(argv):
        subprocess.run([str(x) for x in argv],check=True)
    if not (source/'.git').exists():
        run(['git','init',source])
        run(['git','-C',source,'remote','add','origin',pin['repository']])
    dirty=subprocess.check_output(['git','-C',str(source),'status','--porcelain'],text=True)
    if dirty.strip():
        raise RuntimeError('candidate source is dirty; preserve and inspect it')
    run(['git','-C',source,'fetch','--depth','1','origin',pin['commit']])
    run(['git','-C',source,'checkout','--detach',pin['commit']])
    flags=['-DCMAKE_BUILD_TYPE=Release','-DLLAMA_BUILD_TESTS=OFF',
           '-DGGML_NATIVE=ON']
    if backend=='vulkan':
        flags+=['-DGGML_VULKAN=ON']
    elif backend=='cuda':
        flags+=['-DGGML_CUDA=ON','-DCMAKE_CUDA_ARCHITECTURES=120',
                '-DCMAKE_CUDA_HOST_COMPILER=/usr/bin/g++-15',
                '-DCMAKE_CXX_COMPILER=/usr/bin/g++-15']
    elif backend=='sycl':
        flags+=['-DGGML_SYCL=ON','-DGGML_SYCL_F16=ON','-DGGML_SYCL_DNN=OFF',
                '-DCMAKE_C_COMPILER='+str(sycl_root/'bin/icx'),
                '-DCMAKE_CXX_COMPILER='+str(sycl_root/'bin/icpx'),
                '-DCMAKE_BUILD_RPATH='+str(sycl_root/'lib')]
        if mkl_root is not None:
            # Explicit cache entries override a previous CPU-only MKL discovery.
            flags+=['-DMKL_ROOT='+str(mkl_root),
                    '-DMKL_DIR='+str(mkl_root/'lib/cmake/mkl'),
                    '-DMKL_INCLUDE='+str(mkl_root/'include'),
                    '-DCMAKE_BUILD_RPATH='+str(sycl_root/'lib')+';'+str(mkl_root/'lib')]
    else:
        if rocm_root is None:
            raise ValueError('HIP build requires an explicit isolated ROCm root')
        if not re.fullmatch(r'gfx[0-9a-f]+(?:,gfx[0-9a-f]+)*',gpu_targets):
            raise ValueError('invalid HIP GPU targets')
        flags+=['-DGGML_HIP=ON','-DGPU_TARGETS='+gpu_targets.replace(',',';'),
                '-DCMAKE_PREFIX_PATH='+str(rocm_root),
                '-DCMAKE_C_COMPILER='+str(rocm_root/'llvm/bin/clang'),
                '-DCMAKE_CXX_COMPILER='+str(rocm_root/'llvm/bin/clang++'),
                '-DCMAKE_HIP_COMPILER='+str(rocm_root/'llvm/bin/clang++'),
                '-DCMAKE_BUILD_RPATH='+str(rocm_root/'lib')]
    run(['cmake','-S',source,'-B',output,'-GNinja',*flags])
    run(['cmake','--build',output,'--parallel',str(jobs),'--target',
         'llama-server','llama-cli','llama-bench'])
    binary=output/'bin/llama-server'
    result=subprocess.run([str(binary),'--version'],capture_output=True,text=True,check=True)
    receipt={**pin,'backend':backend,'binary':str(binary),'flags':flags,
             'version':(result.stdout+result.stderr).strip(),
             'status':'built-not-activated'}
    (directory/'build-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True,help='existing executable-runtime directory outside XFS')
    parser.add_argument('--backend',choices=('vulkan','cuda','hip','sycl'),required=True)
    parser.add_argument('--jobs',type=int,default=4)
    parser.add_argument('--rocm-root',type=Path)
    parser.add_argument('--gpu-targets',default='gfx1151,gfx1100')
    parser.add_argument('--sycl-root',type=Path,default=Path('/opt/intel/oneapi/compiler/latest'))
    parser.add_argument('--mkl-root',type=Path)
    args=parser.parse_args()
    if not 1<=args.jobs<=16:
        parser.error('jobs must be 1..16')
    filesystem=subprocess.check_output(['findmnt','-n','-o','FSTYPE','-T',str(args.root)],text=True).strip()
    if filesystem=='xfs':
        parser.error('executable runtime storage must not be on XFS')
    build(args.root,args.backend,args.jobs,args.rocm_root,args.gpu_targets,args.sycl_root,args.mkl_root)


if __name__=='__main__':
    main()
