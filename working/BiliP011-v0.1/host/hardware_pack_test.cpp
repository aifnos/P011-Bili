// Pure algorithm only. ARM preflight runs the NEON branch on the real pen.
#include "../client/hardware_pack.hpp"
#include <iostream>
int main(){auto checks=p011_hw::pack_selftest();std::cout<<"PACK_CHECKS="<<checks<<'\n';return checks>400000?0:1;}
