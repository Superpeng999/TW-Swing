"""TW Swing: sync SQLite market history with Supabase REST. Requires requests.
Usage: python supabase_bridge.py pull|push
Credentials are read ONLY from SUPABASE_URL and SUPABASE_SECRET_KEY env vars.
"""
import os,sys,sqlite3,datetime as dt,time
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parent
DB=ROOT/'tw_swing.sqlite3'
URL=os.environ.get('SUPABASE_URL','').rstrip('/')
KEY=os.environ.get('SUPABASE_SECRET_KEY','')
if not URL.startswith('https://') or not KEY:
    raise SystemExit('Missing SUPABASE_URL or SUPABASE_SECRET_KEY (configure GitHub Actions secrets).')
SESSION=requests.Session()
SESSION.headers.update({'apikey':KEY,'Authorization':'Bearer '+KEY,'Content-Type':'application/json'})
TABLES={
 'tdcc_holdings':('tdcc','d,symbol,tier,holders,shares,pct,source,loaded_at','data_date,symbol,tier,holders,shares,pct,source,loaded_at','data_date,symbol,tier'),
 'institutional_flows':('institutions','d,symbol,market,name,foreign_net,trust_net,source,loaded_at','data_date,symbol,market,stock_name,foreign_net,trust_net,source,loaded_at','data_date,symbol,market'),
 'stock_scores':('snapshots','run_at,symbol,score,level,coverage,large_pct,retail_pct,foreign5,trust5,reason','snapshot_at,symbol,score,level,coverage,large_pct,retail_pct,foreign_5d,trust_5d,reason','snapshot_at,symbol'),
 'update_runs':('runs','run_at,tdcc_count,twse_count,notes','run_at,tdcc_count,institution_count,notes','run_at')
}

def request(method,table,params=None,payload=None,upsert=False):
    h={'Prefer':'resolution=merge-duplicates,return=minimal'} if upsert else {}
    for i in range(4):
        try:
            r=SESSION.request(method,f'{URL}/rest/v1/{table}',params=params,json=payload,headers=h,timeout=90)
            if r.status_code in (429,500,502,503,504):
                time.sleep(2**i);continue
            r.raise_for_status()
            return r.json() if method=='GET' else None
        except requests.RequestException as e:
            if i==3:raise RuntimeError(f'Supabase {table} request failed: {e}') from e
            time.sleep(2**i)
    raise RuntimeError('Supabase retry attempts exhausted for '+table)

def date_value(s):
    v=str(s or '')
    if len(v)==8 and v.isdigit():return f'{v[:4]}-{v[4:6]}-{v[6:8]}'
    return v

def iso_time(s):
    v=str(s or '')
    if v and not any(x in v[10:] for x in ('+','Z')):v+='+00:00'
    return v

def init_sqlite(conn):
    from pipeline import init
    init(conn)


def pull(conn):
    # Only pull windows used by scoring. The complete archive remains in Supabase.
    cutoff=(dt.datetime.now(dt.timezone.utc).date()-dt.timedelta(days=85)).isoformat()
    pulls=[('tdcc_holdings',{'data_date':f'gte.{cutoff}'}),('institutional_flows',{'data_date':f'gte.{cutoff}'})]
    for table,flt in pulls:
        local,_,remote_fields,_=TABLES[table]
        cols=remote_fields.split(',')
        offset=0;count=0
        while True:
            p={'select':remote_fields,'order':'data_date.asc','limit':1000,'offset':offset,**flt}
            rows=request('GET',table,p)
            if not rows:break
            values=[]
            for row in rows:
                v=[row.get(k) for k in cols]
                v[0]=str(v[0]).replace('-','')
                if local=='tdcc':
                    v[3]=int(v[3]) if v[3] is not None else None
                    v[4]=int(v[4]) if v[4] is not None else None
                values.append(tuple(v))
            conn.executemany(f'INSERT OR REPLACE INTO {local} VALUES ({",".join("?" for _ in cols)})',values)
            count+=len(rows);offset+=len(rows)
            if len(rows)<1000:break
        conn.commit();print(f'PULL {table}: {count} historical rows')

def push(conn):
    for table in ('tdcc_holdings','institutional_flows','stock_scores','update_runs'):
        local,lc,rc,keys=TABLES[table]
        rnames=rc.split(',')
        # Use only recent market data; snapshots/runs are current-run data.
        if table in ('tdcc_holdings','institutional_flows'):
            most_recent=conn.execute(f'SELECT MAX(d) FROM {local}').fetchone()[0]
            if not most_recent:continue
            sql=f'SELECT {lc} FROM {local} WHERE d=?'
            cursor=conn.execute(sql,(most_recent,))
        else:
            most_recent=conn.execute(f'SELECT MAX(run_at) FROM {local}').fetchone()[0]
            if not most_recent:continue
            cursor=conn.execute(f'SELECT {lc} FROM {local} WHERE run_at=?',(most_recent,))
        count=0;batch=[]
        for values in cursor:
            record=dict(zip(rnames,values))
            for k in ('data_date',):
                if k in record:record[k]=date_value(record[k])
            for k in ('snapshot_at','run_at'):
                if k in record:record[k]=iso_time(record[k])
            for k in ('holders','shares','foreign_net','trust_net','foreign_5d','trust_5d'):
                if k in record and record[k] is not None:record[k]=int(record[k])
            if table=='update_runs':
                record['fully_scored']=int(conn.execute('SELECT COUNT(*) FROM snapshots WHERE run_at=? AND score IS NOT NULL',(most_recent,)).fetchone()[0])
                record['status']='completed'
            batch.append(record)
            if len(batch)>=400:
                request('POST',table,{'on_conflict':keys},batch,upsert=True)
                count+=len(batch);batch=[]
        if batch:
            request('POST',table,{'on_conflict':keys},batch,upsert=True);count+=len(batch)
        print(f'PUSH {table}: {count} rows (newest date/run only)')
    print('SUPABASE_SYNC_SUCCESS')

if __name__=='__main__':
    if len(sys.argv)!=2 or sys.argv[1] not in ('pull','push'):
        raise SystemExit('Usage: python supabase_bridge.py pull|push')
    with sqlite3.connect(DB) as con:
        init_sqlite(con)
        (pull if sys.argv[1]=='pull' else push)(con)
