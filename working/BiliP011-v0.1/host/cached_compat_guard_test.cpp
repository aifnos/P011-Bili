// SPDX-License-Identifier: GPL-3.0-or-later
#include "../probes/cached_compat_guard.hpp"
#include <cstdio>
int main(){
    unsigned checks=0;
    for(unsigned flags=0;flags<32;flags++)for(unsigned keep=0;keep<9;keep++){
        bool requested=flags&1,nonref=flags&2,throughput=flags&4,production=flags&8,cached=flags&16;
        bool expected=!production&&(!requested?(!nonref&&keep==0):
            nonref&&!throughput&&cached&&(keep==0||keep==2||keep==3));
        if(p011_hw::valid_cached_compat(requested,nonref,keep,throughput,production,cached)!=expected)return 1;
        checks++;
    }
    printf("CACHED_COMPAT_GUARD_PASS=%u\n",checks);return checks==288?0:2;
}
