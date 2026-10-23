"""Refresh GlobalPulse with paced GDELT DOC 2.0 requests. No dependencies."""
import json, time, sys, re, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

TOPICS = {'top':'', 'finance':'theme:ECONOMY', 'technology':'theme:TECH', 'marketing':'(marketing OR advertising)', 'education':'theme:EDUCATION', 'health':'theme:MEDICAL', 'sports':'(cricket OR football OR soccer OR tennis OR olympics)', 'entertainment':'(film OR movie OR music OR bollywood)'}
COUNTRIES = {'world':('World','🌐'), 'IN':('India','🇮🇳'), 'US':('USA','🇺🇸'), 'UK':('UK','🇬🇧'), 'CA':('Canada','🇨🇦'), 'AU':('Australia','🇦🇺'), 'PK':('Pakistan','🇵🇰')}
EXPECTED = {'IN':{'India'},'US':{'United States','United States of America'},'UK':{'United Kingdom'},'CA':{'Canada'},'AU':{'Australia'},'PK':{'Pakistan'}}
path=Path('data.json')
try: previous=json.loads(path.read_text())
except (OSError, ValueError): previous={}
def title_ok(title): return not re.search(r'[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]',title)
def stamp(): return datetime.now(timezone.utc).isoformat()
def recent_records(records):
    cutoff=datetime.now(timezone.utc)-timedelta(days=7)
    kept=[]
    for record in records:
        try:
            raw=record.get('seendate','')
            try: seen=datetime.strptime(raw,'%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
            except ValueError: seen=datetime.fromisoformat(raw.replace('Z','+00:00'))
            if seen.tzinfo is None: seen=seen.replace(tzinfo=timezone.utc)
        except (AttributeError,TypeError,ValueError):
            continue
        if seen >= cutoff: kept.append(record)
    return kept
def prune_records(data):
    for code in COUNTRIES:
        bucket=data.get('world',{}) if code=='world' else data.get('countries',{}).get(code,{})
        for topic in TOPICS:
            if topic in bucket: bucket[topic]=recent_records(bucket[topic])
# A no-network maintenance mode removes unmistakably non-English legacy titles.
if '--validate-only' in sys.argv:
    removed=0
    for code in COUNTRIES:
        bucket=previous.get('world',{}) if code=='world' else previous.get('countries',{}).get(code,{})
        for topic in TOPICS:
            old=bucket.get(topic,[])
            bucket[topic]=[a for a in recent_records(old) if title_ok(a.get('title',''))]
            if len(old)!=len(bucket[topic]):
                removed+=len(old)-len(bucket[topic])
                previous.setdefault('fetchStatus',{}).setdefault(code,{})[topic]='excluded_non_english_titles'
    previous['validatedAt']=stamp()
    prune_records(previous)
    path.write_text(json.dumps(previous,ensure_ascii=False,indent=2)+'\n')
    print('Excluded non-English legacy titles:',removed)
    sys.exit(0)
out={'fetchedAt':None,'world':{},'countries':{},'fetchStatus':{},'queries':{}}
last_request=0
retry_queue=[]

def request(query):
    global last_request
    url='https://api.gdeltproject.org/api/v2/doc/doc'+urllib.parse.urlencode({'query':query,'mode':'artlist','maxrecords':15,'format':'json','timespan':'3d','sort':'datedesc'})
    for attempt in range(2):
        time.sleep(max(0,6.2-(time.monotonic()-last_request)))
        last_request=time.monotonic()
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'GlobalPulseNews/1.0'})
            with urllib.request.urlopen(req,timeout=60) as response: text=response.read().decode('utf-8'); status=response.status
        except urllib.error.HTTPError as e:
            status=e.code; text=e.read().decode('utf-8',errors='replace')
        except Exception as e: return None,'request_error: '+type(e).__name__
        limited=status==429 or 'Please limit requests' in text
        if limited:
            if attempt==0:
                print('Rate limit: back off 61 seconds, retry once',flush=True)
                time.sleep(61)
                continue
            return None,'rate_limited_after_retry'
        if status!=200: return None,'http_'+str(status)
        try: return json.loads(text).get('articles',[]),'success'
        except ValueError: return None,'invalid_json'
    return None,'request_failed'

for code,(name,flag) in COUNTRIES.items():
    target=out['world'] if code=='world' else {'name':name,'flag':flag}
    if code!='world': out['countries'][code]=target
    out['fetchStatus'][code]={}; out['queries'][code]={}
    old=previous.get('world',{}) if code=='world' else previous.get('countries',{}).get(code,{})
    skip=False
    for topic,term in TOPICS.items():
        if skip:
            target[topic]=[]; out['fetchStatus'][code][topic]='skipped_country_code_mismatch'; continue
        query=' '.join(x for x in [term,('sourcecountry:'+code if code!='world' else ''),'sourcelang:English'] if x)
        out['queries'][code][topic]={'query':query,'attemptedAt':stamp()}
        articles,status=request(query)
        if articles and code!='world' and any(a.get('sourcecountry') not in EXPECTED[code] for a in articles):
            articles=[]; status='skipped_country_code_mismatch'; skip=True
            for key in TOPICS: target[key]=[]
        if articles is None:
            target[topic]=[a for a in recent_records(old.get(topic,[])) if title_ok(a.get('title',''))]
            if status=='rate_limited_after_retry': retry_queue.append((code,topic,query,old,target))
            if target[topic]: status+='; retained_previous_records'
        else:
            records=[]
            rejected=0
            for a in articles:
                url=a.get('url','')
                if not url.startswith(('https://','http://')) or not a.get('title'): continue
                if a.get('language','').lower()!='english' or not title_ok(a['title']):
                    rejected+=1; continue
                raw=a.get('seendate','')
                try: seen=datetime.strptime(raw,'%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).isoformat()
                except ValueError: seen=raw
                records.append({'title':a['title'],'url':url,'source':a.get('domain') or urllib.parse.urlparse(url).netloc,'seendate':seen})
            records=recent_records(records)
            target[topic]=records
            if status=='success' and rejected: status='filtered_non_english_records' if records else 'excluded_non_english_titles'
            elif status=='success' and not records: status='empty'
        out['fetchStatus'][code][topic]=status
        print(stamp(),code,topic,status,len(target[topic]),flush=True)
        out['fetchedAt']=stamp()
        prune_records(out)
        path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
# One bounded end-of-run attempt for each section still rate-limited after its normal retry.
retry_skipped=set()
for code,topic,query,old,target in retry_queue:
    if code in retry_skipped or any(s=='skipped_country_code_mismatch' for s in out['fetchStatus'][code].values()): continue
    out['queries'][code][topic]['attemptedAt']=stamp()
    articles,status=request(query)
    if articles and code!='world' and any(a.get('sourcecountry') not in EXPECTED[code] for a in articles):
        articles=[]; status='skipped_country_code_mismatch'; retry_skipped.add(code)
        for key in TOPICS: target[key]=[]
    if articles is None:
        target[topic]=[a for a in recent_records(old.get(topic,[])) if title_ok(a.get('title',''))]
        if target[topic]: status+='; retained_previous_records'
    else:
        records=[]
        rejected=0
        for a in articles:
            url=a.get('url','')
            if not url.startswith(('https://','http://')) or not a.get('title'): continue
            if a.get('language','').lower()!='english' or not title_ok(a['title']):
                rejected+=1; continue
            raw=a.get('seendate','')
            try: seen=datetime.strptime(raw,'%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).isoformat()
            except ValueError: seen=raw
            records.append({'title':a['title'],'url':url,'source':a.get('domain') or urllib.parse.urlparse(url).netloc,'seendate':seen})
        records=recent_records(records)
        target[topic]=records
        if status=='success' and rejected: status='filtered_non_english_records' if records else 'excluded_non_english_titles'
        elif status=='success' and not records: status='empty'
    out['fetchStatus'][code][topic]=status
    print(stamp(),code,topic,'end_retry_'+status,len(target[topic]),flush=True)
out['fetchedAt']=stamp()
prune_records(out)
path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
