// SPDX-License-Identifier: GPL-3.0-or-later
#include "../client/hardware_protocol.hpp"
#include "../client/hardware_cache_gate.hpp"
#include <cassert>
#include <cstdio>
int main(){
    char path[]="/tmp/p011-cache-gate-XXXXXX";int fd=mkstemp(path);assert(fd>=0);
    const char payload[]="owned test fixture";assert(write(fd,payload,sizeof(payload))==ssize_t(sizeof(payload)));
    char*sha=g_compute_checksum_for_data(G_CHECKSUM_SHA256,reinterpret_cast<const guchar*>(payload),sizeof(payload));assert(sha);
    assert(geteuid()==0);assert(p011_hw::cache_vendor_file(path,sha));
    assert(!p011_hw::cache_vendor_file(path,"0000000000000000000000000000000000000000000000000000000000000000"));
    assert(ftruncate(fd,0)==0);assert(!p011_hw::cache_vendor_file(path,sha));
    assert(ftruncate(fd,16*1024*1024+1)==0);assert(!p011_hw::cache_vendor_file(path,sha));
    close(fd);assert(unlink(path)==0);assert(!p011_hw::cache_vendor_file(path,sha));g_free(sha);
    setenv("GST_PLUGIN_PATH_1_0","/tmp/not-a-media-bundle",1);
    assert(p011_hw::cache_bundle_plugin().empty());
    puts("CACHE_VENDOR_GATE_PASS");
}
