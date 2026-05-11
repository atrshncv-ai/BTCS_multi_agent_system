import os, json, psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from typing import List, Dict, Optional
from contextlib import contextmanager

DB_URL = os.getenv("DATABASE_URL", "postgresql://aiserver@localhost/avito_parser")

@contextmanager
def get_db():
    c = psycopg2.connect(DB_URL)
    try: yield c; c.commit()
    except: c.rollback(); raise
    finally: c.close()

def safe_str(val, default="unknown") -> str:
    """Конвертация в строку с защитой от None"""
    if val is None: return default
    s = str(val)
    return s if s else default

def save_seller(sd: Dict, q: Dict) -> Optional[str]:
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # seller_id — безопасная обработка
        sid = sd.get("seller_id") or q.get("seller_id")
        if not sid or not str(sid).strip():
            sid = safe_str(sd.get("seller_name"), "unknown").lower().replace(" ", "_")[:50]
        
        # category — может быть list из LLM или string или None
        cat = sd.get("category")
        if not cat and q.get("product_categories"):
            pcats = q["product_categories"]
            cat = json.dumps(pcats, ensure_ascii=False) if pcats else None
        elif isinstance(cat, (list, tuple)):
            cat = json.dumps(cat, ensure_ascii=False)
        cat = safe_str(cat, None)  # None разрешён для БД
        
        # Все поля через safe_str — slice ТОЛЬКО после конвертации!
        platform = safe_str(sd.get("source_platform"), "manual")
        url = safe_str(sd.get("source_url"))
        name = safe_str(sd.get("seller_name"), "Unknown Seller")
        region = safe_str(sd.get("region"))
        lang = safe_str(sd.get("language"), "ru")
        score = float(q.get("relevance_score", 0))
        priority = safe_str(q.get("priority"), "normal")
        contacts = json.dumps(sd.get("contact_data") or {}, ensure_ascii=False)
        
        # notes и summary — отдельно конвертируем, потом склеиваем
        notes_raw = safe_str(sd.get("notes"))
        summary_raw = safe_str(q.get("summary"))
        notes_field = (notes_raw[:500] + " | AI: " + summary_raw[:300])[:1000]
        
        cur.execute("""INSERT INTO sellers (source_platform,source_url,seller_name,seller_id,
            category,region,language,relevance_score,priority,contact_data,notes)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s) RETURNING id""", (
            platform, url, name, sid, cat, region, lang,
            score, priority, contacts, notes_field
        ))
        rid = str(cur.fetchone()["id"])
        
        # Audit
        cur.execute("""INSERT INTO audit_logs(entity_type,entity_id,action,actor_type,payload)
            VALUES(%s,%s,%s,%s,%s::jsonb)""",
            ("seller", rid, "create_qualify", "intake-agent",
             json.dumps({"score": score, "priority": priority, "ts": datetime.now().isoformat()},
                      ensure_ascii=False)))
        return rid

def get_sellers(limit:int=50, min_score:float=0.0) -> List[Dict]:
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""SELECT * FROM sellers WHERE relevance_score>=%s 
            ORDER BY relevance_score DESC, created_at DESC LIMIT %s""", (min_score, limit))
        return [dict(r) for r in cur.fetchall()]

def get_stats() -> Dict:
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        s = {}
        for t in ["sellers","conversations","messages","documents","extracted_products","audit_logs"]:
            cur.execute(f"SELECT count(*) as c FROM {t}"); s[t] = cur.fetchone()["c"]
        cur.execute("SELECT priority,count(*) as c FROM sellers GROUP BY priority")
        s["by_priority"] = {r["priority"]: r["c"] for r in cur.fetchall()}
        cur.execute("SELECT source_platform,count(*) as c FROM sellers GROUP BY source_platform")
        s["by_platform"] = {r["source_platform"]: r["c"] for r in cur.fetchall()}
        return s

def test_connection() -> bool:
    try:
        with get_db() as conn:
            conn.cursor().execute("SELECT 1"); return True
    except Exception as e:
        print(f"[DB] {e}"); return False

if __name__ == "__main__":
    print("DB Test:", "OK" if test_connection() else "FAIL")
    print(get_stats())
