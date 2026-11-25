"""P011-only loopback Bili service. Python 3.5; no raw API/credential logs.

Native helper stdout is PRIVATE IPC (signed URLs / QR credentials). Never
redirect it into diagnostics. Public results pass through operation-specific
normalizers; account cookies live outside every trial/collection directory.
"""
from __future__ import print_function
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stdlib-json35.zip'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json
import danmaku as danmaku_parser
from story import StoryFeed
from story_cache import StoryCache, can_prefetch
from library import Library
import account_features
import media_actions
import catalog_features
from playback_policy import quality_id, decode_budget, Preferences, settings as clean_settings
import math
import base64
import queue
import re
import signal
import stat
import subprocess
import threading
import time
import zlib
from collections import OrderedDict
from minhttp import BaseHTTPRequestHandler, HTTPServer

PUBLIC_OPS = {'recommend', 'search', 'following', 'bangumi', 'detail', 'open',
              'play', 'qualities', 'comments', 'status', 'qr_new', 'qr_poll', 'qr_cancel', 'logout', 'thumbnail', 'pinyin', 'library', 'library_clear'}
PUBLIC_OPS |= account_features.OPS
PUBLIC_OPS |= media_actions.OPS
PUBLIC_OPS |= catalog_features.OPS
ERRORS = {'URL_REJECTED', 'API_HOST_REJECTED', 'IMAGE_HOST_REJECTED',
          'NETWORK_INIT', 'NETWORK_ERROR', 'HTTP_ERROR', 'INVALID_JSON',
          'LOGIN_REQUIRED', 'API_ERROR', 'API_SCHEMA', 'WBI_KEYS', 'WBI_SIGN',
          'BAD_BVID', 'BAD_ID', 'PAGE_LIMIT', 'BAD_SEARCH', 'BAD_SEARCH_TYPE',
          'BAD_OFFSET', 'BAD_CURSOR', 'BAD_CATALOG', 'DRM_UNSUPPORTED',
          'MEDIA_HOST_UNSUPPORTED', 'NO_SUPPORTED_STREAM', 'QR_SCHEMA',
          'API_SCHEMA_OR_INTERNAL', 'CANCELED', 'QR_EXPIRED', 'COOKIE_REJECTED',
          'PLAYER_BUSY', 'PLAYER_FAILED', 'BAD_INPUT', 'BAD_IMAGE', 'BUSY',
          'HELPER_FAILED', 'HELPER_TIMEOUT', 'INTERNAL', 'API_VERIFICATION_REQUIRED', 'QUALITY_UNAVAILABLE', 'CODEC_UNAVAILABLE', 'STORY_UNAVAILABLE', 'RESOURCE_LIMIT'}
QUALITIES=range(65536)
ERRORS |= account_features.ERRORS
CODECS=(0,7,12,13)
UI_QA_CHECKS = ('bootstrap', 'recommendations', 'pagination', 'details', 'back',
                'keyboard', 'chinese-input', 'search', 'bangumi', 'input-error', 'following-route', 'no-player',
                'description','qualities','quality-selection','comments','comment-has-more',
                'comment-pagination','comment-back-page','comment-sort','detail-return',
                'comment-replies','replies-return','bangumi-details','parts-scroll','input-edit-retry','input-component','api-high-qualities','quality-scroll')
UI_QA_CAPTURES = ('01-recommendations', '02-next-cards', '03-video-details', '04-offline-keyboard',
                  '05-search-input', '06-search-results', '07-bangumi', '08-input-error',
                  '09-description','10-qualities','11-comments','12-comments-next','13-bangumi-details','14-comment-replies','15-bangumi-scrolled','16-input-component','17-api-high-qualities')
UI_QA_ERRORS = ('', 'TIMEOUT', 'MISSING_ITEM', 'INVISIBLE_ITEM', 'ASSERTION', 'CAPTURE_BLOCKED',
               'CAPTURE_SIZE', 'CAPTURE_FAILED', 'NO_CONTENT', 'QML_EXCEPTION','PLAYER_QA_FAILED','TOOLBOX_QA_FAILED')
TOOLBOX_QA_CHECKS=('home','files','lan-off','text','image','snake','large-controls','2048','bricks',
    'game-controls','dashboard','curves','processes','export','toolbox-back','bili-entry','bili-return','bili-reopen')
TOOLBOX_QA_CAPTURES=tuple('toolbox-'+name for name in ('home','files','text','image','snake','2048','bricks','dashboard','curves','processes'))
PLAYER_TEST_ACTIONS = ('pause','seek-','seek+','tap_center','quality-menu','quality_32','danmaku',
    'rotate','more','close','back','swipe_next','seek_dm','progress_quarter','progress_drag',
    'capture_landscape','capture_paused','capture_quality','capture_danmaku',
    'capture_portrait','capture_portrait_controls','capture_next',
    'codec-menu','codec_7','codec_12','codec_13','dm-menu','dm_fixture','story_start','swipe_previous',
    'capture_codecs','capture_hevc','capture_av1','capture_types','capture_types_later','capture_dm_settings','capture_story','capture_story_next',
    'dm-layout','dm-area','dm-opacity','dm-size','dm-speed','dm-reset','aspect-menu','aspect_fit','aspect_fill','stats-menu','quality_80',
    'capture_dm_layout','capture_dm_half','capture_aspect','capture_fill','capture_stats',
    'video_seek_hold','story_drag_hold','story_drag_cancel','gesture_release','capture_story_drag','capture_seek_preview','story_replay_probe')
PLAYER_TEST_ACTIONS += ('menu-next','menu-prev','feature-comments','feature-close','feature-next','feature-down','listen','capture_comments','capture_listen','capture_live')
PLAYER_TEST_ACTIONS += ('feature-subtitles','feature-chapters','feature-select','feature-sub-toggle','feature-sub-settings','feature-sub-size+','feature-sub-delay+','rate_150','rate_100','capture_subtitles','capture_chapters','capture_subtitle_settings','capture_timed_preview')
PLAYER_TEST_ACTIONS += ('hold_rate_start','hold_rate_release')
PLAYER_TEST_ACTIONS += ('rate-menu',)
PLAYER_QA_CHECKS = ('playing','muted','auto-hide','pause','resume','seek-forward','seek-back',
    'quality-menu','quality-switch','dm-loaded','dm-toggle','dm-rendered','portrait',
    'swipe-next','next-playing','portrait-pause','landscape-return','exit',
    'progress-tap','progress-drag','portrait-progress','manual-overlay-show','manual-overlay-hide',
    'codec-menu','hevc-decoded','av1-decoded','avc-return','typed-danmaku','dm-settings','story-source','story-pagination','story-tap','story-previous','story-entry',
    'dm-appearance','aspect-fill','playback-stats','settings-reused')
HARDWARE_QA_CHECKS = ('avc-hardware','hevc-software','av1-software','avc-hardware-return')
UX_HARDWARE_QA_CHECKS = ('story-replay',)


def hardware_cleanup_ok(result):
    value=result.get('hardware',{}) if isinstance(result,dict) else {}
    clean=(isinstance(value,dict) and type(value.get('starts')) is int and value['starts']>0 and
            value.get('normal_exits')==value['starts'] and value.get('abnormal_exits')==0 and
            value.get('forced_kills')==0 and value.get('last_exit')==0)
    if not clean:return False
    if any(key in value for key in ('cache_sessions','cache_failures','cache_last')):
        if type(value.get('cache_sessions')) is not int or value['cache_sessions']!=value['starts'] or value.get('cache_failures')!=0:return False
        last=value.get('cache_last',{})
        if not isinstance(last,dict) or last.get('cache_final') is not True:return False
        for key in ('cache_active','cache_fallback_active','cache_sync_errors','cache_ownership_errors'):
            if type(last.get(key)) is not int or last[key]!=0:return False
        for start,end in (('cache_registered','cache_forgotten'),('cache_read_begin','cache_read_end'),
                          ('cache_fallback_registered','cache_fallback_forgotten'),('cache_fallback_read_begin','cache_fallback_read_end')):
            if type(last.get(start)) is not int or type(last.get(end)) is not int or last[start]<0 or last[start]!=last[end]:return False
    return True


class Failure(Exception):
    def __init__(self, error, code=-1):
        self.error = error if error in ERRORS else 'INTERNAL'
        self.code = code if isinstance(code, int) and not isinstance(code, bool) else -1


def short(value, limit=500):
    if not isinstance(value, str): return ''
    return ''.join(c if ord(c) >= 32 else ' ' for c in value)[:limit]


def identifier(value, pattern):
    return isinstance(value, str) and re.match(pattern+'$', value) is not None


def safe_args(op, args):
    if not isinstance(args, dict): raise Failure('BAD_INPUT')
    if op in media_actions.OPS:return media_actions.arguments(op,args,Failure)
    if op in catalog_features.OPS:return catalog_features.arguments(op,args,Failure)
    if op in account_features.OPS:return account_features.arguments(op,args,Failure)
    result = {}
    if op=='play' and args.get('story') is True and not args.get('bvid'):
        for key,allowed in (('quality',QUALITIES),('codec',CODECS)):
            value=args.get(key,0)
            if type(value) is not int or value not in allowed:raise Failure('BAD_INPUT')
            result[key]=value
        return dict(result,story=True,portrait=True,danmaku=False)
    if op in ('recommend', 'search', 'following', 'bangumi'):
        p = args.get('page', 1)
        if not isinstance(p, int) or isinstance(p, bool) or p < 1 or p > 100: raise Failure('BAD_INPUT')
        result['page'] = p
        if op in ('following', 'bangumi'):
            offset = args.get('offset', '')
            if not isinstance(offset, str) or len(offset) > 128: raise Failure('BAD_INPUT')
            result['offset'] = offset
        if op == 'search':
            term, kind = args.get('query', ''), args.get('type', 'video')
            if not isinstance(term, str) or not term.strip() or len(term.encode('utf-8')) > 160: raise Failure('BAD_SEARCH')
            if kind not in ('video', 'media_bangumi'): raise Failure('BAD_INPUT')
            result.update(query=term.strip(), type=kind)
    elif op in ('detail', 'play', 'qualities'):
        kind = args.get('kind', 'video')
        if kind=='live':
            result=account_features.arguments('live_detail',args,Failure)
            quality=args.get('quality',0)
            if not quality_id(quality):raise Failure('BAD_INPUT')
            result.update(kind='live',quality=quality,codec=7,title=short(args.get('title'),100),up=short(args.get('up'),100),danmaku=True)
            return result
        if kind not in ('video', 'season', 'episode'): raise Failure('BAD_INPUT')
        result['kind'] = kind
        for key in ('bvid', 'cid', 'ep', 'season', 'aid'):
            value = args.get(key, '')
            pattern = r'BV[0-9A-Za-z]{10}' if key == 'bvid' else r'[0-9]{1,20}'
            if value:
                if not identifier(value, pattern): raise Failure('BAD_INPUT')
                result[key] = value
        if kind == 'video' and ('bvid' not in result or (op in ('play','qualities') and 'cid' not in result)): raise Failure('BAD_INPUT')
        if kind != 'video' and not (result.get('ep') or result.get('season')): raise Failure('BAD_INPUT')
        if op in ('play','qualities') and kind not in ('video', 'episode'): raise Failure('BAD_INPUT')
        if op in ('play','qualities'):
            codec=args.get('codec',0)
            if type(codec) is not int or codec not in CODECS:raise Failure('BAD_INPUT')
            result['codec']=codec
        if op == 'play':
            quality = args.get('quality',0)
            if not isinstance(quality,int) or isinstance(quality,bool) or quality not in QUALITIES: raise Failure('BAD_INPUT')
            result['quality'] = quality
            for key in ('portrait','danmaku','listen'):
                value=args.get(key,key=='danmaku')
                if not isinstance(value,bool): raise Failure('BAD_INPUT')
                result[key]=value
            playlist=args.get('queue',[])
            if not isinstance(playlist,list) or len(playlist)>24: raise Failure('BAD_INPUT')
            result['queue']=[safe_args('detail',x) for x in playlist]
            for source,row in zip(playlist,result['queue']):
                for key in ('title','part_title','up'):
                    if key in source:row[key]=short(source[key],100)
            index=args.get('queue_index',0)
            if type(index) is not int or index<0 or index>=max(1,len(playlist)): raise Failure('BAD_INPUT')
            result['queue_index']=index
            if 'queue_source' in args:
                source=args['queue_source']
                if isinstance(source,dict) and source.get('category')=='parts':
                    result['queue_source']=dict(safe_args('detail',source),category='parts')
                else:result['queue_source']=safe_args('catalog_library',source)
            if 'start' in args:
                if not catalog_features.finite(args['start']):raise Failure('BAD_INPUT')
                result['start']=args['start']
            if 'resume' in args:
                if type(args['resume']) is not bool:raise Failure('BAD_INPUT')
                result['resume']=args['resume']
            for key in ('title','part_title','up'):
                if key in args:result[key]=short(args[key],100)
    elif op == 'comments':
        for key in ('aid','bvid','root'):
            value = args.get(key,'')
            if value:
                if not identifier(value,r'BV[0-9A-Za-z]{10}' if key=='bvid' else r'[0-9]{1,20}'): raise Failure('BAD_INPUT')
                result[key] = value
        if not (result.get('aid') or result.get('bvid')): raise Failure('BAD_INPUT')
        for key,default,upper in (('next',0,1000000000),('mode',3,3)):
            value=args.get(key,default)
            if not isinstance(value,int) or isinstance(value,bool) or not 0<=value<=upper: raise Failure('BAD_INPUT')
            result[key]=value
        if result['mode'] not in (2,3): raise Failure('BAD_INPUT')
    elif op == 'open':
        value = args.get('text', '')
        if not isinstance(value, str) or len(value) > 512: raise Failure('BAD_INPUT')
        value = value.strip()
        live=re.match(r'^(?:https?://live\.bilibili\.com/)([0-9]{1,20})(?:[/?#].*)?$',value)
        if live:return {'kind':'live','room':live.group(1)}
        match = re.search(r'(?:^|/)\b(BV[0-9A-Za-z]{10})(?:$|[/?#])', value)
        if match and (value.startswith('BV') or re.match(r'https?://(?:www\.|m\.)?bilibili\.com/', value)):
            return {'kind': 'video', 'bvid': match.group(1)}
        match = re.match(r'^(?:https?://(?:www\.|m\.)?bilibili\.com/bangumi/play/)?(ep|ss)([0-9]{1,20})(?:[/?#].*)?$', value)
        if match: return {'kind': 'season', 'ep' if match.group(1) == 'ep' else 'season': match.group(2)}
        raise Failure('BAD_INPUT')
    elif op == 'thumbnail':
        if not identifier(args.get('key'), r'[a-f0-9]{24}'): raise Failure('BAD_INPUT')
        result['key'] = args['key']
    elif op == 'pinyin':
        code = args.get('code', '')
        if not identifier(code, r'[a-z]{1,48}'): raise Failure('BAD_INPUT')
        result['code'] = code
    elif op == 'library_clear':
        if args.get('section') not in ('history','searches'):raise Failure('BAD_INPUT')
        result['section']=args['section']
    # No UI-provided login keys, signed URLs, paths or commands are accepted.
    return result


def error_result(error):
    if not isinstance(error, Failure): error = Failure('INTERNAL')
    return {'ok': False, 'error': error.error, 'code': error.code}


def decode_danmaku(raw):
    try:return danmaku_parser.decode(raw)
    except (ValueError,TypeError,OverflowError):raise Failure('API_SCHEMA')


class Backend:
    def __init__(self, root, api, player, account, env, helper=None, lifetime=535, automation=False, protocol=1, hardware_required=False):
        self.root, self.api, self.player_bin, self.account = root, api, player, account
        self.env = dict(env)
        self.env['P011_OWNER_PID'] = str(os.getpid())
        self.env['P011_CLIENT_ROOT'] = root
        self.env['P011_BILI_COOKIES'] = os.path.join(account, 'cookies.txt')
        self.deadline = time.monotonic()+lifetime
        self.bootstrap_deadline = time.monotonic()+60
        self.token = base64.urlsafe_b64encode(os.urandom(32)).decode('ascii')
        self.bootstrapped = False
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.jobs = OrderedDict()
        self.queue = queue.Queue(maxsize=6)
        self.children = set()
        self.player = None
        self.story_cache = None
        self.media_relay = None
        self.play_generation = 0
        self.preparing = False
        self.play_end = ''
        self.play_exit_code = None
        self.qr_generation, self.qr_key, self.qr_deadline = 0, '', 0
        self.images, self.image_data = OrderedDict(), OrderedDict()
        self.helper_override = helper
        self.pinyin = None
        self.automation = automation is True
        self.features = account_features.Features(self,Failure,short)
        self.media_actions = media_actions.Actions(self,Failure)
        self.env['P011_ACCOUNT_WRITES']='disabled' if self.automation else 'user-action'
        self.qa_claimed = False
        self.qa_finished = False
        self.protocol = protocol
        self.hardware_required = hardware_required is True
        self.benchmark_danmaku_delay = False
        self.playback_settings = clean_settings({})
        self.preferences = None
        self.library = None
        self.ux_probe = False
        self.feature_probe = False
        self.catalog_probe = False
        self.story_probe = False
        self.story_rounds = []
        self.catalog_evidence = {}
        self.catalog_rounds = []
        self.feature_rounds = []
        self.ux_rounds = []
        self.ux_fault_pending = False
        self.ux_faults = 0
        self.play_item = None
        self.history_at = 0
        self.player_pipe_lock = threading.Lock()
        self.live_danmaku_stats = {}
        self.toolbox = None
        self.threads = []
        for _ in range(2):
            t = threading.Thread(target=self.work)
            t.daemon = True
            t.start()
            self.threads.append(t)

    def performance_finish(self, request):
        if not self.automation or not self.qa_claimed or self.protocol!=2:raise Failure('CANCELED')
        if not isinstance(request,dict):raise Failure('BAD_INPUT')
        mode=request.get('mode','performance')
        if mode not in ('performance','seek') or mode=='seek' and not getattr(self,'benchmark_seek',False):raise Failure('BAD_INPUT')
        if type(request.get('passed')) is not bool or not quality_id(request.get('quality')) or type(request.get('stage')) is not int or not 0<=request['stage']<=(7 if mode=='seek' else 4):raise Failure('BAD_INPUT')
        p=self.state().get('player',{})
        common=request['passed'] and p.get('muted') is True and p.get('pulse_observed') is True and p.get('loaded') is True and p.get('quality')==request['quality']
        if mode=='seek':
            passed=common and request['stage']==7 and p.get('active') is True and p.get('paused') is False and p.get('hardware_backend') is True and p.get('hardware_verified') is True and p.get('scrub_actions',0)>=1 and p.get('pause_actions',0)>=2 and p.get('duration',0)>0 and abs(p.get('position',0)-p['duration']*.25)<2
        else:passed=common and request['stage']==4 and p.get('paused') is True and p.get('position',0)>=30
        report={'passed':bool(passed),'requested_quality':request['quality'],'stage':request['stage'],
                'player':p,'mode':mode,'physical_acceptance':False,'sample':'explicit-public-benchmark','codec_preference':7}
        with open(os.path.join(self.root,'performance-qa.json'),'x') as f:json.dump(report,f)
        return {'recorded':True}

    def bootstrap(self):
        with self.lock:
            if self.bootstrapped or time.monotonic() > self.bootstrap_deadline: raise Failure('CANCELED')
            self.bootstrapped = True
            return self.token

    def qa_start(self):
        # Fixed, one-shot, own-candidate-only test. Not a generic input/file API.
        with self.lock:
            if not self.automation or not self.bootstrapped or self.qa_claimed: raise Failure('CANCELED')
            try:
                fd = os.open(os.path.join(self.root, 'ui-qa.started'), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
                os.close(fd)
                os.mkdir(os.path.join(self.root, 'screenshots'), 0o700)
            except OSError: raise Failure('CANCELED')
            self.qa_claimed = True
            return {'ok': True}

    def ux_state_check(self,request):
        with self.lock:
            if self.story_probe:
                from story_probe import handle
                try:return handle(self,request,hardware_cleanup_ok)
                except (OSError,ValueError,TypeError,KeyError):raise Failure('BAD_INPUT')
            if not self.ux_probe:raise Failure('CANCELED')
            from ux_probe import handle
            try:return handle(self,request,hardware_cleanup_ok)
            except (OSError,ValueError,TypeError,KeyError):raise Failure('BAD_INPUT')

    def feature_check(self,request):
        if self.catalog_probe:
            from catalog_probe import handle
            try:return handle(self,request,hardware_cleanup_ok)
            except (OSError,ValueError,TypeError,KeyError):raise Failure('BAD_INPUT')
        if not self.feature_probe:raise Failure('CANCELED')
        from feature_probe import handle
        try:return handle(self,request,hardware_cleanup_ok)
        except (OSError,ValueError,TypeError,KeyError):raise Failure('BAD_INPUT')

    def qa_finish(self, request):
        with self.lock:
            if not self.qa_claimed or self.qa_finished or not isinstance(request, dict): raise Failure('CANCELED')
            passed, error, step = request.get('passed'), request.get('error'), request.get('step')
            checks, captures = request.get('checks'), request.get('captures')
            expected_captures=UI_QA_CAPTURES+(TOOLBOX_QA_CAPTURES if self.toolbox else ())
            if not isinstance(passed, bool) or error not in UI_QA_ERRORS: raise Failure('BAD_INPUT')
            if not isinstance(step, int) or isinstance(step, bool) or not 0 <= step <= 64: raise Failure('BAD_INPUT')
            for values, allowed in ((checks, UI_QA_CHECKS), (captures, expected_captures)):
                if not isinstance(values, list) or len(values)>len(allowed) or any(not isinstance(x, str) or x not in allowed for x in values) or len(set(values))!=len(values): raise Failure('BAD_INPUT')
            if passed and (error or set(checks)!=set(UI_QA_CHECKS) or set(captures)!=set(expected_captures)): raise Failure('BAD_INPUT')
            toolbox_checks=request.get('toolbox_checks',[])
            if self.toolbox:
                if not isinstance(toolbox_checks,list) or any(not isinstance(x,str) or x not in TOOLBOX_QA_CHECKS for x in toolbox_checks) or len(set(toolbox_checks))!=len(toolbox_checks):raise Failure('BAD_INPUT')
                if passed and (set(toolbox_checks)!=set(TOOLBOX_QA_CHECKS) or self.toolbox.state.transfer_state()['enabled']):raise Failure('BAD_INPUT')
            import struct
            for name in captures:
                path = os.path.join(self.root, 'screenshots', name+'.png')
                if os.path.islink(path) or not os.path.isfile(path) or os.path.getsize(path)>4*1024*1024: raise Failure('BAD_INPUT')
                with open(path, 'rb') as f: header = f.read(24)
                if len(header)!=24 or header[:8]!=b'\x89PNG\r\n\x1a\n' or struct.unpack('>II', header[16:24])!=(800,480): raise Failure('BAD_INPUT')
            player_checks=request.get('player_checks',[])
            native={};preferences_verified=False
            if self.protocol==2:
                expected=PLAYER_QA_CHECKS+(HARDWARE_QA_CHECKS if self.hardware_required else ())+(UX_HARDWARE_QA_CHECKS if self.hardware_required and self.library is not None else ())
                if not isinstance(player_checks,list) or len(player_checks)>len(expected) or any(not isinstance(x,str) or x not in expected for x in player_checks) or len(set(player_checks))!=len(player_checks):raise Failure('BAD_INPUT')
                if passed and set(player_checks)!=set(expected):raise Failure('BAD_INPUT')
                player_stage=request.get('player_stage',0)
                if type(player_stage) is not int or not 0<=player_stage<100:raise Failure('BAD_INPUT')
                if passed:
                    try:
                        # Toolbox navigation invalidates play_generation even
                        # after a clean exit. Inspect the two immutable run
                        # identities, not the mutable cancellation counter.
                        with open(os.path.join(self.root,'player-primary-result.json'),'r') as f:native=json.loads(f.read(16384))
                    except (OSError,ValueError):native={}
                    if not isinstance(native,dict):native={}
                    native_ok=native.get('muted') is True and native.get('pulse') is True and native.get('loaded') is True and native.get('gl_errors')=={}
                    try:
                        with open(os.path.join(self.root,'render-info.json'),'r') as f:render=json.loads(f.read(1024))
                        bits=render.get('rgba_bits',[])
                        color_ok=isinstance(bits,list) and len(bits)==4 and all(type(x) is int and 8<=x<=32 for x in bits)
                    except (OSError,ValueError,AttributeError):color_ok=False
                    if not color_ok:native_ok=False
                    media={}
                    try:
                        with open(os.path.join(self.root,'player-result.json'),'r') as f:secondary=json.loads(f.read(16384))
                        with open(os.path.join(self.root,'media-state.json'),'r') as f:media=json.loads(f.read(8192))
                        if not (native.get('generation')==1 and native.get('reason')=='back' and secondary.get('generation')==2 and secondary.get('loaded') is True and secondary.get('pulse') is True and secondary.get('muted') is True and secondary.get('reason')=='back' and secondary.get('gl_errors')=={} and media.get('generation')==2 and media.get('story') is True):native_ok=False
                        if self.hardware_required and not (hardware_cleanup_ok(native) and hardware_cleanup_ok(secondary)):native_ok=False
                        if self.hardware_required and self.library is not None:
                            if not (type(media.get('story_loop_completed')) is int and media['story_loop_completed']>0 and media.get('story_loop_failures')==0 and media.get('story_loop_pending') is False):native_ok=False
                    except (OSError,ValueError,AttributeError):native_ok=False
                    for key,minimum in (('quality_switches',4),('video_switches',8),('rotation_actions',3),('swipe_actions',7),('pause_actions',6),('seek_actions',6),('scrub_actions',3),('overlay_toggle_actions',2),('danmaku_frames',1),('draws',50),('capture_count',20)):
                        if type(native.get(key)) is not int or native[key]<minimum:native_ok=False
                    if request.get('player_diagnostic',{}).get('native_keyboard_reused') is not True:native_ok=False
                    try:
                        # Reopen the on-disk store, not its in-memory cache.
                        # Only five numerical settings live here, no account.
                        preferences_verified=(self.preferences is not None and os.path.isfile(self.preferences.path) and
                            all(k in media for k in self.playback_settings) and
                            Preferences(self.preferences.directory).load()==self.playback_settings==clean_settings(media))
                    except (OSError,ValueError):preferences_verified=False
                    if not preferences_verified:native_ok=False
                    if not native_ok:passed=False;error='PLAYER_QA_FAILED'
            observed=self.state().get('player',{})
            report = {'passed':passed, 'error':error, 'step':step, 'checks':checks, 'captures':captures,
                      'layer':'P011 copied factory Qt UI', 'audio_played':observed.get('pulse_observed') is True or native.get('pulse') is True,
                      'audio_output_muted':observed.get('muted') is True or native.get('muted') is True, 'account_page_captured':False,
                      'physical_touch_verified':False}
            if self.protocol==2:report.update(player_checks=player_checks,player_stage=player_stage,preferences_reopened_verified=preferences_verified,hardware_required=self.hardware_required)
            if self.toolbox:report.update(toolbox_checks=toolbox_checks,isolated_user_files=True,lan_opened=False)
            if self.protocol==2:
                d=request.get('player_diagnostic',{})
                if not isinstance(d,dict):raise Failure('BAD_INPUT')
                diagnostic={}
                diagnostic['native_keyboard_reused']=d.get('native_keyboard_reused') is True
                for key in ('parts','detail_code','read_code'):
                    if type(d.get(key)) is int and abs(d[key])<100000000:diagnostic[key]=d[key]
                if d.get('failure') in ('','TIMEOUT','MISSING_ITEM','INVISIBLE_ITEM','ASSERTION','DM_UNAVAILABLE','NO_PLAYLIST','QML_EXCEPTION','COMMAND_FAILED'):diagnostic['failure']=d['failure']
                if d.get('screen') in ('catalog','detail','comments','quality','description','searchInput','openInput'):diagnostic['screen']=d['screen']
                for key in ('detail_error','read_error'):
                    if d.get(key) in ERRORS|{'','LOCAL_HTTP','LOCAL_TIMEOUT','INVALID_JSON'}:diagnostic[key]=d[key]
                report['player_diagnostic']=diagnostic
            path = os.path.join(self.root, 'ui-qa-result.json')
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            with os.fdopen(fd, 'w') as f: json.dump(report, f)
            self.qa_finished = True
            return {'ok':True}

    def submit(self, op, args):
        if not isinstance(op, str) or op not in PUBLIC_OPS: raise Failure('BAD_INPUT')
        args = safe_args(op, args)
        with self.lock:
            if self.stopping.is_set() or time.monotonic() >= self.deadline: raise Failure('CANCELED')
            if self.queue.full(): raise Failure('BUSY')
            if op in ('qr_new', 'qr_cancel', 'logout'):
                self.qr_generation += 1
                self.qr_key = ''
            generation = self.qr_generation
            if op == 'play':
                if self.preparing or (self.player is not None and self.player.poll() is None): raise Failure('PLAYER_BUSY')
                self.preparing = True
                self.play_generation += 1
                generation = self.play_generation
            job_id = os.urandom(12).hex()
            self.jobs[job_id] = (time.monotonic(), None)
            # Preserve pending jobs; evict completed jobs first.
            for key in list(self.jobs):
                stamp, result = self.jobs[key]
                if result is not None and (len(self.jobs) > 24 or time.monotonic()-stamp > 180): del self.jobs[key]
            self.queue.put_nowait((job_id, op, args, generation))
            return job_id

    def result(self, job_id):
        with self.lock:
            if job_id not in self.jobs: raise Failure('CANCELED')
            answer = self.jobs[job_id][1]
            return {'pending': True} if answer is None else answer

    def work(self):
        while not self.stopping.is_set():
            try: job_id, op, args, generation = self.queue.get(timeout=.2)
            except queue.Empty: continue
            try: answer = {'ok': True, 'data': self.dispatch(op, args, generation)}
            except Exception as exc: answer = error_result(exc)
            finally:
                if op == 'play':
                    with self.lock: self.preparing = False
            with self.lock:
                if job_id in self.jobs: self.jobs[job_id] = (time.monotonic(), answer)
                if op == 'play' and not answer.get('ok'):
                    self.play_diagnostic('prepare_failed', error=answer.get('error'), code=answer.get('code'))
            self.queue.task_done()

    def play_diagnostic(self, stage, error=None, code=None):
        # Write only internally chosen stages and allowlisted error codes.
        # Raw native stderr, stream addresses and account fields stay private.
        if stage not in ('preparing', 'spawned', 'prepare_failed', 'player_exit'): return
        value = {'stage': stage, 'generation': self.play_generation}
        if error in ERRORS: value['error'] = error
        if isinstance(code, int) and not isinstance(code, bool): value['code'] = code
        path = os.path.join(self.root, 'play-diagnostic.json')
        temp = path+'.'+os.urandom(8).hex()+'.tmp'
        try:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            with os.fdopen(fd, 'w') as f: json.dump(value, f)
            os.replace(temp, path)
        except OSError:
            # Diagnostics must not prevent playback or keep a child alive.
            try: os.unlink(temp)
            except OSError: pass

    def helper(self, op, args, cancel=None):
        if self.stopping.is_set(): raise Failure('CANCELED')
        if op in ('interaction','season_follow','danmaku_send','watch_heartbeat','password_login','password_challenge') and self.automation:raise Failure('ACTION_DISABLED')
        if self.helper_override is not None: return self.helper_override(op, args)
        payload = json.dumps({'op': op, 'args': args}, ensure_ascii=True).encode('ascii')
        with self.lock:
            if self.stopping.is_set(): raise Failure('CANCELED')
            p = subprocess.Popen([self.api], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, env=self.env)
            self.children.add(p)
        try:
            try:
                if cancel is None:stdout, _ = p.communicate(payload, timeout=46)
                else:
                    until=time.monotonic()+44;first=True
                    while True:
                        if cancel.is_set() or self.stopping.is_set():p.kill();p.communicate();raise Failure('CANCELED')
                        if time.monotonic()>until:raise subprocess.TimeoutExpired(self.api,44)
                        try:stdout,_=p.communicate(payload if first else None,timeout=.2);break
                        except subprocess.TimeoutExpired:first=False
            except subprocess.TimeoutExpired:
                p.kill(); p.communicate(); raise Failure('HELPER_TIMEOUT')
            if p.returncode or len(stdout) > 5*1024*1024: raise Failure('HELPER_FAILED')
            if op in ('image','danmaku_xml'): return stdout
            try: response = json.loads(stdout.decode('utf-8'))
            except (ValueError, UnicodeError): raise Failure('HELPER_FAILED')
            if not isinstance(response, dict): raise Failure('HELPER_FAILED')
            if response.get('ok') is not True: raise Failure(response.get('error'), response.get('code'))
            return response.get('data')
        finally:
            with self.lock: self.children.discard(p)

    def image_key(self, url):
        if not isinstance(url, str) or len(url) > 2048: return ''
        if not re.match(r'^https://(?:[a-zA-Z0-9-]+\.)*hdslb\.com/', url): return ''
        # Limit thumbnail transfer / decode dimensions at the image CDN.
        url = url.split('@', 1)[0]+'@320w_180h_1c.jpg'
        with self.lock:
            for key, existing in self.images.items():
                if existing == url: return key
            key = os.urandom(12).hex()
            self.images[key] = url
            while len(self.images) > 160:
                old, _ = self.images.popitem(last=False)
                self.image_data.pop(old, None)
            return key

    def card(self, raw):
        if not isinstance(raw, dict): raise Failure('API_SCHEMA')
        result = {key: short(raw.get(key), 500 if key == 'title' else 120)
                  for key in ('title', 'bvid', 'up', 'duration', 'season', 'ep', 'kind', 'cid', 'badge', 'aid','room','mid','part_title')}
        result['cover_key'] = self.image_key(raw.get('cover'))
        return result

    def dispatch(self, op, args, generation):
        if op in media_actions.OPS:return self.media_actions.dispatch(op,args,generation)
        if op in catalog_features.OPS:return catalog_features.dispatch(self,op,args,generation,Failure,short)
        if op in account_features.OPS:return self.features.dispatch(op,args,generation)
        if op in ('open','detail') and args.get('kind')=='live':return self.features.dispatch('live_detail',args,generation)
        if op == 'pinyin': return self.lookup_pinyin(args['code'])
        if op in ('library','library_clear'):
            if not self.library:return {'history':[],'searches':[],'available':False}
            try:
                if op=='library_clear':self.library.clear(args['section'])
                return dict(self.library.load(),available=True)
            except (OSError,ValueError):raise Failure('INTERNAL')
        if op in ('recommend', 'search', 'following', 'bangumi'):
            data = self.helper(op, args)
            rows = data.get('items')
            if not isinstance(rows, list): raise Failure('API_SCHEMA')
            if op=='search' and self.library:
                try:self.library.search(args['query'])
                except (OSError,ValueError):pass
            return {'items': [self.card(x) for x in rows[:60]],
                    'page': args['page'], 'more': data.get('more') is True,
                    'offset': short(data.get('offset'), 128)}
        if op in ('detail', 'open'):
            data = self.helper('detail', args)
            result = self.card(data)
            result['description'] = short(data.get('description'), 1000)
            all_parts = data.get('parts', [])
            result['parts'] = [self.card(x) for x in all_parts[:2000]]
            result['parts_total'] = len(all_parts)
            result['parts_truncated'] = len(all_parts)>2000
            result['collection_available']=data.get('collection_available') is True
            return result
        if op == 'qualities':
            data=self.helper('live_play' if args.get('kind')=='live' else op,args)
            if args.get('kind')=='live':data=dict(data,items=data.get('qualities',[]))
            rows=data.get('items')
            if not isinstance(rows,list) or not rows or len(rows)>len(QUALITIES): raise Failure('API_SCHEMA')
            result=[]
            for row in rows:
                if not isinstance(row,dict) or type(row.get('id')) is not int or row['id'] not in QUALITIES: raise Failure('API_SCHEMA')
                result.append({'id':row['id'],'label':short(row.get('label'),40)})
            codecs=[{'id':r['id'],'label':short(r.get('label'),40)} for r in data.get('codecs',[]) if isinstance(r,dict) and type(r.get('id')) is int and r['id'] in CODECS]
            return {'items':result,'preview':data.get('preview') is True,'codecs':codecs[:4]}
        if op == 'comments':
            data=self.helper(op,args)
            rows=data.get('items')
            if not isinstance(rows,list) or len(rows)>40 or not identifier(data.get('aid'),r'[0-9]{1,20}'): raise Failure('API_SCHEMA')
            result=[]
            for row in rows:
                if not isinstance(row,dict) or not identifier(row.get('id'),r'[0-9]{1,20}'): raise Failure('API_SCHEMA')
                normalized={'id':row['id'],'author':short(row.get('author'),60),'text':short(row.get('text'),1200),'pinned':row.get('pinned') is True}
                for key in ('likes','replies'):
                    value=row.get(key,0)
                    if type(value) is not int or not 0<=value<=1000000000: raise Failure('API_SCHEMA')
                    normalized[key]=value
                result.append(normalized)
            cursor=data.get('next',0)
            if type(cursor) is not int or not 0<=cursor<=1000000000: raise Failure('API_SCHEMA')
            self.features.note_comments(args.get('bvid'),args.get('root',''),result,generation)
            return {'items':result,'aid':data['aid'],'next':cursor,'more':data.get('more') is True}
        if op == 'status':
            data = self.helper('status', {})
            return {'logged_in': data.get('logged_in') is True, 'name': short(data.get('name'), 60)}
        if op == 'qr_new':
            data = self.helper('qr_new', {})
            matrix = data.get('matrix')
            if not isinstance(matrix, list) or not 21 <= len(matrix) <= 121: raise Failure('QR_SCHEMA')
            if any(not isinstance(row, str) or len(row) != len(matrix) or re.search(r'[^01]', row) for row in matrix): raise Failure('QR_SCHEMA')
            key = data.get('qr_key')
            if not identifier(key, r'[0-9A-Za-z_-]{8,128}'): raise Failure('QR_SCHEMA')
            with self.lock:
                if generation != self.qr_generation: raise Failure('CANCELED')
                self.qr_key, self.qr_deadline = key, time.monotonic()+180
            return {'matrix': matrix, 'expires': 180}
        if op == 'qr_poll':
            with self.lock:
                if generation != self.qr_generation or not self.qr_key or time.monotonic() >= self.qr_deadline: raise Failure('QR_EXPIRED')
                key = self.qr_key
            data = self.helper('qr_poll', {'key': key})
            code = data.get('code')
            if code not in (0, 86038, 86090, 86101): raise Failure('API_ERROR', code)
            with self.lock:
                if generation != self.qr_generation or key != self.qr_key: raise Failure('CANCELED')
                if time.monotonic() >= self.qr_deadline: raise Failure('QR_EXPIRED')
                if code == 0:
                    self.save_cookies(data.get('cookies'))
                    self.qr_key = ''
                elif code == 86038: self.qr_key = ''
            return {'code': code}
        if op in ('qr_cancel', 'logout'):
            with self.lock:
                if generation != self.qr_generation: raise Failure('CANCELED')
                if op == 'logout':
                    path = os.path.join(self.account, 'cookies.txt')
                    if os.path.islink(path): raise Failure('COOKIE_REJECTED')
                    if os.path.exists(path): os.unlink(path)
            return {'done': True}
        if op == 'thumbnail':
            key = args['key']
            with self.lock:
                if key in self.image_data: return self.image_data[key]
                url = self.images.get(key)
            if not url: raise Failure('BAD_IMAGE')
            raw = self.helper('image', {'url': url})
            if not isinstance(raw, bytes) or len(raw) > 512*1024: raise Failure('BAD_IMAGE')
            if raw.startswith(b'\xff\xd8\xff'): mime = 'image/jpeg'
            elif raw.startswith(b'\x89PNG\r\n\x1a\n'): mime = 'image/png'
            else: raise Failure('BAD_IMAGE')
            result = {'source': 'data:'+mime+';base64,'+base64.b64encode(raw).decode('ascii')}
            with self.lock:
                self.image_data[key] = result
                while len(self.image_data) > 12: self.image_data.popitem(last=False)
            return result
        if op == 'play': return self.play(args, generation)
        raise Failure('BAD_INPUT')

    def lookup_pinyin(self, code):
        with self.lock:
            if self.pinyin is None:
                path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pinyin.json.z')
                if not os.path.isfile(path): path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'deps', 'pinyin.json.z')
                with open(path, 'rb') as f: packed = f.read(4*1024*1024+1)
                if len(packed) > 4*1024*1024: raise Failure('BAD_INPUT')
                self.pinyin = json.loads(zlib.decompress(packed).decode('utf-8'))
            dictionary = self.pinyin
        # Longest exact spelling first; unconsumed suffix stays in composition.
        for size in range(len(code), 0, -1):
            if code[:size] in dictionary:
                return {'candidates':[{'text':row[0], 'consume':size} for row in dictionary[code[:size]][:60]]}
        # Abbreviated single syllable, e.g. "zh". Not cloud prediction.
        choices=[]
        for spelling,rows in dictionary.items():
            if len(spelling)<=6 and spelling.startswith(code):
                choices.extend((row[0],row[1]) for row in rows if len(row[0])==1)
        choices.sort(key=lambda x:(-x[1],x[0]))
        return {'candidates':[{'text':row[0], 'consume':len(code)} for row in choices[:60]]}

    def save_cookies(self, rows):
        if not isinstance(rows, list) or not rows or len(rows) > 64: raise Failure('COOKIE_REJECTED')
        valid = []
        session = False
        for row in rows:
            if not isinstance(row, str) or len(row) > 8192 or '\n' in row or '\r' in row: raise Failure('COOKIE_REJECTED')
            fields = row.split('\t')
            if len(fields) != 7: raise Failure('COOKIE_REJECTED')
            domain = fields[0].replace('#HttpOnly_', '', 1).lstrip('.')
            if domain != 'bilibili.com' and not domain.endswith('.bilibili.com'): raise Failure('COOKIE_REJECTED')
            if fields[1] not in ('TRUE', 'FALSE') or fields[3] not in ('TRUE', 'FALSE'): raise Failure('COOKIE_REJECTED')
            if not re.match(r'^[0-9]+$', fields[4]) or not fields[2].startswith('/'): raise Failure('COOKIE_REJECTED')
            if fields[5] == 'SESSDATA' and fields[6]: session = True
            valid.append(row)
        if not session: raise Failure('COOKIE_REJECTED')
        path = os.path.join(self.account, 'cookies.txt')
        if os.path.islink(path): raise Failure('COOKIE_REJECTED')
        temp = path+'.'+os.urandom(8).hex()+'.tmp'
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(('# Netscape HTTP Cookie File\n'+'\n'.join(valid)+'\n').encode('utf-8'))
                f.flush(); os.fsync(f.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp): os.unlink(temp)

    def play(self, args, generation):
        feed=None
        if args.get('story'):
            feed=StoryFeed(lambda a:self.helper('story',a),lambda a,c:self.helper('story',a,c))
            try:index,row=feed.target(1)
            except ValueError:raise Failure('STORY_UNAVAILABLE')
            selected=safe_args('play',dict(row,quality=args.get('quality',0),codec=args.get('codec',0)))
            selected.update(story=True,portrait=True,danmaku=args.get('danmaku',True),title=short(row.get('title'),100),up=short(row.get('up'),40))
            args=selected
        if self.toolbox:self.toolbox.stop_audio()
        with self.lock:
            self.play_diagnostic('preparing')
            self.play_exit_code = None
        live=args.get('kind')=='live'
        source=args.get('queue_source')
        if source and not feed and not live:
            if source['category']=='parts':
                detail=self.dispatch('detail',safe_args('detail',source),self.qr_generation)
                queue_rows=detail['parts'];source_more=False
                for r in queue_rows:r.update(title=detail.get('title',''),up=detail.get('up',''),part_title=r.get('title',''))
            else:
                catalog=self.dispatch('catalog_library',source,self.qr_generation)
                queue_rows=[r for r in catalog['items'] if r.get('kind')=='video' and r.get('playable')]
                source_more=catalog['more']
            selected=next((i for i,r in enumerate(queue_rows) if (r.get('bvid')==args.get('bvid') and (source['category']!='parts' or r.get('cid')==args.get('cid'))) or (args.get('ep') and r.get('ep')==args.get('ep'))),None)
            if selected is not None:args=dict(args,queue=queue_rows,queue_index=selected,queue_more=source_more)
            else:args=dict(args,queue_source=None)
        native_args={k:v for k,v in args.items() if k not in ('queue','queue_source','queue_more')}
        data = self.helper('live_play' if live else 'play', native_args)
        if not isinstance(data, dict) or not isinstance(data.get('video'), str): raise Failure('API_SCHEMA')
        if not decode_budget(data):raise Failure('RESOURCE_LIMIT')
        with self.lock:
            if generation != self.play_generation or self.stopping.is_set(): raise Failure('CANCELED')
            seconds = min(480, int(self.deadline-time.monotonic()-5))
            if seconds < 10: raise Failure('CANCELED')
            env = dict(self.env)
            if self.protocol==2 and self.helper_override is None:
                if self.media_relay is None:
                    from media_relay import MediaRelay
                    self.media_relay=MediaRelay(self)
                env['P011_MEDIA_RELAY']=self.media_relay.endpoint
            env['P011_CLIENT_ROOT'] = self.root
            env['P011_PLAYER_LIMIT'] = str(seconds)
            # Signed URLs travel in an anonymous pipe, never command line / logs.
            if self.automation: env['P011_PLAYER_AUTOMATED']='1'
            if self.automation and generation==2:
                # Retain the numerical first-player evidence before testing
                # the separate QML Story entry in a second player process.
                with open(os.path.join(self.root,'player-result.json'),'r') as f:primary=json.loads(f.read(16384))
                if primary.get('generation')!=1:raise Failure('BAD_INPUT')
                with open(os.path.join(self.root,'player-primary-result.json'),'x') as f:json.dump(primary,f)
            p = subprocess.Popen([self.player_bin], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE if self.protocol==2 else subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, env=env)
            self.children.add(p)
            self.player, self.play_end = p, ''
            self.play_diagnostic('spawned')
            initial={'video': data['video'], 'audio': data.get('audio', ''),'preview': data.get('preview') is True,'width':data.get('width',0),'height':data.get('height',0)}
            if self.protocol==2:
                initial.update(protocol=2,generation=generation,serial=1,muted=self.automation,portrait=args.get('portrait',False),
                    danmaku=args.get('danmaku',True),quality=data.get('quality',0),qualities=data.get('qualities',[]),
                    codec=data.get('codec',7),codecs=data.get('codecs',[]),story=bool(feed),title=args.get('title',''),up=args.get('up',''),
                    settings=self.playback_settings,queue_index=args.get('queue_index',0),queue_count=(len(args.get('queue',[])) or 1)+int(args.get('queue_more',False)))
                initial['switch_ack']=True
                initial.update(live=live,listen=args.get('listen',False),features=True)
                if not feed and not live and args.get('resume',True) and 'start' in args:
                    initial['start']=args['start']
                elif self.library and not feed and not live and args.get('resume',True):
                    try:initial['start']=self.library.resume(args)
                    except (OSError,ValueError):pass
                self.play_item=(generation,1,dict(args)) if not feed and not live else None
            payload = (json.dumps(initial)+'\n').encode('utf-8')
            try:
                p.stdin.write(payload);p.stdin.flush()
                if self.protocol!=2:p.stdin.close()
            except OSError:
                p.kill(); p.wait(); self.children.discard(p); raise Failure('PLAYER_FAILED')
        if self.protocol==2:
            if feed:feed.commit(index)
            bridge=threading.Thread(target=self.player_events,args=(p,generation,args,feed))
            bridge.daemon=True;bridge.start()
            if not live:self.start_danmaku(p,generation,args,1)
            else:self.start_live_danmaku(p,generation,args)
        t = threading.Thread(target=self.reap_player, args=(p,))
        t.daemon = True
        t.start()
        return {'started': True, 'preview': data.get('preview') is True}

    def send_player(self, p, generation, value):
        if p is None:return False
        payload=(json.dumps(value,ensure_ascii=True)+'\n').encode('ascii')
        if len(payload)>1024*1024: raise Failure('API_SCHEMA')
        with self.player_pipe_lock:
            with self.lock:
                if self.stopping.is_set() or self.player is not p or generation!=self.play_generation or p.poll() is not None: return False
            try:p.stdin.write(payload);p.stdin.flush();return True
            except (OSError,ValueError):return False

    def start_danmaku(self,p,generation,args,serial):
        def load():
            try:
                cid=args.get('cid','')
                if not identifier(cid,r'[0-9]{1,20}'): raise Failure('BAD_INPUT')
                d=decode_danmaku(self.helper('danmaku_xml',{'cid':cid}))
                if not isinstance(d,dict) or not isinstance(d.get('items'),list) or len(d['items'])>2000: raise Failure('API_SCHEMA')
                released=None
                if self.benchmark_danmaku_delay and self.automation and self.protocol==2 and generation==1 and serial==1:
                    from dm_delay_probe import wait_for_playback
                    def alive():
                        with self.lock:return self.player is p and generation==self.play_generation and p.poll() is None
                    released=wait_for_playback(self.state,alive,self.stopping)
                    if released is None:return
                sent=self.send_player(p,generation,dict(op='danmaku',serial=serial,ok=True,items=d['items']))
                if released is not None:
                    with open(os.path.join(self.root,'dm-delay-probe.json'),'x') as f:
                        json.dump(dict(delivered=sent,released_position=released,items=len(d['items']),generation=generation,serial=serial),f)
            except Exception:
                self.send_player(p,generation,dict(op='danmaku',serial=serial,ok=False,items=[]))
        t=threading.Thread(target=load);t.daemon=True;t.start()

    def start_live_danmaku(self,p,generation,args):
        account_generation=self.qr_generation
        def alive():
            return not self.stopping.is_set() and self.player is p and generation==self.play_generation and account_generation==self.qr_generation and p.poll() is None and time.monotonic()<self.deadline
        def load():
            stats={};rows=[];sent=[0.]
            self.live_danmaku_stats=stats
            def info():
                if not alive():raise ValueError('canceled')
                try:return self.helper('live_danmaku_info',{'room':args['room']},self.stopping)
                except Failure:raise ValueError('official service unavailable')
            def deliver(row):
                if len(rows)<16:rows.append(dict(row,time=0,mode=1,size=25))
            def tick():
                if time.monotonic()-sent[0]<.5 or not alive():return
                sent[0]=time.monotonic()
                if rows:self.send_player(p,generation,dict(op='live-danmaku',items=list(rows)));rows[:]=[]
                self.send_player(p,generation,dict(op='live-status',authenticated=stats.get('authenticated',False),failed=stats.get('failed',False)))
            try:
                import live_danmaku
                live_danmaku.run(info,deliver,self.stopping,alive,self.env.get('P011_BILI_CA','/etc/ssl/certs/ca-certificates.crt'),stats,tick)
            except Exception:stats['failed']=True
            finally:
                tick()
                # Counters only: never persist room/user IDs, tokens or messages.
                if self.live_danmaku_stats is stats:
                    try:
                        with open(os.path.join(self.root,'live-danmaku-result.json'),'w') as f:json.dump({k:v for k,v in stats.items() if type(v) in (bool,int)},f)
                    except OSError:pass
        t=threading.Thread(target=load);t.daemon=True;t.start()

    def player_events(self,p,generation,initial,feed=None):
        # Private anonymous-pipe protocol. No signed URLs ever enter disk,
        # command line, raw logs, WebChannel or the loopback UI responses.
        current=dict(initial);playlist=initial.get('queue') or [dict(initial)]
        for key in ('queue','queue_source','queue_more'):current.pop(key,None)
        index=initial.get('queue_index',0);serial=1;last=0;feature_last=0;feature_busy=threading.Event()
        queue_source=initial.get('queue_source');queue_more=initial.get('queue_more',False)
        account_generation=self.qr_generation
        cache=None;transactional=False;pending=None
        def commit(value):
            nonlocal current,index,serial,feed
            self.remember_playback(True)
            current=value['args'];index=value['index'];serial=value['serial'];feed=value['feed']
            if feed and not value['keep']:feed.commit(index);index=feed.index
            self.play_item=(generation,serial,dict(current)) if not feed and current.get('kind')!='live' else None
            if not value['keep'] and current.get('kind')!='live':self.start_danmaku(p,generation,current,serial)
            ahead()
        def resolve(requested,cancel=None):
            args=safe_args('play',requested)
            native_op='live_play' if args.get('kind')=='live' else 'play'
            try:data=self.helper(native_op,args,cancel)
            except Failure as e:
                if e.error not in ('QUALITY_UNAVAILABLE','CODEC_UNAVAILABLE'):raise
                args['quality']=0;args['codec']=0;data=self.helper(native_op,args,cancel)
            if not decode_budget(data):raise Failure('RESOURCE_LIMIT')
            return args,data
        def ready(metadata=False):
            state=self.state().get('player',{})
            # The frozen, verified legacy player cannot open private cache
            # files. Its unchanged default must never receive those URLs.
            return (can_prefetch(state,metadata) and p.poll() is None and generation==self.play_generation
                    and (self.media_relay is None or state.get('prefix_cache_capable') is True))
        def ahead():
            nonlocal cache
            if not feed or self.helper_override is not None:return
            if cache is None:
                try:cache=StoryCache(self.root,resolve,lambda a,c:self.helper('prefetch_prefix',a,c),ready,metadata_ready=lambda:ready(True),relay=self.media_relay);self.story_cache=cache
                except (OSError,ValueError):return
            captured_feed=feed;expected=feed.index;quality=current.get('quality',0);codec=current.get('codec',0)
            def provider(cancel):
                rows=captured_feed.lookahead(expected,cancel,2)
                for row in rows:row.update(quality=quality,codec=codec)
                return rows
            cache.schedule_provider(provider)
        try:
            ahead()
            while not self.stopping.is_set():
                raw=p.stdout.readline(4097)
                if not raw:return
                if len(raw)>4096 or not raw.endswith(b'\n'):return
                try:value=json.loads(raw.decode('utf-8'))
                except (ValueError,UnicodeError):continue
                if not isinstance(value,dict):continue
                if value.get('action')=='feature':
                    seq=value.get('seq');op=value.get('op');requested=value.get('args',{})
                    if type(seq) is not int or not feature_last<seq<10000000 or op not in ('comments','relation','favorites','interaction','player_metadata','player_subtitle','player_preview'):continue
                    feature_last=seq;reply={'op':'feature','seq':seq,'serial':serial,'feature':op}
                    if feature_busy.is_set() or pending or current.get('kind')=='live':
                        self.send_player(p,generation,dict(reply,ok=False,error='BUSY' if feature_busy.is_set() or pending else 'FEATURE_UNAVAILABLE'));continue
                    if not isinstance(requested,dict):continue
                    args=dict(requested,bvid=current.get('bvid',''))
                    if op in ('player_metadata','player_subtitle','player_preview'):args['cid']=current.get('cid','')
                    if op=='comments' and current.get('aid'):args['aid']=current['aid']
                    try:args=safe_args(op,args)
                    except Failure as exc:self.send_player(p,generation,dict(reply,**error_result(exc)));continue
                    feature_busy.set()
                    def feature_work(operation,arguments,response,account_generation):
                        try:response.update(ok=True,data=self.dispatch(operation,arguments,account_generation))
                        except Exception as exc:response.update(error_result(exc))
                        finally:feature_busy.clear()
                        self.send_player(p,generation,response)
                    t=threading.Thread(target=feature_work,args=(op,args,reply,self.qr_generation));t.daemon=True;t.start();continue
                if value.get('action')=='capabilities':
                    transactional=value.get('switch_ack') is True
                    continue
                if value.get('action')=='stream_result':
                    if pending and type(value.get('seq')) is int and value['seq']==pending['seq'] and type(value.get('ok')) is bool:
                        if value['ok']:commit(pending)
                        else:ahead()
                        pending=None
                    continue
                if value.get('action')=='settings':
                    save_failed=False
                    with self.lock:
                        if generation==self.play_generation and self.player is p:
                            self.playback_settings=clean_settings(value.get('settings'))
                            try:
                                if self.preferences:self.preferences.save(self.playback_settings)
                                else:save_failed=True
                            except (OSError,ValueError):save_failed=True
                    if save_failed:self.send_player(p,generation,{'op':'preferences','ok':False})
                    continue
                seq,action=value.get('seq'),value.get('action')
                if type(seq) is not int or not last<seq<10000000 or action not in ('quality','codec','next','previous','story'):continue
                last=seq
                response={'op':'stream','seq':seq,'ok':False,'error':'BAD_INPUT'}
                try:
                    if pending:raise Failure('BUSY')
                    if current.get('kind')=='live' and action!='quality':raise Failure('FEATURE_UNAVAILABLE')
                    self.remember_playback(True)
                    if cache:cache.cancel_pending()
                    requested=dict(current);new_index=index;next_feed=feed
                    if action=='story':next_feed=StoryFeed(lambda a:self.helper('story',a),lambda a,c:self.helper('story',a,c))
                    if action in ('quality','codec'):
                        selected=value.get(action)
                        if type(selected) is not int or selected not in (QUALITIES if action=='quality' else CODECS):raise Failure('BAD_INPUT')
                        requested[action]=selected
                    else:
                        if next_feed:
                            try:new_index,row=next_feed.target(-1 if action=='previous' else 1)
                            except IndexError:raise Failure('CANCELED')
                            except ValueError:raise Failure('STORY_UNAVAILABLE')
                            requested=dict(row)
                        else:
                            new_index=index+(1 if action=='next' else -1)
                            if queue_source and self.qr_generation!=account_generation:raise Failure('CANCELED')
                            pages_read=0
                            while new_index==len(playlist) and queue_more and queue_source and queue_source['category']!='parts':
                                if self.qr_generation!=account_generation:raise Failure('CANCELED')
                                if len(playlist)>=2000:raise Failure('RESOURCE_LIMIT')
                                if pages_read>=4:raise Failure('BUSY')
                                if queue_source['page']>=100:queue_more=False;break
                                source=dict(queue_source,page=queue_source['page']+1)
                                data=self.dispatch('catalog_library',safe_args('catalog_library',source),account_generation)
                                known=set(r.get('bvid') for r in playlist)
                                for r in data['items']:
                                    if r.get('kind')=='video' and r.get('playable') and r.get('bvid') not in known:
                                        playlist.append(r);known.add(r['bvid'])
                                queue_source=source;queue_more=data['more']
                                pages_read+=1
                            if not 0<=new_index<len(playlist):raise Failure('CANCELED')
                            requested=dict(playlist[new_index])
                        if not requested.get('cid'):
                            details=self.dispatch('detail',safe_args('detail',requested),0)
                            if not details['parts']:raise Failure('NO_SUPPORTED_STREAM')
                            requested=dict(details['parts'][0])
                            requested.update(title=details.get('title',''),up=details.get('up',''),part_title=requested.get('title',''))
                        requested['quality']=0 if action=='story' else current.get('quality',0)
                        requested['codec']=0 if action=='story' else current.get('codec',0)
                    hit=cache.take(requested) if cache and action in ('next','previous') else None
                    if hit:args,data=hit
                    elif action in ('quality','codec'):
                        args=safe_args('play',requested);data=self.helper('live_play' if args.get('kind')=='live' else 'play',args)
                    else:args,data=resolve(requested)
                    if not decode_budget(data):raise Failure('RESOURCE_LIMIT')
                    keep=action in ('quality','codec')
                    next_serial=serial if keep else serial+1
                    response.update(ok=True,video=data['video'],audio=data.get('audio',''),quality=data.get('quality',0),width=data.get('width',0),height=data.get('height',0),
                        qualities=data.get('qualities',[]),preview=data.get('preview') is True,codec=data.get('codec',7),codecs=data.get('codecs',[]),
                        title=short(requested.get('title'),100),up=short(requested.get('up'),40),story=bool(next_feed),story_page=next_feed.page if next_feed else 0,
                        serial=next_serial,keep_position=keep,queue_index=new_index+(next_feed.base if next_feed else 0),queue_count=len(next_feed.rows)+next_feed.base if next_feed else len(playlist)+int(queue_more))
                    # Explicit isolated acceptance only: reject one unavailable
                    # candidate before opening it, then require native rollback.
                    # No fabricated network request or vendor decoder damage.
                    if self.ux_probe and self.ux_fault_pending and action=='quality':
                        response['video']='';self.ux_fault_pending=False;self.ux_faults+=1
                    if self.send_player(p,generation,response):
                        proposed=dict(seq=seq,args=args,index=new_index,serial=next_serial,feed=next_feed,keep=keep)
                        if transactional:pending=proposed
                        else:commit(proposed)
                except Failure as e:
                    response.update(ok=False,error=e.error);self.send_player(p,generation,response)
                    ahead()
                except Exception:
                    response.update(ok=False,error='INTERNAL');self.send_player(p,generation,response)
                    ahead()
        finally:
            if cache:
                stats=cache.close()
                if self.media_relay:
                    with self.media_relay.lock:stats.update({'relay_'+k:v for k,v in self.media_relay.stats.items()})
                with open(os.path.join(self.root,'prefetch-result.json'),'w') as f:json.dump(stats,f)
            try:p.stdout.close()
            except OSError:pass

    def reap_player(self, p):
        code = p.wait()
        if self.protocol==2:
            with self.player_pipe_lock:
                try:p.stdin.close()
                except (OSError,ValueError):pass
        with self.lock:
            self.children.discard(p)
            if self.player is p:
                self.remember_playback(True)
                # Drain the native EOF/stop snapshot before clearing its identity.
                # Failure disables sync; never retry an uncertain account write.
                try:self.media_actions.observe()
                except Exception as exc:self.media_actions.enabled=False;self.media_actions.failure=getattr(exc,'error','INTERNAL')
                # A completed watch is final. Otherwise polling or closing
                # the service can recreate a history entry the user cleared.
                self.play_item = None
                self.play_end = 'ended' if code == 0 else 'failed'
                self.play_exit_code = code
                self.play_diagnostic('player_exit', code=code)

    def stop_player(self):
        with self.lock:
            self.remember_playback(True)
            try:self.media_actions.observe(final=True)
            except Exception as exc:self.media_actions.enabled=False;self.media_actions.failure=getattr(exc,'error','INTERNAL')
            self.play_generation += 1
            if self.player is not None and self.player.poll() is None: self.player.terminate()

    def remember_playback(self,force=False):
        if not self.library or not self.play_item or (not force and time.monotonic()-self.history_at<15):return
        try:
            with open(os.path.join(self.root,'watch-state.json'),'r') as f:value=json.loads(f.read(8192))
            if not isinstance(value,dict):return
            generation,serial,metadata=self.play_item
            if value.get('generation')!=generation or value.get('serial')!=serial or not value.get('loaded') or value.get('switch_pending'):return
            self.library.record(metadata,value.get('position',0),value.get('duration',0));self.history_at=time.monotonic()
        except (OSError,ValueError,TypeError):pass

    def state(self):
        with self.lock:
            self.remember_playback()
            result={'preparing': self.preparing,
                    'playing': self.player is not None and self.player.poll() is None,
                    'play_end': self.play_end,
                    'play_exit_code': self.play_exit_code,
                    'remaining': max(0, int(self.deadline-time.monotonic()))}
            result['live_danmaku']={k:v for k,v in self.live_danmaku_stats.items() if type(v) in (bool,int)}
            result['cloud_sync']=self.media_actions.state()
            if self.protocol==2:
                try:
                    with open(os.path.join(self.root,'player-state.json'),'r') as f:raw=f.read(8192)
                    value=json.loads(raw)
                    if value.get('generation')==self.play_generation:
                        result['player']={k:v for k,v in value.items() if isinstance(v,(bool,int,float)) and re.match(r'^[a-z_]{1,32}$',k)}
                    with open(os.path.join(self.root,'media-state.json'),'r') as f:media=json.loads(f.read(8192))
                    if media.get('generation')==self.play_generation and 'player' in result:
                        result['player'].update({k:v for k,v in media.items() if isinstance(v,(bool,int,float)) and re.match(r'^[a-z_]{1,32}$',k)})
                except (OSError,ValueError,TypeError):pass
                if self.story_cache and 'player' in result:
                    with self.story_cache.lock:
                        result['player'].update({'prefetch_'+k:v for k,v in self.story_cache.stats.items()})
                if self.media_relay and 'player' in result:
                    with self.media_relay.lock:
                        result['player'].update({'relay_'+k:v for k,v in self.media_relay.stats.items()})
            return result

    def player_test(self,request):
        if not self.automation or not self.qa_claimed or self.protocol!=2:raise Failure('CANCELED')
        if isinstance(request,dict) and request.get('action')=='ux_unavailable_stream':
            if not self.ux_probe or self.ux_fault_pending or self.ux_faults or self.state().get('player',{}).get('paused') is not True:raise Failure('CANCELED')
            self.ux_fault_pending=True
            if not self.send_player(self.player,self.play_generation,dict(op='test',action='quality_32')):
                self.ux_fault_pending=False;raise Failure('CANCELED')
            return {'ok':True}
        if not isinstance(request,dict) or request.get('action') not in PLAYER_TEST_ACTIONS:raise Failure('BAD_INPUT')
        if not self.send_player(self.player,self.play_generation,dict(op='test',action=request['action'])):raise Failure('CANCELED')
        return {'ok':True}

    def close(self):
        with self.lock:
            self.remember_playback(True)
            self.stopping.set()
            self.qr_generation += 1
            self.qr_key = ''
            self.play_generation += 1
            children = list(self.children)
            for p in children:
                if p.poll() is None: p.terminate()
        deadline = time.monotonic()+(12 if self.hardware_required else 3)
        for p in children:
            try: p.wait(timeout=max(.01, deadline-time.monotonic()))
            except subprocess.TimeoutExpired: p.kill(); p.wait()
        for t in self.threads: t.join(.3)
        if self.toolbox:self.toolbox.close();self.toolbox=None
        if self.media_relay:self.media_relay.close();self.media_relay=None
        # No persisted QR or job cache. Credentials are intentionally retained.
        with self.lock: self.jobs.clear(); self.images.clear(); self.image_data.clear()


class Handler(BaseHTTPRequestHandler):
    def reply(self, data, status=200):
        encoded = json.dumps(data, ensure_ascii=True, separators=(',', ':')).encode('ascii')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers(); self.wfile.write(encoded)

    def authorized(self, bootstrap=False):
        hosts = self.headers.get_all('Host', [])
        if hosts != [self.server.expected_host] or self.headers.get('Origin') is not None: return False
        if self.headers.get('Sec-Fetch-Site') is not None: return False
        if bootstrap: return self.headers.get('X-P011-Native-UI') == 'bili-qml-runtime'
        return self.headers.get_all('X-P011-Token', []) == [self.server.backend.token]

    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        if length > 4096: self.error(413); return
        bootstrap = self.path == '/bootstrap'
        if not self.authorized(bootstrap): self.error(403); return
        try:
            raw = self.rfile.read(length)
            if len(raw) != length: self.error(400); return
            if bootstrap: self.reply({'token': self.server.backend.bootstrap()}); return
            if self.path == '/player/stop': self.server.backend.stop_player(); self.reply({'ok': True}); return
            if self.path == '/exit':
                self.server.backend.stop_player()
                path = os.path.join(self.server.backend.root, 'stop.request')
                try:
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
                    os.close(fd)
                except FileExistsError:
                    if os.path.islink(path) or not os.path.isfile(path): raise Failure('BAD_INPUT')
                self.reply({'ok': True}); return
            request = json.loads(raw.decode('utf-8'))
            if not isinstance(request, dict): raise Failure('BAD_INPUT')
            if self.path == '/qa/start': self.reply(self.server.backend.qa_start()); return
            if self.path == '/qa/performance': self.reply(self.server.backend.performance_finish(request)); return
            if self.path == '/qa/finish': self.reply(self.server.backend.qa_finish(request)); return
            if self.path == '/qa/state': self.reply(self.server.backend.ux_state_check(request)); return
            if self.path == '/qa/features': self.reply(self.server.backend.feature_check(request)); return
            if self.path == '/player/test': self.reply(self.server.backend.player_test(request)); return
            if self.path == '/pinyin':
                args = safe_args('pinyin', request)
                self.reply({'ok':True, 'data':self.server.backend.lookup_pinyin(args['code'])}); return
            if self.path != '/jobs': self.error(404); return
            job = self.server.backend.submit(request.get('op'), request.get('args', {}))
            self.reply({'job': job})
        except (ValueError, UnicodeError): self.reply(error_result(Failure('BAD_INPUT')), 400)
        # Qt 5's XMLHttpRequest can expose HTTP 409 as status=0 with no body.
        # Authenticated application errors use the normal JSON envelope so the
        # UI can distinguish invalid input / expired QR / busy from transport.
        # Origin/token/Host failures remain actual HTTP 403 above.
        except Failure as exc: self.reply(error_result(exc), 409 if bootstrap else 200)

    def do_GET(self):
        if not self.authorized(): self.error(403); return
        if self.path == '/state': self.reply(self.server.backend.state()); return
        if re.match(r'^/jobs/[0-9a-f]{24}$', self.path):
            try: self.reply(self.server.backend.result(self.path[6:]))
            except Failure as exc: self.reply(error_result(exc), 404)
            return
        self.error(404)


def main():
    import ctypes
    import config as C
    from native_safety import owned_directory
    # Linux guard: process dies if guardian worker dies, and cores disabled.
    libc = ctypes.CDLL(None)
    class Limit(ctypes.Structure): _fields_ = [('cur', ctypes.c_ulong), ('max', ctypes.c_ulong)]
    libc.setrlimit(4, ctypes.byref(Limit(0, 0)))
    parent = os.getppid()
    libc.prctl(1, signal.SIGTERM, 0, 0, 0)
    if os.getppid() != parent or parent == 1: raise SystemExit('parent unavailable')
    root = owned_directory(C.REMOTE, create=False)
    account = owned_directory('/mnt/data/p011-toolbox/bili-account', create=True)
    os.chmod(account, 0o700)
    cookie = os.path.join(account, 'cookies.txt')
    if os.path.lexists(cookie):
        info = os.lstat(cookie)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid(): raise SystemExit('unsafe private account file')
        os.chmod(cookie, 0o600)
    env = dict(os.environ, LD_LIBRARY_PATH=C.MEDIA+'/lib', XDG_RUNTIME_DIR='/run/user/0',
               WAYLAND_DISPLAY='wayland-0', SDL_VIDEODRIVER='wayland',
               P011_AWAKE_LEASE=root+'/lease.json', P011_AWAKE_SESSION=C.SESSION)
    for key in ('http_proxy','https_proxy','all_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','LD_PRELOAD','SDL_DYNAMIC_API'):
        env.pop(key, None)
    state = Backend(root, C.MEDIA+'/bin/bili-api', C.MEDIA+'/bin/bili-player', account, env,
                    automation=getattr(C, 'UI_AUTOMATION', False),protocol=getattr(C,'PLAYER_PROTOCOL',1),hardware_required='bin/bili-hw' in C.MEDIA_FILES)
    state.benchmark_seek=getattr(C,'BENCHMARK_SEEK',False) is True
    state.ux_probe=(getattr(C,'UX_PROBE',False) is True and getattr(C,'UX_STATE',False) is True and state.automation and state.hardware_required and state.protocol==2)
    state.feature_probe=(getattr(C,'FEATURE_PROBE',False) is True and state.automation and state.protocol==2)
    state.catalog_probe=(getattr(C,'CATALOG_PROBE',False) is True and state.automation and state.protocol==2)
    state.story_probe=(getattr(C,'STORY_PROBE',False) is True and state.automation and state.protocol==2 and state.hardware_required)
    state.benchmark_danmaku_delay=(state.automation and state.protocol==2 and
        type(getattr(C,'BENCHMARK_DANMAKU_DELAY',None)) is int and C.BENCHMARK_DANMAKU_DELAY==8 and
        getattr(C,'BENCHMARK_QUALITY',None) in (80,116) and not state.benchmark_seek)
    try:
        state.preferences=Preferences(root+'/preferences' if state.automation else '/mnt/data/p011-toolbox/bili-preferences')
        state.playback_settings=state.preferences.load()
    except (OSError,ValueError):state.preferences=None
    # Do not promise resume when a legacy, separately frozen media runtime
    # is selected by the original entry point. It ignores the start field.
    if getattr(C,'UX_STATE',False) is True:
        try:state.library=Library(root+'/library' if state.automation else '/mnt/data/p011-toolbox/bili-library')
        except (OSError,ValueError):state.library=None
    if getattr(C,'TOOLBOX',False):
        from toolbox_runtime import Toolbox
        state.toolbox=Toolbox(root,state.automation)
    server = HTTPServer(('127.0.0.1', 0), Handler)
    server.backend = state
    server.expected_host = '127.0.0.1:'+str(server.server_address[1])
    endpoint = os.path.join(root, 'bili-endpoint.json')
    addresses={'url': 'http://'+server.expected_host}
    if state.toolbox:addresses['toolbox_url']=state.toolbox.endpoint
    with open(endpoint, 'w') as f: json.dump(addresses, f)
    os.chmod(endpoint, 0o600)
    def stop(signum, frame): state.stopping.set()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    t = threading.Thread(target=server.serve_forever)
    t.daemon = True; t.start()
    print('P011_BILI_SERVICE_READY', flush=True)
    try:
        while not state.stopping.wait(.25) and time.monotonic() < state.deadline: pass
    finally:
        server.shutdown()
        state.close()
        server.server_close()
        if os.path.isfile(endpoint): os.unlink(endpoint)
        print('P011_BILI_SERVICE_STOPPED', flush=True)


if __name__ == '__main__': main()
