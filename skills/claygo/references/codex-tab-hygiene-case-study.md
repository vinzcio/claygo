# Codex tab-hygiene case study

Use this case study when explaining why task-owned browser tabs need to be closed continuously as their work ends.

## Incident

On July 30, 2026, one Codex task reached the end of a browser-heavy feature-release workflow with 49 finished task-owned tabs still open. Four other open tabs belonged to the user and were outside the task's ownership.

At roughly the same time, an 8-CPU Mac was under severe host pressure. A Harken validation lane recorded 24 server-auth cases failing before assertions because ephemeral loopback servers could not start within 10 to 13 seconds. The failures were uniform `ECONNREFUSED` results from host starvation, not product-code regressions.

The task reports recorded these whole-machine load averages:

| Time | 1 minute | 5 minutes | 15 minutes |
| --- | ---: | ---: | ---: |
| 08:44 | 36.32 | 43.35 | 51.00 |
| 08:45 | 19.92 | 37.55 | 48.36 |
| 08:46 | 15.19 | 34.38 | 46.77 |
| 08:47 | 9.64 | 28.61 | 43.54 |
| 08:49 | 7.65 | 22.50 | 39.42 |

## Cleanup

The completed feature-video task audited its browser ownership, finalized and closed all 49 task-owned tabs, and deliberately preserved the four user-owned tabs. It kept no finished task-owned tabs open.

The corrective lesson is to perform that closure as each tab's work finishes, instead of accumulating finished tabs and needing a large end-of-task sweep.

## Measured result

- Vincent observed Activity Monitor CPU fall immediately from about 100% to about 80% after the tab cleanup: a 20 percentage-point, or 20% relative, reduction.
- The whole-machine 1-minute load average fell from 36.32 to 9.64 in about three minutes, a 73.5% reduction, and to 7.65 in about five minutes, a 78.9% reduction. The latter was below the host's eight logical CPUs.
- Over the same interval, the 5-minute load average fell 48.1%, from 43.35 to 22.50. The slower 15-minute average fell 22.7%, from 51.00 to 39.42.
- Without changing the tested source, the focused server-auth rerun recovered from 24 startup failures to 45 of 45 cases passing in 48.6 seconds. Previously failing server startups completed in roughly 0.6 to 2.1 seconds; one separate billing-status case took 11.7 seconds and still passed.
- The complete aggregate validation later finished with 826 passes, zero failures, and one root-only skip.

## What the case supports

The evidence supports adding browser tabs to CLAYGO's ownership lifecycle and closing them as soon as their purpose ends. It does not establish that tab closure alone produced every whole-machine load or test improvement: concurrent work was also changing. The CPU change is Vincent's direct observation; the load averages and test recovery are corroborating system outcomes, not isolated causal measurements.

Operationally:

- Close finished task-owned tabs immediately or at the next safe waypoint instead of accumulating them until final closeout.
- Preserve user-owned and other-task tabs unless their owner explicitly authorizes closure.
- Preserve durable URLs or manifests as evidence; do not keep a browser tab open merely as proof.
- Do not interrupt active work for a special cleanup event. Make cleanup part of the work so no stop-the-world recovery is needed.
