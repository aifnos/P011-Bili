"""Ordering experiment's host guard checks; never a GPU readiness claim."""
from pathlib import Path
import unittest

BASE=Path(__file__).resolve().parents[1]

class DisplayFirstTests(unittest.TestCase):
    def setUp(self):
        self.source=(BASE/'client/player_v2.cpp').read_text(encoding='utf-8')
        self.function=self.source.split('static bool prepare_display_buffers(',1)[1].split('\n#endif',1)[0]

    def test_prepares_before_media_initialization(self):
        call=self.source.index('if(!prepare_display_buffers(window))')
        self.assertLess(call,self.source.index('mpv_handle*m=mpv_create()',call))
        self.assertLess(call,self.source.index('if(load_selected(request,initial_position,false)<0)'))

    def test_observed_allocations_not_frame_count_or_sleep(self):
        for evidence in ('p011_drm_trace::snapshot()', 'r.value("result",-1)==0',
                         'r.value("errno",-1)==0', 'if(matched>=3)'):
            self.assertIn(evidence,self.function)
        for forbidden in ('SDL_Delay(', 'usleep(', 'glGenFramebuffers', 'hw.open('):
            self.assertNotIn(forbidden,self.function)

    def test_stops_on_error_or_deadline(self):
        for gate in ('frames<48','SDL_GetTicks()-began)<750','!stopping','!quit',
                     'inspect_gl("prepare_clear")','inspect_gl("prepare_swap")',
                     'catch(...){evidence();throw;}'):
            self.assertIn(gate,self.function)

    def test_build_is_explicit_and_restricted(self):
        source=(BASE/'build/build_client.py').read_text()
        self.assertIn("if '--display-first' in sys.argv:",source)
        self.assertIn("if '--graphics-trace' not in sys.argv or '--strip-window' not in sys.argv:",source)
        self.assertIn('#ifdef P011_DISPLAY_FIRST',self.source)

    def test_safe_archive_retains_numeric_allocation_evidence(self):
        source=(BASE/'host/client_results.py').read_text(encoding='utf-8')
        self.assertIn("'device/display-prepare.json'",source)

if __name__=='__main__':unittest.main()
