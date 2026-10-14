"""데모 모드에서 모든 API 를 한 번씩 호출해 보는 스모크 테스트."""
import json
import sys
import time

from fastapi.testclient import TestClient

from app.main import app

failures = []
sys.stdout = open("smoke.log", "w", encoding="utf-8")
sys.stderr = sys.stdout


def check(name, resp, status=200, show=None):
    ok = resp.status_code == status
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:300]
    mark = "OK " if ok else "FAIL"
    print(f"[{mark}] {name} -> {resp.status_code}")
    if not ok:
        failures.append(name)
        print("      ", str(body)[:600])
    elif show:
        print("      ", str(show(body))[:600])
    return body


with TestClient(app) as c:
    t = time.time()
    check("info", c.get("/api/info"), show=lambda b: (b["mode"], b["user"], b["account"]))
    check("owners", c.get("/api/owners"), show=lambda b: b)
    check("owners+sys", c.get("/api/owners?include_system=true"), show=lambda b: [o["owner"] for o in b])
    check("objects SALES", c.get("/api/owners/SALES/objects"), show=lambda b: b[:2])
    check("owner refs", c.get("/api/owner-references"), show=lambda b: b)
    check("detail ORDERS", c.get("/api/tables/SALES/ORDERS"),
          show=lambda b: {k: (v if k not in ("columns",) else v[:2]) for k, v in b.items() if k != "view_text"})
    check("detail 404", c.get("/api/tables/SALES/NOPE"), 404)

    body = {"page": 1, "page_size": 50}
    check("rows", c.post("/api/tables/SALES/ORDERS/rows", json=body),
          show=lambda b: (len(b["rows"]), b["has_more"], b["elapsed_ms"], b["rows"][0]))
    q = {"search": "", "filters": [{"column": "STATUS", "op": "eq", "value": "배송완료"},
                                   {"column": "TOTAL_AMOUNT", "op": "between", "value": "100", "value2": "500"}],
         "sort": {"column": "ORDER_DATE", "direction": "desc"}}
    check("rows filtered page 3", c.post("/api/tables/SALES/ORDERS/rows", json={"page": 3, "page_size": 20, **q}),
          show=lambda b: (len(b["rows"]), b["has_more"], b["elapsed_ms"], b["rows"][:1]))
    check("rows search", c.post("/api/tables/SALES/CUSTOMERS/rows", json={"page": 1, "page_size": 10, "search": "서울"}),
          show=lambda b: (len(b["rows"]), b["rows"][:1]))
    for op, v, v2 in [("neq", "1", None), ("gt", "10", None), ("lt", "10", None), ("contains", "a", None),
                      ("starts_with", "a", None), ("is_null", None, None), ("not_null", None, None), ("in", "1,2,3", None)]:
        f = {"column": "CUSTOMER_ID" if op in ("neq", "gt", "lt", "in") else "EMAIL", "op": op}
        if v is not None:
            f["value"] = v
        check(f"filter {op}", c.post("/api/tables/SALES/CUSTOMERS/rows",
                                     json={"page": 1, "page_size": 5, "filters": [f]}),
              show=lambda b: (len(b["rows"]), b["has_more"]))
    check("rows bad column", c.post("/api/tables/SALES/ORDERS/rows",
                                    json={"page": 1, "page_size": 5, "filters": [{"column": "X", "op": "eq", "value": "1"}]}), 400)
    check("rows bad number", c.post("/api/tables/SALES/ORDERS/rows",
                                    json={"page": 1, "page_size": 5, "filters": [{"column": "ORDER_ID", "op": "eq", "value": "abc"}]}), 400)
    check("rows view", c.post("/api/tables/SALES/V_ORDER_SUMMARY/rows", json=body), show=lambda b: (len(b["rows"]), b["rows"][:1]))
    check("rows CLOB", c.post("/api/tables/INVENTORY/PRODUCTS/rows", json={"page": 1, "page_size": 3}),
          show=lambda b: b["rows"][:1])
    check("count", c.post("/api/tables/SALES/ORDERS/count", json=q), show=lambda b: b)
    r = c.get("/api/tables/SALES/ORDERS/export", params={"q": json.dumps(q)})
    check("export", r, show=lambda b: (r.headers.get("content-disposition"), len(r.content), r.text[:150]))

    check("sql", c.post("/api/sql", json={"sql": "SELECT owner, COUNT(*) cnt FROM all_tables GROUP BY owner ORDER BY 1;", "max_rows": 100}),
          show=lambda b: b)
    check("sql big", c.post("/api/sql", json={"sql": "select * from sales.order_items", "max_rows": 1000}),
          show=lambda b: (b["row_count"], b["truncated"], b["elapsed_ms"]))
    for bad in ["delete from sales.orders", "select 1 from dual; drop table x", "update sales.orders set status='x'",
                "select * from sales.orders for update", "begin null; end;", "select * from read_csv('x.csv')",
                "select * from sales.orders@remote", "select dbms_random.value from dual"]:
        check(f"reject: {bad[:30]}", c.post("/api/sql", json={"sql": bad}), 400)
    check("sql syntax err", c.post("/api/sql", json={"sql": "select * from nope_table"}), 400)
    r = c.get("/api/sql/export", params={"sql": "select * from hr.employees"})
    check("sql export", r, show=lambda b: (len(r.content), r.text[:120]))

    check("profile meta ORDERS", c.get("/api/tables/SALES/ORDERS/profile/metadata"),
          show=lambda b: {k: v for k, v in b.items() if k != "columns"} | {"cols": str(b["columns"])[:300]})
    check("profile meta backup", c.get("/api/tables/SALES/ORDERS_BACKUP_2024/profile/metadata"),
          show=lambda b: b.get("quality"))
    check("profile meta view", c.get("/api/tables/SALES/V_ORDER_SUMMARY/profile/metadata"), show=lambda b: b.get("quality"))
    check("profile sample", c.post("/api/tables/SALES/ORDER_ITEMS/profile/sample"),
          show=lambda b: {k: v for k, v in b.items() if k != "columns"} | {"cols": str(b["columns"])[:300]})
    check("profile sample view", c.post("/api/tables/SALES/V_ORDER_SUMMARY/profile/sample"),
          show=lambda b: {k: v for k, v in b.items() if k != "columns"})
    check("profile exact", c.post("/api/tables/SALES/ORDERS/profile/exact"),
          show=lambda b: {k: v for k, v in b.items() if k != "columns"} | {"cols": str(b["columns"])[:300]})
    for col, src in [("STATUS", "stats"), ("TOTAL_AMOUNT", "stats"), ("ORDER_DATE", "stats"),
                     ("STATUS", "sample"), ("TOTAL_AMOUNT", "sample"), ("ORDER_DATE", "sample"), ("ORDER_ID", "sample")]:
        check(f"dist {col}/{src}", c.get("/api/tables/SALES/ORDERS/distribution", params={"column": col, "source": src}),
              show=lambda b: {k: (v[:4] if isinstance(v, list) else v) for k, v in b.items()})
    check("dist CLOB", c.get("/api/tables/INVENTORY/PRODUCTS/distribution", params={"column": "DESCRIPTION", "source": "sample"}),
          show=lambda b: b)
    check("dist backup stats", c.get("/api/tables/SALES/ORDERS_BACKUP_2024/distribution", params={"column": "STATUS", "source": "stats"}),
          show=lambda b: b)

    check("erd SALES", c.get("/api/owners/SALES/erd"),
          show=lambda b: ([n["id"] for n in b["nodes"]], len(b["edges"]), b["edges"][:1]))
    check("erd ANALYTICS all", c.get("/api/owners/ANALYTICS/erd?related_only=false"), show=lambda b: [n["id"] for n in b["nodes"]])
    check("neighborhood", c.get("/api/tables/SALES/ORDERS/neighborhood?depth=2"),
          show=lambda b: ([n["id"] for n in b["nodes"]], len(b["edges"])))
    check("search order", c.get("/api/search?q=order"), show=lambda b: {k: (len(v) if isinstance(v, list) else v) for k, v in b.items()})
    check("search comment", c.get("/api/search", params={"q": "고객", "kinds": "comment"}), show=lambda b: b)
    check("search column", c.get("/api/search?q=customer_id&kinds=column"), show=lambda b: b["columns"][:3])
    check("search similar", c.get("/api/search?q=ORDERS&kinds=similar"), show=lambda b: b["similar"][:5])
    check("related", c.get("/api/tables/SALES/ORDERS/related"),
          show=lambda b: {k: (v[:3] if isinstance(v, list) else v) for k, v in b.items()})
    check("cache clear", c.post("/api/cache/clear"))
    print("total", round(time.time() - t, 1), "s")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
