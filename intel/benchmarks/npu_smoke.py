import json
import numpy as np
import openvino as ov
from openvino import opset13 as ops
c=ov.Core(); r={}
for name in ['FULL_DEVICE_NAME','DEVICE_ARCHITECTURE','NPU_DRIVER_VERSION','SUPPORTED_PROPERTIES']:
 try:r[name]=str(c.get_property('NPU',name))
 except Exception as e:r[name]=str(e)
x=ops.parameter([1,16],np.float32)
m=ov.Model([ops.relu(x)],[x])
try:
 compiled=c.compile_model(m,'NPU')
 r['result']=compiled({0:np.ones((1,16),np.float32)})[0].tolist()
except Exception as e:r['error']=str(e)
print(json.dumps(r,indent=2))
