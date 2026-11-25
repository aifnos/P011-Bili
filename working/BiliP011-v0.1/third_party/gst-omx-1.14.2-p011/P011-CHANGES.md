# P011 private OMX copy experiment

Upstream: gst-omx 1.14.2 release, https://gstreamer.freedesktop.org/src/gst-omx/gst-omx-1.14.2.tar.xz.
Original notices and LGPL-2.1 terms remain in each source and COPYING.

2026-09-25: two output-copy sites in gstomxvideodec.c call p011_omx_copy.
The reference build still delegates to libc memcpy; the experimental build
uses NEON in bounded 64/16-byte blocks with a scalar tail. No global symbol
interposition, physical address, port reconfiguration, OMX buffer ownership,
decoder-library replacement or factory configuration changes are involved.
Both use the same source/compiler/options except P011_OMX_NEON_COPY.
Exports supply mode identity and 17,408 synthetic offset/tail/guard checks.

Follow-up: the generic upstream reference handed out OMX memory and exited
abnormally after its first frame on P011. Both current probe builds therefore
disable the upstream downstream OMX pool/OMX_UseBuffer path and keep the
observed factory copy-out boundary. This is an explicit compatibility change,
not a claim that the upstream plugin exactly matches the vendor binary.
Factory no-disable-outport and event-order workarounds remain unchanged.

The reference/NEON pair did not establish a performance win. Numerical
function timings now distinguish thread CPU from wall time for output-loop,
buffer acquisition, frame matching, allocation, fill/copy, push and release.
The boxed read-only p011-probe-profile property contains only counters.
There are no diagnostic files, URLs, system changes or per-row timestamps.
Counters are process-wide; the isolated worker owns one decoder.

Function timing found full-frame copy dominant. Mode 2 is a new experiment:
one persistent pthread helper copies disjoint stripes concurrently with the
output thread for frames >=512 KiB. Completion is joined before output push
or OMX release; decoder finalization joins the helper. No per-frame threads,
no port ownership changes, no physical-address or cache-policy manipulation.
1,620 synthetic cases cover row stride, reverse stride, offsets, tiny/empty
planes, serial fallback, parallel completion and full-buffer guards. A host
ASan/UBSan run plus the existing 17,408 byte-copy checks gate ARM builds.

Mode 3 adds a second persistent helper and splits each plane into three
disjoint stripes, preserving the same completion/ownership boundary. If the
second helper cannot be created, the existing two-thread path is retained.
Both two- and three-thread builds run the 19,028 host sanitizer checks (38,056
total) before ARM export. This is a throughput experiment, not a claim of
60fps decoding or a change to system thread policy/frequency/affinity.

Build uses public 1.14.2 GStreamer headers and private link-only copies of
factory ABI libraries. Vendor libraries are not redistributed. The probe
plugin is not installed into /usr/lib; it is not a tested product release.
