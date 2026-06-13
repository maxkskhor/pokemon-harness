#!/usr/bin/env python3
"""Generate a self-contained HTML trace viewer for a pokemon-harness run.

Usage:
    python3 scripts/generate_trace_html.py runs/<run_id>
    python3 scripts/generate_trace_html.py runs/<run_id> -o /tmp/trace.html
"""

import base64
import json
import sys
from pathlib import Path


def b64_img(path: Path) -> str:
    return f"data:image/png;base64,{base64.b64encode(path.read_bytes()).decode()}"


def esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_json_block(raw: str) -> str:
    try:
        obj = json.loads(raw)
        pretty = json.dumps(obj, indent=2)
    except Exception:
        pretty = raw
    return f'<pre class="json-block">{esc(pretty)}</pre>'


def render_message(msg: dict, frames: dict, frame_img: str | None = None) -> str:
    role = msg["role"]
    content = msg.get("content")
    tool_calls = msg.get("tool_calls", [])
    tool_call_id = msg.get("tool_call_id")

    role_class = {
        "system": "msg-system",
        "user": "msg-user",
        "assistant": "msg-assistant",
        "tool": "msg-tool",
    }.get(role, "msg-unknown")

    parts = []

    # Content rendering
    if isinstance(content, str) and content:
        parts.append(f'<div class="msg-text">{esc(content)}</div>')
    elif isinstance(content, list):
        for item in content:
            if item.get("type") == "text":
                text = item.get("text", "")
                if text:
                    parts.append(f'<div class="msg-text">{esc(text)}</div>')
            elif item.get("type") == "image_url":
                url = item["image_url"]["url"]
                # <image> placeholder means we don't have the actual image embedded
                if url == "<image>":
                    if frame_img:
                        parts.append(f'<img class="msg-img" src="{frame_img}" />')
                    else:
                        parts.append('<div class="msg-img-placeholder">[image not embedded]</div>')
                elif url.startswith("data:"):
                    parts.append(f'<img class="msg-img" src="{url}" />')
                else:
                    parts.append(f'<img class="msg-img" src="{esc(url)}" />')

    # Tool calls (in assistant messages)
    for tc in tool_calls:
        fn = tc.get("function", tc)  # handle both {function:{name,arguments}} and {name,arguments}
        name = fn.get("name", "?")
        args_raw = fn.get("arguments", "{}")
        call_id = tc.get("id", "")
        try:
            args_obj = json.loads(args_raw)
            args_pretty = json.dumps(args_obj, indent=2)
        except Exception:
            args_pretty = args_raw
        parts.append(
            f'<div class="tool-call">'
            f'<span class="tool-call-fn">{esc(name)}()</span>'
            f'<span class="tool-call-id">{esc(call_id)}</span>'
            f'<pre class="json-block">{esc(args_pretty)}</pre>'
            f"</div>"
        )

    # Tool result (in tool messages)
    if role == "tool":
        label = f"result for {esc(tool_call_id or '')}"
        parts.append(f'<div class="tool-result-label">{label}</div>')
        if isinstance(content, str):
            parts.append(render_json_block(content))

    body_html = "\n".join(parts) if parts else '<span class="empty">(empty)</span>'

    role_label = {
        "system": "SYSTEM",
        "user": "USER",
        "assistant": "ASSISTANT",
        "tool": "TOOL RESULT",
    }.get(role, role.upper())

    return f"""
<div class="msg {role_class}">
  <div class="msg-header">
    <span class="msg-role-badge">{role_label}</span>
  </div>
  <div class="msg-body">{body_html}</div>
</div>"""


def render_llm_call(call_idx: int, ev: dict, frames: dict) -> str:
    p = ev["payload"]
    usage = p.get("usage", {})
    response = p.get("response", {})
    messages = p.get("messages", [])
    model = p.get("model", "?")
    frame = ev.get("frame", 0)
    ts = ev.get("timestamp", "")[:19].replace("T", " ")

    tokens = usage.get("total_tokens", 0)
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    cached_tokens = usage.get("cached_tokens", 0)
    latency = usage.get("latency_ms", 0)
    cost = usage.get("cost_usd", 0)
    run_cost = usage.get("run_cost_usd", 0)

    # Screenshot for this call's frame
    frame_img_html = ""
    if frame in frames:
        frame_img_html = f'<img class="call-frame-img" src="{frames[frame]}" title="Frame {frame}" />'

    # Messages HTML — pass the call's frame image for <image> placeholders in user messages
    frame_img = frames.get(frame)
    msgs_html = "\n".join(
        render_message(m, frames, frame_img if m["role"] == "user" else None)
        for m in messages
    )

    # Response section
    resp_parts = []
    reasoning = response.get("reasoning")
    resp_content = response.get("content") or ""
    resp_tool_calls = response.get("tool_calls", [])

    if reasoning:
        resp_parts.append(
            f'<details class="reasoning-block">'
            f'<summary>Reasoning ({len(reasoning)} chars)</summary>'
            f'<pre class="reasoning-text">{esc(reasoning)}</pre>'
            f"</details>"
        )
    if resp_content:
        resp_parts.append(f'<div class="resp-content">{esc(resp_content)}</div>')
    for tc in resp_tool_calls:
        name = tc.get("name", "?")
        args_raw = tc.get("arguments", "{}")
        try:
            args_obj = json.loads(args_raw)
            args_pretty = json.dumps(args_obj, indent=2)
        except Exception:
            args_pretty = args_raw
        resp_parts.append(
            f'<div class="tool-call resp-tool-call">'
            f'<span class="tool-call-fn">→ {esc(name)}()</span>'
            f'<pre class="json-block">{esc(args_pretty)}</pre>'
            f"</div>"
        )

    resp_html = "\n".join(resp_parts) if resp_parts else '<span class="empty">(no response content)</span>'

    cost_str = f"${cost:.5f}" if cost else ""
    run_cost_str = f"${run_cost:.4f}" if run_cost else ""

    return f"""
<details class="llm-call">
  <summary class="llm-call-summary">
    <span class="call-num">Call #{call_idx}</span>
    <span class="call-model">{esc(model)}</span>
    <span class="call-stat">{tokens:,} tokens</span>
    <span class="call-stat">{latency:,} ms</span>
    <span class="call-stat cost">{cost_str}</span>
    <span class="call-time">{ts}</span>
  </summary>
  <div class="llm-call-body">
    <div class="call-cols">
      <div class="call-frame">{frame_img_html}<div class="frame-label">Frame {frame}</div></div>
      <div class="call-usage-box">
        <table class="usage-table">
          <tr><td>Prompt tokens</td><td>{prompt_tokens:,}</td></tr>
          <tr><td>Completion tokens</td><td>{completion_tokens:,}</td></tr>
          <tr><td>Cached tokens</td><td>{cached_tokens:,}</td></tr>
          <tr><td>Total tokens</td><td><strong>{tokens:,}</strong></td></tr>
          <tr><td>Latency</td><td>{latency:,} ms</td></tr>
          <tr><td>Call cost</td><td>{cost_str}</td></tr>
          <tr><td>Run cost so far</td><td>{run_cost_str}</td></tr>
        </table>
      </div>
    </div>

    <div class="section-label">Context sent to LLM ({len(messages)} messages)</div>
    <div class="messages-container">{msgs_html}</div>

    <div class="section-label">Model Response</div>
    <div class="response-container">{resp_html}</div>
  </div>
</details>"""


def render_actions(ev: dict) -> str:
    p = ev.get("payload", {})
    summary = p.get("summary", "")
    tool_calls = p.get("tool_calls", [])

    rows = []
    for tc in tool_calls:
        tool = tc.get("tool", "?")
        args = tc.get("args", {})
        result = tc.get("result", {})
        moved = result.get("moved")
        after = result.get("after", {})
        pressed = result.get("pressed")

        if tool == "move":
            status_icon = "✓" if moved else "✗"
            status_class = "action-ok" if moved else "action-blocked"
            detail = f"({after.get('x','?')},{after.get('y','?')}) map={after.get('map_id','?')}"
        elif tool == "press_button":
            status_icon = "✓"
            status_class = "action-ok"
            detail = f"pressed {pressed}"
        else:
            status_icon = "·"
            status_class = ""
            detail = json.dumps(result)

        args_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
        rows.append(
            f'<tr class="action-row {status_class}">'
            f'<td class="action-status">{status_icon}</td>'
            f'<td class="action-tool">{esc(tool)}({esc(args_str)})</td>'
            f'<td class="action-detail">{esc(detail)}</td>'
            f"</tr>"
        )

    rows_html = "\n".join(rows)
    summary_html = f'<div class="actions-summary-text">{esc(summary)}</div>' if summary else ""

    return f"""
<div class="actions-block">
  <div class="section-label">Actions Taken</div>
  {summary_html}
  <table class="actions-table">
    <thead><tr><th></th><th>Tool Call</th><th>Result</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>"""


def render_milestone(ev: dict) -> str:
    p = ev.get("payload", {})
    label = p.get("label", p.get("key", "?"))
    index = p.get("index", 0)
    total = p.get("total", 0)
    cost = p.get("run_cost_usd", 0)
    turn = p.get("turn", "")
    cost_str = f" · ${cost:.4f}" if cost else ""
    return (
        f'<div class="event-banner milestone-banner">'
        f'<span class="banner-icon">🏁</span>'
        f'<span class="banner-text">MILESTONE {index + 1}/{total}: {esc(label)}</span>'
        f'<span class="banner-meta">turn {turn}{cost_str}</span>'
        f"</div>"
    )


def render_rollback(ev: dict) -> str:
    p = ev.get("payload", {})
    reason = p.get("reason", "")
    checkpoint = p.get("checkpoint", "")
    n = p.get("rollbacks_this_milestone", "")
    return (
        f'<div class="event-banner rollback-banner">'
        f'<span class="banner-icon">↩</span>'
        f'<span class="banner-text">ROLLBACK: {esc(reason)}</span>'
        f'<span class="banner-meta">→ {esc(checkpoint)} (#{n})</span>'
        f"</div>"
    )


def render_steering(ev: dict) -> str:
    p = ev.get("payload", {})
    msg = p.get("message", "")
    return (
        f'<div class="event-banner steer-banner">'
        f'<span class="banner-icon">🧑</span>'
        f'<span class="banner-text">HUMAN STEER: {esc(msg)}</span>'
        f"</div>"
    )


_BANNER_RENDERERS = {
    "milestone": render_milestone,
    "rollback": render_rollback,
    "steering": render_steering,
}


def render_turn(turn_id: str, events: list, frames: dict, turn_idx: int) -> str:
    started = next((e for e in events if e["type"] == "turn_started"), None)
    finished = next((e for e in events if e["type"] == "turn_finished"), None)
    llm_calls = [e for e in events if e["type"] == "llm_call"]
    actions_ev = next((e for e in events if e["type"] == "actions"), None)
    banners = [e for e in events if e["type"] in _BANNER_RENDERERS]

    goal = started["payload"].get("goal", "") if started else ""
    status = finished["payload"].get("status", "?") if finished else "running"
    elapsed_ms = finished["payload"].get("elapsed_ms", 0) if finished else 0
    elapsed_str = f"{elapsed_ms / 1000:.1f}s" if elapsed_ms else "—"
    frame_start = started["payload"].get("frame", 0) if started else 0
    frame_end = finished["payload"].get("frame", 0) if finished else 0

    turn_tokens = sum(
        e["payload"].get("usage", {}).get("total_tokens", 0) for e in llm_calls
    )
    turn_cost = sum(
        e["payload"].get("usage", {}).get("cost_usd", 0) for e in llm_calls
    )

    status_class = "status-ok" if status == "ok" else "status-error" if status == "error" else "status-running"

    llm_html = "\n".join(
        render_llm_call(i + 1, ev, frames) for i, ev in enumerate(llm_calls)
    )

    actions_html = render_actions(actions_ev) if actions_ev else ""

    banners_html = "\n".join(_BANNER_RENDERERS[e["type"]](e) for e in banners)
    # A milestone/rollback turn is a story beat — open it and flag it in the header.
    has_milestone = any(e["type"] == "milestone" for e in banners)
    has_rollback = any(e["type"] == "rollback" for e in banners)
    marker = " 🏁" if has_milestone else (" ↩" if has_rollback else "")
    open_attr = ' open' if (turn_idx == 0 or banners) else ''

    return f"""
<details class="turn-card"{open_attr}>
  <summary class="turn-header">
    <span class="turn-id">{esc(turn_id)}{marker}</span>
    <span class="turn-goal">{esc(goal)}</span>
    <span class="turn-badge {status_class}">{status}</span>
    <span class="turn-stat">{elapsed_str}</span>
    <span class="turn-stat">{len(llm_calls)} LLM calls</span>
    <span class="turn-stat">{turn_tokens:,} tokens</span>
    <span class="turn-stat cost">${turn_cost:.4f}</span>
    <span class="turn-frames">frames {frame_start}→{frame_end}</span>
  </summary>
  <div class="turn-body">
    {banners_html}
    <div class="section-label">LLM Calls ({len(llm_calls)})</div>
    {llm_html}
    {actions_html}
  </div>
</details>"""


CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  font-size: 13px;
  background: #F5F0E8;
  color: #1A1A1A;
  line-height: 1.5;
}
a { color: #C4674A; }

/* ── Top bar ── */
.topbar {
  background: #1A1A1A;
  color: #FAF8F4;
  padding: 12px 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.topbar h1 { font-size: 15px; font-weight: 600; }
.topbar .meta-pill {
  background: #333;
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 11px;
  color: #CCC;
}
.topbar .meta-pill strong { color: #FAF8F4; }

/* ── Stats row ── */
.stats-row {
  background: #EDE8DE;
  border-bottom: 1px solid #D9D0C3;
  padding: 8px 20px;
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
}
.stat-item { display: flex; flex-direction: column; }
.stat-item .stat-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; color: #888; }
.stat-item .stat-value { font-size: 14px; font-weight: 600; color: #1A1A1A; }

/* ── Turn cards ── */
.turns-container { padding: 16px 20px; display: flex; flex-direction: column; gap: 10px; }
.turn-card {
  background: white;
  border: 1px solid #D9D0C3;
  border-radius: 8px;
  overflow: hidden;
}
.turn-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  cursor: pointer;
  user-select: none;
  background: #FAF8F4;
  flex-wrap: wrap;
}
.turn-header:hover { background: #F0EBE0; }
.turn-id {
  font-weight: 700;
  font-size: 13px;
  color: #C4674A;
  min-width: 70px;
}
.turn-goal {
  flex: 1;
  font-style: italic;
  color: #444;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.turn-badge {
  border-radius: 4px;
  padding: 1px 7px;
  font-size: 11px;
  font-weight: 600;
}
.status-ok { background: #D4EDDA; color: #155724; }
.status-error { background: #F8D7DA; color: #721C24; }
.status-running { background: #D1ECF1; color: #0C5460; }
.turn-stat { font-size: 11px; color: #666; }
.turn-stat.cost { color: #C4674A; font-weight: 600; }
.turn-frames { font-size: 11px; color: #999; margin-left: auto; }

.turn-body {
  padding: 14px;
  border-top: 1px solid #EDE8DE;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* ── Event banners (milestone / rollback / steer) ── */
.event-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}
.event-banner .banner-icon { font-size: 15px; }
.event-banner .banner-text { flex: 1; }
.event-banner .banner-meta { font-size: 11px; font-weight: 500; opacity: 0.85; }
.milestone-banner { background: #D4EDDA; color: #155724; border: 1px solid #A3D9B1; }
.rollback-banner { background: #FFE9D6; color: #8A4B1F; border: 1px solid #F0C9A3; }
.steer-banner { background: #E3D9F5; color: #4B2A82; border: 1px solid #C8B8EE; }

/* ── Section labels ── */
.section-label {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #888;
  margin-bottom: 6px;
}

/* ── LLM Call ── */
.llm-call {
  border: 1px solid #E8E0D5;
  border-radius: 6px;
  background: #FDFCFA;
  overflow: hidden;
  margin-bottom: 6px;
}
.llm-call-summary {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
  flex-wrap: wrap;
}
.llm-call-summary:hover { background: #F5F0E8; }
.call-num { font-weight: 700; color: #C4674A; min-width: 48px; }
.call-model { font-size: 11px; color: #666; }
.call-stat { font-size: 11px; color: #555; }
.call-stat.cost { color: #C4674A; }
.call-time { font-size: 10px; color: #999; margin-left: auto; }

.llm-call-body { padding: 12px; border-top: 1px solid #E8E0D5; display: flex; flex-direction: column; gap: 12px; }

/* ── Call frame + usage cols ── */
.call-cols { display: flex; gap: 16px; align-items: flex-start; }
.call-frame { display: flex; flex-direction: column; align-items: center; gap: 4px; }
.call-frame-img {
  width: 120px;
  height: 108px;
  object-fit: contain;
  image-rendering: pixelated;
  border: 1px solid #D9D0C3;
  border-radius: 4px;
  background: #000;
}
.frame-label { font-size: 10px; color: #999; }
.call-usage-box { flex: 1; }
.usage-table { border-collapse: collapse; width: 100%; font-size: 12px; }
.usage-table td { padding: 3px 8px; border-bottom: 1px solid #F0EBE0; }
.usage-table td:first-child { color: #888; width: 140px; }
.usage-table td:last-child { font-weight: 500; }

/* ── Messages ── */
.messages-container { display: flex; flex-direction: column; gap: 8px; }
.msg { border-radius: 6px; overflow: hidden; }
.msg-header {
  padding: 4px 10px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.msg-role-badge {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.08em;
  padding: 2px 6px;
  border-radius: 3px;
}
.msg-body { padding: 8px 10px; display: flex; flex-direction: column; gap: 6px; }
.msg-text { white-space: pre-wrap; word-break: break-word; font-size: 12px; }

/* Role colors */
.msg-system { background: #F0EBE0; border: 1px solid #D9D0C3; }
.msg-system .msg-header { background: #E8E0D5; }
.msg-system .msg-role-badge { background: #6C757D; color: white; }

.msg-user { background: #EEF4FB; border: 1px solid #C8DCED; }
.msg-user .msg-header { background: #D6E8F5; }
.msg-user .msg-role-badge { background: #3A80B5; color: white; }

.msg-assistant { background: #F0F7EE; border: 1px solid #C5DCC2; }
.msg-assistant .msg-header { background: #DCF0D9; }
.msg-assistant .msg-role-badge { background: #2E7D32; color: white; }

.msg-tool { background: #FFF8EC; border: 1px solid #F5DFA0; }
.msg-tool .msg-header { background: #FEEFC3; }
.msg-tool .msg-role-badge { background: #B07800; color: white; }

/* ── Images ── */
.msg-img {
  max-width: 160px;
  image-rendering: pixelated;
  border: 1px solid #D9D0C3;
  border-radius: 3px;
  cursor: zoom-in;
}
.msg-img-placeholder { color: #999; font-style: italic; font-size: 11px; }

/* ── Tool calls ── */
.tool-call {
  background: #F8F4FF;
  border: 1px solid #D5C8F5;
  border-radius: 5px;
  padding: 6px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.tool-call-fn { font-weight: 700; font-size: 12px; color: #6B3FA0; }
.tool-call-id { font-size: 10px; color: #999; }
.tool-result-label { font-size: 10px; color: #999; }

/* ── JSON blocks ── */
.json-block {
  background: #1E1E2E;
  color: #CDD6F4;
  border-radius: 4px;
  padding: 8px 10px;
  font-size: 11px;
  font-family: "JetBrains Mono", "Fira Code", monospace;
  overflow-x: auto;
  white-space: pre;
  max-height: 200px;
  overflow-y: auto;
}

/* ── Response ── */
.response-container { display: flex; flex-direction: column; gap: 8px; }
.resp-content {
  background: #F0F7EE;
  border: 1px solid #C5DCC2;
  border-radius: 5px;
  padding: 8px 10px;
  font-size: 12px;
  white-space: pre-wrap;
}
.resp-tool-call { background: #F0EBFF; border-color: #C8B8EE; }
.resp-tool-call .tool-call-fn { color: #5B2DA0; }
.reasoning-block {
  background: #FFFBEF;
  border: 1px solid #F5E4A0;
  border-radius: 5px;
  overflow: hidden;
}
.reasoning-block summary {
  padding: 6px 10px;
  cursor: pointer;
  font-size: 11px;
  font-weight: 600;
  color: #7A6000;
  background: #FFF3C0;
}
.reasoning-text {
  padding: 8px 10px;
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-word;
  color: #554400;
  max-height: 300px;
  overflow-y: auto;
}

/* ── Actions ── */
.actions-block { display: flex; flex-direction: column; gap: 8px; }
.actions-summary-text { font-size: 11px; color: #555; font-style: italic; }
.actions-table { border-collapse: collapse; width: 100%; font-size: 12px; }
.actions-table th { background: #EDE8DE; padding: 4px 8px; text-align: left; font-size: 10px; color: #888; font-weight: 600; text-transform: uppercase; }
.actions-table td { padding: 4px 8px; border-bottom: 1px solid #F0EBE0; }
.action-status { font-size: 13px; width: 24px; text-align: center; }
.action-tool { font-family: monospace; font-size: 11px; }
.action-detail { color: #666; font-size: 11px; }
.action-ok .action-status { color: #2E7D32; }
.action-blocked .action-status { color: #C62828; }

/* ── Image lightbox ── */
#lightbox {
  display: none;
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.85);
  z-index: 1000;
  align-items: center;
  justify-content: center;
  cursor: zoom-out;
}
#lightbox.open { display: flex; }
#lightbox img {
  max-width: 90vw;
  max-height: 90vh;
  image-rendering: pixelated;
  border: 2px solid #fff;
}

.empty { color: #AAA; font-style: italic; font-size: 11px; }
"""


JS = """
// Lightbox for images
document.addEventListener('click', e => {
  if (e.target.classList.contains('msg-img') || e.target.classList.contains('call-frame-img')) {
    const lb = document.getElementById('lightbox');
    document.getElementById('lightbox-img').src = e.target.src;
    lb.classList.add('open');
  }
});
document.getElementById('lightbox').addEventListener('click', () => {
  document.getElementById('lightbox').classList.remove('open');
});
"""


def generate(run_dir: Path, output: Path):
    meta = json.loads((run_dir / "meta.json").read_text())
    run_id = meta.get("run_id", run_dir.name)
    agent_info = meta.get("agent", {})
    agent_name = agent_info.get("name", "?")
    model = agent_info.get("model", "?")
    rom = meta.get("rom", {}).get("title", "?")
    started_at = meta.get("started_at", "")[:19].replace("T", " ")
    status = meta.get("status", "?")

    events = []
    with open(run_dir / "harness.jsonl") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))

    # Load frames as base64
    frames: dict[int, str] = {}
    frames_dir = run_dir / "frames"
    if frames_dir.exists():
        for png in frames_dir.glob("*.png"):
            try:
                frames[int(png.stem)] = b64_img(png)
            except ValueError:
                pass
    print(f"  Loaded {len(frames)} frames")

    # Group events by turn
    turns_order: list[str] = []
    turns_events: dict[str, list] = {}
    pre_events: list = []

    for ev in events:
        tid = ev.get("turn_id")
        if tid is None:
            pre_events.append(ev)
        else:
            if tid not in turns_events:
                turns_events[tid] = []
                turns_order.append(tid)
            turns_events[tid].append(ev)

    # Aggregate stats
    all_llm = [e for e in events if e["type"] == "llm_call"]
    total_tokens = sum(e["payload"].get("usage", {}).get("total_tokens", 0) for e in all_llm)
    total_cost = max(
        (e["payload"].get("usage", {}).get("run_cost_usd", 0) for e in all_llm),
        default=0,
    )
    total_latency = sum(e["payload"].get("usage", {}).get("latency_ms", 0) for e in all_llm)
    n_turns = len(turns_order)
    n_calls = len(all_llm)

    milestone_evs = [e for e in events if e["type"] == "milestone"]
    n_rollbacks = sum(1 for e in events if e["type"] == "rollback")
    milestones_total = (
        milestone_evs[-1]["payload"].get("total", 0) if milestone_evs else 0
    )
    last_milestone = (
        milestone_evs[-1]["payload"].get("label", "—") if milestone_evs else "—"
    )
    milestones_str = (
        f"{len(milestone_evs)}/{milestones_total}" if milestones_total else str(len(milestone_evs))
    )

    # Render turns
    turns_html = "\n".join(
        render_turn(tid, turns_events[tid], frames, idx)
        for idx, tid in enumerate(turns_order)
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trace: {esc(run_id)}</title>
<style>{CSS}</style>
</head>
<body>

<div id="lightbox"><img id="lightbox-img" src="" /></div>

<div class="topbar">
  <h1>TRACE</h1>
  <div class="meta-pill"><strong>{esc(run_id)}</strong></div>
  <div class="meta-pill">Agent: <strong>{esc(agent_name)}</strong></div>
  <div class="meta-pill">Model: <strong>{esc(model)}</strong></div>
  <div class="meta-pill">ROM: <strong>{esc(rom)}</strong></div>
  <div class="meta-pill">Started: <strong>{esc(started_at)}</strong></div>
  <div class="meta-pill">Status: <strong>{esc(status)}</strong></div>
</div>

<div class="stats-row">
  <div class="stat-item"><span class="stat-label">Turns</span><span class="stat-value">{n_turns}</span></div>
  <div class="stat-item"><span class="stat-label">Milestones</span><span class="stat-value">{milestones_str}</span></div>
  <div class="stat-item"><span class="stat-label">Furthest</span><span class="stat-value">{esc(last_milestone)}</span></div>
  <div class="stat-item"><span class="stat-label">Rollbacks</span><span class="stat-value">{n_rollbacks}</span></div>
  <div class="stat-item"><span class="stat-label">LLM Calls</span><span class="stat-value">{n_calls}</span></div>
  <div class="stat-item"><span class="stat-label">Total Tokens</span><span class="stat-value">{total_tokens:,}</span></div>
  <div class="stat-item"><span class="stat-label">Total Cost</span><span class="stat-value">${total_cost:.4f}</span></div>
  <div class="stat-item"><span class="stat-label">Total LLM Time</span><span class="stat-value">{total_latency/1000:.1f}s</span></div>
</div>

<div class="turns-container">
{turns_html}
</div>

<script>{JS}</script>
</body>
</html>"""

    output.write_text(html, encoding="utf-8")
    size_kb = output.stat().st_size // 1024
    print(f"  Written: {output} ({size_kb} KB)")


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: generate_trace_html.py <run_dir> [-o output.html]", file=sys.stderr)
        sys.exit(1)

    run_dir = Path(args[0])
    if not run_dir.exists():
        print(f"Error: {run_dir} does not exist", file=sys.stderr)
        sys.exit(1)

    output = run_dir / "trace.html"
    if "-o" in args:
        idx = args.index("-o")
        output = Path(args[idx + 1])

    print(f"Generating trace for {run_dir.name}...")
    generate(run_dir, output)
    print("Done.")


if __name__ == "__main__":
    main()
