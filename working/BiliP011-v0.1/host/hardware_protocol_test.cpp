// SPDX-License-Identifier: GPL-3.0-or-later
#include "../client/hardware_protocol.hpp"
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>
#include <cstring>
#include <iostream>
#include <stdexcept>
using namespace p011_hw;
int main(){int checks=0;auto check=[&](bool b){if(!b)throw std::runtime_error(std::to_string(checks));checks++;};
 try{
  for(int c:{0,7,12,13})for(int w:{0,640,1080,1920,3840})for(int h:{0,360,1080,1920,2160})for(bool dash:{false,true}){
   bool expected=c==7&&dash&&w>0&&h>0&&w<=1920&&h<=1920&&(w<=1080||h<=1080);check(supported(c,w,h,dash)==expected);
  }
  for(unsigned w:{0u,32u,1080u,1920u,1921u})for(unsigned h:{0u,18u,1080u,1920u,1921u})check(valid(w,h,w*h*3/2)==(w&&h&&w%2==0&&h%2==0&&w<=1920&&h<=1920&&(w<=1080||h<=1080)));
  check(!valid(1920,1080,1920*1080*3/2-1));check(!valid(960,540,0));
  auto*s=static_cast<Shared*>(mmap(nullptr,sizeof(Shared),PROT_READ|PROT_WRITE,MAP_SHARED|MAP_ANONYMOUS,-1,0));check(s!=MAP_FAILED);memset(s,0,sizeof(*s));
  pid_t child=fork();check(child>=0);
  if(child==0){for(uint32_t n=1;n<=10000;n++){bool stored=false;while(!stored){for(auto&f:s->frames)if(take(f.state,Free,Writing)){f.serial=n;f.width=32;f.height=18;f.bytes=32*18*3/2;memset(f.pixels,n%251,f.bytes);set(f.state,Ready);stored=true;break;}if(!stored)usleep(10);}}_exit(0);}
  unsigned seen=0;while(seen<10000){bool got=false;for(auto&f:s->frames)if(take(f.state,Ready,Reading)){
   check(valid(f.width,f.height,f.bytes));for(unsigned n=0;n<f.bytes;n+=17)check(f.pixels[n]==f.serial%251);check(!take(f.state,Ready,Writing));set(f.state,Free);seen++;got=true;
  }if(!got)usleep(10);}
  int result=0;check(waitpid(child,&result,0)==child&&WIFEXITED(result)&&WEXITSTATUS(result)==0);munmap(s,sizeof(*s));
  std::cout<<"{\"checks\":"<<checks<<",\"passed\":true,\"device_tested\":false}\n";return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
