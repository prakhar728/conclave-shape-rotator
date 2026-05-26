from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ToolCallTrace:
    tool_name: str
    input_summary: str
    output_summary: str
    timestamp: str = ""
    filtered: bool = False


class TraceStore:
    def __init__(self):
        self.traces: list[ToolCallTrace] = []
        self.filter_events: list[dict] = []

    def log_tool_call(self, tool_name: str, input_summary: str, output_summary: str, filtered: bool = False):
        self.traces.append(ToolCallTrace(
            tool_name=tool_name,
            input_summary=input_summary,
            output_summary=output_summary,
            timestamp=datetime.utcnow().isoformat(),
            filtered=filtered,
        ))

    def log_filter_event(self, event_type: str, details: str):
        self.filter_events.append({
            "event_type": event_type,
            "details": details,
            "timestamp": datetime.utcnow().isoformat(),
        })

    def get_traces(self) -> list[dict]:
        return [
            {
                "tool_name": t.tool_name,
                "input_summary": t.input_summary,
                "output_summary": t.output_summary,
                "timestamp": t.timestamp,
                "filtered": t.filtered,
            }
            for t in self.traces
        ]

    def get_summary(self) -> dict:
        return {
            "total_tool_calls": len(self.traces),
            "filtered_calls": sum(1 for t in self.traces if t.filtered),
            "filter_events": len(self.filter_events),
        }
