// SPDX-License-Identifier: GPL-3.0-or-later
// One in-flight private IPC packet. No I/O, GL, FreeType or player state is
// touched by this worker. Backpressure preserves command order and bounds RAM.
#pragma once
#include "danmaku_timeline.hpp"
#include <chrono>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <functional>
namespace p011_ipc {
struct Packet {p011_dm::Json value;std::vector<p011_dm::Item> danmaku;std::vector<unsigned char> image;int image_width=0,image_height=0;};
struct Stats {uint64_t packets=0,danmaku_packets=0,max_parse_us=0,max_bytes=0;};
class Decoder {
    std::mutex mutex;std::condition_variable changed;
    bool stopped=false,occupied=false,failed=false;
    std::unique_ptr<std::string> input;std::unique_ptr<Packet> output;
    Stats counters;std::function<void(Packet&)> process;std::thread worker;
    void run(){
        for(;;){
            std::unique_ptr<std::string> raw;
            {std::unique_lock<std::mutex> lock(mutex);changed.wait(lock,[&]{return stopped||bool(input);});
             if(stopped)return;raw=std::move(input);}
            try{
                auto began=std::chrono::steady_clock::now();auto packet=std::make_unique<Packet>();
                packet->value=p011_dm::Json::parse(*raw,nullptr,false);bool dm=false;
                if(!packet->value.is_object())packet->value=nullptr;
                else{
                    auto op=packet->value.find("op");
                    dm=op!=packet->value.end()&&op->is_string()&&(op->get<std::string>()=="danmaku"||op->get<std::string>()=="live-danmaku");
                    if(dm){auto items=packet->value.find("items");
                        if(items!=packet->value.end())packet->danmaku=p011_dm::rows(*items);
                        // Destroy the large JSON tree HERE, not on the UI thread.
                        packet->value.erase("items");
                    }
                    if(process)process(*packet);
                }
                uint64_t elapsed=std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now()-began).count();
                std::lock_guard<std::mutex> lock(mutex);if(stopped)return;
                counters.packets++;counters.danmaku_packets+=dm;counters.max_parse_us=std::max(counters.max_parse_us,elapsed);
                counters.max_bytes=std::max(counters.max_bytes,uint64_t(raw->size()));output=std::move(packet);
            }catch(...){std::lock_guard<std::mutex> lock(mutex);failed=true;return;}
        }
    }
public:
    static constexpr size_t max_bytes=1024*1024;
    explicit Decoder(std::function<void(Packet&)> extra={}):process(std::move(extra)),worker(&Decoder::run,this){}
    Decoder(const Decoder&)=delete;Decoder&operator=(const Decoder&)=delete;
    ~Decoder(){{std::lock_guard<std::mutex> lock(mutex);stopped=true;}changed.notify_one();worker.join();}
    bool submit(const std::string&buffer,size_t length){
        if(length>max_bytes||length>buffer.size())throw std::length_error("IPC packet bound");
        std::lock_guard<std::mutex> lock(mutex);if(failed)throw std::runtime_error("IPC decode failed");
        if(occupied)return false;
        input=std::make_unique<std::string>(buffer.data(),length);occupied=true;changed.notify_one();return true;
    }
    bool take(std::unique_ptr<Packet>&packet){
        std::lock_guard<std::mutex> lock(mutex);if(failed)throw std::runtime_error("IPC decode failed");
        if(!output)return false;packet=std::move(output);occupied=false;return true;
    }
    Stats stats(){std::lock_guard<std::mutex> lock(mutex);return counters;}
};
}
