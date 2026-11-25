"""Private worker/driver copies: compare existing policies with verified cache."""


def replace_once(source,old,new):
    if source.count(old)!=1:raise ValueError('Cached compatibility anchor changed')
    return source.replace(old,new,1)


def overlay(source):
    source=replace_once(source,'#include "h264_access_unit.hpp"',
                        '#include "h264_access_unit.hpp"\n#include "cached_compat_guard.hpp"')
    source=replace_once(source,
        'w!=1920||h!=1080||request.value("nonref_probe",false)||request.value("high_fps_compat",false))return 41;',
        '''w!=1920||h!=1080||!p011_hw::valid_cached_compat(
           request.value("cached_compat_probe",false),request.value("nonref_probe",false),
           request.value("nonref_keep_every",0u),request.value("throughput_probe",false),
           request.value("high_fps_compat",false),cache_mode=="cached"))return 41;''')
    return replace_once(source,
        'status.update(cache_snapshot());status["output_cache_probe"]=true;status["output_cache_enabled"]=cache_mode=="cached";',
        'status.update(cache_snapshot());status["output_cache_probe"]=true;status["output_cache_enabled"]=cache_mode=="cached";\n            status["cached_compat_probe"]=request.value("cached_compat_probe",false);')


def client_overlay(source):
    source=replace_once(source,'#include "hardware_clock.hpp"',
                        '#include "hardware_clock.hpp"\n#include "cached_compat_guard.hpp"')
    return replace_once(source,
        'request.value("ion_observe",false)||request.value("nonref_probe",false)||request.value("high_fps_compat",false))return false;',
        '''request.value("ion_observe",false)||!p011_hw::valid_cached_compat(
               request.value("cached_compat_probe",false),request.value("nonref_probe",false),
               request.value("nonref_keep_every",0u),request.value("throughput_probe",false),
               request.value("high_fps_compat",false),cache_mode=="cached"))return false;''')


def probe_overlay(source):
    # The generated probe must resolve the generated sibling header, not the
    # original ../client header. The build also checks the compiler depfile.
    return replace_once(source,'#include "../client/hardware_client.hpp"',
                        '#include "hardware_client.hpp"')
