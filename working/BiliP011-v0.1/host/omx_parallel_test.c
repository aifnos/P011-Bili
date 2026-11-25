/* SPDX-License-Identifier: LGPL-2.1-only */
#include <stdio.h>
#include "../third_party/gst-omx-1.14.2-p011/omx/p011_copy.h"
#include "../third_party/gst-omx-1.14.2-p011/omx/p011_parallel_copy.h"
int main(void){
  unsigned copy=p011_omx_copy_selftest(),parallel=p011_omx_parallel_selftest();
  printf("COPY=%u PARALLEL=%u\n",copy,parallel);
  return copy==17408&&parallel==1620?0:1;
}
