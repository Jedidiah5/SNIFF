"""ClearGuard entry point: python3 main.py <data folder> <output file>"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import load_data, as_list  # noqa: E402
from decide import Index, decide_hit  # noqa: E402


def run(data_dir, out_path, debug=False):
    try:
        import llm_locate
        llm_locate.reset_run_state()
    except Exception:
        pass
    data = load_data(data_dir)
    ix = Index(data)
    alerts = {a["alert_id"]: a for a in data["alerts"]}
    lines = []
    for h in sorted(data["hits"], key=lambda x: (x.get("alert_id") or "", x.get("hit_id") or "")):
        alert = alerts.get(h.get("alert_id"), {})
        try:
            r = decide_hit(ix, alert, h)
        except Exception as e:  # never drop a hit: fall back to the safe decision
            from decide import make_trace
            reason = (f"The hit could not be processed automatically ({type(e).__name__}), so a person "
                      f"must review it.")
            r = {"decision": "REVIEW", "reason_code": "INSUFFICIENT_DATA", "customer_record_id": None,
                 "reason": reason, "evidence": [], "path": [],
                 "trace": make_trace("INSUFFICIENT_DATA", [reason], [])}
        row = {"hit_id": h.get("hit_id"), "alert_id": h.get("alert_id"), "decision": r["decision"],
               "reason_code": r["reason_code"], "customer_record_id": r["customer_record_id"],
               "reason": r["reason"], "evidence": r["evidence"]}
        if debug:
            row["path"] = r.get("path")
            row["trace"] = r.get("trace")
        lines.append(row)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for row in lines:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n")
    return lines


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: run <data folder> <output file>", file=sys.stderr)
        sys.exit(2)
    run(sys.argv[1], sys.argv[2], debug="--debug" in sys.argv)
