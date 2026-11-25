"""No streams, frames or display: enumerate stock OpenMAX core components."""
import ctypes as c
import re
import signal


def main():
    signal.alarm(6)
    core=c.CDLL('/usr/lib/libsprd_omx_core.so')
    ptr=c.c_void_p;u32=c.c_uint32
    def bind(name,args):
        f=getattr(core,name);f.restype=u32;f.argtypes=args;return f
    init=bind('OMX_Init',[]);deinit=bind('OMX_Deinit',[])
    enum=bind('OMX_ComponentNameEnum',[c.c_char_p,u32,u32])
    roles=bind('OMX_GetRolesOfComponent',[c.c_char_p,c.POINTER(u32),ptr])
    result={'init':int(init()),'components':[]}
    try:
        if result['init']==0:
            for index in range(32):
                name=c.create_string_buffer(128);code=int(enum(name,128,index))
                if code:result['enum_end']=code;break
                text=name.value.decode('ascii','replace')
                if re.match(r'^OMX\.sprd\.[A-Za-z0-9._-]{1,90}$',text):
                    count=u32();rc=int(roles(name,c.byref(count),None))
                    result['components'].append({'name':text,'roles_count':count.value,'roles_code':rc})
    finally:result['deinit']=int(deinit())
    print('P011_OMX_RESULT='+ascii(result))


if __name__=='__main__':
    try:main()
    except Exception as error:
        # A loader error can include a path. Export only its class and a
        # constrained symbol name, never unfiltered vendor diagnostics.
        match=re.search(r'undefined symbol: ([A-Za-z0-9_]+)',str(error))
        print('P011_OMX_RESULT='+ascii({'error_type':type(error).__name__,'missing_symbol':match.group(1) if match else ''}))
