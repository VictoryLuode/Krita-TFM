"""Compare preserved/current worker binaries using the same current shaders.

Measures startup, per-request IPC+compute and peak worker working set. Alternating
shaders and shrinking/growing buffers also check cache isolation byte-for-byte.
"""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import struct
import subprocess
import threading
import time


def shader(path):
    words=[int(x,16) for x in re.findall(r'0x([0-9a-f]+)u',path.read_text(encoding='utf-8'))]
    return struct.pack('<'+'I'*len(words),*words)


def summary(values):
    return {'median':statistics.median(values),'p95':sorted(values)[math.ceil(len(values)*.95)-1],'samples':values}


def memory(process):
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in
                  ('peak','working','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile')]
    counters=Counters();counters.cb=ctypes.sizeof(counters)
    fn=ctypes.WinDLL('psapi').GetProcessMemoryInfo
    fn.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD]
    if not fn(int(process._handle),ctypes.byref(counters),counters.cb):
        raise ctypes.WinError()
    return counters.peak


def frames(source):
    pointwise=shader(source/'tfm_pointwise_spv.h')
    motion=shader(source/'tfm_motion_spv.h')
    for repeat in range(8):
        for kind,side in [('pointwise',512),('motion',64),('pointwise',128),('pointwise',1024)]:
            if kind=='pointwise':
                pixels=bytes(range(256))*(side*side*4//256)
                generic=[60.,0.,1.,.5,1.]+[0.]*3
                params=struct.pack('<13i21fi',4,side,side,*([0]*10),*([0.]*13),*generic,0)
                code=pointwise
            else:
                pixels=struct.pack('<4f',1.2,-.1,.5,.7)*(side*side)
                rect=[0,0,side,side]
                params=struct.pack('<16i4f4i4f',*(rect*4),side/2,side/2,17.,.5,1,200,0,0,0.,0.,0.,0.)
                code=motion
            frame=b'TFMV'+struct.pack('<11I',1,len(code),len(pixels),len(params),len(pixels),
                                      (side+15)//16,(side+15)//16,1,0,1,2)+code+pixels+params
            yield f'{kind}-{side}',frame,len(pixels)


def measure(worker,source):
    start=time.perf_counter()
    process=subprocess.Popen([str(worker)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    timer=threading.Timer(90,process.kill);timer.daemon=True;timer.start()
    try:
        def take(size):
            value=process.stdout.read(size)
            if len(value)!=size: raise RuntimeError('Truncated worker protocol')
            return value
        def u32(): return struct.unpack('<I',take(4))[0]
        def string(): return take(u32()).decode('utf-8',errors='replace')
        assert take(4)==b'TFMV' and u32()==0
        ok,float64=u32(),u32();name,error=string(),string()
        if not ok: raise RuntimeError(error)
        startup=(time.perf_counter()-start)*1000
        timings,hashes={},[]
        for label,frame,size in frames(source):
            start=time.perf_counter()
            process.stdin.write(frame);process.stdin.flush()
            assert take(4)==b'TFMV' and u32()==3
            ok=u32();device,error=string(),string()
            if not ok: raise RuntimeError(error)
            data=take(size)
            elapsed=(time.perf_counter()-start)*1000
            timings.setdefault(label,[]).append(elapsed)
            hashes.append(hashlib.sha256(data).hexdigest())
        peak=memory(process)
        process.stdin.write(b'TFMV'+struct.pack('<I',2));process.stdin.flush()
        assert process.wait(timeout=5)==0
        return {'worker_sha256':hashlib.sha256(worker.read_bytes()).hexdigest(),'gpu':name,
                'startup_ms':startup,'peak_working_set_bytes':peak,
                'requests':{k:{'first_ms':v[0],'warm_ms':summary(v[1:])} for k,v in timings.items()},
                'output_hashes':hashes}
    finally:
        timer.cancel()
        if process.poll() is None:process.kill();process.wait(timeout=5)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--current',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    source=Path(__file__).resolve().parents[1]/'native/fx/src'
    before=measure(args.baseline.resolve(),source)
    after=measure(args.current.resolve(),source)
    assert before['output_hashes']==after['output_hashes'],'cached worker changed pixels'
    report={'platform':platform.platform(),'cpu':os.environ.get('PROCESSOR_IDENTIFIER'),
            'shader_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
                             (source/'tfm_pointwise_spv.h',source/'tfm_motion_spv.h')},
            'baseline':before,'current':after,'output_equal':True}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({label:{'startup_ms':r['startup_ms'],'peak_bytes':r['peak_working_set_bytes'],
                            'warm_medians_ms':{k:v['warm_ms']['median'] for k,v in r['requests'].items()}}
                      for label,r in [('baseline',before),('current',after)]},indent=2))


if __name__=='__main__':main()
