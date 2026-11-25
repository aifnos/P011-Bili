// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "player_geometry.hpp"
#include <algorithm>

namespace p011_player {
// Layout and automation retain the established 800x480 panel coordinates.
// A content-only Wayland surface removes the unused margins exactly once at
// the native input / rendering boundary. Embedded QML is not transformed.
struct Surface {
    bool content_only=false;
    double width() const { return Layout::physical_width; }
    double height() const { return content_only?Layout::physical_height:480.; }
    double top() const { return content_only?Layout::content_top:0.; }
    Point local(Point panel) const { return {panel.x,panel.y-top()}; }
    Point panel(Point local) const { return {local.x,local.y+top()}; }
    Point from_normalized(Point p) const { return panel({p.x*width(),p.y*height()}); }
    Point ndc(Point panel_point) const {
        Point p=local(panel_point);return {p.x*2/width()-1,1-p.y*2/height()};
    }
    struct Clip {int x,y,w,h;};
    Clip clip(Point panel_a,Point panel_b,int drawable_w,int drawable_h) const {
        Point a=local(panel_a),b=local(panel_b);
        double left=std::max(0.,std::min(width(),std::min(a.x,b.x)));
        double right=std::max(left,std::min(width(),std::max(a.x,b.x)));
        double upper=std::max(0.,std::min(height(),std::min(a.y,b.y)));
        double lower=std::max(upper,std::min(height(),std::max(a.y,b.y)));
        return {int(left*drawable_w/width()),int((height()-lower)*drawable_h/height()),
                int((right-left)*drawable_w/width()),int((lower-upper)*drawable_h/height())};
    }
};
inline Surface active_surface() {
#ifdef P011_STRIP_WINDOW
    return {true};
#else
    return {false};
#endif
}
}
