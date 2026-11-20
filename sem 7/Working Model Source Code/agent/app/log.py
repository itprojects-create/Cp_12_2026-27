"""Structured JSON logging. Every line carries session/stage/agent for audit + replay."""
from __future__ import annotations
import json
import logging
import os

LOG_PATH = "data/sessions.log"
os.makedirs("data", exist_ok=True)

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.Record) -> str:
        payload = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
                   "level": record.levelname, "logger": record.name,
                   "msg": record.getMessage()}
        extra = getattr(record, "qp", None)
        if isinstance(extra, dict):
            payload.update(extra)
        return json.dumps(payload)

def get_logger(name: str = "qp") -> logging.Logger:
    lg = logging.getLogger(name)
    if not lg.handlers:
        h = logging.FileHandler(LOG_PATH, encoding="utf-8")
        h.setFormatter(JsonFormatter())
        lg.addHandler(h)
        lg.setLevel(logging.INFO)
        lg.propagate = False
    return lg

def log(session_id: str, stage: str, agent: str, status: str, **fields):
    get_logger().info(status, extra={"qp": {"session": session_id, "stage": stage,
                                            "agent": agent, "status": status, **fields}})
