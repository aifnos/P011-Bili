"""Static safety contract, not evidence that a compositor positioned anything."""
from pathlib import Path
import unittest

BASE=Path(__file__).resolve().parents[1]
class CenteredWindowTests(unittest.TestCase):
    def setUp(self):
        self.sdl=(BASE/'third_party/SDL2-2.0.8-p011/src/video/wayland/SDL_waylandwindow.c').read_text(encoding='utf-8')
        self.player=(BASE/'client/player_v2.cpp').read_text(encoding='utf-8')
    def test_fresh_configure_and_dimensions_required(self):
        for value in ('data->p011_wl_configure_count != previous',
                      'data->p011_wl_width == 800','data->p011_wl_height == 480',
                      'P011_WaitForConfigure(data, previous, SDL_TRUE)'):
            self.assertIn(value,self.sdl)
    def test_centers_before_drawing_and_media_initialization(self):
        at=self.player.index('center_content(window)')
        self.assertLess(at,self.player.index('SDL_GL_CreateContext(window)'))
        self.assertLess(at,self.player.index('prepare_display_buffers(window)'))
    def test_no_fallback_on_unconfirmed_role(self):
        self.assertIn('if(center_result!=0)return 39;',self.player)
        for value in ('window->w != 800 || window->h != 268',
                      'SDL_WINDOW_FULLSCREEN | SDL_WINDOW_RESIZABLE',
                      'data->waylandData->shell.zxdg || !data->waylandData->shell.wl'):
            self.assertIn(value,self.sdl)
    def test_fixed_buffer_ignores_output_size_hint(self):
        start=self.sdl.index('handle_configure_wl_shell_surface(')
        callback=self.sdl[start:self.sdl.index('handle_popup_done_wl_shell_surface',start)]
        self.assertLess(callback.index('center_requested'),callback.index('window->w = width'))
        self.assertIn('if (wind->p011_center_requested)',callback)
    def test_runtime_contract_loss_closes(self):
        self.assertIn('wind->p011_center_established &&',self.sdl)
        self.assertIn('SDL_SendWindowEvent(window, SDL_WINDOWEVENT_CLOSE, 0, 0);',self.sdl)
    def test_confirmation_not_claimed_physical(self):
        self.assertIn('"actual_scanout_checked",false',self.player)
    def test_legacy_protocol_is_private_explicit_opt_in(self):
        video=(BASE/'third_party/SDL2-2.0.8-p011/src/video/wayland/SDL_waylandvideo.c').read_text(encoding='utf-8')
        self.assertIn('!SDL_GetHintBoolean("P011_WAYLAND_CENTERED_WL_SHELL", SDL_FALSE)',video)
        self.assertLess(self.player.index('SDL_SetHint("P011_WAYLAND_CENTERED_WL_SHELL"'),self.player.index('SDL_Init(SDL_INIT_VIDEO'))
        self.assertIn('WL_SHELL_SURFACE_FULLSCREEN_METHOD_FILL',self.sdl)
    def test_bounded_no_sleep_guess(self):
        wait=self.sdl.split('static int P011_WaitForConfigure(',1)[1].split('int P011_WaylandCenterContentWindow',1)[0]
        self.assertIn('SDL_GetTicks() + 500',wait)
        self.assertNotIn('SDL_Delay',wait)
        self.assertNotIn('wl_display_roundtrip',wait)
    def test_screen_hold_is_only_explicit_automation(self):
        from build_awake_trial import build
        options=dict(client=True,automated=True,player_protocol=2,ux_state=True,toolbox=True,screen_check=True)
        for change in ({'client':False},{'automated':False},{'player_protocol':1},{'ux_state':False},
                       {'toolbox':False},{'feature_probe':True},{'catalog_probe':True},{'ux_probe':True},
                       {'soak_seconds':130},{'benchmark_quality':32},{'demo_seconds':180},{'screen_check':1}):
            with self.assertRaises(ValueError):build(None,**dict(options,**change))
    def test_stable_pose_hold_does_not_change_manual_player(self):
        qml=(BASE/'client/PlayerAutomation.qml').read_text(encoding='utf-8')
        self.assertIn('property int screenHoldMs: 0',qml)
        self.assertIn('if(!screenHoldMs)return true;',qml)
        self.assertEqual(qml.count('if(!screenReady('),3)
        self.assertIn('screenReady(p.generation===2&&p.story&&p.portrait)',qml)
        self.assertNotIn('screenHoldMs',self.player)
    def test_focused_pose_requires_fixed_muted_benchmark(self):
        from build_awake_trial import build
        options=dict(client=True,automated=True,player_protocol=2,ux_state=True,benchmark_quality=32,window_pose='portrait')
        for change in ({'window_pose':'bad'},{'automated':False},{'player_protocol':1},{'ux_state':False},
                       {'benchmark_quality':80},{'benchmark_bvid':'BV1234567890'},{'benchmark_seek':True},
                       {'toolbox':True},{'screen_check':True},{'feature_probe':True}):
            with self.assertRaises(ValueError):build(None,**dict(options,**change))

if __name__=='__main__':unittest.main()
