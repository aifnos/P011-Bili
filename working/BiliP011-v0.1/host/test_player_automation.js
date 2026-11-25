// PC-only check of the exact QML automation queue, no ADB or playback.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../client/PlayerAutomation.qml'), 'utf8');
const begin = source.indexOf('    function command(');
const end = source.indexOf('    function finish(', begin);
assert(begin >= 0 && end > begin);
function fixture() {
    const sent = [], replies = [];
    const context = {running: true, sending: false, commands: [], failure: '',
        panel: {http(method, url, body, callback) {
            assert.equal(method, 'POST'); assert.equal(url, '/player/test');
            sent.push(body.action); replies.push(callback);
        }}, finish(passed) {assert.equal(passed, false); context.running = false;}};
    vm.createContext(context); vm.runInContext(source.slice(begin, end), context);
    return {context, sent, replies};
}
{
    const {context: c, sent, replies} = fixture();
    c.command('close'); c.command('pause'); c.command('rotate');
    assert.deepEqual(sent, ['close']);
    replies.shift()({ok: true}); assert.deepEqual(sent, ['close', 'pause']);
    replies.shift()({ok: true}); assert.deepEqual(sent, ['close', 'pause', 'rotate']);
    replies.shift()({ok: true}); assert.equal(c.sending, false);
    assert.equal(c.commands.length, 0);
}
{
    const {context: c, sent, replies} = fixture();
    c.command('close'); c.command('rotate'); replies.shift()({ok: false});
    assert.deepEqual(sent, ['close']); assert.equal(c.failure, 'COMMAND_FAILED');
    assert.equal(c.running, false);
}
{
    const {context: c, sent, replies} = fixture();
    c.command('close'); c.command('rotate'); c.running = false;
    replies.shift()({ok: true}); assert.deepEqual(sent, ['close']);
}
console.log('PASS: QML command ordering, failure and stopped-session gates');

// A restored catalogue may leave card zero outside the clip, despite visible.
{
    const ui=fs.readFileSync(path.join(__dirname,'../client/BiliAutomation.qml'),'utf8');
    const start=ui.indexOf('    function click('),end=ui.indexOf('    function check(',start);
    const calls=[];let positioned=false;
    const c={target:{screen:'catalog'},ListView:{Contain:4},Qt:{LeftButton:1,NoModifier:0},
        captureHelper:{wait(ms){assert.equal(ms,120);calls.push('settled');}},
        item(name){if(name==='biliCatalog')return {forceLayout(){calls.push('layout');},positionViewAtIndex(index,mode){assert.equal(index,0);assert.equal(mode,4);positioned=true;calls.push('position');}};
            assert.equal(name,'biliCard0');assert(positioned);return {visible:true,enabled:true,width:227,height:200};},
        touch:{mouseClick(){calls.push('click');return true;}}};
    vm.createContext(c);vm.runInContext(ui.slice(start,end),c);c.click('biliCard0');
    assert.deepEqual(calls,['layout','position','settled','click']);
}
// No hidden P button is clicked while the detail navigation is still pending.
{
    const start=source.indexOf('    function run('),end=source.indexOf('    Timer {',start);
    let clicks=0,advances=0;const c={stage:2,panel:{busy:false,screen:'catalog',partCount:1},
        click(name){assert.equal(name,'biliPart0');clicks++;},advance(){advances++;}};
    vm.createContext(c);vm.runInContext(source.slice(start,end),c);c.run({});
    c.panel.screen='detail';c.panel.partCount=0;c.run({});assert.equal(clicks,0);
    c.panel.partCount=1;c.run({});assert.equal(clicks,1);assert.equal(advances,1);
}
// Replay cannot pass from a mere reopen request or a paused/stale frame.
{
    const start=source.indexOf('    function run('),end=source.indexOf('    Timer {',start);
    const checks=[];const c={stage:68,loopBase:2,check(name,ok){assert(ok);checks.push(name);}};
    vm.createContext(c);vm.runInContext(source.slice(start,end),c);
    const p={story_loop_completed:2,story_loop_failures:0,active:true,switch_pending:false,position:2,
        hardware_backend:true,hardware_verified:true,story_loop_pending:false};
    c.run({player:p});assert.equal(c.stage,68);
    c.run({player:{...p,story_loop_completed:3,active:false}});assert.equal(c.stage,68);
    c.run({player:{...p,story_loop_completed:3,switch_pending:true}});assert.equal(c.stage,68);
    c.run({player:{...p,story_loop_completed:3}});assert.equal(c.stage,59);
    assert.deepEqual(checks,['story-replay']);
    c.stage=68;assert.throws(()=>c.run({player:{...p,story_loop_failures:1}}));
}
console.log('PASS: restored-card clipping, detail readiness and actual story replay gates');

// The explicit soak fixture changes only its first playlist item, still using
// real details and the following live recommendations. It is not a feed claim.
{
    const start=source.indexOf('    function run('),end=source.indexOf('    Timer {',start);
    const original=[{kind:'video',bvid:'BV1111111111'},{kind:'video',bvid:'BV2222222222'}];
    let requested;
    const c={stage:0,soakBvid:'BV1R7eg6gEnJ',panel:{busy:false,rows:original,details(row,op){requested={row,op};}}};
    vm.createContext(c);vm.runInContext(source.slice(start,end),c);c.run({});
    assert.equal(requested.row.bvid,c.soakBvid);assert.equal(requested.op,'detail');
    assert.equal(c.panel.rows.length,3);assert.equal(c.panel.rows[1],original[0]);assert.equal(c.stage,2);
}
// A request count and a stale position are not new-frame seek acceptance.
{
    const start=source.indexOf('    function run('),end=source.indexOf('    Timer {',start);
    const checks=[],commands=[];const c={stage:25,check(n,ok){assert(ok);checks.push(n);},command(a){commands.push(a);},advance(){c.stage++;}};
    vm.createContext(c);vm.runInContext(source.slice(start,end),c);
    const p={loaded:true,switch_pending:true,scrub_actions:1,position:50,duration:200,paused:true};
    c.run({player:p});assert.equal(checks.length,0);
    c.run({player:{...p,switch_pending:false,loaded:false}});assert.equal(checks.length,0);
    c.run({player:{...p,switch_pending:false}});assert.deepEqual(checks,['progress-tap']);assert.deepEqual(commands,['progress_drag']);
}
console.log('PASS: fixed-source reproduction and first-frame seek acceptance');
