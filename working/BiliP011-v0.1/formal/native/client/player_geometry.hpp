// SPDX-License-Identifier: GPL-3.0-or-later
// Pure geometry for the protocol-2 portrait player. No system orientation or
// embedded-QML transform is changed.
#pragma once
#include <cmath>

namespace p011_player {
struct Point { double x, y; };
enum class Orientation { Landscape, PortraitClockwise };
enum class Swipe { None, Next, Previous };

struct Layout {
    Orientation orientation = Orientation::Landscape;
    static constexpr double physical_width = 800;
    static constexpr double physical_height = 268;
    static constexpr double content_top = 106;

    double width() const { return portrait() ? physical_height : physical_width; }
    double height() const { return portrait() ? physical_width : physical_height; }
    bool portrait() const { return orientation == Orientation::PortraitClockwise; }
    bool contains(Point logical) const {
        return std::isfinite(logical.x) && std::isfinite(logical.y) &&
               logical.x >= 0 && logical.y >= 0 && logical.x <= width() && logical.y <= height();
    }
    Point physical(Point logical) const {
        return portrait() ? Point{physical_width-logical.y, content_top+logical.x}
                          : Point{logical.x, content_top+logical.y};
    }
    bool logical(Point screen, Point &result) const {
        if (!std::isfinite(screen.x) || !std::isfinite(screen.y) || screen.x < 0 ||
            screen.x > physical_width || screen.y < content_top ||
            screen.y > content_top+physical_height) return false;
        result = portrait() ? Point{screen.y-content_top, physical_width-screen.x}
                            : Point{screen.x, screen.y-content_top};
        return contains(result);
    }
    // Classify in LOGICAL coordinates, after inverse rotation. A gesture that
    // started on a button remains owned by that button, even after moving away.
    Swipe swipe(Point start, Point end, unsigned elapsed_ms, bool button_owned) const {
        if (!portrait() || button_owned || !contains(start) || !contains(end) ||
            elapsed_ms == 0 || elapsed_ms > 1500) return Swipe::None;
        const double dx=end.x-start.x, dy=end.y-start.y;
        if (std::abs(dy) < 72 || std::abs(dy) < 1.4*std::abs(dx)) return Swipe::None;
        return dy < 0 ? Swipe::Next : Swipe::Previous;
    }
};
}
