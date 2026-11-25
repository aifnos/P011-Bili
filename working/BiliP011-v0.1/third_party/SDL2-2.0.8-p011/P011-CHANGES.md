# Private P011 window-handshake experiment

This is an altered copy of SDL 2.0.8, not an upstream release or a replacement
for the pen's system SDL. Upstream copyright and zlib notices remain intact.
Source: https://www.libsdl.org/release/SDL2-2.0.8.tar.gz

Changes are confined to `src/video/wayland/SDL_waylandwindow.c`,
`SDL_waylandwindow.h` and `SDL_waylandsym.h`: track the real xdg configure/ack,
wait with a 500 ms monotonic deadline before returning a drawable window, and
reject timeout, connection failure or an early close. The runtime marker
`P011_WaylandConfigureTimeoutMs` identifies this private build. No fixed sleep
is treated as readiness. No vendor library or firmware is modified.

Builds and target trials must use immutable content identities and the P011
host/device safety gates. A synthetic probe pass is not video, touch, layout,
power-management or full product acceptance. The existing software baseline
must remain the default until the complete candidate passes its own checks.
