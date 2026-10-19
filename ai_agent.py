"""ШІ-агент підтримки NeonDrop: вільна розмова українською + інструменти, якими він РОЗВ'ЯЗУЄ проблеми (а не лише радить).
Логіка агента (інструменти, ліміти автономності, схвалення власника, скасування дій) — власна, у app.py.
Мовна модель підключається ззовні — на безкоштовному Render модель усередині сайту не запустити:
  • Claude API:            AI_KEY=<ключ>  (AI_MODEL за замовчуванням claude-haiku-4-5-20251001)
  • будь-який OpenAI-сумісний сервіс (Groq, OpenRouter, Gemini-compat, свій Ollama/vLLM): AI_URL=<база API>, AI_KEY=<ключ>, AI_MODEL=<модель>
Без підключеної моделі сайт працює у спрощеному режимі (support_ai.py)."""
import json, os, requests

_key = os.getenv("AI_KEY") or os.getenv("ANTHROPIC_API_KEY", "")
_url = os.getenv("AI_URL", "").strip()
_prov = (os.getenv("AI_PROVIDER") or ("openai" if _url else "anthropic")).lower()
CFG = {"key": _key, "url": _url, "provider": _prov, "model": os.getenv("AI_MODEL") or ("claude-haiku-4-5-20251001" if _prov == "anthropic" else "")}


def enabled():
    return bool(CFG["model"] and (CFG["key"] or (CFG["provider"] == "openai" and CFG["url"])))


def _to_anthropic(msgs):
    out = []
    for m in msgs:
        if m["role"] == "user": out.append({"role": "user", "content": m["text"]})
        elif m["role"] == "assistant":
            out.append({"role": "assistant", "content": ([{"type": "text", "text": m["text"]}] if m.get("text") else []) + [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["args"]} for c in m.get("calls", [])]})
        else:
            blk = {"type": "tool_result", "tool_use_id": m["id"], "content": m["result"]}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list): out[-1]["content"].append(blk)
            else: out.append({"role": "user", "content": [blk]})
    return out


def _call_anthropic(system, msgs, tools):
    body = {"model": CFG["model"], "max_tokens": 700, "system": system, "messages": _to_anthropic(msgs)}
    if tools: body["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["schema"]} for t in tools]
    r = requests.post((CFG["url"] or "https://api.anthropic.com").rstrip("/") + "/v1/messages", headers={"x-api-key": CFG["key"], "anthropic-version": "2023-06-01", "content-type": "application/json"}, json=body, timeout=60)
    j = r.json()
    if r.status_code != 200: raise RuntimeError(str(j)[:200])
    text = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text").strip()
    return text, [{"id": b["id"], "name": b["name"], "args": b.get("input") or {}} for b in j.get("content", []) if b.get("type") == "tool_use"]


def _to_openai(system, msgs):
    out = [{"role": "system", "content": system}]
    for m in msgs:
        if m["role"] == "user": out.append({"role": "user", "content": m["text"]})
        elif m["role"] == "assistant":
            d = {"role": "assistant", "content": m.get("text") or None}
            if m.get("calls"): d["tool_calls"] = [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["args"], ensure_ascii=False)}} for c in m["calls"]]
            out.append(d)
        else: out.append({"role": "tool", "tool_call_id": m["id"], "content": m["result"]})
    return out


def _call_openai(system, msgs, tools):
    body = {"model": CFG["model"], "max_tokens": 700, "messages": _to_openai(system, msgs)}
    if tools: body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["schema"]}} for t in tools]
    h = {"content-type": "application/json"}
    if CFG["key"]: h["Authorization"] = "Bearer " + CFG["key"]
    r = requests.post(CFG["url"].rstrip("/") + "/chat/completions", headers=h, json=body, timeout=60); j = r.json()
    if r.status_code != 200: raise RuntimeError(str(j)[:200])
    msg = j["choices"][0]["message"]
    calls = []
    for c in msg.get("tool_calls") or []:
        try: args = json.loads(c["function"].get("arguments") or "{}")
        except Exception: args = {}
        calls.append({"id": c["id"], "name": c["function"]["name"], "args": args})
    return (msg.get("content") or "").strip(), calls


def run(system, history, tools, run_tool, max_steps=6):
    """history — [("user"|"assistant", текст)], остання — від гравця. Повертає фінальний текст для гравця."""
    call = _call_anthropic if CFG["provider"] == "anthropic" else _call_openai
    msgs = [{"role": r, "text": t} for r, t in history]; text = ""
    for step in range(max_steps):
        text, calls = call(system, msgs, tools if step < max_steps - 1 else [])  # на останньому кроці без інструментів — змушуємо відповісти
        if not calls: return text
        msgs.append({"role": "assistant", "text": text, "calls": calls})
        for c in calls: msgs.append({"role": "tool", "id": c["id"], "name": c["name"], "result": str(run_tool(c["name"], c["args"]))[:1500]})
    return text
