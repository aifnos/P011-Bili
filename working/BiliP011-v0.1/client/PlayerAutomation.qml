// SPDX-License-Identifier: GPL-3.0-or-later
// Only in protocol-2 automated bundles. Muted, finite, candidate-scoped inputs.
import QtQuick 2.7
Item {
    id: qa
    property var panel: null
    property var click: null
    property var checks: []
    property int stage: 0
    property bool running: false
    property bool polling: false
    property double started: 0
    property double stageStarted: 0
    property double seekBase: 0
    property int chosen: -1
    property string failure: ""
    property int extraCaptures: 0
    property int storySwipes: 0
    property int storyBase: 0
    property double storySettledAt: 0
    property int gestureAttempts: 0
    property var commands: []
    property bool sending: false
    // Test-only hold, frozen by the builder. Normal trials never load this.
    property int soakSeconds: 0
    // Explicit screen-output test only. Keep poses still while ADB samples
    // before/output/after; ordinary playback and manual trials never use it.
    property int screenHoldMs: 0
    property double screenStableAt: 0
    property string soakBvid: ""
    property bool hardwareRequired: false
    property bool uxState: false
    property int loopBase: 0
    property double soakStarted: 0
    property double soakLastPosition: -1
    property double soakLastAdvance: 0
    signal completed(bool passed)
    function begin(target,clicker) {panel=target;click=clicker;started=Date.now();stageStarted=started;running=true;click("biliRecommend");}
    function check(name,condition) {if(!condition)throw "ASSERTION";checks.push(name);}
    function advance(){stage++;stageStarted=Date.now();screenStableAt=0;}
    function screenReady(ready){
        if(!screenHoldMs)return true;
        if(!ready){screenStableAt=0;return false;}
        if(!screenStableAt)screenStableAt=Date.now();
        return Date.now()-screenStableAt>=screenHoldMs;
    }
    // XHR completion order is not submission order. Preserve input ordering,
    // especially close -> resume -> rotate and danmaku-on -> seek.
    function command(action){commands.push(action);drain();}
    function drain(){
        if(!running||sending||!commands.length)return;
        sending=true;var action=commands.shift();
        panel.http("POST","/player/test",{action:action},function(reply){
            sending=false;if(!running)return;
            if(!reply.ok){failure="COMMAND_FAILED";finish(false);return;}
            drain();
        },false);
    }
    function finish(passed){if(!running)return;running=false;commands=[];if(!passed)panel.http("POST","/player/stop",{},function(reply){qa.completed(false);},false);else completed(true);}
    function seconds(text){var fields=text.split(":");if(fields.length<2)return 0;var total=0;for(var i=0;i<fields.length;i++)total=total*60+Number(fields[i]);return total;}
    function tick(){
        if(!running||polling)return;
        if(Date.now()-started>380000+soakSeconds*1000 || Date.now()-stageStarted>50000+(stage===3?soakSeconds*1000:0)){failure="TIMEOUT";finish(false);return;}
        polling=true;panel.http("GET","/state",null,function(state){try{if(running)run(state);}catch(e){var code=String(e);failure=["MISSING_ITEM","INVISIBLE_ITEM","ASSERTION","DM_UNAVAILABLE","NO_PLAYLIST"].indexOf(code)>=0?code:"QML_EXCEPTION";finish(false);}finally{polling=false;}},false);
    }
    function run(s){
        var p=s.player||{};
        if(stage>=3&&stage<48&&stage!==24&&!s.playing&&!s.preparing&&s.play_end){finish(false);return;}
        switch(stage){
        case 0:
            if(panel.busy)return;
            if(panel.rows.length<2)throw "NO_PLAYLIST";
            if(soakBvid){
                // Explicit reproduction only: real public details/streams,
                // followed by the live recommendation queue. This does not
                // count as proof that the fixed item was recommended.
                var fixed={kind:"video",bvid:soakBvid},queue=[fixed];
                for(var q=0;q<panel.rows.length;q++)if(panel.rows[q].bvid!==soakBvid)queue.push(panel.rows[q]);
                panel.rows=queue;panel.details(fixed,"detail");stage=2;stageStarted=Date.now();break;
            }
            for(var i=0;i<panel.rows.length-1;i++){var length=seconds(panel.rows[i].duration||"");if(panel.rows[i].kind==="video"&&length>Math.max(120,soakSeconds+30)&&length<1800){chosen=i;break;}}
            if(chosen<0&&soakSeconds>0)throw "NO_PLAYLIST";
            if(chosen<0)chosen=0;
            advance();break;
        case 1:
            if(panel.busy)return;
            if(panel.rowAt+3<=chosen){click("biliNext");return;}
            click("biliCard"+chosen);advance();break;
        case 2:
            if(panel.busy||panel.screen!=="detail"||panel.partCount<1)return;
            click("biliPart0");advance();break;
        case 3:
            if(soakStarted&&Date.now()-soakLastAdvance>5000)throw "ASSERTION";
            if(!p.loaded||!p.active||p.position<5||p.progress_visible)return;
            if(!screenReady(!p.switch_pending&&!p.portrait))return;
            if(soakSeconds>0){
                if(!soakStarted){soakStarted=Date.now();soakLastAdvance=soakStarted;}
                if(p.position>soakLastPosition+0.03){soakLastPosition=p.position;soakLastAdvance=Date.now();}
                if(Date.now()-soakStarted<soakSeconds*1000)return;
            }
            checks.push("playing");
            if(hardwareRequired)check("avc-hardware",p.hardware_backend&&p.hardware_verified&&p.submitted_frames>30);
            if(!p.muted||p.queue_count<2)throw "ASSERTION";
            checks.push("muted");checks.push("auto-hide");command("capture_landscape");advance();break;
        case 4:
            if(p.capture_count<1)return;command("tap_center");stage=28;stageStarted=Date.now();break;
        case 5:
            if(!p.paused)return;check("pause",p.pause_actions>=1);command("capture_paused");advance();break;
        case 6:
            if(p.capture_count<2)return;command("progress_quarter");stage=25;stageStarted=Date.now();break;
        case 7:
            if(p.paused||!p.active)return;check("resume",p.pause_actions>=2);seekBase=p.position;command("seek+");advance();break;
        case 8:
            if(p.switch_pending||!p.loaded)return;
            if(p.seek_actions<1||p.position<seekBase+8)return;checks.push("seek-forward");command("seek-");advance();break;
        case 9:
            if(p.switch_pending||!p.loaded)return;
            if(p.seek_actions<2||p.position>seekBase+8)return;checks.push("seek-back");command("quality-menu");advance();break;
        case 10:
            if(p.menu!==1)return;checks.push("quality-menu");command("capture_quality");advance();break;
        case 11:
            if(p.capture_count<3)return;seekBase=p.position;command("quality_32");advance();break;
        case 12:
            if(p.quality_switches<1||p.quality!==32||!p.active||p.switch_pending)return;
            check("quality-switch",p.position>=seekBase-1&&p.position<seekBase+45);advance();break;
        case 13:
            if(p.danmaku_failed)throw "DM_UNAVAILABLE";
            if(!p.danmaku_loaded||p.danmaku_count<1)return;checks.push("dm-loaded");command("danmaku");advance();break;
        case 14:
            if(p.danmaku_visible)return;checks.push("dm-toggle");command("danmaku");command("seek_dm");advance();break;
        case 15:
            if(!p.danmaku_visible||p.danmaku_frames<1||!p.active)return;checks.push("dm-rendered");command("capture_danmaku");advance();break;
        case 16:
            if(p.capture_count<4)return;command("codec-menu");stage=30;stageStarted=Date.now();break;
        case 17:
            if(!screenReady(p.loaded&&p.active&&!p.switch_pending&&p.portrait))return;
            if(!p.portrait)return;check("portrait",p.rotation_actions>=1);command("capture_portrait");advance();break;
        case 18:
            if(p.capture_count<5+extraCaptures)return;command("swipe_next");advance();break;
        case 19:
            if(p.swipe_actions<1||p.video_switches<1||!p.active||p.switch_pending)return;checks.push("swipe-next");checks.push("next-playing");command("capture_next");advance();break;
        case 20:
            if(p.capture_count<6+extraCaptures)return;command("pause");advance();break;
        case 21:
            if(!p.paused)return;checks.push("portrait-pause");command("capture_portrait_controls");advance();break;
        case 22:
            if(p.capture_count<7+extraCaptures)return;command("progress_quarter");stage=27;stageStarted=Date.now();break;
        case 23:
            if(p.portrait)return;check("landscape-return",p.rotation_actions>=2);command("story_start");stage=40;stageStarted=Date.now();break;
        case 24:
            if(s.playing||typeof s.play_exit_code!=="number")return;check("exit",s.play_exit_code===0);panel.playing=false;click("biliStory");stage=48;stageStarted=Date.now();break;
        case 25:
            if(p.switch_pending||!p.loaded)return;
            if(p.scrub_actions<1||Math.abs(p.position-p.duration*.25)>2)return;
            check("progress-tap",p.paused);command("progress_drag");advance();break;
        case 26:
            if(p.switch_pending||!p.loaded)return;
            if(p.scrub_actions<2||Math.abs(p.position-p.duration*.5)>2)return;
            check("progress-drag",p.paused);command("pause");stage=7;stageStarted=Date.now();break;
        case 27:
            if(p.switch_pending||!p.loaded)return;
            if(p.scrub_actions<3||Math.abs(p.position-p.duration*.25)>2)return;
            check("portrait-progress",p.paused&&p.portrait);command("rotate");stage=23;stageStarted=Date.now();break;
        case 28:
            if(!p.progress_visible)return;checks.push("manual-overlay-show");command("tap_center");advance();break;
        case 29:
            if(p.progress_visible)return;checks.push("manual-overlay-hide");command("pause");stage=5;stageStarted=Date.now();break;
        case 30:
            if(p.menu!==3)return;checks.push("codec-menu");command("capture_codecs");advance();break;
        case 31:
            if(p.capture_count<5)return;seekBase=p.position;command("codec_12");advance();break;
        case 32:
            if(p.observed_codec!==12||!p.active||p.switch_pending)return;
            if(Date.now()-stageStarted<2500||p.position<seekBase+1)return;
            check("hevc-decoded",p.position>=seekBase-1);command("capture_hevc");advance();break;
        case 33:
            if(p.capture_count<6)return;
            if(hardwareRequired&&p.observed_codec===12)check("hevc-software",!p.hardware_backend);
            seekBase=p.position;command("codec_13");advance();break;
        case 34:
            if(p.observed_codec!==13||!p.active||p.switch_pending)return;
            if(Date.now()-stageStarted<2500||p.position<seekBase+1)return;
            check("av1-decoded",p.position>=seekBase-1);command("capture_av1");advance();break;
        case 35:
            if(p.capture_count<7)return;
            if(hardwareRequired&&p.observed_codec===13)check("av1-software",!p.hardware_backend);
            command("codec_7");advance();break;
        case 36:
            if(p.observed_codec!==7||!p.active||p.switch_pending)return;
            check("avc-return",p.codec_switches>=3);if(hardwareRequired)check("avc-hardware-return",p.hardware_backend&&p.hardware_verified);command("dm_fixture");advance();break;
        case 37:
            if(!p.dm_fixture||!p.paused||p.dm_scheduled<7||Date.now()-stageStarted<1800)return;
            checks.push("typed-danmaku");command("capture_types");advance();break;
        case 38:
            if(p.capture_count<8||Date.now()-stageStarted<2000)return;command("capture_types_later");advance();break;
        case 39:
            if(p.capture_count<9)return;command("dm-menu");stage=44;stageStarted=Date.now();break;
        case 44:
            if(p.menu!==4)return;checks.push("dm-settings");command("capture_dm_settings");advance();break;
        case 45:
            if(p.capture_count<10)return;command("close");command("dm-layout");stage=50;stageStarted=Date.now();break;
        case 50:
            if(p.menu!==5)return;command("dm-area");command("dm-area");command("dm-opacity");command("dm-opacity");command("dm-opacity");command("dm-size");command("dm-speed");advance();break;
        case 51:
            if(p.dm_area!==50||p.dm_opacity!==75||p.dm_size!==120||p.dm_speed!==125)return;
            check("dm-appearance",p.settings_changes>=7);command("capture_dm_layout");advance();break;
        case 52:
            if(p.capture_count<11)return;command("close");command("capture_dm_half");advance();break;
        case 53:
            if(p.capture_count<12)return;command("aspect-menu");command("capture_aspect");advance();break;
        case 54:
            if(p.capture_count<13||p.menu!==6)return;command("aspect_fill");advance();break;
        case 55:
            if(p.aspect!==1||p.menu!==0)return;checks.push("aspect-fill");command("capture_fill");advance();break;
        case 56:
            if(p.capture_count<14)return;command("stats-menu");advance();break;
        case 57:
            if(p.menu!==7||!p.source_width||!p.source_height)return;check("playback-stats",p.skipped_draws>0);command("capture_stats");advance();break;
        case 58:
            if(p.capture_count<15)return;extraCaptures=11;command("close");command("aspect_fit");command("pause");command("rotate");stage=17;stageStarted=Date.now();break;
        case 40:
            if(!p.story||!p.portrait||!p.active||p.switch_pending)return;
            checks.push("story-source");storyBase=p.video_switches;command("capture_story");advance();break;
        case 41:
            // A first-frame commit precedes the 240ms incoming-card animation.
            // Never count a swipe dispatched while the player still owns that
            // transition. Also require a short settled interval for telemetry
            // sampled on the same frame as the commit.
            if(p.capture_count<19||!p.active||p.switch_pending||p.video_switches<storyBase+storySwipes||Math.abs(p.slide_offset||0)>.1){storySettledAt=0;return;}
            if(!storySettledAt){storySettledAt=Date.now();return;}
            if(Date.now()-storySettledAt<350)return;
            if(storySwipes<5){storySwipes++;storySettledAt=0;command("swipe_next");stageStarted=Date.now();return;}
            check("story-pagination",p.story_page>=3);command("capture_story_next");stage=46;stageStarted=Date.now();break;
        case 42:
            if(p.capture_count<20||!p.paused)return;command("tap_center");advance();break;
        case 43:
            if(p.paused||!p.active)return;checks.push("story-tap");command("back");stage=24;stageStarted=Date.now();break;
        case 46:
            if(p.capture_count<20)return;command("swipe_previous");advance();break;
        case 47:
            if(p.queue_index!==4||!p.active||p.switch_pending)return;check("story-previous",p.video_switches>=storyBase+6);command("tap_center");stage=42;stageStarted=Date.now();break;
        case 48:
            // Keep the WINDOW pose stable, not a single clip's timeline.
            // Official short clips may loop inside this sampling interval.
            if(!screenReady(p.generation===2&&p.story&&p.portrait))return;
            if(p.generation!==2||!p.story||!p.portrait||!p.active||p.position<2)return;
            check("story-entry",!p.danmaku_visible&&p.muted);check("settings-reused",p.dm_area===50&&p.dm_opacity===75&&p.dm_size===120&&p.dm_speed===125&&p.aspect===0);
            if(uxState&&hardwareRequired){
                if(typeof p.story_loop_completed!=="number")throw "ASSERTION";
                loopBase=p.story_loop_completed;command("story_replay_probe");stage=68;
            }else stage=59;
            stageStarted=Date.now();break;
        case 68:
            if(p.story_loop_failures)throw "ASSERTION";
            if(p.story_loop_completed<=loopBase||!p.active||p.switch_pending||p.position<1)return;
            check("story-replay",p.hardware_backend&&p.hardware_verified&&!p.story_loop_pending);
            stage=59;stageStarted=Date.now();break;
        case 59:
            // Existing frozen players keep their original regression path.
            if(typeof p.video_seek_actions!=="number"){command("back");stage=49;stageStarted=Date.now();return;}
            if(!p.active||p.switch_pending)return;
            if(!p.prefetch_completed&&Date.now()-stageStarted<18000)return;
            if(!p.prefetch_resolved)throw "ASSERTION";
            command("story_drag_hold");advance();break;
        case 60:
            if(!(p.slide_offset<0&&p.slide_offset>-800))return;
            command("capture_story_drag");advance();break;
        case 61:
            if(p.capture_count<1)return;command("gesture_release");advance();break;
        case 62:
            if(p.slide_cancels<1||Math.abs(p.slide_offset)>.1||!p.loaded||p.switch_pending||!p.active)return;
            command("pause");advance();break;
        case 63:
            if(!p.paused||!p.loaded||p.switch_pending||!(p.duration>0)||Math.abs(p.slide_offset||0)>.1)return;
            seekBase=p.position;gestureAttempts=1;command("video_seek_hold");advance();break;
        case 64:
            if(!p.gesture_seeking){
                // An official short clip can reach EOS between the sampled
                // ready state and the queued touch. Finish that unowned drag
                // and retry only after the new frame is ready; never count an
                // unacknowledged gesture, and never retry an account action.
                if(p.loaded&&!p.switch_pending&&p.paused&&p.duration>0&&gestureAttempts<3&&Date.now()-stageStarted>1500){
                    command("gesture_release");seekBase=p.position;command("video_seek_hold");gestureAttempts++;stageStarted=Date.now();
                }
                return;
            }
            command("capture_seek_preview");advance();break;
        case 65:
            if(p.capture_count<2)return;command("gesture_release");advance();break;
        case 66:
            if(p.switch_pending||!p.loaded)return;
            if(p.video_seek_actions<1||p.position<seekBase+.1)return;
            command("pause");command("swipe_next");advance();break;
        case 67:
            if(p.switch_pending||!p.active||p.video_switches<1)return;
            if(!(p.prefetch_media_hits||p.prefetch_metadata_hits))throw "ASSERTION";
            command("back");stage=49;stageStarted=Date.now();break;
        case 49:
            if(s.playing||typeof s.play_exit_code!=="number")return;if(s.play_exit_code!==0)throw "ASSERTION";finish(true);break;
        }
    }
    Timer {interval:550;repeat:true;running:qa.running;onTriggered:qa.tick()}
}
