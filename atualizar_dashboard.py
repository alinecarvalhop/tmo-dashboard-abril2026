#!/usr/bin/env python3
"""
atualizar_dashboard.py — v2.0
Atualiza TODAS as abas do dashboard TMO com dados do HALO pipeline (BigQuery).
Executa via Windows Task Scheduler diariamente às 08:00.
"""
import subprocess, json, re, sys
from datetime import date, datetime, timedelta

QUEUE       = "BR_Publicaciones_Sellers_Mature"
META_CHAT   = 27.54   # target oficial CHAT (grid.adminml.com)
META_C2C    = 19.73   # target oficial C2C (grid.adminml.com)
META_GLOBAL = 26.0    # meta global ponderada
REPO        = r"C:\Users\alicarvalho\tmo-dashboard-abril2026"
HTML        = REPO + r"\index.html"

# ---- helpers ---------------------------------------------------------------
def bq(sql):
    r = subprocess.run(
        ["bq", "query", "--use_legacy_sql=false", "--format=json", "--max_rows=500", sql],
        capture_output=True, text=True, timeout=120
    )
    if r.returncode != 0:
        print(f"ERRO BQ:\n{r.stderr}"); sys.exit(1)
    out = r.stdout.strip()
    if not out or out == "[]":
        return []
    try:
        return json.loads(out)
    except:
        return []

def bq_csv(sql):
    r = subprocess.run(
        ["bq", "query", "--use_legacy_sql=false", "--format=csv", "--max_rows=500", sql],
        capture_output=True, text=True, timeout=120
    )
    if r.returncode != 0:
        print(f"ERRO BQ CSV:\n{r.stderr}")
        return []
    lines = [l for l in r.stdout.strip().splitlines() if l and not l.startswith("Waiting")]
    if len(lines) < 2:
        return []
    header = lines[0].split(",")
    rows = []
    for l in lines[1:]:
        vals = l.split(",")
        rows.append(dict(zip(header, vals)))
    return rows

def fmt(v, dec=2):
    try: return round(float(v), dec)
    except: return 0

def read_html():
    with open(HTML, encoding="utf-8") as f:
        return f.read()

def write_html(html):
    with open(HTML, "w", encoding="utf-8") as f:
        f.write(html)

def replace_js_var(html, varname, new_value):
    """Substitui o valor de uma variável JS inline no HTML."""
    pat = rf"(const {re.escape(varname)} = \[)[^\]]*(\];)"
    m = re.search(pat, html, re.DOTALL)
    if m:
        return html[:m.start()] + f"const {varname} = [\n{new_value}\n];" + html[m.end():]
    print(f"  AVISO: variável {varname} não encontrada no HTML")
    return html

def replace_kpis_object(html, month_key, new_obj):
    """Substitui a entrada do objeto KPIS para o mês."""
    pat = rf"('{re.escape(month_key)}': \{{)[^}}]*(\}})"
    m = re.search(pat, html)
    if m:
        return html[:m.start()] + f"'{month_key}': {{{new_obj}}}" + html[m.end():]
    print(f"  AVISO: KPIS['{month_key}'] não encontrado")
    return html

def lider_of(rep):
    """Mapeamento rep → lider (estático)."""
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
def get_month_kpis(mes_ini, mes_fim):
    """TMO geral, por canal e total."""
    rows = bq_csv(f"""
        SELECT USER_TEAM_CHANNEL AS canal,
            SUM(NUMERATOR_VALUE)/NULLIF(SUM(DENOMINATOR_VALUE),0)/60 AS tmo,
            SUM(DENOMINATOR_VALUE) AS vol
        FROM `meli-bi-data.SBOX_CX_BI_ADS_CORE.CONSOLIDADO_KPI_LDAP`
        WHERE USER_TEAM_NAME="{QUEUE}" AND KPI_NAME="TMO"
          AND TIME_WINDOW="MONTH_ID" AND CS_CENTER="BR"
          AND DTTM_ID="{mes_ini}"
        GROUP BY 1 ORDER BY vol DESC
    """)
    canais = {r["canal"]: {"tmo": fmt(r["tmo"]), "vol": int(float(r.get("vol",0)))} for r in rows}
    chat = canais.get("MULTICANAL CHAT", {"tmo": 0, "vol": 0})
    c2c  = canais.get("MULTICANAL C2C",  {"tmo": 0, "vol": 0})
    total_vol = chat["vol"] + c2c["vol"]
    tmo_global = (chat["tmo"]*chat["vol"] + c2c["tmo"]*c2c["vol"]) / max(total_vol, 1)
    return chat, c2c, round(tmo_global, 2), total_vol

def get_lider_data(mes_ini):
    rows = bq_csv(f"""
        SELECT USER_TEAM_CHANNEL AS canal, USER_LDAP AS rep,
            SUM(NUMERATOR_VALUE)/NULLIF(SUM(DENOMINATOR_VALUE),0)/60 AS tmo
        FROM `meli-bi-data.SBOX_CX_BI_ADS_CORE.CONSOLIDADO_KPI_LDAP`
        WHERE USER_TEAM_NAME="{QUEUE}" AND KPI_NAME="TMO"
          AND TIME_WINDOW="MONTH_ID" AND CS_CENTER="BR" AND DTTM_ID="{mes_ini}"
        GROUP BY 1,2
    """)
    lider_sum = {}
    for r in rows:
        l = lider_of(r["rep"])
        c = r["canal"]
        key = f"{l}|{c}"
        if key not in lider_sum:
            lider_sum[key] = {"lider": l, "canal": c, "sum_tmo": 0, "n": 0}
        lider_sum[key]["sum_tmo"] += fmt(r["tmo"])
        lider_sum[key]["n"] += 1
    result = sorted(
        [{"l": v["lider"] + (" C2C" if "C2C" in v["canal"] else ""),
          "t": round(v["sum_tmo"] / v["n"], 2)}
         for v in lider_sum.values()],
        key=lambda x: -x["t"]
    )
    return result

def get_quartil_data(mes_ini):
    rows = bq_csv(f"""
        WITH base AS (
            SELECT USER_LDAP AS rep, USER_TEAM_CHANNEL AS canal,
                SUM(NUMERATOR_VALUE)/NULLIF(SUM(DENOMINATOR_VALUE),0)/60 AS tmo,
                SUM(DENOMINATOR_VALUE) AS vol
            FROM `meli-bi-data.SBOX_CX_BI_ADS_CORE.CONSOLIDADO_KPI_LDAP`
            WHERE USER_TEAM_NAME="{QUEUE}" AND KPI_NAME="TMO"
              AND TIME_WINDOW="MONTH_ID" AND CS_CENTER="BR" AND DTTM_ID="{mes_ini}"
            GROUP BY 1,2
        ), q AS (
            SELECT *, CONCAT("Q", CAST(NTILE(4) OVER (PARTITION BY canal ORDER BY tmo ASC) AS STRING)) AS quartil
            FROM base
        )
        SELECT quartil, rep, canal, ROUND(tmo,2) AS tmo, CAST(vol AS INT64) AS vol FROM q
        ORDER BY canal, quartil, tmo
    """)
    lines = []
    for r in rows:
        l = lider_of(r["rep"])
        dev = round(fmt(r["tmo"]) - (META_C2C if "C2C" in r["canal"] else META_CHAT), 2)
        lines.append(f"  {{q:'{r['quartil']}',rep:'{r['rep']}',lider:'{l}',canal:'{r['canal']}',vol:{r['vol']},tmo:{r['tmo']},dev:{dev}}},")
    return "\n".join(lines)

def get_processo_data(mes_ini):
    rows = bq_csv(f"""
        SELECT USER_TEAM_CHANNEL AS canal, ASSIGN_PROCESS_NAME AS proc,
            COUNT(*) AS vol,
            ROUND(AVG(TMO_SEC)/60,2) AS tmo
        FROM `meli-bi-data.WHOWNER.DM_CX_TMO`
        WHERE USER_TEAM_NAME="{QUEUE}"
          AND DATE(ASSIGN_DTTM) BETWEEN "{mes_ini}" AND LAST_DAY(DATE("{mes_ini}"))
          AND FLAG_IS_OUTLIER=FALSE AND FLAG_DROP=FALSE AND FLAG_WITHOUT_AGENT_TOUCH=FALSE
        GROUP BY 1,2 ORDER BY tmo DESC
    """)
    # Tabela de metas por processo
    META_PROC = {
        "Reputación|MULTICANAL CHAT": 38.17, "Reputación|MULTICANAL C2C": 20.08,
        "Gestión de Publicación|MULTICANAL CHAT": 40.92, "Gestión de Publicación|MULTICANAL C2C": 20.63,
        "Reputación ME|MULTICANAL CHAT": 38.47, "Reputación ME|MULTICANAL C2C": 22.73,
        "Potenciar Ventas|MULTICANAL CHAT": 41.58, "Potenciar Ventas|MULTICANAL C2C": 22.38,
        "PR - Propiedad intelectual|MULTICANAL CHAT": 41.73, "PR - Propiedad intelectual|MULTICANAL C2C": 24.03,
        "PR - Técnica prohibida|MULTICANAL CHAT": 39.07, "PR - Técnica prohibida|MULTICANAL C2C": 22.65,
        "PR - Artículos prohibidos|MULTICANAL CHAT": 45.73, "PR - Artículos prohibidos|MULTICANAL C2C": 22.18,
        "Antes de publicar|MULTICANAL CHAT": 39.82, "Antes de publicar|MULTICANAL C2C": 19.72,
        "Calidad de foto|MULTICANAL CHAT": 33.22, "Calidad de foto|MULTICANAL C2C": 15.48,
    }
    lines = []
    for r in rows:
        key = f"{r['proc']}|{r['canal']}"
        meta = META_PROC.get(key, META_CHAT if "CHAT" in r["canal"] else META_C2C)
        dev = round(fmt(r["tmo"]) - meta, 2)
        lines.append(f"  {{proc:'{r['proc']}',canal:'{r['canal']}',vol:{r['vol']},tmo:{r['tmo']},meta:{meta},dev:{dev},min:0,max:0}},")
    return "\n".join(lines)

def get_semanal_data(mes_ini):
    year_month = mes_ini[:7]
    rows = bq_csv(f"""
        SELECT DATE_TRUNC(DTTM_ID, WEEK(MONDAY)) AS semana,
            USER_LDAP AS rep, USER_TEAM_CHANNEL AS canal,
            SUM(NUMERATOR_VALUE)/NULLIF(SUM(DENOMINATOR_VALUE),0)/60 AS tmo
        FROM `meli-bi-data.SBOX_CX_BI_ADS_CORE.CONSOLIDADO_KPI_LDAP`
        WHERE USER_TEAM_NAME="{QUEUE}" AND KPI_NAME="TMO"
          AND TIME_WINDOW="WEEK_ID" AND CS_CENTER="BR"
          AND DTTM_ID BETWEEN "{mes_ini}" AND DATE_ADD("{mes_ini}", INTERVAL 1 MONTH)
        GROUP BY 1,2,3 ORDER BY rep, semana
    """)
    lines = []
    for r in rows:
        l = lider_of(r["rep"])
        lines.append(f"  ['{r['rep']}','{l}','{r['canal']}','{r['semana']}',{round(fmt(r['tmo']),2)}],")
    return "\n".join(lines)

def get_prod_rep_data(mes_ini):
    """TMO produtivo (CONVERSATION_DURATION_SEC) e não produtivo por rep."""
    rows = bq_csv(f"""
        SELECT USER_LDAP AS rep, USER_TEAM_CHANNEL AS canal,
            ROUND(SUM(CASE WHEN KPI_NAME='TMO' THEN NUMERATOR_VALUE END)/NULLIF(SUM(CASE WHEN KPI_NAME='TMO' THEN DENOMINATOR_VALUE END),0)/60,2) AS tmo,
            ROUND(SUM(CASE WHEN KPI_NAME='CONVERSATION_DURATION_SEC' THEN NUMERATOR_VALUE END)/NULLIF(SUM(CASE WHEN KPI_NAME='CONVERSATION_DURATION_SEC' THEN DENOMINATOR_VALUE END),0)/60,2) AS conv,
            ROUND(SUM(CASE WHEN KPI_NAME='POST_CONVERSATION_DURATION_SEC' THEN NUMERATOR_VALUE END)/NULLIF(SUM(CASE WHEN KPI_NAME='POST_CONVERSATION_DURATION_SEC' THEN DENOMINATOR_VALUE END),0)/60,2) AS acw
        FROM `meli-bi-data.SBOX_CX_BI_ADS_CORE.CONSOLIDADO_KPI_LDAP`
        WHERE USER_TEAM_NAME="{QUEUE}"
          AND KPI_NAME IN ("TMO","CONVERSATION_DURATION_SEC","POST_CONVERSATION_DURATION_SEC")
          AND TIME_WINDOW="MONTH_ID" AND CS_CENTER="BR" AND DTTM_ID="{mes_ini}"
        GROUP BY 1,2 ORDER BY canal, tmo DESC
    """)
    lines = []
    for r in rows:
        l = lider_of(r["rep"])
        tmo = fmt(r.get("tmo",0)); conv = fmt(r.get("conv",0))
        np_ = round(tmo - conv, 2); acw = fmt(r.get("acw",0))
        lines.append(f"  {{rep:'{r['rep']}',lider:'{l}',canal:'{r['canal']}',assigns:0,tmo:{tmo},prod:{conv},np:{np_},hold:0,acw:{acw}}},")
    return "\n".join(lines)

def get_produ_rep_data(mes_ini):
    rows = bq_csv(f"""
        SELECT USER_LDAP AS rep, USER_TEAM_CHANNEL AS canal,
            ROUND(SUM(DENOMINATOR_PRODU),2) AS den,
            ROUND(SUM(NUMERATOR_PRODU)/NULLIF(SUM(DENOMINATOR_PRODU),0),2) AS produ
        FROM `meli-bi-data.WHOWNER.BT_CX_REP_PRODUCTIVITY`
        WHERE USER_TEAM_NAME="{QUEUE}" AND DATE_ID BETWEEN "{mes_ini}" AND DATE_ADD("{mes_ini}", INTERVAL 1 MONTH)
          AND DENOMINATOR_PRODU>0
        GROUP BY 1,2 ORDER BY canal, produ DESC
    """)
    # TMO para o mesmo período (precisa de outra query — usa HALO)
    tmo_rows = bq_csv(f"""
        SELECT USER_LDAP AS rep, USER_TEAM_CHANNEL AS canal,
            SUM(NUMERATOR_VALUE)/NULLIF(SUM(DENOMINATOR_VALUE),0)/60 AS tmo
        FROM `meli-bi-data.SBOX_CX_BI_ADS_CORE.CONSOLIDADO_KPI_LDAP`
        WHERE USER_TEAM_NAME="{QUEUE}" AND KPI_NAME="TMO"
          AND TIME_WINDOW="MONTH_ID" AND CS_CENTER="BR" AND DTTM_ID="{mes_ini}"
        GROUP BY 1,2
    """)
    tmo_map = {f"{r['rep']}|{r['canal']}": fmt(r["tmo"]) for r in tmo_rows}
    lines = []
    for r in rows:
        l = lider_of(r["rep"])
        tmo = tmo_map.get(f"{r['rep']}|{r['canal']}", 0)
        lines.append(f"  {{rep:'{r['rep']}',lider:'{l}',canal:'{r['canal']}',produ:{fmt(r['produ'])},tmo:{tmo}}},")
    return "\n".join(lines)

# ---- main ------------------------------------------------------------------
def main():
    today = date.today()
    mes_ini = today.replace(day=1).isoformat()
    mes_label = today.strftime("%B %Y").capitalize()
    is_abril = today.month == 4 and today.year == 2026
    mes_key = today.strftime("%Y-%m")
    js_month_key = f"'{today.year}-{today.month:02d}'"

    print(f"\n{'='*60}")
    print(f"[{datetime.now():%H:%M:%S}] Atualizando dashboard — {mes_label}")
    print(f"{'='*60}")

    # Determinar a chave JS do mês atual
    if today.month == 4 and today.year == 2026:
        print("  Mês de Abril — dados históricos, pulando atualização automática.")
        return

    print(f"  Mês ativo: {mes_key} ({mes_ini})")

    # 1. KPIs
    print("[1/7] Buscando KPIs gerais...")
    chat, c2c, tmo_global, vol_total = get_month_kpis(mes_ini, today.isoformat())
    desvio = round(tmo_global - META_GLOBAL, 2)
    pct = round(abs(desvio) / META_GLOBAL * 100, 1)
    partial = True
    kpi_obj = (f"tmo:{tmo_global}, tmoCaso:null, volume:{vol_total}, reps:51, "
               f"desvio:{desvio}, pct:{pct}, label:'{mes_label}', partial:{str(partial).lower()}")

    # 2. Canal data
    canal_js = (f"[{{c:'MULTICANAL CHAT',v:{chat['vol']},t:{chat['tmo']},"
                f"d:{round(chat['tmo']-META_CHAT,2)}}},{{c:'MULTICANAL C2C',v:{c2c['vol']},"
                f"t:{c2c['tmo']},d:{round(c2c['tmo']-META_C2C,2)}}}]")

    # 3. Lider data
    print("[2/7] Buscando dados por líder...")
    lider_list = get_lider_data(mes_ini)
    lider_js = "[" + ",".join([f"{{l:'{i['l']}',t:{i['t']}}}" for i in lider_list]) + "]"

    # 4. Quartilização
    print("[3/7] Calculando quartilização...")
    quartil_js = get_quartil_data(mes_ini)

    # 5. Processo
    print("[4/7] Buscando TMO por processo...")
    proc_js = get_processo_data(mes_ini)

    # 6. Semanal
    print("[5/7] Buscando dados semanais...")
    semanal_js = get_semanal_data(mes_ini)

    # 7. Produtivo/NP
    print("[6/7] Buscando TMO produtivo/NP...")
    prod_js = get_prod_rep_data(mes_ini)

    # 8. Produtividade
    print("[7/7] Buscando produtividade...")
    produ_js = get_produ_rep_data(mes_ini)

    # ---- Atualizar HTML ----
    print("\n[HTML] Aplicando atualizações...")
    html = read_html()

    # KPIS
    html = replace_kpis_object(html, f"'{mes_key}'", kpi_obj)

    # CANAL_DATA
    html = re.sub(
        rf"('{re.escape(mes_key)}': )\[.*?\](?=\s*[,}}])",
        lambda m: m.group(1) + canal_js,
        html, count=1, flags=re.DOTALL
    )

    # LIDER_DATA
    html = re.sub(
        rf"('{re.escape(mes_key)}': \[)(?:[^\]]*?)(\])",
        lambda m: m.group(1) + "".join([f"{{l:'{i['l']}',t:{i['t']}}}," for i in lider_list]) + m.group(2),
        html, count=1
    )

    # Variáveis MAY_*
    html = replace_js_var(html, "MAY_quartilData", quartil_js)
    html = replace_js_var(html, "MAY_processoData", proc_js)
    html = replace_js_var(html, "MAY_prodRepData", prod_js)
    html = replace_js_var(html, "MAY_produRepData", produ_js)

    # semanalRaw — substituir apenas entradas do mês atual
    semanal_prefix = f"'{mes_key}"
    # Remover entradas antigas do mês atual e adicionar novas
    pat = rf"\s*\['{re.escape(mes_key)}[^]]*\],?\n"
    html_clean = re.sub(pat, "", html)
    # Inserir novas entradas antes do fechamento do array
    html = re.sub(
        r"(  // Maio 2026[^\]]*?\]\n)",
        "  // Auto-gerado\n" + semanal_js + "\n];\n",
        html_clean, flags=re.DOTALL
    ) if semanal_js else html_clean

    write_html(html)
    print("  HTML atualizado com sucesso.")

    # ---- Git commit + push ----
    print("\n[GIT] Publicando...")
    msg = f"Auto-update {mes_key}: TMO {tmo_global}min · {vol_total} contatos [{today.isoformat()}]"
    subprocess.run(["git", "-C", REPO, "add", "index.html"], check=True)
    result = subprocess.run(["git", "-C", REPO, "diff", "--cached", "--quiet"])
    if result.returncode == 0:
        print("  Sem alterações para commitar.")
    else:
        subprocess.run(["git", "-C", REPO, "commit", "-m", msg], check=True)
        subprocess.run(["git", "-C", REPO, "push"], check=True)
        print(f"  ✅ Publicado: {msg}")

    print(f"\n[{datetime.now():%H:%M:%S}] Atualização concluída.")
    print(f"  🔗 https://alinecarvalhop.github.io/tmo-dashboard-abril2026")

if __name__ == "__main__":
    main()
