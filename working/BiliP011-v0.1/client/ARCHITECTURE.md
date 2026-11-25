# P011 Bili client adapter v0.2

Goal remains all five user functions, not merely the anonymous probe. This adapter uses the pen's Qt 5.10/QML styling, a confined offline Pinyin/ASCII keyboard, and native libcurl/OpenSSL + libmpv in a private runtime. The original keyboard inspected is principally alphanumeric, not a verified Chinese input method. The previously cross-built full wiliwili worktree remains intact as upstream reference; its desktop layout is not represented as adapted or device-tested.

## Boundaries

- UI: 800×268 inside the temporary copied factory UI, no duplicate y offset or rotation. Three large horizontal cards, detail/part selection, recommendation/following/search/bangumi tabs, explicit QR login. Text is plain, never untrusted QML/HTML.
- Loopback service: exact Host, no browser Origin, one-shot native bootstrap, per-session header token, bounded workers and jobs. Only fixed API/media operations; no shell or arbitrary commands/paths.
- API helper: stdin/stdout JSON is private IPC, never raw-logged. HTTPS certificate checks on, API and image hosts allowlisted; no account cookies to CDN/image hosts. Normalized responses, WBI, authorized play URLs and QR protocol derived from pinned wiliwili.
- Credentials: only `/mnt/data/p011-toolbox/bili-account/` (0700; cookie file 0600) plus process memory. No credentials in UI results, CLI arguments, telemetry or archives. QR matrix lives in memory; no login-page screenshots in automated collection. Local logout requires an explicit UI action.
- Player: libmpv + vendor SDL/GLES, system font files only. Independent URL pair arrives over stdin, not argv/logs. Pause/resume/seek/volume/back controls; real playback heartbeat holds a finite lease through the factory bridge.
- Supervision: reuse exact v2.4.0 identity gates and on-device guardian; neither `/usr/bin/Z03` nor startup/system libraries are replaced. All child cleanup precedes original-loop restoration. Every release remains a bounded trial until complete acceptance.
- Test layers: host normalization/security tests, real Qt rendering and controls, target anonymous APIs and playback, then user QR login/following/authorized bangumi and physical recovery. None substitutes for another.

## Dependency sources

`../wiliwili` is pinned to `88e5876bea9502d06f46a8656e3530684d3aaf7d` (GPL-3.0); preserve upstream notices when using its API protocol/WBI code. QR encoder is Nayuki's MIT-licensed C++ implementation already in that checkout. A private zip of CPython 3.5.10's JSON package supplies the firmware's missing stdlib package, under the PSF license; it is never installed into system Python. No bundled fonts.

Offline Pinyin data: Rime `rime-pinyin-simp`, commit `0c6861ef7420ee780270ca6d993d18d4101049d0`, Apache-2.0 / Android Pinyin IME origin. Conversion retains source, LICENSE and AUTHORS, changes representation/order, and caps each spelling at 60 candidates. 38,999 spellings occupy 539,936 compressed bytes. Input lookup never leaves the pen.

The first device UI trial exposed an integration defect: a Loader inside NaviPanel cannot cover its outer siblings (mode switch z=10, swipe area z=2, drawer z=200). Correct integration uses the stock `sceneSource` change handler, which hides all of `inner` and reparents the scene under the 800x268 `main`. Raising only the nested Loader's z does not fix this ownership problem.
