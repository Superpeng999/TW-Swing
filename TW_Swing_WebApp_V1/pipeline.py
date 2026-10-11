"""TW Swing V1: official TDCC + TWSE ingest, SQLite history, scoring CSVs.
Requires requests; uses only Python standard library for data/storage (Excel generated separately).
"""
import argparse,csv,datetime as dt,json,re,sqlite3,time
from collections import defaultdict
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parent
DB=ROOT/'tw_swing.sqlite3'; OUT=ROOT/'output'; OUT.mkdir(exist_ok=True)
TDCC='https://openapi.tdcc.com.tw/v1/opendata/1-5'
TWSE='https://www.twse.com.tw/rwd/zh/fund/T86'
HEADER={'User-Agent':'Mozilla/5.0 (compatible; TWSwingResearch/1.0)'}
SCORE_WEIGHTS={'large_2w':25,'large_4w':15,'institution_5d':20,'institution_10d':10,'retail_2w':10}

def get_json(url,params=None):
    r=requests.get(url,params=params,headers=HEADER,timeout=40);r.raise_for_status();return r.json()
def num(x):
    try:return float(str(x).replace(',','').replace('%','').strip())
    except (TypeError,ValueError):return None
def norm(s):return re.sub(r'[\s\u3000\ufeff\u200b()（）%％、/·.-]','',str(s)).lower()
def select(row,*names):
    n={norm(k):v for k,v in row.items()}
    for name in names:
        k=norm(name)
        if k in n:return n[k]
    return None

def init(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS tdcc (d TEXT,symbol TEXT,tier INTEGER,holders REAL,shares REAL,pct REAL,source TEXT,loaded_at TEXT, PRIMARY KEY(d,symbol,tier));
    CREATE TABLE IF NOT EXISTS institutions (d TEXT,symbol TEXT,market TEXT,name TEXT,foreign_net REAL,trust_net REAL,source TEXT,loaded_at TEXT,PRIMARY KEY(d,symbol,market));
    CREATE TABLE IF NOT EXISTS runs (run_at TEXT PRIMARY KEY,tdcc_count INTEGER,twse_count INTEGER,notes TEXT);
    CREATE TABLE IF NOT EXISTS snapshots (run_at TEXT,symbol TEXT,score REAL,level TEXT,coverage TEXT,large_pct REAL,retail_pct REAL,foreign5 REAL,trust5 REAL,reason TEXT,PRIMARY KEY(run_at,symbol));''')

def load_tdcc(c):
    """Download TDCC 1-5; accept official Chinese/English column variants.

    Fail visibly if no valid rows. Do not turn incomplete data into scores.
    """
    data = get_json(TDCC)
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [])
    if not isinstance(data, list) or not data:
        raise ValueError('TDCC response contains no records')

    def tdcc_value(row, *aliases):
        # Both 占 and 佔 appear in published field descriptions.
        candidates = {norm(str(k).replace('佔', '占')): v for k, v in row.items()}
        for alias in aliases:
            key = norm(alias.replace('佔', '占'))
            if key in candidates:
                return candidates[key]
        return None

    rows = []
    skipped = 0
    now = dt.datetime.now().isoformat(timespec='seconds')
    for row in data:
        if not isinstance(row, dict):
            skipped += 1
            continue
        raw_date = str(tdcc_value(row, '資料日期', 'Date') or '').strip()
        d = re.sub(r'[^0-9]', '', raw_date)
        sym = str(tdcc_value(row, '證券代號', 'Securities Code', 'SecuritiesCode') or '').strip()
        tier = num(tdcc_value(row, '持股分級', 'Securities Holding Range', 'SecuritiesHoldingRange'))
        pct = num(tdcc_value(row,
            '占集保庫存數比例%', '佔集保庫存數比例%', '占集保庫存數比例',
            'Percentage of Centrally Deposited Securities',
            'PercentageOfCentrallyDepositedSecurities',
            'Percentage of Centrally Deposited Securities (%)'))
        holders = num(tdcc_value(row, '人數', 'Number of Holders', 'NumberOfHolders'))
        shares = num(tdcc_value(row, '股數', 'Number of Shares/Units', 'NumberOfSharesUnits', 'Number of Shares'))
        if not (len(d) == 8 and d.isdigit() and re.fullmatch(r'[0-9A-Za-z]{4,6}', sym)
                and tier is not None and 1 <= tier <= 17 and pct is not None and 0 <= pct <= 100):
            skipped += 1
            continue
        # Tier 16 is adjustment, tier 17 is total. The scoring code uses 1..15.
        rows.append((d, sym, int(tier), holders, shares, pct, TDCC, now))
    if not rows:
        example_keys = list(data[0].keys()) if isinstance(data[0], dict) else []
        raise ValueError('TDCC: no valid rows; sample field names=' + repr(example_keys)
                         + '; examined=' + str(len(data)))
    c.executemany('INSERT OR REPLACE INTO tdcc VALUES(?,?,?,?,?,?,?,?)', rows)
    print('TDCC parsed rows:', len(rows), 'skipped:', skipped, 'sample keys:', list(data[0].keys()))
    return len(rows)

def load_twse(c,d):
    data=get_json(TWSE,{'date':d,'selectType':'ALLBUT0999','response':'json'})
    if data.get('stat')!='OK':raise ValueError(f'TWSE {d} status: {data.get("stat")}')
    fields=data.get('fields',[])
    def idx(*keywords):
        for key in keywords:
            for i,f in enumerate(fields):
                if norm(key)==norm(f):return i
        return None
    symbol_i=idx('證券代號');name_i=idx('證券名稱')
    foreign_i=idx('外陸資買賣超股數(不含外資自營商)','外陸資買賣超股數不含外資自營商')
    trust_i=idx('投信買賣超股數')
    # Avoid silently reading the wrong numeric column if TWSE schema changes.
    if None in (symbol_i,foreign_i,trust_i):raise ValueError('TWSE headers changed: '+repr(fields))
    rows=[]
    for a in data.get('data',[]):
        s=re.sub('<[^>]+>','',str(a[symbol_i])).strip()
        if not re.fullmatch(r'\d{4}',s):continue
        f=num(a[foreign_i]);t=num(a[trust_i])
        if f is None or t is None:continue
        name=re.sub('<[^>]+>','',str(a[name_i])).strip() if name_i is not None else ''
        rows.append((d,s,'TWSE',name,f,t,TWSE,dt.datetime.now().isoformat(timespec='seconds')))
    if not rows:raise ValueError('TWSE no usable stock rows')
    c.executemany('INSERT OR REPLACE INTO institutions VALUES(?,?,?,?,?,?,?,?)',rows)
    return len(rows)

def import_tpex_csv(c,path,d):
    """Optional official TPEx manually downloaded normalized CSV: symbol,name,foreign_net,trust_net.
       Input is explicit/validated; unsupported external API payloads never fabricated.
    """
    rows=[]
    with open(path,encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            s=(r.get('symbol') or '').strip();a=num(r.get('foreign_net'));b=num(r.get('trust_net'))
            if not re.fullmatch(r'\d{4}',s) or a is None or b is None:continue
            rows.append((d,s,'TPEX',r.get('name',''),a,b,str(path),dt.datetime.now().isoformat(timespec='seconds')))
    if not rows:raise ValueError('No valid TPEx normalized CSV rows')
    c.executemany('INSERT OR REPLACE INTO institutions VALUES(?,?,?,?,?,?,?,?)',rows)
    return len(rows)

def write_csv(name,header,rows):
    with open(OUT/name,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(header);w.writerows(rows)

def score(c,run):
    # TDCC holder tiers: >=12 represents >=400k shares; <=5 as smaller accounts.
    # Use >=12 as explicit editable research proxy, NOT identify beneficial owners.
    data=defaultdict(dict)
    for d,s,t,p in c.execute('SELECT d,symbol,tier,pct FROM tdcc WHERE tier BETWEEN 1 AND 15'):
        if p is None:continue
        x=data[(s,d)];x['large']=x.get('large',0)+(p if t>=12 else 0);x['retail']=x.get('retail',0)+(p if t<=5 else 0)
    histories=defaultdict(list)
    for (s,d),v in data.items():histories[s].append((d,v))
    inst=defaultdict(list);names={}
    for d,s,m,n,f,t in c.execute('SELECT d,symbol,market,name,foreign_net,trust_net FROM institutions ORDER BY d'):
        inst[s].append((d,f,t));names[s]=n or names.get(s,'')
    rows=[];snap=[]
    for sym in sorted(set(histories)|set(inst)):
        hs=sorted(histories.get(sym,[]),reverse=True)[:5]; it=sorted(inst.get(sym,[]),reverse=True)[:10]
        large=hs[0][1]['large'] if hs else None;retail=hs[0][1]['retail'] if hs else None
        l2=(len(hs)>=3 and all(hs[k][1]['large']>hs[k+1][1]['large'] for k in range(2)))
        l4=(len(hs)>=5 and hs[0][1]['large']>hs[4][1]['large'])
        r2=(len(hs)>=3 and hs[0][1]['retail']<hs[2][1]['retail'])
        f5=sum(x[1] for x in it[:5]) if len(it)>=5 else None
        t5=sum(x[2] for x in it[:5]) if len(it)>=5 else None
        i5=(f5+t5>0) if f5 is not None else None
        i10=(sum(x[1]+x[2] for x in it[:10])>0) if len(it)>=10 else None
        valid={'large_2w':l2 if len(hs)>=3 else None,'large_4w':l4 if len(hs)>=5 else None,'institution_5d':i5,'institution_10d':i10,'retail_2w':r2 if len(hs)>=3 else None}
        available=sum(SCORE_WEIGHTS[k] for k,v in valid.items() if v is not None)
        points=sum(SCORE_WEIGHTS[k] for k,v in valid.items() if v is True)
        # Strict completeness threshold: do not grade partially built histories.
        complete=(available==sum(SCORE_WEIGHTS.values()))
        score=round(100*points/available,1) if complete else None
        level='仔細分析' if score is not None and score>=70 else ('開始關注' if score is not None else '資料不足')
        # No automatic '準備下手' without technical, revenue and trade plan confirmation.
        latest_tdcc=hs[0][0] if hs else '';latest_inst=it[0][0] if it else ''
        reason='完整籌碼條件待技術與營收確認' if complete else '歷史資料不足／尚未完整納入上市櫃'
        rows.append([run,sym,names.get(sym,''),latest_tdcc,latest_inst,large,retail,f5,t5,int(l2) if len(hs)>=3 else '',int(l4) if len(hs)>=5 else '',int(r2) if len(hs)>=3 else '',int(i5) if i5 is not None else '',int(i10) if i10 is not None else '',score,level,'完整' if complete else '不足',reason])
        snap.append((run,sym,score,level,'完整' if complete else '不足',large,retail,f5,t5,reason))
    c.executemany('INSERT OR REPLACE INTO snapshots VALUES(?,?,?,?,?,?,?,?,?,?)',snap)
    write_csv('latest_scores.csv',['執行時間','代號','名稱','集保資料日','法人資料日','大戶占比%','散戶占比%','法人外資5日股數','投信5日股數','大戶連2週','大戶4週上升','散戶2週下降','法人5日正','法人10日正','籌碼分數','階段','資料完整度','說明'],rows)
    write_csv('score_history.csv',['執行時間','代號','籌碼分數','階段','資料完整度','大戶占比%','散戶占比%','外資5日','投信5日','說明'],c.execute('SELECT * FROM snapshots ORDER BY run_at DESC,symbol'))
    write_csv('institutions_history.csv',['日期','代號','市場','名稱','外資淨買股數','投信淨買股數','來源','匯入時間'],c.execute('SELECT * FROM institutions ORDER BY d DESC,symbol'))
    write_csv('tdcc_history.csv',['日期','代號','級距','人數','股數','比例%','來源','匯入時間'],c.execute('SELECT * FROM tdcc ORDER BY d DESC,symbol,tier'))
    return len(rows),sum(1 for r in rows if r[16]=='完整')

def main():
    p=argparse.ArgumentParser();p.add_argument('--date',help='TWSE date YYYYMMDD (default today)');p.add_argument('--backfill-days',type=int,default=15);p.add_argument('--offline',action='store_true');p.add_argument('--tpex-csv',help='Optional normalized TPEx file');args=p.parse_args()
    conn=sqlite3.connect(DB);init(conn);tdc=0;twc=0;messages=[]
    if not args.offline:
        try:tdc=load_tdcc(conn);conn.commit()
        except Exception as e:messages.append('TDCC:'+str(e))
        today=dt.datetime.strptime(args.date,'%Y%m%d').date() if args.date else dt.date.today()
        for gap in range(args.backfill_days):
            day=today-dt.timedelta(days=gap)
            if day.weekday()>=5:continue
            date=day.strftime('%Y%m%d')
            if conn.execute('SELECT 1 FROM institutions WHERE d=? AND market="TWSE" LIMIT 1',(date,)).fetchone():continue
            try:twc+=load_twse(conn,date);conn.commit()
            except Exception as e:messages.append('TWSE '+date+':'+str(e)[:85])
            time.sleep(.6)
    if args.tpex_csv:
        try:twc+=import_tpex_csv(conn,Path(args.tpex_csv),args.date or dt.date.today().strftime('%Y%m%d'));conn.commit()
        except Exception as e:messages.append('TPEx CSV:'+str(e))
    run=dt.datetime.now().isoformat(timespec='seconds')
    count,complete=score(conn,run)
    conn.execute('INSERT INTO runs VALUES(?,?,?,?)',(run,tdc,twc,' | '.join(messages)));conn.commit()
    write_csv('run_log.csv',['執行時間','TDCC資料列','法人資料列','錯誤或附註'],conn.execute('SELECT * FROM runs ORDER BY run_at DESC'))
    print(json.dumps({'run':run,'tdcc_imported':tdc,'institution_imported':twc,'stocks':count,'fully_scored':complete,'messages':messages[:12]},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
