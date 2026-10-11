"""TW Swing public dashboard — Supabase read-only, GitHub admin dispatch.
Deploy as TW_Swing_WebApp_V1/app.py. No private service role key is needed here.
"""
import hmac
import os
from datetime import datetime, timezone
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title='TW Swing｜台股波段選股',page_icon='📈',layout='wide',initial_sidebar_state='collapsed')
st.markdown('''<style>.block-container{max-width:1150px;padding:1rem;}[data-testid="stMetricValue"]{font-size:1.55rem;}@media(max-width:650px){.block-container{padding:.7rem;}div[data-testid="stHorizontalBlock"]{gap:.4rem;}}</style>''',unsafe_allow_html=True)

def cfg(name):
    try:return str(st.secrets.get(name,'') or '').strip()
    except Exception:return os.getenv(name,'').strip()

URL=cfg('SUPABASE_URL').rstrip('/')
PUBLIC_KEY=cfg('SUPABASE_PUBLISHABLE_KEY')
OWNER=cfg('GITHUB_OWNER') or 'Superpeng999'
REPO=cfg('GITHUB_REPO') or 'TW-Swing'
BRANCH=cfg('GITHUB_BRANCH') or 'main'

@st.cache_data(ttl=180,show_spinner=False)
def read_api(table,query=None,limit=1000):
    if not URL.startswith('https://') or not PUBLIC_KEY:
        return [],'未設定 Supabase 公開讀取金鑰'
    if table not in {'stock_scores','update_runs','institutional_flows','tdcc_holdings'}:
        return [],'未知的資料表'
    headers={'apikey':PUBLIC_KEY,'Accept':'application/json'}
    # Modern sb_publishable_ key goes in apikey, not JWT Authorization.
    if not PUBLIC_KEY.startswith('sb_publishable_'):
        headers['Authorization']='Bearer '+PUBLIC_KEY
    query=dict(query or {})
    query['limit']=str(min(limit,1000))
    try:
        r=requests.get(f'{URL}/rest/v1/{table}',params=query,headers=headers,timeout=18)
        if not r.ok:
            try:
                err=r.json();reason=str(err.get('code') or err.get('message') or '')[:140]
            except ValueError:reason=''
            return [],f'讀取資料失敗（HTTP {r.status_code}；{reason}）'
        data=r.json()
        return (data,None) if isinstance(data,list) else ([], 'API 回傳格式不符')
    except requests.RequestException:
        return [],'雲端資料庫目前無法連線'

@st.cache_data(ttl=180,show_spinner=False)
def latest_snapshot():
    runs,error=read_api('stock_scores',{'select':'snapshot_at','order':'snapshot_at.desc'},1)
    if error or not runs:return pd.DataFrame(),None,error
    stamp=runs[0]['snapshot_at']
    allrows=[]
    # Intended universe ~ 4,000 records. Bound requests to protect hosted app.
    for offset in range(0,10000,1000):
        rec,e=read_api('stock_scores',{'select':'snapshot_at,symbol,stock_name,score,level,coverage,large_pct,retail_pct,foreign_5d,trust_5d,reason','snapshot_at':f'eq.{stamp}','order':'symbol.asc','offset':str(offset)},1000)
        if e:return pd.DataFrame(),stamp,e
        allrows.extend(rec)
        if len(rec)<1000:break
    return pd.DataFrame(allrows),stamp,None

@st.cache_data(ttl=180,show_spinner=False)
def score_history(code):
    return read_api('stock_scores',{'select':'snapshot_at,symbol,score,level,coverage,large_pct,retail_pct,foreign_5d,trust_5d,reason','symbol':f'eq.{code}','order':'snapshot_at.desc'},500)

@st.cache_data(ttl=180,show_spinner=False)
def holdings(code):
    rows,e=read_api('tdcc_holdings',{'select':'data_date,symbol,tier,holders,shares,pct','symbol':f'eq.{code}','order':'data_date.desc,tier.asc'},120)
    return pd.DataFrame(rows),e

@st.cache_data(ttl=180,show_spinner=False)
def institutions(code):
    rows,e=read_api('institutional_flows',{'select':'data_date,symbol,market,stock_name,foreign_net,trust_net','symbol':f'eq.{code}','order':'data_date.desc'},80)
    return pd.DataFrame(rows),e

st.title('📈 TW Swing')
st.caption('台股 2–8 週波段選股｜公開唯讀｜官方資料非即時報價・非投資建議')
if st.button('🔄 重新讀取最新資料',help='清除網站短期快取，不會觸發資料抓取'):
    read_api.clear();latest_snapshot.clear();score_history.clear();holdings.clear();institutions.clear();st.rerun()

pub,stock,hist,about,admin=st.tabs(['📋 選股總覽','🔎 個股籌碼','📊 歷史評分','ℹ️ 來源與限制','🔐 管理者'])
with pub:
    df,stamp,error=latest_snapshot()
    if error:st.warning(error)
    elif df.empty:st.info('雲端資料庫已連接，但尚無評分快照。請由管理者確認更新工作及資料完整度。')
    else:
        df['symbol']=df['symbol'].astype(str)
        df['score']=pd.to_numeric(df['score'],errors='coerce')
        df['level']=df['level'].fillna('資料不足')
        complete=df['coverage'].eq('完整')
        cols=st.columns(4)
        for c,(name,val) in zip(cols,[('股票記錄',len(df)),('籌碼資料完整',int(complete.sum())),('仔細分析',int((df['level']=='仔細分析').sum())),('準備下手',int((df['level']=='準備下手').sum()))]):c.metric(name,val)
        st.caption(f'最近評分快照：{stamp}。不同資料來源日期未必相同。')
        if not complete.any():st.warning('目前資料尚不足以計算完整的 2–4 週大戶與 5／10 日法人趨勢；空白分數不是 0 分，也不代表股票不符合條件。')
        st.info('「準備下手」仍須通過營收與技術面檢查，目前不會自動升級。')
        a,b=st.columns([1,2]);stage=a.selectbox('階段',['全部','開始關注','仔細分析','準備下手','資料不足']);q=b.text_input('搜尋股票代號／名稱',placeholder='例如 2330')
        view=df.copy()
        if stage!='全部':view=view[view['level'].eq(stage)]
        if q.strip():view=view[view['symbol'].str.contains(q.strip(),regex=False)|view['stock_name'].fillna('').astype(str).str.contains(q.strip(),regex=False)]
        view=view.sort_values(['score','symbol'],ascending=[False,True],na_position='last')
        named={'symbol':'代號','stock_name':'名稱','level':'階段','score':'籌碼分數','large_pct':'大戶占比%','retail_pct':'散戶占比%','foreign_5d':'外資5日淨買股數','trust_5d':'投信5日淨買股數','coverage':'資料完整度','reason':'說明'}
        show=view[list(named)].rename(columns=named)
        st.dataframe(show,hide_index=True,use_container_width=True)
        st.download_button('下載目前名單 CSV',show.to_csv(index=False).encode('utf-8-sig'),file_name='tw_swing_watchlist.csv',mime='text/csv')
    recent,e=read_api('update_runs',{'select':'run_at,tdcc_count,institution_count,fully_scored,status,notes','order':'run_at.desc'},5)
    if recent:
        st.subheader('最近更新紀錄');st.dataframe(pd.DataFrame(recent),hide_index=True,use_container_width=True)
    elif e:st.caption('更新紀錄尚不可讀：'+e)
with stock:
    code=st.text_input('查詢代號（上市普通股示例：2330）',value='2330',key='stock_code').strip()
    if not (code.isdigit() and len(code) in (4,5,6)):
        st.info('請輸入 4–6 位數字證券代號。')
    else:
        h,he=holdings(code);ins,ie=institutions(code)
        if he:st.warning('集保：'+he)
        if ie:st.warning('法人：'+ie)
        st.subheader('集保持股分布')
        if h.empty:st.info('尚無這檔證券的集保資料。')
        else:
            h['tier']=pd.to_numeric(h['tier'],errors='coerce')
            latest_day=h['data_date'].max();cur=h[(h['data_date']==latest_day)&(h['tier'].between(1,15))].copy()
            st.caption(f'資料日期：{latest_day}；第 17 級距為總計列，已排除；第 16 級距另列，不併入大戶比例。')
            pct=pd.to_numeric(cur['pct'],errors='coerce')
            large=round(pct[cur['tier'].between(12,15)].sum(),2)
            small=round(pct[cur['tier'].between(1,5)].sum(),2)
            a,b=st.columns(2);a.metric('第 12–15 級距比例',f'{large:.2f}%');b.metric('第 1–5 級距比例',f'{small:.2f}%')
            st.dataframe(cur[['tier','holders','shares','pct']].rename(columns={'tier':'級距','holders':'人數','shares':'股數','pct':'占比%'}),hide_index=True,use_container_width=True)
            older=h[h['data_date']<latest_day]
            if older.empty:st.warning('只有一週資料，不能判斷大戶是否連續增持。')
        st.subheader('外資與投信每日淨買賣')
        if ins.empty:st.info('尚無此證券的法人歷史資料。')
        else:
            for col in ('foreign_net','trust_net'):ins[col]=pd.to_numeric(ins[col],errors='coerce')
            ins=ins.sort_values('data_date',ascending=False)
            a,b=st.columns(2)
            if len(ins)>=5:
                a.metric('外資近5日淨買賣（股）',f'{ins.head(5)["foreign_net"].sum():,.0f}')
                b.metric('投信近5日淨買賣（股）',f'{ins.head(5)["trust_net"].sum():,.0f}')
            else:st.warning('法人資料少於 5 個交易日，暫不計算 5 日累計。')
            st.dataframe(ins.rename(columns={'data_date':'日期','foreign_net':'外資淨買股數','trust_net':'投信淨買股數','market':'市場','stock_name':'名稱','symbol':'代號'}),hide_index=True,use_container_width=True)
with hist:
    code=st.text_input('查詢歷史評分代號',value='2330',key='history_code').strip()
    if code:
        rows,e=score_history(code)
        if e:st.warning(e)
        elif not rows:st.info('尚無此檔證券的評分歷史。')
        else:
            hh=pd.DataFrame(rows)
            st.dataframe(hh,hide_index=True,use_container_width=True)
            plot=hh[['snapshot_at','score']].copy();plot['score']=pd.to_numeric(plot['score'],errors='coerce');plot=plot.dropna().sort_values('snapshot_at')
            if len(plot)>=2:st.line_chart(plot.set_index('snapshot_at')['score'])
            else:st.caption('有效評分不足兩筆，暫不繪製趨勢圖。')
with about:
    st.markdown('''**官方來源**：臺灣集中保管結算所 TDCC 股權分散表；臺灣證券交易所 TWSE 法人日報。\n\n**目前限制**：上櫃法人、月營收、技術進場條件及主力分點尚未全面串接。集保持股級距並不等於單一大戶；第 17 級距為合計列，不參與級距加總。資料不足時不給分數。\n\n**提醒**：資料日期與執行日期不同，分數並非買賣建議。對外公開使用前，應確認資料來源的再利用及轉載規範。''')
    st.markdown('[TDCC OpenAPI](https://openapi.tdcc.com.tw/) · [TWSE 法人日報](https://www.twse.com.tw/zh/trading/foreign/t86.html)')
with admin:
    st.write('只有管理者驗證成功後，才能透過 GitHub Actions 送出更新工作；公開頁面不能直接寫入資料庫。')
    pw=cfg('ADMIN_PASSWORD');token=cfg('GITHUB_PAT')
    if not pw or not token:st.warning('管理者功能未啟用。須在 Streamlit App Secrets 設定 ADMIN_PASSWORD 與 GITHUB_PAT。')
    else:
        entered=st.text_input('管理者密碼',type='password')
        if entered and hmac.compare_digest(entered.encode(),pw.encode()):
            st.success('管理者已驗證')
            if st.button('啟動官方資料更新',type='primary'):
                endpoint=f'https://api.github.com/repos/{OWNER}/{REPO}/actions/workflows/update.yml/dispatches'
                try:
                    response=requests.post(endpoint,headers={'Authorization':f'Bearer {token}','Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'},json={'ref':BRANCH},timeout=16)
                    if response.status_code==204:st.success('工作已送出。待 GitHub Actions 執行完成後按「重新讀取最新資料」。')
                    else:st.error(f'GitHub 更新失敗（HTTP {response.status_code}）')
                except requests.RequestException:st.error('GitHub 暫時無法連線')
            st.link_button('查看 GitHub 更新紀錄',f'https://github.com/{OWNER}/{REPO}/actions/workflows/update.yml')
        elif entered:st.error('密碼不正確')
        else:st.caption('密碼由伺服器端檢查，請勿放在 GitHub 公開程式碼中。')
