// Host state-machine tests: not a Qt engine or hardware test.
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const path = require('path');
const source = fs.readFileSync(path.join(__dirname, '../bridge/Bridge.qml'), 'utf8');
function fn(name) {
    const start = source.indexOf('function ' + name + '(');
    assert(start >= 0);
    let open = source.indexOf('{', start), count = 1, i = open + 1;
    // These three functions have no unmatched braces inside literals/comments.
    for (; count; i++) { if (source[i] === '{') count++; else if (source[i] === '}') count--; }
    return source.slice(start, i);
}
let count = 0;
function test(name, run) {run(); console.log('PASS ' + name); count++;}
function make() {
    const c = {sessionId:'abcd', stateUrl:'file:///private/lease.json', held:false, disposed:false,
        request:null, lastSequence:-2, lastFresh:0, requestAt:0, ticks:20, now:10000,
        commands:[], requests:[], stopped:false, console:{log(){}}, JSON,
        engineSocket:{}, heartbeat:{}};
    c.Date={now:()=>c.now};
    c.engineSocket.sendEnableSysAutoOffScreen=(v)=>c.commands.push(v);
    c.heartbeat.stop=()=>{c.stopped=true;};
    c.XMLHttpRequest=function(){c.requests.push(this);this.open=()=>{};this.send=()=>{};this.abort=()=>{this.aborted=true;};};
    c.XMLHttpRequest.DONE=4;
    vm.createContext(c);vm.runInContext(fn('release')+'\n'+fn('accept')+'\n'+fn('poll'),c);return c;
}
function payload(seq,active=true){return JSON.stringify({session:'abcd',seq,active});}
test('fresh playing acquires once',()=>{const c=make();c.accept(payload(1));c.accept(payload(2));assert.deepStrictEqual(c.commands,[false]);});
test('pause immediately releases',()=>{const c=make();c.accept(payload(1));c.accept(payload(2,false));assert.deepStrictEqual(c.commands,[false,true]);});
test('resume reacquires with new sequence',()=>{const c=make();c.accept(payload(1));c.accept(payload(2,false));c.accept(payload(3));assert.deepStrictEqual(c.commands,[false,true,false]);});
test('repeated file does not renew lease',()=>{const c=make();c.accept(payload(1));c.now+=2600;c.accept(payload(1));c.poll();assert(!c.held);assert.deepStrictEqual(c.commands,[false,true]);});
test('crashed producer expires',()=>{const c=make();c.accept(payload(1));c.now+=2600;c.poll();assert(!c.held);});
test('wrong session rejected',()=>{const c=make();c.accept(JSON.stringify({session:'other',seq:1,active:true}));assert(!c.held);});
test('malformed JSON releases',()=>{const c=make();c.accept(payload(1));c.accept('broken');assert(!c.held);});
test('malformed state type rejected',()=>{const c=make();c.accept(JSON.stringify({session:'abcd',seq:1,active:'true'}));assert(!c.held);});
test('clock rollback releases',()=>{const c=make();c.accept(payload(1));c.now-=100;c.poll();assert(!c.held);});
test('hard deadline stops bridge',()=>{const c=make();c.accept(payload(1));c.ticks=1199;c.poll();assert(!c.held&&c.stopped);});
test('hung request aborted and released',()=>{const c=make();c.accept(payload(1));c.poll();const x=c.request;c.now+=1600;c.poll();assert(x.aborted&&!c.held&&c.request===null);});
test('late response cannot affect disposed bridge',()=>{const c=make();c.poll();const x=c.request;c.disposed=true;x.readyState=4;x.status=0;x.responseText=payload(1);x.onreadystatechange();assert(!c.held);});
test('outdated response ignored',()=>{const c=make();c.poll();const x=c.request;c.request=null;x.readyState=4;x.status=0;x.responseText=payload(1);x.onreadystatechange();assert(!c.held);});
console.log('HOST_BRIDGE_TESTS='+count+'; DEVICE_TESTED=false');
