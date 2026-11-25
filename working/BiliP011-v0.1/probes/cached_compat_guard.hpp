// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
namespace p011_hw {
// Only a separate, muted, finite cached-output diagnostic may compare these
// existing disposable-picture policies. No unsynchronized skipping benchmark.
inline bool valid_cached_compat(bool requested,bool nonref,unsigned keep,
                                bool throughput,bool production_flag,bool cached){
    if(production_flag)return false;
    if(!requested)return !nonref&&keep==0;
    return nonref&&cached&&!throughput&&(keep==0||keep==2||keep==3);
}
}
