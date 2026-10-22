"""Refresh GlobalPulse with paced GDELT DOC 2.0 requests. No dependencies."""
import json, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone
from pathlib import Path

TOPICS = {'top':'', 'finance':'theme:ECONOMY', 'technology':'theme:TECH', 'marketing':'(marketing OR advertising)', 'education':'theme:EDUCATION', 'health':'theme:MEDICAL', 'sports':'(cricket OR football OR soccer OR tennis OR olympics)', 'entertainment':'(film OR movie OR music OR bollywood)'}
COUNTRIES = {'world':('World','🌐'), 'IN':('India','🇮🇳'), 'US':('USA','🇺🇸'), 'UK':('UK','🇬🇧'), 'CA':('Canada','🇨🇦'), 'AU':('Australia','🇦🇺'), 'PK':('Pakistan','🇵🇰')}
EXPECTED = {'IN':{'India'},'US':{'United States','United States of America'},'UK':{'United Kingdom'},'CA':{'Canada'},'AU':{'Australia'},'PK':{'Pakistan'}}
path=Path('data.json')
try: previous=json.loads(path.read_text())
except (OSError, ValueError): previous={}
out={'fetchedAt':None,'world':{},'countries':{},'fetchStatus':{},'queries':{}}
last_request=0

def stamp(): return datetime.now(timezone.utc).isoformat()
def request(query):
    global last_request
    url='https://api.gdeltproject.org/api/v2/doc/doc?'+urllib.parse.urlencode({'query':query,'mode':'artlist','maxrecords':15,'format':'json'})
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
            # Never retain potentially mislabeled country content.
            for key in TOPICS: target[key]=[]
        if articles is None:
            target[topic]=old.get(topic,[])
            if target[topic]: status+='; retained_previous_records'
        else:
            records=[]
            for a in articles:
                url=a.get('url','')
                if not url.startswith(('https://','http://')) or not a.get('title'): continue
                raw=a.get('seendate','')
                try: seen=datetime.strptime(raw,'%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).isoformat()
                except ValueError: seen=raw
                records.append({'title':a['title'],'url':url,'source':a.get('domain') or urllib.parse.urlparse(url).netloc,'seendate':seen})
            target[topic]=records
            if status=='success' and not records: status='empty'
        out['fetchStatus'][code][topic]=status
        print(code,topic,status,len(target[topic]),flush=True)
        out['fetchedAt']=stamp()
        path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
# fetchedAt is the completion of this fetch attempt; per-query statuses distinguish failures.
out['fetchedAt']=stamp()
path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
