/* SPDX-License-Identifier: LGPL-2.1-only
 * Private, numerical-only function timing. No files, URLs, or system changes.
 * Counters are process-wide: the finite worker owns exactly one decoder.
 */
#ifndef P011_OMX_PROFILE_H
#define P011_OMX_PROFILE_H
#include <time.h>

enum P011ProfileGroup { P011_LOOP, P011_ACQUIRE, P011_MATCH, P011_FILL,
  P011_COPY, P011_ALLOCATE, P011_PUSH, P011_RELEASE, P011_GROUPS };
static const char *p011_profile_names[P011_GROUPS] = {
  "loop", "acquire", "match", "fill", "copy", "allocate", "push", "release"
};
static GMutex p011_profile_lock;
static guint64 p011_profile_values[P011_GROUPS][3];
static guint64 p011_profile_errors;
typedef struct { unsigned group; guint64 wall, cpu; gboolean valid; } P011Measurement;

static gboolean
p011_profile_clock (clockid_t clock, guint64 *value)
{
  struct timespec ts;
  if (clock_gettime (clock, &ts)) return FALSE;
  *value = (guint64) ts.tv_sec * 1000000000ULL + ts.tv_nsec;
  return TRUE;
}

static P011Measurement
p011_profile_begin (unsigned group)
{
  P011Measurement m = { group, 0, 0, FALSE };
  m.valid = p011_profile_clock (CLOCK_MONOTONIC, &m.wall) &&
      p011_profile_clock (CLOCK_THREAD_CPUTIME_ID, &m.cpu);
  return m;
}

static void
p011_profile_end (P011Measurement *m)
{
  guint64 wall = 0, cpu = 0;
  gboolean valid = m->valid && p011_profile_clock (CLOCK_THREAD_CPUTIME_ID, &cpu) &&
      p011_profile_clock (CLOCK_MONOTONIC, &wall) && wall >= m->wall && cpu >= m->cpu;
  g_mutex_lock (&p011_profile_lock);
  if (valid && m->group < P011_GROUPS) {
    guint64 *v = p011_profile_values[m->group];
    v[0]++; v[1] += wall - m->wall; v[2] += cpu - m->cpu;
  } else {
    p011_profile_errors++;
  }
  g_mutex_unlock (&p011_profile_lock);
}

/* GCC cleanup covers normal returns, error gotos and early exits. One sample
 * per operation/frame, never a timestamp per image row or pixel. */
#define P011_PROFILE(group) P011Measurement _p011_measurement \
  __attribute__((cleanup(p011_profile_end))) = p011_profile_begin (P011_##group)

static GstStructure *
p011_profile_snapshot (void)
{
  GstStructure *s = gst_structure_new_empty ("p011-omx-profile");
  static const char *fields[3] = { "count", "wall_ns", "cpu_ns" };
  unsigned i, j;
  g_mutex_lock (&p011_profile_lock);
  for (i = 0; i < P011_GROUPS; i++) for (j = 0; j < 3; j++) {
    char name[48];
    g_snprintf (name, sizeof(name), "%s_%s", p011_profile_names[i], fields[j]);
    gst_structure_set (s, name, G_TYPE_UINT64, p011_profile_values[i][j], NULL);
  }
  gst_structure_set (s, "clock_errors", G_TYPE_UINT64, p011_profile_errors, NULL);
  g_mutex_unlock (&p011_profile_lock);
  return s;
}

/* Called in a separate preflight process; never modifies worker counters. */
unsigned p011_omx_profile_selftest (void)
{
  unsigned i;
  for (i = 0; i < P011_GROUPS; i++) {
    P011Measurement m = p011_profile_begin (i);
    p011_profile_end (&m);
  }
  for (i = 0; i < P011_GROUPS; i++)
    if (p011_profile_values[i][0] != 1) return 0;
  return p011_profile_errors ? 0 : P011_GROUPS;
}
#endif
