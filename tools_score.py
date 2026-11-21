"""Score output against practice labels: python3 tools_score.py <labels.jsonl> <output.jsonl> [-v]"""
import json, sys
from collections import Counter


def field_list(v):
    """Practice labels use a JSON list; the browse workbook used ';'-separated strings."""
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [p.strip() for p in str(v).split(";") if p.strip()]


labels = {json.loads(l)["hit_id"]: json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()}
out = {json.loads(l)["hit_id"]: json.loads(l) for l in open(sys.argv[2], encoding="utf-8") if l.strip()}
v = "-v" in sys.argv
conf = Counter(); ok_dec = ok_code = ok_cust = 0; wrong = []
for hid, lab in labels.items():
    o = out.get(hid, {"decision": "MISSING", "reason_code": "", "customer_record_id": None, "evidence": []})
    codes = field_list(lab.get("reason_codes"))
    custs = field_list(lab.get("customer_record_ids"))
    conf[(lab["decision"], o["decision"])] += 1
    d = o["decision"] == lab["decision"]; ok_dec += d
    ok_code += d and o["reason_code"] in codes
    ok_cust += str(o["customer_record_id"]) in custs
    if not d or o["reason_code"] not in codes or str(o["customer_record_id"]) not in custs:
        wrong.append((hid, lab["decision"], codes, custs, o["decision"], o["reason_code"], o["customer_record_id"], o.get("reason", "")))
n = len(labels)
print(f"decision {ok_dec}/{n}  decision+code {ok_code}/{n}  customer {ok_cust}/{n}")
print("confusion (true -> predicted):")
for (t, p), c in sorted(conf.items()): print(f"  {t:17s} -> {p:17s} {c}")
wc = conf[("SAME_ENTITY", "DIFFERENT_ENTITY")] + conf[("REVIEW", "DIFFERENT_ENTITY")]
print("WRONGFUL CLEARS:", wc)
if v:
    for w in wrong: print(" ", w)
