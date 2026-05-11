#!/usr/bin/env python3
"""
atualizar_dashboard.py — v3.0
Atualiza TODAS as abas do dashboard TMO para as 3 filas (Publicações, Vendas, ME).
Executa via Windows Task Scheduler diariamente às 08:00.

TARGETS: Lidos de targets.json (mesmo diretório).
  Fonte: https://grid.adminml.com/d/01KQ7PT60VCDG3Q91HA8M1YQG0/view
  Para atualizar: editar targets.json quando o grid mostrar novos valores.
"""
import subprocess, json, re, sys, os
from datetime import date, datetime, timedelta
sys.stdout.reconfigure(encoding='utf-8', errors='replace') if hasattr(sys.stdout, 'reconfigure') else None

REPO = r"C:\Users\alicarvalho\tmo-dashboard-abril2026"
HTML = REPO + r"\index.html"

# ============================================================
# TARGETS — lidos de targets.json; fallback hardcoded
# ============================================================
_TARGETS_FALLBACK = {
    "BR_Publicaciones_Sellers_Mature": {"chat": 27.54, "c2c": 19.73, "global": 26.0},
    "BR_Ventas_Sellers_Mature":        {"chat": 28.89, "c2c": 16.91, "global": 24.0},
    "BR_ME_Sellers_Mature":            {"chat": 22.0,  "c2c": 17.0,  "global": 20.5},
}
try:
    _targets_path = os.path.join(REPO, "targets.json")
    with open(_targets_path, encoding="utf-8") as _f:
        _tj = json.load(_f)
    TARGETS = {k: v for k, v in _tj.items() if not k.startswith("_")}
    print(f"[TARGETS] Lido de targets.json (atualizado: {_tj.get('_updated','?')})")
except Exception as e:
    TARGETS = _TARGETS_FALLBACK
    print(f"[TARGETS] targets.json não encontrado, usando fallback ({e})")

# Configuração das filas
QUEUES = {
    "publi": {
        "name":     "BR_Publicaciones_Sellers_Mature",
        "js_kpis":  "KPIS",
        "js_canal": "CANAL_DATA",
        "js_lider": "LIDER_DATA",
        "js_prefix": "MAY_",
        "label":    "Publicacoes",
    },
    "ventas": {
        "name":     "BR_Ventas_Sellers_Mature",
        "js_kpis":  "VENTAS_KPIS",
        "js_canal": "VENTAS_CANAL",
        "js_lider": "VENTAS_LIDER",
        "js_prefix": "VENTAS_",
        "label":    "Vendas",
    },
    "me": {
        "name":     "BR_ME_Sellers_Mature",
        "js_kpis":  "ME_KPIS",
        "js_canal": "ME_CANAL",
        "js_lider": "ME_LIDER",
        "js_prefix": "ME_",
        "label":    "ME",
    },
    "melipro": {
        "name":     "MELI_PRO_MLB",
        "js_kpis":  "MELIPRO_KPIS",
        "js_canal": "MELIPRO_CANAL",
        "js_lider": "MELIPRO_LIDER",
        "js_prefix": "MELIPRO_",
        "label":    "Pro MLB",
    },
    "vip": {
        "name":     "MELIPRO_VIP_MLB",
        "js_kpis":  "VIP_KPIS",
        "js_canal": "VIP_CANAL",
        "js_lider": "VIP_LIDER",
        "js_prefix": "VIP_",
        "label":    "VIP MLB",
    },
}

# ---- helpers ---------------------------------------------------------------
BQ_PATH = r"C:\Users\alicarvalho\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\bq.cmd"

def bq_csv(sql, max_rows=1000):
    # bq.cmd via subprocess requer SQL em linha única
    sql_flat = ' '.join(l.strip() for l in sql.splitlines() if l.strip())
    r = subprocess.run(
        [BQ_PATH, "query", "--use_legacy_sql=false", "--format=csv",
         f"--max_rows={max_rows}", sql_flat],
        capture_output=True, text=True, timeout=180
    )
    if r.returncode != 0:
        err = r.stderr or r.stdout
        print(f"  ERRO BQ:\n{err[:200]}")
        return []
    lines = [l for l in r.stdout.strip().splitlines()
             if l and not l.startswith("Waiting") and not l.startswith("Current")]
    if len(lines) < 2:
        return []
    header = [h.strip() for h in lines[0].split(",")]
    rows = []
    for l in lines[1:]:
        vals = l.split(",")
        rows.append(dict(zip(header, vals)))
    return rows

def fmt(v, dec=2):
    try: return round(float(v), dec)
    except: return 0.0

def read_html():
    with open(HTML, encoding="utf-8") as f:
        return f.read()

def write_html(html):
    with open(HTML, "w", encoding="utf-8") as f:
        f.write(html)

def replace_js_array(html, varname, new_content):
    """Substitui const VARNAME = [...] no HTML. Suporta arrays com colchetes internos."""
    marker = f"const {varname} = ["
    start = html.find(marker)
    if start == -1:
        print(f"  AVISO: variável {varname} não encontrada no HTML")
        return html
    # Find the closing ]; by counting bracket depth
    depth = 0
    pos = start + len(marker) - 1  # position of the opening [
    end = -1
    for i in range(pos, len(html)):
        if html[i] == '[': depth += 1
        elif html[i] == ']':
            depth -= 1
            if depth == 0:
                # Check if followed by ;
                if i + 1 < len(html) and html[i+1] == ';':
                    end = i + 2
                break
    if end == -1:
        print(f"  AVISO: fechamento de {varname} não encontrado")
        return html
    return html[:start] + f"const {varname} = [\n{new_content}\n];" + html[end:]

def replace_js_month_in_obj(html, obj_name, month_key, new_entry_content):
    """Substitui a entrada '{month_key}': {...} dentro do objeto obj_name."""
    # Encontra o objeto e substitui o mês específico
    pat = rf"('{re.escape(month_key)}': \{{)[^}}]*(\}})"
    # Limitar ao escopo do objeto
    obj_start = html.find(f"const {obj_name} = {{")
    if obj_start == -1:
        obj_start = html.find(f"const {obj_name}={{")
    if obj_start == -1:
        print(f"  AVISO: objeto {obj_name} não encontrado")
        return html
    obj_end = html.find("\n};", obj_start) + 3
    obj_text = html[obj_start:obj_end]
    new_obj_text = re.sub(pat, lambda m: m.group(1) + new_entry_content + m.group(2), obj_text)
    return html[:obj_start] + new_obj_text + html[obj_end:]

def replace_stats_month(html, stats_varname, month_key, new_stats_content):
    """Substitui a entrada '{month_key}': {...} dentro do STATS object (inclui arrays internos)."""
    pat = rf"('{re.escape(month_key)}': \{{)(.*?)(\}},?\n  '\d\d\d\d-\d\d'|\}}\n\}};)"
    obj_start = html.find(f"const {stats_varname} = {{")
    if obj_start == -1:
        print(f"  AVISO: {stats_varname} não encontrado")
        return html
    obj_end = html.find("\n};", obj_start) + 3
    obj_text = html[obj_start:obj_end]
    # Encontrar abertura do mês
    month_start = obj_text.find(f"'{month_key}': {{")
    if month_start == -1:
        print(f"  AVISO: '{month_key}' não encontrado em {stats_varname}")
        return html
    # Encontrar fechamento: próximo '},' ou '}' seguido de nova entrada ou '};'
    depth = 0
    pos = month_start + len(f"'{month_key}': {{") - 1
    for i, c in enumerate(obj_text[pos:]):
        if c == '{': depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                month_end = pos + i + 1
                break
    new_obj = obj_text[:month_start] + f"'{month_key}': {{\n{new_stats_content}\n  }}" + obj_text[month_end:]
    return html[:obj_start] + new_obj + html[obj_end:]

# ---- lider mapping ----------------------------------------------------------
def get_lider_map(queue_name, mes_ini):
    """Busca mapeamento rep → lider do DM_CX_TMO."""
    rows = bq_csv(f"""
        SELECT DISTINCT USER_LDAP AS rep, USER_TEAM_LEADER_LDAP AS lider
        FROM `meli-bi-data.WHOWNER.DM_CX_TMO`
        WHERE USER_TEAM_NAME = '{queue_name}'
          AND DATE(ASSIGN_DTTM) BETWEEN '{mes_ini}' AND DATE_ADD(DATE '{mes_ini}', INTERVAL 1 MONTH)
          AND USER_TEAM_LEADER_LDAP IS NOT NULL
        ORDER BY 1 LIMIT 500
    """, max_rows=500)
    return {r["rep"].strip(): r["lider"].strip() for r in rows}

def publi_lider_of(rep):
    """Fallback estático para Publicações."""
    bk = "aldmelo,gbmontilha,blvicente,camcsilva,polivdaraujo,vdpiedade,fenunes,kroza,lecandido,czago,leibarcelos,maybalazshaz".split(",")
    ac = "stdiniz,cafarias,aaugustinho,lyalves,losouza,lianadsilva,phegoncalves,uizfsilva,marlaraujo,vfarias".split(",")
    th = "amcaldeira,kperrone,jamonteiro,marfreitas,cchimenez,ulissouza,casbarreiros,bemarques,acruz".split(",")
    is_ = "mrmarques,vfonorio,amcandido,mandoliveira,renataperei,mfvieira,elaoliveira,mariasilva,ccnnasciment,cccsousa".split(",")
    if rep in bk: return "bkaroline"
    if rep in ac: return "alicarvalho"
    if rep in th: return "thaidossanto"
    if rep in is_: return "isabmot"
    return "lrossetto"

# ---- data extraction -------------------------------------------------------
def get_kpis(queue_name, mes_ini, meta_chat, meta_c2c, meta_global):
    rows = bq_csv(f"""
        SELECT USER_TEAM_CHANNEL AS canal,
            SUM(NUMERATOR_VALUE)/NULLIF(SUM(DENOMINATOR_VALUE),0)/60 AS tmo,
            SUM(DENOMINATOR_VALUE) AS vol
        FROM `meli-bi-data.SBOX_CX_BI_ADS_CORE.CONSOLIDADO_KPI_LDAP`
        WHERE USER_TEAM_NAME='{queue_name}' AND KPI_NAME='TMO'
          AND TIME_WINDOW='MONTH_ID' AND CS_CENTER='BR' AND DTTM_ID='{mes_ini}'
        GROUP BY 1 ORDER BY vol DESC
    """)
    canais = {r["canal"]: {"tmo": fmt(r["tmo"]), "vol": int(float(r.get("vol",0)))} for r in rows}
    chat = canais.get("MULTICANAL CHAT", {"tmo": 0, "vol": 0})
    c2c  = canais.get("MULTICANAL C2C",  {"tmo": 0, "vol": 0})
    total_vol = chat["vol"] + c2c["vol"]
    tmo_global = (chat["tmo"]*chat["vol"] + c2c["tmo"]*c2c["vol"]) / max(total_vol, 1)
    tmo_global = round(tmo_global, 2)
    desvio = round(tmo_global - meta_global, 2)
    pct = round(abs(desvio) / max(meta_global, 0.01) * 100, 1)
    reps_row = bq_csv(f"""
        SELECT COUNT(DISTINCT USER_LDAP) AS reps
        FROM `meli-bi-data.SBOX_CX_BI_ADS_CORE.CONSOLIDADO_KPI_LDAP`
        WHERE USER_TEAM_NAME='{queue_name}' AND KPI_NAME='TMO'
          AND TIME_WINDOW='MONTH_ID' AND CS_CENTER='BR' AND DTTM_ID='{mes_ini}'
    """)
    reps = int(float(reps_row[0]["reps"])) if reps_row else 0
    return chat, c2c, tmo_global, total_vol, reps, desvio, pct

def get_lider_data_js(queue_name, mes_ini, lider_map):
    rows = bq_csv(f"""
        SELECT USER_TEAM_CHANNEL AS canal, USER_LDAP AS rep,
            SUM(NUMERATOR_VALUE)/NULLIF(SUM(DENOMINATOR_VALUE),0)/60 AS tmo
        FROM `meli-bi-data.SBOX_CX_BI_ADS_CORE.CONSOLIDADO_KPI_LDAP`
        WHERE USER_TEAM_NAME='{queue_name}' AND KPI_NAME='TMO'
          AND TIME_WINDOW='MONTH_ID' AND CS_CENTER='BR' AND DTTM_ID='{mes_ini}'
        GROUP BY 1,2
    """)
    lider_sum = {}
    for r in rows:
        rep = r["rep"]
        l = lider_map.get(rep) or publi_lider_of(rep)
        c = r["canal"]
        key = f"{l}|{c}"
        if key not in lider_sum:
            lider_sum[key] = {"lider": l, "canal": c, "sum": 0, "n": 0}
        lider_sum[key]["sum"] += fmt(r["tmo"])
        lider_sum[key]["n"] += 1
    result = sorted(
        [{"l": v["lider"] + (" C2C" if "C2C" in v["canal"] else ""),
          "t": round(v["sum"] / v["n"], 2)}
         for v in lider_sum.values()],
        key=lambda x: -x["t"]
    )
    return result

def get_quartil_data_js(queue_name, mes_ini, lider_map, meta_chat, meta_c2c):
    rows = bq_csv(f"""
        WITH base AS (
            SELECT USER_LDAP AS rep, USER_TEAM_CHANNEL AS canal,
                SUM(NUMERATOR_VALUE)/NULLIF(SUM(DENOMINATOR_VALUE),0)/60 AS tmo,
                SUM(DENOMINATOR_VALUE) AS vol, KM_STATUS AS seniority
            FROM `meli-bi-data.SBOX_CX_BI_ADS_CORE.CONSOLIDADO_KPI_LDAP`
            WHERE USER_TEAM_NAME='{queue_name}' AND KPI_NAME='TMO'
              AND TIME_WINDOW='MONTH_ID' AND CS_CENTER='BR' AND DTTM_ID='{mes_ini}'
            GROUP BY 1,2,5
        ), q AS (
            SELECT *, CONCAT("Q", CAST(NTILE(4) OVER (PARTITION BY canal ORDER BY tmo ASC) AS STRING)) AS quartil
            FROM base
        )
        SELECT quartil, rep, canal, ROUND(tmo,2) AS tmo, CAST(vol AS INT64) AS vol, seniority
        FROM q ORDER BY canal, quartil, tmo
    """, max_rows=500)
    lines = []
    for r in rows:
        rep = r["rep"]
        l = lider_map.get(rep) or publi_lider_of(rep)
        meta = meta_c2c if "C2C" in r["canal"] else meta_chat
        dev = round(fmt(r["tmo"]) - meta, 2)
        sen = r.get("seniority","EXPERT").strip()
        lines.append(f"  {{q:'{r['quartil']}',rep:'{rep}',lider:'{l}',seniority:'{sen}',canal:'{r['canal']}',vol:{r['vol']},tmo:{r['tmo']},dev:{dev}}},")
    return "\n".join(lines)

def get_processo_data_js(queue_name, mes_ini, meta_chat, meta_c2c):
    rows = bq_csv(f"""
        SELECT USER_TEAM_CHANNEL AS canal, ASSIGN_PROCESS_NAME AS proc,
            COUNT(*) AS vol, ROUND(AVG(TMO_SEC)/60,2) AS tmo
        FROM `meli-bi-data.WHOWNER.DM_CX_TMO`
        WHERE USER_TEAM_NAME LIKE '%{queue_name.replace("BR_","").split("_Sellers")[0]}%Mature%'
          AND DATE(ASSIGN_DTTM) BETWEEN '{mes_ini}' AND DATE_ADD(DATE '{mes_ini}', INTERVAL 1 MONTH)
          AND FLAG_IS_OUTLIER=FALSE AND FLAG_DROP=FALSE AND FLAG_WITHOUT_AGENT_TOUCH=FALSE
        GROUP BY 1,2 ORDER BY tmo DESC
        LIMIT 50
    """, max_rows=100)
    # Process-level targets: read from targets.json
    proc_targets = TARGETS.get(queue_name, {}).get("processos", {})
    lines = []
    for r in rows:
        key = f"{r['proc']}|{r['canal']}"
        meta = proc_targets.get(key, meta_chat if "CHAT" in r["canal"] else meta_c2c)
        dev = round(fmt(r["tmo"]) - meta, 2)
        proc = r["proc"].replace("'", "\\'")
        lines.append(f"  {{proc:'{proc}',canal:'{r['canal']}',vol:{r['vol']},tmo:{r['tmo']},meta:{meta},dev:{dev},min:0,max:0}},")
    return "\n".join(lines)

def get_semanal_data_js(queue_name, mes_ini, lider_map):
    rows = bq_csv(f"""
        SELECT DATE_TRUNC(DTTM_ID, WEEK(MONDAY)) AS semana,
            USER_LDAP AS rep, USER_TEAM_CHANNEL AS canal,
            SUM(NUMERATOR_VALUE)/NULLIF(SUM(DENOMINATOR_VALUE),0)/60 AS tmo
        FROM `meli-bi-data.SBOX_CX_BI_ADS_CORE.CONSOLIDADO_KPI_LDAP`
        WHERE USER_TEAM_NAME='{queue_name}' AND KPI_NAME='TMO'
          AND TIME_WINDOW='WEEK_ID' AND CS_CENTER='BR'
          AND DTTM_ID BETWEEN '{mes_ini}' AND DATE_ADD(DATE '{mes_ini}', INTERVAL 1 MONTH)
        GROUP BY 1,2,3 ORDER BY rep, semana
    """, max_rows=1000)
    lines = []
    for r in rows:
        rep = r["rep"]
        l = lider_map.get(rep) or publi_lider_of(rep)
        lines.append(f"  ['{rep}','{l}','{r['canal']}','{r['semana']}',{round(fmt(r['tmo']),2)}],")
    return "\n".join(lines)

def get_prod_rep_data_js(queue_name, mes_ini, lider_map):
    """TMO produtivo/NP por rep."""
    rows = bq_csv(f"""
        SELECT USER_LDAP AS rep, USER_TEAM_CHANNEL AS canal,
            ROUND(SUM(CASE WHEN KPI_NAME='TMO' THEN NUMERATOR_VALUE END)/NULLIF(SUM(CASE WHEN KPI_NAME='TMO' THEN DENOMINATOR_VALUE END),0)/60,2) AS tmo,
            ROUND(SUM(CASE WHEN KPI_NAME='CONVERSATION_DURATION_SEC' THEN NUMERATOR_VALUE END)/NULLIF(SUM(CASE WHEN KPI_NAME='CONVERSATION_DURATION_SEC' THEN DENOMINATOR_VALUE END),0)/60,2) AS conv,
            ROUND(SUM(CASE WHEN KPI_NAME='POST_CONVERSATION_DURATION_SEC' THEN NUMERATOR_VALUE END)/NULLIF(SUM(CASE WHEN KPI_NAME='POST_CONVERSATION_DURATION_SEC' THEN DENOMINATOR_VALUE END),0)/60,2) AS acw
        FROM `meli-bi-data.SBOX_CX_BI_ADS_CORE.CONSOLIDADO_KPI_LDAP`
        WHERE USER_TEAM_NAME='{queue_name}'
          AND KPI_NAME IN ('TMO','CONVERSATION_DURATION_SEC','POST_CONVERSATION_DURATION_SEC')
          AND TIME_WINDOW='MONTH_ID' AND CS_CENTER='BR' AND DTTM_ID='{mes_ini}'
        GROUP BY 1,2 ORDER BY canal, tmo DESC
    """, max_rows=500)
    lines = []
    for r in rows:
        rep = r["rep"]
        l = lider_map.get(rep) or publi_lider_of(rep)
        tmo = fmt(r.get("tmo",0)); conv = fmt(r.get("conv",0))
        np_ = round(tmo - conv, 2); acw = fmt(r.get("acw",0))
        lines.append(f"  {{rep:'{rep}',lider:'{l}',canal:'{r['canal']}',assigns:0,tmo:{tmo},prod:{conv},np:{np_},hold:0,acw:{acw}}},")
    return "\n".join(lines)

def get_produ_rep_data_js(queue_name, mes_ini, lider_map):
    """Produtividade por rep."""
    rows = bq_csv(f"""
        SELECT USER_LDAP AS rep, USER_TEAM_CHANNEL AS canal,
            ROUND(SUM(NUMERATOR_PRODU)/NULLIF(SUM(DENOMINATOR_PRODU),0),2) AS produ
        FROM `meli-bi-data.WHOWNER.BT_CX_REP_PRODUCTIVITY`
        WHERE USER_TEAM_NAME='{queue_name}'
          AND DATE_ID BETWEEN '{mes_ini}' AND DATE_ADD(DATE '{mes_ini}', INTERVAL 1 MONTH)
          AND DENOMINATOR_PRODU>0
        GROUP BY 1,2 ORDER BY canal, produ DESC
    """, max_rows=500)
    tmo_rows = bq_csv(f"""
        SELECT USER_LDAP AS rep, USER_TEAM_CHANNEL AS canal,
            SUM(NUMERATOR_VALUE)/NULLIF(SUM(DENOMINATOR_VALUE),0)/60 AS tmo
        FROM `meli-bi-data.SBOX_CX_BI_ADS_CORE.CONSOLIDADO_KPI_LDAP`
        WHERE USER_TEAM_NAME='{queue_name}' AND KPI_NAME='TMO'
          AND TIME_WINDOW='MONTH_ID' AND CS_CENTER='BR' AND DTTM_ID='{mes_ini}'
        GROUP BY 1,2
    """, max_rows=500)
    tmo_map = {f"{r['rep']}|{r['canal']}": fmt(r["tmo"]) for r in tmo_rows}
    lines = []
    for r in rows:
        rep = r["rep"]
        l = lider_map.get(rep) or publi_lider_of(rep)
        tmo = tmo_map.get(f"{rep}|{r['canal']}", 0)
        lines.append(f"  {{rep:'{rep}',lider:'{l}',canal:'{r['canal']}',produ:{fmt(r['produ'])},tmo:{tmo}}},")
    return "\n".join(lines)

def get_toque_rep_data_js(queue_name, mes_ini, lider_map):
    """Toque (touch time) por rep — DM_CX_TMO."""
    team_filter = queue_name.replace("BR_","").split("_Sellers")[0]
    rows = bq_csv(f"""
        SELECT USER_LDAP AS rep, USER_TEAM_CHANNEL AS canal,
            COUNT(*) AS assigns,
            ROUND(AVG(TOUCH_TIME_SEC)/60,2) AS toque,
            ROUND(MAX(TOUCH_TIME_SEC)/60,2) AS toqueMax,
            ROUND(AVG(TMO_SEC)/60,2) AS tmo
        FROM `meli-bi-data.WHOWNER.DM_CX_TMO`
        WHERE USER_TEAM_NAME LIKE '%{team_filter}%Mature%'
          AND DATE(ASSIGN_DTTM) BETWEEN '{mes_ini}' AND DATE_ADD(DATE '{mes_ini}', INTERVAL 1 MONTH)
          AND FLAG_IS_OUTLIER=FALSE AND FLAG_DROP=FALSE AND FLAG_WITHOUT_AGENT_TOUCH=FALSE
        GROUP BY 1,2 ORDER BY toque DESC
    """, max_rows=500)
    lines = []
    for r in rows:
        rep = r["rep"]
        l = lider_map.get(rep) or publi_lider_of(rep)
        lines.append(f"  {{rep:'{rep}',lider:'{l}',canal:'{r['canal']}',assigns:{r['assigns']},toque:{r['toque']},toqueMax:{r['toqueMax']},tmo:{r['tmo']}}},")
    return "\n".join(lines)

def compute_stats(prod_js, produ_js, toque_js, mes_label):
    """Calcula os campos do STATS a partir dos dados já gerados."""
    import re as re2
    def parse_js(txt):
        out = []
        for line in txt.splitlines():
            line = line.strip().rstrip(",")
            if not line.startswith("{"): continue
            d = {}
            for m in re2.finditer(r"(\w+):(['\"]?)([^,'\"{}]+)\2", line):
                d[m.group(1)] = m.group(3).strip()
            out.append(d)
        return out

    def fnum(v):
        try: return float(v)
        except: return 0.0

    prod = parse_js(prod_js)
    produ = parse_js(produ_js)
    toque = parse_js(toque_js)

    # Toque stats
    t_chat = [r for r in toque if "CHAT" in r.get("canal","")]
    t_c2c  = [r for r in toque if "C2C" in r.get("canal","")]
    mc2c   = round(sum(fnum(r["toque"]) for r in t_c2c) / max(len(t_c2c),1), 2)
    mchat  = round(sum(fnum(r["toque"]) for r in t_chat) / max(len(t_chat),1), 2)
    tmax   = max((fnum(r["toqueMax"]) for r in toque), default=0)
    tmax_rep = (max(toque, key=lambda r: fnum(r["toqueMax"]), default={}).get("rep","—"))
    casos_alto = sum(1 for r in toque if fnum(r["toque"]) > 20)
    chat_vol = sum(int(r.get("assigns","0")) for r in t_chat)
    c2c_vol  = sum(int(r.get("assigns","0")) for r in t_c2c)

    # Produtividade stats
    p_chat = [r for r in produ if "CHAT" in r.get("canal","")]
    p_c2c  = [r for r in produ if "C2C" in r.get("canal","")]
    pg = round(sum(fnum(r["produ"]) for r in produ) / max(len(produ),1), 2)
    pc = round(sum(fnum(r["produ"]) for r in p_chat) / max(len(p_chat),1), 2)
    p2 = round(sum(fnum(r["produ"]) for r in p_c2c) / max(len(p_c2c),1), 2)
    best  = max(produ, key=lambda r: fnum(r["produ"]), default={})
    worst = min(produ, key=lambda r: fnum(r["produ"]), default={})

    # TMO produtivo/NP
    pd_chat = [r for r in prod if "CHAT" in r.get("canal","")]
    pd_c2c  = [r for r in prod if "C2C" in r.get("canal","")]
    pt_cp = round(sum(fnum(r["prod"]) for r in pd_chat) / max(len(pd_chat),1), 2)
    pt_2p = round(sum(fnum(r["prod"]) for r in pd_c2c) / max(len(pd_c2c),1), 2)
    pt_cn = round(sum(fnum(r["np"])   for r in pd_chat) / max(len(pd_chat),1), 2)
    pt_2n = round(sum(fnum(r["np"])   for r in pd_c2c) / max(len(pd_c2c),1), 2)

    # Prodtime by lider+canal
    from collections import defaultdict
    pt = defaultdict(lambda: {"n":0,"t":0,"p":0,"np":0,"h":0,"a":0})
    for r in prod:
        k = (r.get("lider","—"), r.get("canal",""))
        pt[k]["n"]  += 1
        pt[k]["t"]  += fnum(r["tmo"])
        pt[k]["p"]  += fnum(r["prod"])
        pt[k]["np"] += fnum(r["np"])
        pt[k]["h"]  += fnum(r["hold"])
        pt[k]["a"]  += fnum(r["acw"])
    prodtime_lines = []
    for (lider,canal),v in sorted(pt.items(), key=lambda x: -x[1]["t"]/max(x[1]["n"],1)):
        n = v["n"]
        prodtime_lines.append(
            "      {lider:'%s',canal:'%s',reps:%d,assigns:0,tmo:%.2f,prod:%.2f,np:%.2f,hold:%.2f,acw:%.2f}," % (
                lider,canal,n,v["t"]/n,v["p"]/n,v["np"]/n,v["h"]/n,v["a"]/n
            )
        )
    prodtime_js = "\n".join(prodtime_lines)

    return {
        "label": mes_label,
        "toque_mc2c": mc2c, "toque_chat": mchat,
        "toque_casos_alto": casos_alto, "toque_max": int(tmax),
        "toque_max_rep": tmax_rep,
        "toque_chat_vol": f"{chat_vol:,}".replace(",","."),
        "toque_c2c_vol": f"{c2c_vol:,}".replace(",","."),
        "produ_geral": pg, "produ_chat": pc, "produ_chat_reps": len(p_chat),
        "produ_c2c": p2, "produ_c2c_reps": len(p_c2c),
        "produ_best": fnum(best.get("produ",0)),
        "produ_best_sub": f"{best.get('rep','—')} · {best.get('canal','').replace('MULTICANAL ','')} · {best.get('lider','—')}",
        "produ_worst": fnum(worst.get("produ",0)),
        "produ_worst_sub": f"{worst.get('rep','—')} · {worst.get('canal','').replace('MULTICANAL ','')} · {worst.get('lider','—')}",
        "pt_chat_prod": pt_cp, "pt_c2c_prod": pt_2p,
        "pt_chat_np": pt_cn, "pt_c2c_np": pt_2n,
        "prodtime_js": prodtime_js,
    }

def build_stats_entry(s, nps_canal_js="", nps_insight=""):
    return f"""    label: '{s["label"]}',
    toque_mc2c: {s["toque_mc2c"]}, toque_chat: {s["toque_chat"]}, toque_casos_alto: {s["toque_casos_alto"]}, toque_max: {s["toque_max"]}, toque_max_rep: '{s["toque_max_rep"]}',
    toque_chat_vol: '{s["toque_chat_vol"]}', toque_c2c_vol: '{s["toque_c2c_vol"]}',
    produ_geral: {s["produ_geral"]}, produ_chat: {s["produ_chat"]}, produ_chat_reps: {s["produ_chat_reps"]},
    produ_c2c: {s["produ_c2c"]}, produ_c2c_reps: {s["produ_c2c_reps"]},
    produ_best: {s["produ_best"]}, produ_best_sub: '{s["produ_best_sub"]}',
    produ_worst: {s["produ_worst"]}, produ_worst_sub: '{s["produ_worst_sub"]}',
    pt_chat_prod: {s["pt_chat_prod"]}, pt_c2c_prod: {s["pt_c2c_prod"]}, pt_chat_np: {s["pt_chat_np"]}, pt_c2c_np: {s["pt_c2c_np"]},
    prodtime: [
{s["prodtime_js"]}
    ],
    nps_canal: [{nps_canal_js}],
    nps_insight: '{nps_insight}',"""

# ---- main ------------------------------------------------------------------
def main():
    today = date.today()
    mes_ini = today.replace(day=1).isoformat()
    mes_label = today.strftime("%B %Y").capitalize()
    mes_key = today.strftime("%Y-%m")
    partial = today.day < 25

    print(f"\n{'='*60}")
    print(f"[{datetime.now():%H:%M:%S}] Atualizando dashboard — {mes_label}")
    print(f"  Mês ativo: {mes_key} | Parcial: {partial}")
    print(f"{'='*60}")

    html = read_html()

    for q_key, q_cfg in QUEUES.items():
        queue_name = q_cfg["name"]
        prefix = q_cfg["js_prefix"]
        tgt = TARGETS.get(queue_name, {"chat":27.54,"c2c":19.73,"global":26.0})
        meta_chat, meta_c2c, meta_global = tgt["chat"], tgt.get("c2c") or tgt["chat"], tgt["global"]
        label_fila = q_cfg.get("label", q_key)

        print(f"\n[{q_key.upper()}] {queue_name}")

        # Lider map
        print(f"  Buscando líderes...")
        lider_map = get_lider_map(queue_name, mes_ini)
        print(f"  {len(lider_map)} reps mapeados")

        # KPIs
        print(f"  [1/7] KPIs gerais...")
        chat, c2c, tmo_g, vol, reps, desvio, pct = get_kpis(
            queue_name, mes_ini, meta_chat, meta_c2c, meta_global
        )

        # Atualizar KPIS object
        kpi_entry = (f"tmo:{tmo_g}, tmoCaso:null, volume:{vol}, reps:{reps}, "
                     f"desvio:{desvio}, pct:{pct}, label:'{mes_label} {label_fila}', partial:{str(partial).lower()}")
        html = replace_js_month_in_obj(html, q_cfg["js_kpis"], mes_key, kpi_entry)

        # Atualizar CANAL_DATA
        canal_entry = (f"[{{c:'MULTICANAL CHAT',v:{chat['vol']},t:{chat['tmo']},"
                       f"d:{round(chat['tmo']-meta_chat,2)}}},{{c:'MULTICANAL C2C',v:{c2c['vol']},"
                       f"t:{c2c['tmo']},d:{round(c2c['tmo']-meta_c2c,2)}}}]")
        # Substituir dentro do objeto de canal
        obj_start = html.find(f"const {q_cfg['js_canal']} = {{")
        if obj_start != -1:
            obj_end = html.find("\n};", obj_start) + 3
            obj_text = html[obj_start:obj_end]
            new_obj = re.sub(
                rf"('{re.escape(mes_key)}': )\[.*?\]",
                lambda m: m.group(1) + canal_entry,
                obj_text, flags=re.DOTALL
            )
            html = html[:obj_start] + new_obj + html[obj_end:]

        # Lider data
        print(f"  [2/7] Dados por líder...")
        lider_list = get_lider_data_js(queue_name, mes_ini, lider_map)
        lider_entry = "".join([f"{{l:'{i['l']}',t:{i['t']}}}," for i in lider_list])
        obj_start = html.find(f"const {q_cfg['js_lider']} = {{")
        if obj_start != -1:
            obj_end = html.find("\n};", obj_start) + 3
            obj_text = html[obj_start:obj_end]
            new_obj = re.sub(
                rf"('{re.escape(mes_key)}': \[).*?(\])",
                lambda m: m.group(1) + lider_entry + m.group(2),
                obj_text, flags=re.DOTALL
            )
            html = html[:obj_start] + new_obj + html[obj_end:]

        # Quartilização
        print(f"  [3/7] Quartilização...")
        quartil_js = get_quartil_data_js(queue_name, mes_ini, lider_map, meta_chat, meta_c2c)
        html = replace_js_array(html, f"{prefix}quartilData", quartil_js)

        # Processo
        print(f"  [4/7] TMO por processo...")
        proc_js = get_processo_data_js(queue_name, mes_ini, meta_chat, meta_c2c)
        html = replace_js_array(html, f"{prefix}processoData", proc_js)

        # Semanal
        print(f"  [5/7] Dados semanais...")
        semanal_js = get_semanal_data_js(queue_name, mes_ini, lider_map)
        if q_key == "publi":
            # Para publi: preservar entradas de outros meses, substituir apenas o mês atual
            # Extrair conteúdo atual do semanalRaw, remover entradas do mes_key, adicionar novas
            m_arr = re.search(r"const semanalRaw = \[(.*?)\];", html, re.DOTALL)
            if m_arr:
                old_content = m_arr.group(1)
                # Remover linhas do mês atual
                clean = re.sub(
                    rf"\s*\['{re.escape(mes_key)}-[^']*'[^\]]*\],?",
                    "", old_content
                )
                new_content = clean.rstrip(",\n") + "\n" + semanal_js
                html = html[:m_arr.start()] + f"const semanalRaw = [\n{new_content}\n];" + html[m_arr.end():]
        else:
            html = replace_js_array(html, f"{prefix}semanalRaw", semanal_js)

        # Produtivo/NP
        print(f"  [6/7] TMO produtivo/NP...")
        prod_js = get_prod_rep_data_js(queue_name, mes_ini, lider_map)
        html = replace_js_array(html, f"{prefix}prodRepData", prod_js)

        # Produtividade
        print(f"  [7/7] Produtividade...")
        produ_js = get_produ_rep_data_js(queue_name, mes_ini, lider_map)
        html = replace_js_array(html, f"{prefix}produRepData", produ_js)

        # Toque (DM_CX_TMO)
        print(f"  [+] Toque...")
        toque_js = get_toque_rep_data_js(queue_name, mes_ini, lider_map)
        html = replace_js_array(html, f"{prefix}toqueRepData", toque_js)

        # STATS
        print(f"  [+] STATS...")
        stats_varname = {"publi":"STATS","ventas":"VENTAS_STATS","me":"ME_STATS","melipro":"MELIPRO_STATS","vip":"VIP_STATS"}.get(q_key,"STATS")
        s = compute_stats(prod_js, produ_js, toque_js, f"{mes_label} {label_fila}")
        s["label"] = f"{mes_label} · {label_fila}" + (" ⚡ (parcial)" if partial else "")
        nps_insight = "" if q_key != "publi" else f"Dados de {mes_label}: TMO {tmo_g} min"
        stats_entry = build_stats_entry(s, "", nps_insight)
        html = replace_stats_month(html, stats_varname, mes_key, stats_entry)

        print(f"  OK {label_fila}: TMO {tmo_g} min / {vol} contatos / {reps} reps")

    # ---- Targets no JS -------------------------------------------------------
    print("\n[TARGETS] Atualizando FILAS_META no HTML...")
    for q_key, q_cfg in QUEUES.items():
        tgt = TARGETS[q_cfg["name"]]
        old_pat = rf"({q_key}:\s*\{{chat:)[\d.]+,(?: c2c:)[\d.]+"
        new_val = f"{q_key}: {{chat:{tgt['chat']}, c2c:{tgt['c2c']}"
        html = re.sub(old_pat, new_val, html)

    # ---- HTML write ----------------------------------------------------------
    write_html(html)
    print("\n  HTML atualizado com sucesso.")

    # ---- Git commit + push ---------------------------------------------------
    print("\n[GIT] Publicando...")
    msg = f"Auto-update {mes_key}: {datetime.now():%Y-%m-%d %H:%M} — Publi/Vendas/ME"
    subprocess.run(["git", "-C", REPO, "add", "index.html"], check=True)
    result = subprocess.run(["git", "-C", REPO, "diff", "--cached", "--quiet"])
    if result.returncode == 0:
        print("  Sem alterações para commitar.")
    else:
        subprocess.run(["git", "-C", REPO, "commit", "-m", msg], check=True)
        subprocess.run(["git", "-C", REPO, "push"], check=True)
        print(f"  Publicado: {msg}")

    print(f"\n[{datetime.now():%H:%M:%S}] Atualização concluída.")
    print(f"  https://alinecarvalhop.github.io/tmo-dashboard-abril2026")

if __name__ == "__main__":
    main()
