// SPDX-License-Identifier: GPL-3.0-or-later
// Explicit benchmark only: muted fixed sample, 6s warmup + 25s + 13s pause.
import QtQuick 2.7
Item {
    id:driver
    property var target:null
    property int stage:0
    property bool pending:false
    property bool done:false
    property double started:Date.now()
    property double pausedAt:0
    property bool captured:false
    property bool capturedStats:false
    property double statsAt:0
    property bool seekProbe:false
    property string windowPose:""
    property bool windowRotated:false
    property double seekTarget:0
    function finish(passed){if(done)return;done=true;
        target.http("POST","/qa/performance",{passed:passed,quality:@BENCHMARK_QUALITY@,stage:driver.stage,mode:seekProbe?"seek":"performance"},function(r){
            target.http("POST","/player/stop",{},function(r){target.quitTrial();},false);
        },false);
    }
    function tick(){
        if(!target||!target.token||done||pending)return;
        if(Date.now()-started>(@BENCHMARK_QUALITY@>=120?45000:115000)){finish(false);return;}
        if(stage===0){pending=true;target.http("POST","/qa/start",{},function(r){pending=false;if(!r.ok){finish(false);return;}target.details({kind:"video",bvid:"@BENCHMARK_BVID@"},"detail");stage=1;},false);return;}
        if(stage===1){if(target.busy)return;if(!target.partCount){finish(false);return;}target.selectedQuality=@BENCHMARK_QUALITY@;target.selectedCodec=7;target.playPart(0);stage=2;return;}
        pending=true;target.http("GET","/state",null,function(s){pending=false;var p=s.player||{};
            if(!s.playing&&!s.preparing&&(s.play_end||s.play_exit_code!==null&&s.play_exit_code!==undefined)){finish(false);return;}
            if(windowPose==="portrait"&&!windowRotated&&p.loaded&&p.active&&p.position>=3){
                windowRotated=true;target.http("POST","/player/test",{action:"rotate"},function(r){if(!r.ok)finish(false);},false);
            }
            if(seekProbe&&p.loaded&&p.position>=4&&!captured){captured=true;target.http("POST","/player/test",{action:"capture_landscape"},function(r){},false);}
            if(seekProbe){
                if(stage===2&&p.active&&p.position>=6&&p.duration>0){stage=5;target.http("POST","/player/test",{action:"pause"},function(r){},false);}
                else if(stage===5&&p.paused){
                    seekTarget=p.duration*.25;stage=6;
                    target.http("POST","/player/test",{action:"progress_quarter"},function(r){},false);
                }else if(stage===6&&p.paused&&p.scrub_actions>=1&&Math.abs(p.position-seekTarget)<2){
                    stage=7;target.http("POST","/player/test",{action:"pause"},function(r){},false);
                }else if(stage===7&&p.active&&p.position>=seekTarget+.3){
                    finish(p.quality===@BENCHMARK_QUALITY@&&p.muted&&p.pulse_observed&&p.hardware_backend&&p.hardware_verified);
                }
                return;
            }
            if(stage===2&&p.active&&p.position>=6)stage=3;
            // glReadPixels and PNG encoding disturb active-frame timing.
            // Keep the complete playing interval free of screenshot work;
            // capture the actual final frame only after playback is paused.
            if(stage===4&&p.paused&&!captured){
                captured=true;target.http("POST","/player/test",{action:"capture_landscape"},function(r){},false);
            }
            if(stage===4&&p.paused&&p.capture_count>=1&&p.high_fps_compat&&!capturedStats){
                capturedStats=true;statsAt=Date.now();
                target.http("POST","/player/test",{action:"stats-menu"},function(r){
                    target.http("POST","/player/test",{action:"capture_stats"},function(r){},false);
                },false);
            }
            if(statsAt&&p.menu===7&&p.capture_count>=2&&Date.now()-statsAt>1500){statsAt=0;target.http("POST","/player/test",{action:"close"},function(r){},false);}
            if(stage===3&&p.active&&p.position>=31){stage=4;target.http("POST","/player/test",{action:"pause"},function(r){},false);}
            if(stage===4&&p.paused){if(!pausedAt)pausedAt=Date.now();if(Date.now()-pausedAt>13000)finish(p.quality===@BENCHMARK_QUALITY@&&p.muted&&p.pulse_observed);}
        },false);
    }
    Timer {interval:400;repeat:true;running:!driver.done;onTriggered:driver.tick()}
}
