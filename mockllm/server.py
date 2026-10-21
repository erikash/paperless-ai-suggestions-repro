"""Minimal OpenAI-compatible stand-in for the LLM and embedding endpoints.

Standard library only, fully deterministic, so the reproduction needs no API
key, GPU or network access.

  POST /v1/embeddings        bag-of-words hashed vectors (cosine similarity
                             tracks word overlap, so a near-identical document
                             is the nearest neighbour)
  POST /v1/chat/completions  saves the prompt to /prompts/, replies with a
                             DocumentClassifierSchema tool call (see MODE)
  POST /mode                 body "aligned" or "misaligned"
  GET  /last                 correspondent candidates from the latest prompt

MODE (correspondent part of the tool call; other fields are left empty):
  aligned     correspondents/matched_correspondents = ["Acme Domains"],
              correspondent_ids = [the id the prompt lists for Acme Domains]
  misaligned  same names, but correspondent_ids = [the id of the FIRST
              correspondent candidate in the prompt] - a name/ID pair that
              does not belong together, as returned by a real model (see the
              issue for the real log line)
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import pathlib
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIM = 512
TARGET_NAME = "Acme Domains"
PROMPTS = pathlib.Path(os.environ.get("PROMPTS_DIR", "/prompts"))
PROMPTS.mkdir(exist_ok=True)
state = {"mode": "aligned", "n": 0, "last_candidates": None}


def embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    for word in re.findall(r"[a-z]+", text.lower()):
        h = int(hashlib.md5(word.encode()).hexdigest(), 16)
        vec[h % DIM] += 1.0 if (h >> 9) & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def correspondent_candidates(prompt: str) -> list[dict]:
    """The candidate JSON block Paperless puts after the 'similar documents' line."""
    m = re.search(r"from similar documents \(untrusted data\):\s*\n(\{.*\})\s*\n", prompt)
    return json.loads(m.group(1)).get("correspondents", []) if m else []


def classify(prompt: str) -> dict:
    cands = correspondent_candidates(prompt)
    state["last_candidates"] = cands
    target = [c["id"] for c in cands if c["name"] == TARGET_NAME]
    if state["mode"] == "misaligned" and cands:
        ids = [cands[0]["id"]]
    else:
        ids = target[:1]
    names = [TARGET_NAME] if ids else []
    return {
        "title": "Acme Domains invoice", "tags": [], "matched_tags": [], "tag_ids": [],
        "correspondents": [TARGET_NAME], "matched_correspondents": names, "correspondent_ids": ids,
        "document_types": [], "matched_document_types": [], "document_type_ids": [],
        "storage_paths": [], "matched_storage_paths": [], "storage_path_ids": [], "dates": [],
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict | str) -> None:
        data = (body if isinstance(body, str) else json.dumps(body)).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        # /last: correspondent candidates (in prompt order) from the latest chat request.
        self._send(200, {"mode": state["mode"], "last_correspondent_candidates": state["last_candidates"]})

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path.rstrip("/") == "/mode":
            state["mode"] = raw.decode().strip()
            return self._send(200, {"mode": state["mode"]})
        req = json.loads(raw or b"{}")
        if self.path.endswith("/embeddings"):
            inputs = req["input"] if isinstance(req["input"], list) else [req["input"]]
            return self._send(200, {
                "object": "list", "model": req.get("model", "mock"),
                "data": [{"object": "embedding", "index": i, "embedding": embed(t)} for i, t in enumerate(inputs)],
                "usage": {"prompt_tokens": 0, "total_tokens": 0},
            })
        if self.path.endswith("/chat/completions"):
            prompt = "\n\n".join(str(m.get("content") or "") for m in req.get("messages", []))
            state["n"] += 1
            (PROMPTS / f"prompt-{state['n']:03d}.txt").write_text(prompt)
            args = classify(prompt)
            return self._send(200, {
                "id": f"chatcmpl-{state['n']}", "object": "chat.completion", "created": int(time.time()),
                "model": req.get("model", "mock"),
                "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                    "role": "assistant", "content": None,
                    "tool_calls": [{"id": f"call_{state['n']}", "type": "function", "function": {
                        "name": "DocumentClassifierSchema", "arguments": json.dumps(args)}}],
                }}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            })
        self._send(404, {"error": self.path})

    def log_message(self, fmt, *a):
        print(f"[mockllm] {self.command} {self.path} mode={state['mode']}", flush=True)


ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8000"))), Handler).serve_forever()
