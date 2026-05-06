#!/usr/bin/env python3
"""
atualizar_dashboard.py
Atualiza automaticamente o dashboard TMO com dados do BigQuery.
Executa via Windows Task Scheduler diariamente.
"""
import subprocess, json, re, sys
from datetime import date, datetime

QUEUE = "BR_Publicaciones_Sellers_Mature"
META  = 27
REPO  = r"C:\Users\alicarvalho\tmo-dashboard-abril2026"

def bq(sql):
    r = subprocess.run(
        ["bq", "query", "--use_legacy_sql=false", "--format=json", sql],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        print("ERRO BQ:", r.stderr); sys.exit(1)
    return json.loads(r.stdout) if r.stdout.strip() else []

def fmt(v, dec=2):
    try: return round(float(v), dec)
    except: return 0

today    = date.today()
mes_ini  = today.replace(day=1).isoformat()
mes_fim  = today.isoformat()
mes_key  = today.strftime("%Y-%m")
mes_lbl  = today.strftime("%B %Y").capitalize()
partial  = True
is_last_day = (today.replace(month=today.month % 12 + 1, day=1) - __import__('datetime').timedelta(days=1)).day == today.day if today.month < 12 else today.day == 31

print(f"[{datetime.now():%H:%M:%S}] Consultando BigQuery para {mes_key} ({mes_ini} → {mes_fim})...")

# ── KPIs gerais ──────────────────────────────────────────────────────────────
kpi_rows = bq(f"""
SELECT COUNT(*) AS vol,
  ROUND(AVG(TMO_SEC)/60,2) AS tmo,
  COUNT(DISTINCT USER_LDAP) AS reps
FROM `meli-bi-data.WHOWNER.DM_CX_TMO`
WHERE USER_TEAM_NAME="{QUEUE}"
  AND DATE(ASSIGN_DTTM) BETWEEN "{mes_ini}" AND "{mes_fim}"
  AND FLAG_IS_OUTLIER=FALSE AND FLAG_DROP=FALSE AND FLAG_WITHOUT_AGENT_TOUCH=FALSE
""")
kpi = kpi_rows[0] if kpi_rows else {}
tmo   = fmt(kpi.get('tmo', 0))
vol   = int(kpi.get('vol', 0))
reps  = int(kpi.get('reps', 0))
desvio = round(tmo - META, 2)
pct    = round(abs(desvio) / META * 100, 1)

# ── Por canal ────────────────────────────────────────────────────────────────
canal_rows = bq(f"""
SELECT USER_TEAM_CHANNEL AS c, COUNT(*) AS v, ROUND(AVG(TMO_SEC)/60,2) AS t
FROM `meli-bi-data.WHOWNER.DM_CX_TMO`
WHERE USER_TEAM_NAME="{QUEUE}"
  AND DATE(ASSIGN_DTTM) BETWEEN "{mes_ini}" AND "{mes_fim}"
  AND FLAG_IS_OUTLIER=FALSE AND FLAG_DROP=FALSE AND FLAG_WITHOUT_AGENT_TOUCH=FALSE
GROUP BY 1 ORDER BY v DESC
""")
canal_js = "[" + ",".join(
    f"{{c:'{r['c']}',v:{r['v']},t:{fmt(r['t'])},d:{round(fmt(r['t'])-META,2)}}}"
    for r in canal_rows
) + "]"

# ── Por líder ────────────────────────────────────────────────────────────────
lider_rows = bq(f"""
SELECT USER_TEAM_LEADER_LDAP AS l, ROUND(AVG(TMO_SEC)/60,2) AS t
FROM `meli-bi-data.WHOWNER.DM_CX_TMO`
WHERE USER_TEAM_NAME="{QUEUE}"
  AND DATE(ASSIGN_DTTM) BETWEEN "{mes_ini}" AND "{mes_fim}"
  AND FLAG_IS_OUTLIER=FALSE AND FLAG_DROP=FALSE AND FLAG_WITHOUT_AGENT_TOUCH=FALSE
  AND USER_TEAM_CHANNEL='MULTICANAL CHAT'
GROUP BY 1 ORDER BY t DESC
""")
lider_js = "[" + ",".join(f"{{l:'{r['l']}',t:{fmt(r['t'])}}}" for r in lider_rows) + "]"

# ── Quartilização ─────────────────────────────────────────────────────────────
quartil_rows = bq(f"""
WITH base AS (
  SELECT USER_LDAP AS rep, USER_TEAM_CHANNEL AS canal, USER_TEAM_LEADER_LDAP AS lider,
    COUNT(*) AS vol, ROUND(AVG(TMO_SEC)/60,2) AS tmo
  FROM `meli-bi-data.WHOWNER.DM_CX_TMO`
  WHERE USER_TEAM_NAME="{QUEUE}"
    AND DATE(ASSIGN_DTTM) BETWEEN "{mes_ini}" AND "{mes_fim}"
    AND FLAG_IS_OUTLIER=FALSE AND FLAG_DROP=FALSE AND FLAG_WITHOUT_AGENT_TOUCH=FALSE
  GROUP BY 1,2,3
), q AS (
  SELECT *, CONCAT('Q', CAST(NTILE(4) OVER (PARTITION BY canal ORDER BY tmo ASC) AS STRING)) AS q
  FROM base
)
SELECT q, rep, lider, canal, vol, tmo FROM q ORDER BY canal, tmo
""")
def qrow(r):
    return (f"{{q:'{r['q']}',rep:'{r['rep']}',lider:'{r['lider']}',"
            f"canal:'{r['canal']}',vol:{r['vol']},tmo:{fmt(r['tmo'])},"
            f"dev:{round(fmt(r['tmo'])-META,2)}}}")
quartil_js = "[" + ",".join(qrow(r) for r in quartil_rows) + "]"

# ── Por processo ──────────────────────────────────────────────────────────────
proc_rows = bq(f"""
SELECT ASSIGN_PROCESS_NAME AS proc, USER_TEAM_CHANNEL AS canal,
  COUNT(*) AS vol, ROUND(AVG(TMO_SEC)/60,2) AS tmo
FROM `meli-bi-data.WHOWNER.DM_CX_TMO`
WHERE USER_TEAM_NAME="{QUEUE}"
  AND DATE(ASSIGN_DTTM) BETWEEN "{mes_ini}" AND "{mes_fim}"
  AND FLAG_IS_OUTLIER=FALSE AND FLAG_DROP=FALSE AND FLAG_WITHOUT_AGENT_TOUCH=FALSE
GROUP BY 1,2 ORDER BY tmo DESC
""")
def prow(r):
    return (f"{{proc:'{r['proc']}',canal:'{r['canal']}',vol:{r['vol']},"
            f"tmo:{fmt(r['tmo'])},dev:{round(fmt(r['tmo'])-META,2)},min:0,max:0}}")
proc_js = "[" + ",".join(prow(r) for r in proc_rows) + "]"

# ── Q4 por processo ───────────────────────────────────────────────────────────
q4_rows = bq(f"""
WITH base AS (
  SELECT ASSIGN_PROCESS_NAME AS proc, USER_TEAM_CHANNEL AS canal,
    USER_LDAP AS rep, USER_TEAM_LEADER_LDAP AS lider,
    COUNT(*) AS vol, ROUND(AVG(TMO_SEC)/60,2) AS tmo
  FROM `meli-bi-data.WHOWNER.DM_CX_TMO`
  WHERE USER_TEAM_NAME="{QUEUE}"
    AND DATE(ASSIGN_DTTM) BETWEEN "{mes_ini}" AND "{mes_fim}"
    AND FLAG_IS_OUTLIER=FALSE AND FLAG_DROP=FALSE AND FLAG_WITHOUT_AGENT_TOUCH=FALSE
  GROUP BY 1,2,3,4 HAVING COUNT(*)>=5
), q AS (
  SELECT *, NTILE(4) OVER (PARTITION BY proc, canal ORDER BY tmo ASC) AS q
  FROM base
)
SELECT proc, canal, rep, lider, vol, tmo FROM q WHERE q=4 ORDER BY tmo DESC LIMIT 80
""")
def q4row(r):
    canal_short = r['canal'].replace('MULTICANAL ','')
    return (f"{{proc:'{r['proc']}',canal:'{canal_short}',rep:'{r['rep']}',"
            f"lider:'{r['lider']}',vol:{r['vol']},tmo:{fmt(r['tmo'])},"
            f"dev:{round(fmt(r['tmo'])-META,2)}}}")
q4_js = "[" + ",".join(q4row(r) for r in q4_rows) + "]"

# ── Injetar no HTML ───────────────────────────────────────────────────────────
html_path = REPO + r"\index.html"
with open(html_path, encoding='utf-8') as f:
    html = f.read()

# Atualiza KPIs do mês atual
kpi_block = (
    f"  '{mes_key}': {{tmo:{tmo}, tmoCaso:null, volume:{vol}, reps:{reps}, "
    f"desvio:{desvio}, pct:{pct}, label:'{mes_lbl}', partial:{str(partial).lower()}}}"
)
html = re.sub(
    rf"  '{re.escape(mes_key)}': \{{[^}}]+\}}",
    kpi_block, html
)

# Atualiza dados do canal
html = re.sub(
    rf"  '{re.escape(mes_key)}': \[.*?\](?=\n\}};)",
    f"  '{mes_key}': {canal_js}", html, flags=re.DOTALL, count=1
)

# Atualiza bloco de dados de Maio/mês atual
var_prefix = "MAY" if mes_key == "2026-05" else mes_key.replace("-","_")
for var, data in [
    (f"{var_prefix}_quartilData", quartil_js),
    (f"{var_prefix}_processoData", proc_js),
    (f"{var_prefix}_q4Data", q4_js),
]:
    html = re.sub(
        rf"const {var} = \[.*?\];",
        f"const {var} = {data};",
        html, flags=re.DOTALL
    )

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)

print(f"[{datetime.now():%H:%M:%S}] HTML atualizado — TMO {tmo} min | Vol {vol} | {reps} reps")

# ── Git commit + push ─────────────────────────────────────────────────────────
print(f"[{datetime.now():%H:%M:%S}] Publicando no GitHub...")
msg = f"Auto-update {mes_key}: TMO {tmo}min, {vol} contatos [{today.isoformat()}]"
cmds = [
    ["git", "-C", REPO, "add", "index.html"],
    ["git", "-C", REPO, "commit", "-m", msg],
    ["git", "-C", REPO, "push"],
]
for cmd in cmds:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode not in (0, 1):
        print("AVISO:", r.stderr.strip())

print(f"[{datetime.now():%H:%M:%S}] ✅ Dashboard atualizado e publicado!")
print(f"    🔗 https://alinecarvalhop.github.io/tmo-dashboard-abril2026")
