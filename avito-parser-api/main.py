from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security import APIKeyHeader
import httpx, os, json, re, subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict
from pydantic import BaseModel

app = FastAPI(title="OpenClaw API v2")

# API Key security
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

def get_api_key(api_key: str = Security(API_KEY_HEADER)) -> str:
    """Validate API key from header or environment."""
    valid_key = os.environ.get("API_KEY", "openclaw-dev-key")
    if api_key is None:
        # Allow if no key provided in dev mode (can be disabled)
        if os.environ.get("REQUIRE_API_KEY", "false").lower() == "true":
            raise HTTPException(status_code=403, detail="API key required")
        return "dev"
    if api_key != valid_key:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key


OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:26b")
DB_OK = False
INT_OK = False

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from contextlib import contextmanager
    @contextmanager
    def db():
        c = psycopg2.connect("postgresql://aiserver@localhost/avito_parser")
        try: yield c; c.commit()
        except: c.rollback(); raise
        finally: c.close()
    try:
        with db() as c: c.cursor().execute("SELECT 1")
        DB_OK = True
    except: pass
except: pass

if (Path.home()/ "parser_avito" / "real_integrator.py").exists():
    import sys
    sys.path.insert(0, str(Path.home() / "parser_avito"))
    try:
        from real_integrator import RealAvitoIntegrator
        INTEGRATOR = RealAvitoIntegrator()
        INT_OK = True
    except: pass

class SIn(BaseModel):
    sp: str = "manual"; su: Optional[str] = None; sn: str; si: Optional[str] = None
    cat: Optional[str] = None; reg: Optional[str] = None; lang: str = "ru"
    cd: Dict = {}; notes: Optional[str] = None

class QRes(BaseModel):
    si: str; rs: float; pc: List[str]; lang: str; pri: str; sum: str; dbid: Optional[str] = None

class CStart(BaseModel):
    sid: str; ch: str = "avito"; mode: str = "auto"; op: str = "AI"

class CMsg(BaseModel):
    cid: str; dir: str; txt: str; tid: Optional[str] = None

class CRes(BaseModel):
    mid: Optional[str]; cid: str; stg: Optional[str]
    intnt: Optional[str] = None; conf: float = 0.0
    act: Optional[str] = None; rh: bool = False

class APReq(BaseModel):
    urls: List[str]; geo: Optional[str] = "Moscow"; urp: bool = True

def ss(v, d="unknown"): return str(v) if v else d

def ej(t):
    for p in [r"\{[^{}]*\}", r"```json\s*(\{.*?\})\s*```"]:
        m = re.search(p, t, re.DOTALL)
        if m:
            try: return json.loads(m.group(1) if "\\" in p else m.group(0))
            except: continue
    raise ValueError(f"No JSON")

async def llm(p, t=0.1):
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{OLLAMA}/api/generate", json={"model": MODEL, "prompt": p, "stream": False, "options": {"temperature": t}})
        return r.json().get("response", "")

def sv(sd, q):
    if not DB_OK: raise Exception("DB off")
    with db() as cn:
        cu = cn.cursor(cursor_factory=RealDictCursor)
        sid = sd.get("si") or q.get("si") or ss(sd.get("sn"), "").lower().replace(" ", "_")[:50]
        ct = sd.get("cat")
        if not ct and q.get("pc"): ct = json.dumps(q["pc"], ensure_ascii=False)
        elif isinstance(ct, list): ct = json.dumps(ct, ensure_ascii=False)
        cu.execute("""INSERT INTO sellers(sp,su,sn,si,cat,reg,lang,rs,pri,cd,notes) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s) RETURNING id""",
            (ss(sd.get("sp"),"manual"), ss(sd.get("su")), ss(sd.get("sn"),"Unknown"), sid, ct,
             ss(sd.get("reg")), ss(sd.get("lang"),"ru"), float(q.get("rs",0)), ss(q.get("pri"),"normal"),
             json.dumps(sd.get("cd"),{}), (ss(sd.get("notes"),"")[:500]+" | AI: "+ss(q.get("sum"),"")[:300])[:1000]))
        rid = str(cu.fetchone()["id"])
        cu.execute("""INSERT INTO al(et,eid,a,at,p) VALUES(%s,%s,%s,%s,%s::jsonb)""", ("s", rid, "cq", "ia", json.dumps({"sc":q.get("rs"),"ts":datetime.now().isoformat()}, ensure_ascii=False)))
        return rid

@app.get("/")
def rt(): return {"s":"Avito v2","db":"ok" if DB_OK else "off","m":MODEL,"i":"ok" if INT_OK else "?","prian":"ready"}

@app.post("/qualify", response_model=QRes)
async def ql(s:SIn):
    p=f'Qualify B2B supplier: Name:{s.sn} Cat:{s.cat or "?"} Reg:{s.reg or "?"} Return JSON:{{"si","rs"(0-1),"pc":[],"lang","pri"(h/n/l),"sum"}}'
    r=await llm(); d=ej(r); res=QRes(**d)
    if DB_OK:
        try: res.dbid=sv(s.model_dump(),d)
        except Exception as e: res.dbid=f"e:{e}"
    return res

@app.post("/qualify/batch")
async def bq(sl:List[SIn]):
    rs=[]
    for i,x in enumerate(sl):
        try: rs.append({"i":i,"ok":True,"d":(await ql(x)).model_dump()})
        except Exception as e: rs.append({"i":i,"ok":False,"e":str(e)})
    return {"t":len(sl),"o":sum(1 for x in rs if x["ok"]),"r":rs}

@app.post("/parse/avito+qualify")
async def fp(req:APReq):
    ai=[]; md="?"
    if INT_OK and req.urp:
        try:
            pr=INTEGRATOR.run_full_pipeline(req.urls,geo=req.geo)
            ls=pr.get("listings",[]) or INTEGRATOR._read_xlsx()
            nm=INTEGRATOR.to_seller_inputs(ls); seen={x.get("si") for x in ai}
            for x in nm:
                if x.get("si") not in seen: ai.append(x); seen.add(x.get("si"))
            md=pr.get("status","?")
        except Exception as e: md=f"e:{str(e)[:30]}"
    if not ai:
        xl=INTEGRATOR._read_xlsx() if INT_OK else []
        if xl: ai.extend(INTEGRATOR.to_seller_inputs(xl)); md="xlsx"
    if not ai:
        md="mock"
        for u in req.urls[:5]: ai.append({"sp":"am","su":u,"sn":f"AS_{hash(u)%1000}","reg":req.geo or "Moscow"})
    rs=[]
    for si in ai:
        inp=SIn(**{k:v for k,v in si.items() if k in SIn.__fields__})
        try:
            q=await ql(inp)
            rs.append({"u":si.get("su",""),"s":"q","src":md,"t":si.get("notes","")[:40],"r":q.model_dump()})
        except Exception as e: rs.append({"u":si.get("su",""),"s":"f","src":md,"e":str(e)})
    return {"p":"a->x->l->q->db","m":md,"in":len(req.urls),"q":sum(1 for x in rs if x["s"]=="q"),"f":len(rs)-sum(1 for x in rs if x["s"]=="q"),"r":rs}

@app.post("/conversation/start")
async def cs(req:CStart):
    if not DB_OK: raise Exception("DB off")
    cid=sv_conversation(req.sid,req.ch)
    g=await llm('Gen brief professional B2B greeting for supplier. 2 sentences. Purpose: request catalog/pricing.')
    mid=sv_msg(cid,'outgoing',g.strip(),ai_generated=True)
    up_conversation(cid,st='greeting_sent')
    return {"cid":cid,"st":"greeting_sent","txt":g.strip(),"mid":mid}

@app.post("/conversation/send", response_model=CRes)
async def cm(req:CMsg):
    if not DB_OK: raise Exception("DB off")
    cv=get_conv(req.cid)
    if not cv: raise Exception("Not found")
    if req.dir=='incoming': sv_msg(cv['id'],req.dir,req.txt)
    ap=f'Analyze:"{req.txt}" Stage:{cv.get("st","?")} Return JSON:{{"intnt","conf"(0-1),"act","esc":bool}}'
    raw=await llm(); cd=ej(raw)
    esc=cd.get("esc",False) or any(x in req.txt.lower() for x in ['скидка','отсрочка']) or len(req.txt)<10
    mid=sv_msg(cv['id'],'outgoing',f'[AI intent:{cd.get("intnt","?")}]',ai_generated=True,rh=esc)
    ns=cd.get('next_scenario') or cv.get('st')
    if ns!=cv.get('st'): up_conversation(cid,st=ns)
    return {"mid":mid,"cid":req.cid,"st":ns,"intnt":cd.get("intnt"),"conf":cd.get("conf",0),"act":cd.get("act"),"rh":esc}

@app.get("/conversation/{cid}")
def gc(cid:str):
    if not DB_OK: return {"err":"off"}
    cv=get_conv(cid)
    if not cv: raise Exception("404")
    return {"id":str(cv['id']),'sid':str(cv.get('sid','')),'ch':cv.get('ch','?'),'st':cv.get('st','?'),'s':'a'}

@app.get("/sellers")
def ls(lim:int=20,ms:float=0.0): return {"db":"ok" if DB_OK else "off","s":gs(lim,ms) if DB_OK else []}

@app.get("/stats")
def st():
    d={"db":"ok" if DB_OK else "off"}
    if DB_OK: d.update(gst())
    return d

class PReq(BaseModel):
    urls: List[str]
    max_items: int = 50000
    max_pages: int = 1000

@app.post("/parse/prian")
async def parse_prian_api(req: PReq):
    PRIAN_PARSER = Path(__file__).parent.parent / "extensions" / "prian_parser" / "parse_prian.py"
    if not PRIAN_PARSER.exists():
        return {"ok": False, "error": "Prian parser not found"}
    results = []
    for url in req.urls:
        if "prian.ru" not in url:
            results.append({"url": url, "ok": False, "error": "Invalid Prian URL"})
            continue
        try:
            # Use python3.10 for stability
            proc = subprocess.run(
                ["/opt/homebrew/bin/python3.10", str(PRIAN_PARSER), "--url", url, "--max-items", str(req.max_items), "--max-pages", str(req.max_pages)],
                capture_output=True, text=True, timeout=1800
            )
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                results.append({"url": url, "ok": True, "data": data})
            else:
                results.append({"url": url, "ok": False, "error": proc.stderr[:200]})
        except Exception as e:
            results.append({"url": url, "ok": False, "error": str(e)})
    return {"parsed": len([r for r in results if r["ok"]]), "total": len(req.urls), "results": results}


class CReq(BaseModel):
    urls: List[str]
    mode: str = "single"  # "single", "catalog", "enrich"


@app.post("/parse/company")
async def parse_company_api(req: CReq):
    COMPANY_PARSER = Path(__file__).parent.parent / "extensions" / "prian_parser" / "parse_company.py"
    if not COMPANY_PARSER.exists():
        return {"ok": False, "error": "Company parser not found"}

    if req.mode in ("catalog", "enrich"):
        try:
            cmd = ["/opt/homebrew/bin/python3.10", str(COMPANY_PARSER), "--url", req.mode, "--max-pages", "20"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                return {"ok": True, "mode": req.mode, "count": len(data), "results": data}
            else:
                return {"ok": False, "error": proc.stderr[:300]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    results = []
    for url in req.urls:
        if "prian.ru" not in url or "/company/" not in url:
            results.append({"url": url, "ok": False, "error": "Invalid company URL"})
            continue
        try:
            proc = subprocess.run(
                ["/opt/homebrew/bin/python3.10", str(COMPANY_PARSER), "--url", url],
                capture_output=True, text=True, timeout=60
            )
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                results.append({"url": url, "ok": True, "data": data})
            else:
                results.append({"url": url, "ok": False, "error": proc.stderr[:200]})
        except Exception as e:
            results.append({"url": url, "ok": False, "error": str(e)})
    return {"parsed": len([r for r in results if r["ok"]]), "total": len(req.urls), "results": results}


OJP_PARSER = Path(__file__).parent.parent / "extensions" / "ojp_parser" / "parse_ojp.py"
OJP_SCANNER = Path(__file__).parent.parent / "extensions" / "ojp_parser" / "scan_profiles.py"
OJP_PROGRESS_DIR = Path(__file__).parent.parent / "ojp_progress"

class OJPReq(BaseModel):
    mode: str = "jobs"
    keyword: str = ""
    category: str = "virtual-assistant"
    url: str = ""
    max_pages: int = 3
    full_time: bool = True
    part_time: bool = False


@app.post("/parse/ojp")
async def parse_ojp_api(req: OJPReq):
    if not OJP_PARSER.exists():
        return {"ok": False, "error": "OJP parser not found"}
    mode_flag = "--mode" if req.mode in ("all-profiles", "all-jobs", "detail", "profiles") else "--mode"
    cmd = ["/opt/homebrew/bin/python3.10", str(OJP_PARSER),
           mode_flag, req.mode, "--max-pages", str(req.max_pages)]
    if req.keyword:
        cmd += ["--keyword", req.keyword]
    if req.category:
        cmd += ["--category", req.category]
    if req.url:
        cmd += ["--url", req.url]
    if req.part_time:
        cmd += ["--part-time"]
    timeout = 1800 if req.mode in ("all-profiles",) else 600 if req.mode == "all-jobs" else 300
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            return {"ok": True, "mode": req.mode, "count": data.get("count", len(data) if isinstance(data, list) else 1),
                    "results": data.get("results", data) if isinstance(data, dict) else data}
        return {"ok": False, "error": proc.stderr[:300]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


class OJPScanReq(BaseModel):
    action: str = "status"
    max_profiles: int = 0
    start_from: int = 0


@app.post("/parse/ojp_scan")
async def ojp_scan_api(req: OJPScanReq):
    if not OJP_SCANNER.exists():
        return {"ok": False, "error": "OJP scanner not found"}
    try:
        if req.action == "status":
            cmd = ["/opt/homebrew/bin/python3.10", str(OJP_SCANNER), "--mode", "status"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            data = json.loads(proc.stdout)
            return {"ok": True, **data}
        elif req.action == "phase1sitemap":
            cmd = ["/opt/homebrew/bin/python3.10", str(OJP_SCANNER), "--mode", "phase1sitemap"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            data = json.loads(proc.stdout)
            return {"ok": True, **data}
        elif req.action == "phase1":
            cmd = ["/opt/homebrew/bin/python3.10", str(OJP_SCANNER), "--mode", "phase1"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            data = json.loads(proc.stdout)
            return {"ok": True, **data}
        elif req.action == "phase2":
            cmd = ["/opt/homebrew/bin/python3.10", str(OJP_SCANNER), "--mode", "phase2"]
            if req.start_from > 0:
                cmd += ["--start-from", str(req.start_from)]
            if req.max_profiles > 0:
                cmd += ["--max-profiles", str(req.max_profiles)]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                return {"ok": True, **data}
            return {"ok": False, "error": proc.stderr[:500]}
        elif req.action == "export":
            cmd = ["/opt/homebrew/bin/python3.10", str(OJP_SCANNER), "--mode", "export"]
            if req.max_profiles > 0:
                cmd += ["--max-profiles", str(req.max_profiles)]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                return {"ok": True, **data}
            return {"ok": False, "error": proc.stderr[:300]}
        elif req.action == "full":
            cmd = ["/opt/homebrew/bin/python3.10", str(OJP_SCANNER), "--mode", "full"]
            if req.max_profiles > 0:
                cmd += ["--max-profiles", str(req.max_profiles)]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=86400)
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                return {"ok": True, **data}
            return {"ok": False, "error": proc.stderr[:500]}
        elif req.action == "quick":
            cmd = ["/opt/homebrew/bin/python3.10", str(OJP_SCANNER), "--mode", "quick"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                return {"ok": True, **data}
            return {"ok": False, "error": proc.stderr[:300]}
        else:
            return {"ok": False, "error": f"Unknown action: {req.action}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Scan timeout (still running in background, check /ojp_scan_progress)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/ojp_scan_progress")
def ojp_scan_progress():
    progress_file = OJP_PROGRESS_DIR / "scan_progress.json"
    ids_file = OJP_PROGRESS_DIR / "profile_ids.json"
    if not progress_file.exists():
        return {"ok": True, "status": "not_started", "total_ids": 0, "processed": 0}
    try:
        progress = json.loads(progress_file.read_text())
        
        # Fix: use processed_ids count as total if ids_file doesn't exist
        if ids_file.exists():
            total_ids = len(json.loads(ids_file.read_text()))
        else:
            total_ids = len(progress.get("processed_ids", []))
        
        processed = len(progress.get("processed_ids", []))
        errors = len(progress.get("errors", []))
        
        # If we have processed but no total_ids yet, estimate from processed
        if total_ids == 0 and processed > 0:
            total_ids = 100000  # Default assumption
        
        pct = round(processed / total_ids * 100, 1) if total_ids else 0

        # Check if scanner is actually running
        import os
        scanner_running = os.popen("ps aux | grep scan_profiles | grep -v grep | grep phase2").read().strip() != ""
        
        if processed >= total_ids:
            status = "completed"
        elif scanner_running:
            status = "running"
        else:
            status = "stopped"

        return {
            "ok": True,
            "status": status,
            "total_ids": total_ids,
            "processed": processed,
            "errors": errors,
            "progress_pct": pct,
            "active_profiles": progress.get("total_active", 0),
            "started_at": progress.get("started_at", ""),
            "last_updated": progress.get("last_updated", ""),
            "completed_at": progress.get("completed_at", ""),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/ojp_scan_export")
def ojp_scan_export():
    csv_path = OJP_PROGRESS_DIR / "profiles.csv"
    if not csv_path.exists():
        return {"ok": False, "error": "No export file found. Run export action first."}
    try:
        count = sum(1 for _ in open(csv_path)) - 1
        return {"ok": True, "path": str(csv_path), "count": count}
    except Exception as e:
        return {"ok": False, "error": str(e)}


OJP_TEST_URL = "https://www.onlinejobs.ph/employers/skillsearch/all"
OJP_TEST_SEARCH_ID = "a181a603769c1f98ad927e7367c7aa5112147425"


@app.post("/parse/ojp_test")
async def ojp_test_api(max_profiles: int = 1000):
    
    import re
    import html as html_module
    import asyncio
    import aiohttp
    
    results = []
    CONCURRENCY = 10
    
    async def fetch_page(offset: int):
        url = f"{OJP_TEST_URL}/{OJP_TEST_SEARCH_ID}/{offset}"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                return await resp.text(encoding="utf-8", errors="replace")
    
    async def fetch_profile(profile_id: str):
        url = f"https://www.onlinejobs.ph/jobseekers/info/{profile_id}"
        headers = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                html = await resp.text(encoding="utf-8", errors="replace")
                return parse_single_profile(html, url, profile_id)
    
    def parse_single_profile(html_text: str, url: str, profile_id: str) -> dict:
        result = {
            "profile_id": profile_id,
            "name": "",
            "title": "",
            "url": url,
            "id_proof_score": "",
            "education": "",
            "last_active": "",
            "description": "",
            "skills_top": "",
            "hourly_rate": "",
            "availability": "",
        }
        
        name_m = re.search(r'jobseeker-name[^>]*>([^<]+)', html_text)
        if name_m:
            result["name"] = name_m.group(1).strip()
        
        title_m = re.search(r'<h1[^>]*>([^<]+)<', html_text)
        if title_m:
            result["title"] = title_m.group(1).strip()
        
        idproof = re.search(r'class="badge">(\d+)</span>\s*ID PROOF', html_text)
        if idproof:
            result["id_proof_score"] = idproof.group(1)
        
        # Find education (Bachelors, Associates, High School, etc)
        for edu in ['Bachelors degree', 'Associates degree', 'High School', 'College Undergraduate', 'Master']:
            if edu in html_text:
                result["education"] = edu
                break
        
        active_m = re.search(r'Last Active</strong></p>\s*<p[^>]*>([^<]+)<', html_text)
        if active_m:
            result["last_active"] = active_m.group(1).strip()
        
        rate_m = re.search(r'>\s*at\s*<strong>\$([\d,.]+)/hour', html_text)
        if rate_m:
            result["hourly_rate"] = "$" + rate_m.group(1) + "/hour"
        
        desc_m = re.search(r'>Profile Description</h3>\s*(.*?)(?:<h3|</div>)', html_text, re.DOTALL)
        if desc_m:
            text = re.sub(r"<[^>]+>", " ", desc_m.group(1))
            text = html_module.unescape(re.sub(r"\s+", " ", text).strip())
            result["description"] = text[:400]
        
        skills_m = re.search(r'>Top Skills</h3>(.*?)(?:<h3|</div>)', html_text, re.DOTALL)
        if skills_m:
            skills = re.findall(r'>([^<]{2,50})</a>', skills_m.group(1))
            result["skills_top"] = ", ".join(skills[:5])
        
        avail_m = re.search(r'>Availability</h3>(.*?)(?:<h3|</div>)', html_text, re.DOTALL)
        if avail_m:
            text = re.sub(r"<[^>]+>", " ", avail_m.group(1))
            result["availability"] = re.sub(r"\s+", " ", text).strip()[:100]
        
        return result
    
    try:
        collected_ids = set()
        
        for offset in range(0, max_profiles, 30):
            html = await fetch_page(offset)
            ids = re.findall(r'/jobseekers/info/(\d+)', html)
            if not ids:
                break
            collected_ids.update(ids)
            await asyncio.sleep(0.1)
        
        profile_ids = list(collected_ids)[:max_profiles]
        
        async with aiohttp.ClientSession() as session:
            semaphore = asyncio.Semaphore(CONCURRENCY)
            
            async def fetch_with_limit(pid):
                async with semaphore:
                    return await fetch_profile(pid)
            
            tasks = [fetch_with_limit(pid) for pid in profile_ids]
            for coro in asyncio.as_completed(tasks):
                result = await coro
                if result:
                    results.append(result)
        
        return {"ok": True, "count": len(results), "results": results}
    
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/outreach/contacts")
def outreach_contacts(status: str = "", limit: int = 50):
    if not DB_OK:
        return {"error": "DB off"}
    try:
        with db() as cn:
            cu = cn.cursor(cursor_factory=RealDictCursor)
            q = "SELECT * FROM prian_contacts WHERE 1=1"
            p = []
            if status:
                q += " AND status = %s"
                p.append(status)
            q += " ORDER BY priority DESC, total_objects DESC NULLS LAST LIMIT %s"
            p.append(limit)
            cu.execute(q, p)
            contacts = [dict(r) for r in cu.fetchall()]
            return {"ok": True, "count": len(contacts), "contacts": contacts}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/outreach/stats")
def outreach_stats():
    if not DB_OK:
        return {"error": "DB off"}
    try:
        with db() as cn:
            cu = cn.cursor(cursor_factory=RealDictCursor)
            cu.execute("SELECT COUNT(*) as total FROM prian_contacts")
            total = cu.fetchone()["total"]
            cu.execute("SELECT COUNT(*) as cnt FROM prian_contacts WHERE array_length(phones, 1) > 0")
            with_phones = cu.fetchone()["cnt"]
            cu.execute("SELECT COUNT(*) as cnt FROM prian_contacts WHERE whatsapp IS NOT NULL AND whatsapp != ''")
            with_wa = cu.fetchone()["cnt"]
            cu.execute("SELECT COUNT(*) as cnt FROM prian_contacts WHERE telegram IS NOT NULL AND telegram != ''")
            with_tg = cu.fetchone()["cnt"]
            cu.execute("SELECT status, COUNT(*) as cnt FROM prian_contacts GROUP BY status ORDER BY cnt DESC")
            by_status = [dict(r) for r in cu.fetchall()]
            return {"ok": True, "total": total, "with_phones": with_phones, "with_whatsapp": with_wa, "with_telegram": with_tg, "by_status": by_status}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/health")
def h():
    hh={"a":"ok","db":"ok" if DB_OK else "off","i":"ready" if INT_OK else "?","ts":datetime.now().isoformat()}
    try:
        r=httpx.get(f"{OLLAMA}/api/tags",timeout=5)
        hh["ol"]="ok" if r.status_code==200 else "f"; hh["ml"]=[m["name"] for m in r.json().get("models",[])]
    except: hh["ol"]="?"
    hh["p"]="ok" if (Path.home()/"parser_avito"/"dto.py").exists() else "?"
    hh["ov"]="healthy" if all(v=="ok" for v in [hh.get("db",""),hh.get("ol",""),hh.get("i",""),hh.get("p","")]) else "?"
    return hh

# DB helpers
def sv_conversation(sid,ch,s='active'):
    with db() as cn:
        cu=cn.cursor(cursor_factory=RealDictCursor)
        cu.execute("INSERT INTO conv(sid,ch,cst,s,ca) VALUES(%s,%s,'init',%s,NOW()) RETURNING id",(sid,ch,s))
        return str(cu.fetchone()["id"])

def get_conv(cid):
    with db() as cn:
        cu=cn.cursor(cursor_factory=RealDictCursor)
        cu.execute("SELECT * FROM conv WHERE id=%s",(cid,))
        r=cu.fetchone()
        return dict(r) if r else None

def up_conversation(cid, st='greeting_sent'):
    """
    Обновление стадии диалога в БД
    
    Args:
        cid: UUID диалога
        st: Строка с названием стадии (НЕ функция!)
    """
    # КРИТИЧНО: Принудительное преобразование в строку!
    # Это исправляет "can't adapt type 'function'"
    if callable(st):
        print(f"⚠️ WARNING: st is function, calling it...")
        stage_str = str(st())
    else:
        stage_str = str(st).strip()
    
    if not stage_str:
        stage_str = 'greeting_sent'  # fallback
    
    try:
        with db() as cn:
            cu = cn.cursor(cursor_factory=RealDictCursor)
            cu.execute(
                "UPDATE conversations SET current_stage=%s, updated_at=NOW() WHERE id=%s",
                (stage_str, cid)
            )
            cn.commit()
            return True
    except Exception as e:
        print(f"❌ Error in up_conversation: {e}")
        return False


def sv_msg(cid, direction, text, ai_generated=False):
    """
    Сохранение сообщения в БД
    """
    try:
        with db() as cn:
            cu = cn.cursor(cursor_factory=RealDictCursor)
            cu.execute(
                """INSERT INTO messages (
                       conversation_id, direction, text, 
                       ai_generated, sent_at
                   ) VALUES (%s, %s, %s, %s, NOW()) RETURNING id""",
                (cid, direction, text, ai_generated)
            )
            msg_id = cu.fetchone()['id']
            cn.commit()
            return msg_id
    except Exception as e:
        print(f"❌ Error saving message: {e}")
        return None


def gs(lim=50,ms=0.0):
    with db() as cn:
        cu=cn.cursor(cursor_factory=RealDictCursor)
        cu.execute("SELECT * FROM sellers_short WHERE rs>=%s ORDER BY rs DESC LIMIT %s",(ms,lim))
        return [dict(r) for r in cu.fetchall()]

def gst():
    with db() as cn:
        cu=cn.cursor(cursor_factory=RealDictCursor)
        s={}
        for t in ['sellers','conv','msg','docs','ep','al']:
            cu.execute(f"SELECT count(*) as c FROM {t if t != 'docs' else 'documents'}"); s[t]=cu.fetchone()["c"]
        return s

if __name__=="__main__":
    import uvicorn
    print("AVITO V2 READY on :8001")
    uvicorn.run(app,host="127.0.0.1",port=8001)
