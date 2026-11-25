/*
  Simple DirectMedia Layer
  Copyright (C) 1997-2018 Sam Lantinga <slouken@libsdl.org>

  This software is provided 'as-is', without any express or implied
  warranty.  In no event will the authors be held liable for any damages
  arising from the use of this software.

  Permission is granted to anyone to use this software for any purpose,
  including commercial applications, and to alter it and redistribute it
  freely, subject to the following restrictions:

  1. The origin of this software must not be misrepresented; you must not
     claim that you wrote the original software. If you use this software
     in a product, an acknowledgment in the product documentation would be
     appreciated but is not required.
  2. Altered source versions must be plainly marked as such, and must not be
     misrepresented as being the original software.
  3. This notice may not be removed or altered from any source distribution.
*/

#include "../../SDL_internal.h"

#if SDL_VIDEO_DRIVER_WAYLAND && SDL_VIDEO_OPENGL_EGL

#include "../SDL_sysvideo.h"
#include "../../events/SDL_windowevents_c.h"
#include "../SDL_egl_c.h"
#include "SDL_waylandevents_c.h"
#include "SDL_waylandwindow.h"
#include "SDL_waylandvideo.h"
#include "SDL_waylandtouch.h"
#include "SDL_waylanddyn.h"
#include "SDL_hints.h"
#include "SDL_timer.h"
#include <errno.h>
#include <poll.h>

#include "xdg-shell-unstable-v6-client-protocol.h"

/* On modern desktops, we probably will use the xdg-shell protocol instead
   of wl_shell, but wl_shell might be useful on older Wayland installs that
   don't have the newer protocol, or embedded things that don't have a full
   window manager. */

static void
handle_ping_wl_shell_surface(void *data, struct wl_shell_surface *shell_surface,
            uint32_t serial)
{
    wl_shell_surface_pong(shell_surface, serial);
}

static void
handle_configure_wl_shell_surface(void *data, struct wl_shell_surface *shell_surface,
                 uint32_t edges, int32_t width, int32_t height)
{
    SDL_WindowData *wind = (SDL_WindowData *)data;
    SDL_Window *window = wind->sdlwindow;
    struct wl_region *region;

    ++wind->p011_wl_configure_count;
    wind->p011_wl_width = width;
    wind->p011_wl_height = height;
    if (wind->p011_center_requested) {
        if (wind->p011_center_established && (width != 800 || height != 480))
            SDL_SendWindowEvent(window, SDL_WINDOWEVENT_CLOSE, 0, 0);
        /* The fullscreen dimensions describe the output, not our EGL buffer. */
        return;
    }

    /* wl_shell_surface spec states that this is a suggestion.
       Ignore if less than or greater than max/min size. */

    if (width == 0 || height == 0) {
        return;
    }

    if (!(window->flags & SDL_WINDOW_FULLSCREEN)) {
        if ((window->flags & SDL_WINDOW_RESIZABLE)) {
            if (window->max_w > 0) {
                width = SDL_min(width, window->max_w);
            } 
            width = SDL_max(width, window->min_w);

            if (window->max_h > 0) {
                height = SDL_min(height, window->max_h);
            }
            height = SDL_max(height, window->min_h);
        } else {
            return;
        }
    }

    if (width == window->w && height == window->h) {
        return;
    }

    window->w = width;
    window->h = height;
    WAYLAND_wl_egl_window_resize(wind->egl_window, window->w, window->h, 0, 0);

    region = wl_compositor_create_region(wind->waylandData->compositor);
    wl_region_add(region, 0, 0, window->w, window->h);
    wl_surface_set_opaque_region(wind->surface, region);
    wl_region_destroy(region);
    SDL_SendWindowEvent(window, SDL_WINDOWEVENT_RESIZED, window->w, window->h);
}

static void
handle_popup_done_wl_shell_surface(void *data, struct wl_shell_surface *shell_surface)
{
}

static const struct wl_shell_surface_listener shell_surface_listener_wl = {
    handle_ping_wl_shell_surface,
    handle_configure_wl_shell_surface,
    handle_popup_done_wl_shell_surface
};




static void
handle_configure_zxdg_shell_surface(void *data, struct zxdg_surface_v6 *zxdg, uint32_t serial)
{
    SDL_WindowData *wind = (SDL_WindowData *)data;
    SDL_Window *window = wind->sdlwindow;
    struct wl_region *region;
    WAYLAND_wl_egl_window_resize(wind->egl_window, window->w, window->h, 0, 0);

    region = wl_compositor_create_region(wind->waylandData->compositor);
    wl_region_add(region, 0, 0, window->w, window->h);
    wl_surface_set_opaque_region(wind->surface, region);
    wl_region_destroy(region);
    SDL_SendWindowEvent(window, SDL_WINDOWEVENT_RESIZED, window->w, window->h);
    zxdg_surface_v6_ack_configure(zxdg, serial);
    /* P011 private alteration. Only this actual callback marks readiness. */
    wind->shell_surface.zxdg.initial_configure_seen = SDL_TRUE;
    ++wind->shell_surface.zxdg.configure_count;
}

static const struct zxdg_surface_v6_listener shell_surface_listener_zxdg = {
    handle_configure_zxdg_shell_surface
};


static void
handle_configure_zxdg_toplevel(void *data,
			  struct zxdg_toplevel_v6 *zxdg_toplevel_v6,
			  int32_t width,
			  int32_t height,
			  struct wl_array *states)
{
    SDL_WindowData *wind = (SDL_WindowData *)data;
    SDL_Window *window = wind->sdlwindow;

    /* wl_shell_surface spec states that this is a suggestion.
       Ignore if less than or greater than max/min size. */

    if (width == 0 || height == 0) {
        return;
    }

    if (!(window->flags & SDL_WINDOW_FULLSCREEN)) {
        if ((window->flags & SDL_WINDOW_RESIZABLE)) {
            if (window->max_w > 0) {
                width = SDL_min(width, window->max_w);
            } 
            width = SDL_max(width, window->min_w);

            if (window->max_h > 0) {
                height = SDL_min(height, window->max_h);
            }
            height = SDL_max(height, window->min_h);
        } else {
            return;
        }
    }

    if (width == window->w && height == window->h) {
        return;
    }

    window->w = width;
    window->h = height;
}

static void
handle_close_zxdg_toplevel(void *data, struct zxdg_toplevel_v6 *zxdg_toplevel_v6)
{
    SDL_WindowData *window = (SDL_WindowData *)data;
    window->shell_surface.zxdg.close_requested = SDL_TRUE;
    SDL_SendWindowEvent(window->sdlwindow, SDL_WINDOWEVENT_CLOSE, 0, 0);
}

static const struct zxdg_toplevel_v6_listener toplevel_listener_zxdg = {
    handle_configure_zxdg_toplevel,
    handle_close_zxdg_toplevel
};


#ifdef SDL_VIDEO_DRIVER_WAYLAND_QT_TOUCH
static void
handle_onscreen_visibility(void *data,
        struct qt_extended_surface *qt_extended_surface, int32_t visible)
{
}

static void
handle_set_generic_property(void *data,
        struct qt_extended_surface *qt_extended_surface, const char *name,
        struct wl_array *value)
{
}

static void
handle_close(void *data, struct qt_extended_surface *qt_extended_surface)
{
    SDL_WindowData *window = (SDL_WindowData *)data;
    SDL_SendWindowEvent(window->sdlwindow, SDL_WINDOWEVENT_CLOSE, 0, 0);
}

static const struct qt_extended_surface_listener extended_surface_listener = {
    handle_onscreen_visibility,
    handle_set_generic_property,
    handle_close,
};
#endif /* SDL_VIDEO_DRIVER_WAYLAND_QT_TOUCH */

SDL_bool
Wayland_GetWindowWMInfo(_THIS, SDL_Window * window, SDL_SysWMinfo * info)
{
    SDL_WindowData *data = (SDL_WindowData *) window->driverdata;
    const Uint32 version = ((((Uint32) info->version.major) * 1000000) +
                            (((Uint32) info->version.minor) * 10000) +
                            (((Uint32) info->version.patch)));

    /* Before 2.0.6, it was possible to build an SDL with Wayland support
       (SDL_SysWMinfo will be large enough to hold Wayland info), but build
       your app against SDL headers that didn't have Wayland support
       (SDL_SysWMinfo could be smaller than Wayland needs. This would lead
       to an app properly using SDL_GetWindowWMInfo() but we'd accidentally
       overflow memory on the stack or heap. To protect against this, we've
       padded out the struct unconditionally in the headers and Wayland will
       just return an error for older apps using this function. Those apps
       will need to be recompiled against newer headers or not use Wayland,
       maybe by forcing SDL_VIDEODRIVER=x11. */
    if (version < 2000006) {
        info->subsystem = SDL_SYSWM_UNKNOWN;
        SDL_SetError("Version must be 2.0.6 or newer");
        return SDL_FALSE;
    }

    info->info.wl.display = data->waylandData->display;
    info->info.wl.surface = data->surface;
    info->info.wl.shell_surface = data->shell_surface.wl;
    info->subsystem = SDL_SYSWM_WAYLAND;

    return SDL_TRUE;
}

int
Wayland_SetWindowHitTest(SDL_Window *window, SDL_bool enabled)
{
    return 0;  /* just succeed, the real work is done elsewhere. */
}

static void
SetFullscreen(_THIS, SDL_Window * window, struct wl_output *output)
{
    const SDL_VideoData *viddata = (const SDL_VideoData *) _this->driverdata;
    SDL_WindowData *wind = window->driverdata;

    if (viddata->shell.zxdg) {
        if (output) {
            zxdg_toplevel_v6_set_fullscreen(wind->shell_surface.zxdg.roleobj.toplevel, output);
        } else {
            zxdg_toplevel_v6_unset_fullscreen(wind->shell_surface.zxdg.roleobj.toplevel);
        }
    } else {
        if (output || wind->p011_center_requested) {
            wl_shell_surface_set_fullscreen(wind->shell_surface.wl,
                                            wind->p011_center_requested ? WL_SHELL_SURFACE_FULLSCREEN_METHOD_FILL : WL_SHELL_SURFACE_FULLSCREEN_METHOD_DEFAULT,
                                            0, output);
        } else {
            wl_shell_surface_set_toplevel(wind->shell_surface.wl);
        }
    }

    WAYLAND_wl_display_flush( ((SDL_VideoData*)_this->driverdata)->display );
}

void Wayland_ShowWindow(_THIS, SDL_Window *window)
{
    struct wl_output *output = (struct wl_output *) window->fullscreen_mode.driverdata;
    SetFullscreen(_this, window, (window->flags & SDL_WINDOW_FULLSCREEN) ? output : NULL);
}

#ifdef SDL_VIDEO_DRIVER_WAYLAND_QT_TOUCH
static void SDLCALL
QtExtendedSurface_OnHintChanged(void *userdata, const char *name,
        const char *oldValue, const char *newValue)
{
    struct qt_extended_surface *qt_extended_surface = userdata;

    if (name == NULL) {
        return;
    }

    if (strcmp(name, SDL_HINT_QTWAYLAND_CONTENT_ORIENTATION) == 0) {
        int32_t orientation = QT_EXTENDED_SURFACE_ORIENTATION_PRIMARYORIENTATION;

        if (newValue != NULL) {
            if (strcmp(newValue, "portrait") == 0) {
                orientation = QT_EXTENDED_SURFACE_ORIENTATION_PORTRAITORIENTATION;
            } else if (strcmp(newValue, "landscape") == 0) {
                orientation = QT_EXTENDED_SURFACE_ORIENTATION_LANDSCAPEORIENTATION;
            } else if (strcmp(newValue, "inverted-portrait") == 0) {
                orientation = QT_EXTENDED_SURFACE_ORIENTATION_INVERTEDPORTRAITORIENTATION;
            } else if (strcmp(newValue, "inverted-landscape") == 0) {
                orientation = QT_EXTENDED_SURFACE_ORIENTATION_INVERTEDLANDSCAPEORIENTATION;
            }
        }

        qt_extended_surface_set_content_orientation(qt_extended_surface, orientation);
    } else if (strcmp(name, SDL_HINT_QTWAYLAND_WINDOW_FLAGS) == 0) {
        uint32_t flags = 0;

        if (newValue != NULL) {
            char *tmp = strdup(newValue);
            char *saveptr = NULL;

            char *flag = strtok_r(tmp, " ", &saveptr);
            while (flag) {
                if (strcmp(flag, "OverridesSystemGestures") == 0) {
                    flags |= QT_EXTENDED_SURFACE_WINDOWFLAG_OVERRIDESSYSTEMGESTURES;
                } else if (strcmp(flag, "StaysOnTop") == 0) {
                    flags |= QT_EXTENDED_SURFACE_WINDOWFLAG_STAYSONTOP;
                } else if (strcmp(flag, "BypassWindowManager") == 0) {
                    // See https://github.com/qtproject/qtwayland/commit/fb4267103d
                    flags |= 4 /* QT_EXTENDED_SURFACE_WINDOWFLAG_BYPASSWINDOWMANAGER */;
                }

                flag = strtok_r(NULL, " ", &saveptr);
            }

            free(tmp);
        }

        qt_extended_surface_set_window_flags(qt_extended_surface, flags);
    }
}

static void QtExtendedSurface_Subscribe(struct qt_extended_surface *surface, const char *name)
{
    SDL_AddHintCallback(name, QtExtendedSurface_OnHintChanged, surface);
}

static void QtExtendedSurface_Unsubscribe(struct qt_extended_surface *surface, const char *name)
{
    SDL_DelHintCallback(name, QtExtendedSurface_OnHintChanged, surface);
}
#endif /* SDL_VIDEO_DRIVER_WAYLAND_QT_TOUCH */

void
Wayland_SetWindowFullscreen(_THIS, SDL_Window * window,
                            SDL_VideoDisplay * _display, SDL_bool fullscreen)
{
    struct wl_output *output = (struct wl_output *) _display->driverdata;
    SetFullscreen(_this, window, fullscreen ? output : NULL);
}

void
Wayland_RestoreWindow(_THIS, SDL_Window * window)
{
    SDL_WindowData *wind = window->driverdata;
    const SDL_VideoData *viddata = (const SDL_VideoData *) _this->driverdata;

    if (viddata->shell.zxdg) {
    } else {
        wl_shell_surface_set_toplevel(wind->shell_surface.wl);
    }

    WAYLAND_wl_display_flush( ((SDL_VideoData*)_this->driverdata)->display );
}

void
Wayland_MaximizeWindow(_THIS, SDL_Window * window)
{
    SDL_WindowData *wind = window->driverdata;
    SDL_VideoData *viddata = (SDL_VideoData *) _this->driverdata;

    if (viddata->shell.zxdg) {
        zxdg_toplevel_v6_set_maximized(wind->shell_surface.zxdg.roleobj.toplevel);
    } else {
        wl_shell_surface_set_maximized(wind->shell_surface.wl, NULL);
    }

    WAYLAND_wl_display_flush( viddata->display );
}

/* P011 private build marker; not an upstream SDL API. */
__attribute__((visibility("default"))) int P011_WaylandConfigureTimeoutMs(void)
{
    return 500;
}

/* P011 private alteration: use SDL's own listeners, no unbounded roundtrip,
   no drawing before configure/ack, and no sleep-based readiness heuristic. */
static SDL_bool P011_ConfigureReady(SDL_WindowData *data, Uint32 previous,
                                    SDL_bool centered)
{
    SDL_zxdg_shell_surface *s = &data->shell_surface.zxdg;
    if (centered)
        return data->p011_wl_configure_count != previous &&
               data->p011_wl_width == 800 && data->p011_wl_height == 480;
    return s->initial_configure_seen && s->configure_count != previous;
}

static int P011_WaitForConfigure(SDL_WindowData *data, Uint32 previous,
                                SDL_bool centered)
{
    struct wl_display *display = data->waylandData->display;
    Uint32 deadline = SDL_GetTicks() + 500;
    while (!P011_ConfigureReady(data, previous, centered)) {
        struct pollfd fd;
        int count;
        Uint32 now;
        if (!centered && data->shell_surface.zxdg.close_requested)
            return SDL_SetError("P011 window closed before configure");
        if (WAYLAND_wl_display_dispatch_pending(display) < 0)
            return SDL_SetError("P011 configure dispatch failed");
        /* A single dispatch can deliver both configure and close. */
        if (!centered && data->shell_surface.zxdg.close_requested)
            return SDL_SetError("P011 window closed before configure");
        if (P011_ConfigureReady(data, previous, centered))
            break;
        now = SDL_GetTicks();
        if (SDL_TICKS_PASSED(now, deadline))
            return SDL_SetError("P011 initial configure timeout");
        if (WAYLAND_wl_display_prepare_read(display) != 0)
            continue;
        if (WAYLAND_wl_display_flush(display) < 0 && errno != EAGAIN) {
            WAYLAND_wl_display_cancel_read(display);
            return SDL_SetError("P011 configure flush failed");
        }
        fd.fd = WAYLAND_wl_display_get_fd(display);
        fd.events = POLLIN;
        fd.revents = 0;
        count = poll(&fd, 1, (int)SDL_min(deadline - now, 20));
        if (count > 0 && (fd.revents & (POLLERR | POLLHUP | POLLNVAL))) {
            WAYLAND_wl_display_cancel_read(display);
            return SDL_SetError("P011 configure connection closed");
        }
        if (count > 0 && (fd.revents & POLLIN)) {
            if (WAYLAND_wl_display_read_events(display) < 0)
                return SDL_SetError("P011 configure read failed");
        } else {
            WAYLAND_wl_display_cancel_read(display);
            if (count < 0 && errno != EINTR)
                return SDL_SetError("P011 configure poll failed");
        }
    }
    return 0;
}

/* P011 private API, not upstream SDL. Called before the first buffer draw.
   Only the explicitly selected wl_shell/output pair is accepted; there is
   no system SDL, random-toplevel or enlarged-buffer fallback. */
__attribute__((visibility("default"))) int P011_WaylandCenterContentWindow(SDL_Window *window)
{
    SDL_WindowData *data;
    Uint32 previous;
    const char *driver = SDL_GetCurrentVideoDriver();
    if (!driver || SDL_strcmp(driver, "wayland") != 0)
        return SDL_SetError("P011 centered content requires Wayland");
    if (!window || window->w != 800 || window->h != 268 ||
        (window->flags & (SDL_WINDOW_FULLSCREEN | SDL_WINDOW_RESIZABLE)))
        return SDL_SetError("P011 centered content requires a fixed 800x268 window");
    data = window->driverdata;
    if (!data || data->waylandData->shell.zxdg || !data->waylandData->shell.wl ||
        !data->shell_surface.wl)
        return SDL_SetError("P011 centered content requires the private wl_shell opt-in");
    previous = data->p011_wl_configure_count;
    data->p011_center_requested = SDL_TRUE;
    wl_shell_surface_set_fullscreen(data->shell_surface.wl,
                                   WL_SHELL_SURFACE_FULLSCREEN_METHOD_FILL, 0, NULL);
    wl_surface_commit(data->surface);
    if (P011_WaitForConfigure(data, previous, SDL_TRUE) < 0)
        return -1;
    data->p011_center_established = SDL_TRUE;
    return 0;
}

int Wayland_CreateWindow(_THIS, SDL_Window *window)
{
    SDL_WindowData *data;
    SDL_VideoData *c;
    struct wl_region *region;

    data = calloc(1, sizeof *data);
    if (data == NULL)
        return SDL_OutOfMemory();

    c = _this->driverdata;
    window->driverdata = data;

    if (!(window->flags & SDL_WINDOW_OPENGL)) {
        SDL_GL_LoadLibrary(NULL);
        window->flags |= SDL_WINDOW_OPENGL;
    }

    if (window->x == SDL_WINDOWPOS_UNDEFINED) {
        window->x = 0;
    }
    if (window->y == SDL_WINDOWPOS_UNDEFINED) {
        window->y = 0;
    }

    data->waylandData = c;
    data->sdlwindow = window;

    data->surface =
        wl_compositor_create_surface(c->compositor);
    wl_surface_set_user_data(data->surface, data);

    if (c->shell.zxdg) {
        data->shell_surface.zxdg.surface = zxdg_shell_v6_get_xdg_surface(c->shell.zxdg, data->surface);
        /* !!! FIXME: add popup role */
        data->shell_surface.zxdg.roleobj.toplevel = zxdg_surface_v6_get_toplevel(data->shell_surface.zxdg.surface);
        zxdg_toplevel_v6_add_listener(data->shell_surface.zxdg.roleobj.toplevel, &toplevel_listener_zxdg, data);
        zxdg_toplevel_v6_set_app_id(data->shell_surface.zxdg.roleobj.toplevel, c->classname);
    } else {
        data->shell_surface.wl = wl_shell_get_shell_surface(c->shell.wl, data->surface);
        wl_shell_surface_set_class(data->shell_surface.wl, c->classname);
    }

#ifdef SDL_VIDEO_DRIVER_WAYLAND_QT_TOUCH
    if (c->surface_extension) {
        data->extended_surface = qt_surface_extension_get_extended_surface(
                c->surface_extension, data->surface);

        QtExtendedSurface_Subscribe(data->extended_surface, SDL_HINT_QTWAYLAND_CONTENT_ORIENTATION);
        QtExtendedSurface_Subscribe(data->extended_surface, SDL_HINT_QTWAYLAND_WINDOW_FLAGS);
    }
#endif /* SDL_VIDEO_DRIVER_WAYLAND_QT_TOUCH */

    data->egl_window = WAYLAND_wl_egl_window_create(data->surface,
                                            window->w, window->h);

    /* Create the GLES window surface */
    data->egl_surface = SDL_EGL_CreateSurface(_this, (NativeWindowType) data->egl_window);
    
    if (data->egl_surface == EGL_NO_SURFACE) {
        return SDL_SetError("failed to create a window surface");
    }

    if (c->shell.zxdg) {
        if (data->shell_surface.zxdg.surface) {
            zxdg_surface_v6_set_user_data(data->shell_surface.zxdg.surface, data);
            zxdg_surface_v6_add_listener(data->shell_surface.zxdg.surface, &shell_surface_listener_zxdg, data);
        }
    } else {
        if (data->shell_surface.wl) {
            wl_shell_surface_set_user_data(data->shell_surface.wl, data);
            wl_shell_surface_add_listener(data->shell_surface.wl, &shell_surface_listener_wl, data);
        }
    }

#ifdef SDL_VIDEO_DRIVER_WAYLAND_QT_TOUCH
    if (data->extended_surface) {
        qt_extended_surface_set_user_data(data->extended_surface, data);
        qt_extended_surface_add_listener(data->extended_surface,
                                         &extended_surface_listener, data);
    }
#endif /* SDL_VIDEO_DRIVER_WAYLAND_QT_TOUCH */

    region = wl_compositor_create_region(c->compositor);
    wl_region_add(region, 0, 0, window->w, window->h);
    wl_surface_set_opaque_region(data->surface, region);
    wl_region_destroy(region);

    if (c->relative_mouse_mode) {
        Wayland_input_lock_pointer(c->input);
    }

    wl_surface_commit(data->surface);
    WAYLAND_wl_display_flush(c->display);

    if (c->shell.zxdg && P011_WaitForConfigure(data, 0, SDL_FALSE) < 0)
        return -1;

    return 0;
}

void Wayland_SetWindowSize(_THIS, SDL_Window * window)
{
    SDL_VideoData *data = _this->driverdata;
    SDL_WindowData *wind = window->driverdata;
    struct wl_region *region;

    WAYLAND_wl_egl_window_resize(wind->egl_window, window->w, window->h, 0, 0);

    region =wl_compositor_create_region(data->compositor);
    wl_region_add(region, 0, 0, window->w, window->h);
    wl_surface_set_opaque_region(wind->surface, region);
    wl_region_destroy(region);
}

void Wayland_SetWindowTitle(_THIS, SDL_Window * window)
{
    SDL_WindowData *wind = window->driverdata;
    SDL_VideoData *viddata = (SDL_VideoData *) _this->driverdata;
    
    if (window->title != NULL) {
        if (viddata->shell.zxdg) {
            zxdg_toplevel_v6_set_title(wind->shell_surface.zxdg.roleobj.toplevel, window->title);
        } else {
            wl_shell_surface_set_title(wind->shell_surface.wl, window->title);
        }
    }

    WAYLAND_wl_display_flush( ((SDL_VideoData*)_this->driverdata)->display );
}

void Wayland_DestroyWindow(_THIS, SDL_Window *window)
{
    SDL_VideoData *data = _this->driverdata;
    SDL_WindowData *wind = window->driverdata;

    if (data) {
        SDL_EGL_DestroySurface(_this, wind->egl_surface);
        WAYLAND_wl_egl_window_destroy(wind->egl_window);

        if (data->shell.zxdg) {
            if (wind->shell_surface.zxdg.roleobj.toplevel) {
                zxdg_toplevel_v6_destroy(wind->shell_surface.zxdg.roleobj.toplevel);
            }
            if (wind->shell_surface.zxdg.surface) {
                zxdg_surface_v6_destroy(wind->shell_surface.zxdg.surface);
            }
        } else {
            if (wind->shell_surface.wl) {
                wl_shell_surface_destroy(wind->shell_surface.wl);
            }
        }

#ifdef SDL_VIDEO_DRIVER_WAYLAND_QT_TOUCH
        if (wind->extended_surface) {
            QtExtendedSurface_Unsubscribe(wind->extended_surface, SDL_HINT_QTWAYLAND_CONTENT_ORIENTATION);
            QtExtendedSurface_Unsubscribe(wind->extended_surface, SDL_HINT_QTWAYLAND_WINDOW_FLAGS);
            qt_extended_surface_destroy(wind->extended_surface);
        }
#endif /* SDL_VIDEO_DRIVER_WAYLAND_QT_TOUCH */
        wl_surface_destroy(wind->surface);

        SDL_free(wind);
        WAYLAND_wl_display_flush(data->display);
    }
    window->driverdata = NULL;
}

#endif /* SDL_VIDEO_DRIVER_WAYLAND && SDL_VIDEO_OPENGL_EGL */

/* vi: set ts=4 sw=4 expandtab: */
