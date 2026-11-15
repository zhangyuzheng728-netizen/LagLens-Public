# AI Diagnostic Skill: Network vs Local

## Scope

This is a project-local rule card injected into the existing AI assistant
request. It is not a plugin, does not execute tools, does not train a
model and does not add another API call.

The general assistant prompt stays in `ai_insight.SYSTEM_PROMPT`.
The optional rule card lives in `ai_skills.py` and is selected locally
from the current question and recent conversation.

## Existing data and the missing-measurement distinction

LagLens now measures frame timing, CPU/GPU/RAM telemetry and, when the
user enables it, gateway/public network RTT. It still has no game-server
latency measurement.

Therefore:

- a report without a network sidecar says **网络：未采集网络**;
- a public probe is not game-server latency;
- a probe timeout is not proof of game packet loss;
- missing network data must not be replaced by a guess;
- game-server latency is always labelled **未测游戏服务器延迟**.

The network sidecar provides only timestamped gateway/public probe
samples. It never labels a public target as a game server. Automated AI
skill tests still use synthetic probe data for deterministic coverage;
the Network page has a separate real-sampler test path.

## When the card loads

`ai_skills.select_skills(question, history, has_report)` loads the
network card when:

- the question mentions network latency, packet loss, jitter, teleporting
  teammates, online play, disconnects or similar;
- the question mentions stutter, hitches or frame drops;
- a short follow-up such as **那更像哪边？** follows recent turns that
  already discuss both network and display behaviour.

It does not load for:

- normal performance questions such as **需要改吗？**;
- metric-definition questions such as **1% Low 是什么？** or
  **P95 怎么算？**;
- a deictic follow-up when the recent context contains only one side.

Without a linked report the card may still be loaded to explain how to
distinguish the two, but its rules explicitly forbid diagnosing this
capture without measurements.

## Card content

The card tells the model to:

1. separate whole-frame updates from stable rendering with teleporting
   teammates or input delay;
2. rank only measured evidence, without proving Wi-Fi/router failure or
   excluding an untested game server;
3. distinguish instrument measurements, player descriptions and
   speculation;
4. give at most one next action, and say **这次不用改** when nothing is
   wrong.

## Request budget

The card is optional. Trimming order for the final UTF-8 body:

1. older conversation turns;
2. optional diagnostic details and event/segment tables;
3. the optional skill card;
4. the last remaining previous turn.

The latest question, core measured facts and missing-data markers are
kept. If they alone exceed 4 KiB, `PromptTooLarge` is raised and the UI
asks the user to shorten the question. No skill selection API call is
made.

## Why this rule is worth adding

The useful rule is not “卡 = 网络”. The data-present misjudgements worth
targeting are:

- treating public-probe latency or timeouts as in-game latency/packet
  loss;
- seeing stable displayed frames plus network jitter and declaring a
  device failure instead of a local-connection investigation;
- seeing a display stall plus stable network probes and treating the
  network as the proven cause;
- merging two separately abnormal sides into one root cause.

Missing measurements are handled by the report/UI, not by a rule card.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_ai_skill -v
```

Tests cover normal questions, metric explanations, direct network/stutter
questions, context-dependent follow-ups, no-report general explanation,
missing network data, synthetic network probes, skill-budget trimming,
long conversations and report isolation. They validate the request
content and budget, not real model wording.
