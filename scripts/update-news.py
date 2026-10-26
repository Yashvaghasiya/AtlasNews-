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
    url='https://api.gdeltproject.org/api/v2/doc/doc?'+urllib.parse.urlencode({'query':query,'mode':'artlist','maxrecords':15,'format':'json','timespan':'3d','sort':'datedesc'})
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
# Fallbacks run only after the existing GDELT end-of-run retry pass.
# Official references: currentsapi.services/en/docs/latest_news (V2 taxonomy),
# currentsapi.services/en/docs/ratelimit, newsdata.io/documentation/latest-news-api,
# newsdata.io/documentation/api-rate-limit and newsdata.io/openapi.json.
import os

FALLBACK_CATEGORIES = {
    'currents': {
        'top': 'general', 'finance': 'economy_business_finance',
        'technology': 'science_technology', 'marketing': 'economy_business_finance',
        'education': 'education', 'health': 'health', 'sports': 'sport',
        'entertainment': 'arts_culture_entertainment',
    },
    'newsdata': {
        'top': 'top', 'finance': 'business', 'technology': 'technology',
        'marketing': 'business', 'education': 'education', 'health': 'health',
        'sports': 'sports', 'entertainment': 'entertainment',
    },
}
FALLBACK_COUNTRIES = {'IN': 'in', 'US': 'us', 'UK': 'gb', 'CA': 'ca', 'AU': 'au', 'PK': 'pk'}
fallback_sources = {
    'currents': {'key': os.environ.get('CURRENTS_API_KEY', '').strip(),
                 'endpoint': 'https://api.currentsapi.services/v2/latest-news',
                 'header': 'Authorization', 'limit': 40, 'used': 0, 'stopped': False},
    'newsdata': {'key': os.environ.get('NEWSDATA_API_KEY', '').strip(),
                 'endpoint': 'https://newsdata.io/api/1/latest',
                 'header': 'X-ACCESS-KEY', 'limit': 30, 'used': 0, 'stopped': False},
}
fallback_last_request = 0.0


def fallback_records(source, articles):
    """Normalize provider timestamps to the same UTC ISO seendate GDELT stores."""
    records = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        title = article.get('title')
        url = article.get('url' if source == 'currents' else 'link', '')
        language = str(article.get('language') or '').lower()
        if not isinstance(title, str) or not title or not title_ok(title):
            continue
        if not isinstance(url, str) or not url.startswith(('https://', 'http://')):
            continue
        if language not in ('en', 'english'):
            continue
        raw = article.get('published' if source == 'currents' else 'pubDate')
        if not isinstance(raw, str):
            continue
        try:
            try:
                seen = datetime.fromisoformat(raw.replace('Z', '+00:00'))
            except ValueError:
                seen = datetime.strptime(raw, '%Y-%m-%d %H:%M:%S %z')
            # NewsData's default publication timezone is UTC.
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
            seen = seen.astimezone(timezone.utc).isoformat()
        except ValueError:
            continue
        publisher = article.get('source_name') if source == 'newsdata' else None
        records.append({'title': title, 'url': url,
                        'source': publisher or urllib.parse.urlparse(url).netloc,
                        'seendate': seen})
    return recent_records(records)[:15]


def fallback_error_detail(text):
    """Keep public error diagnostics short and redact both providers' keys/URLs."""
    for config in fallback_sources.values():
        key = config['key']
        if key:
            for value in (key, urllib.parse.quote(key, safe=''),
                          urllib.parse.quote_plus(key), json.dumps(key)[1:-1]):
                text = text.replace(value, '[REDACTED]')
    text = re.sub(r'https?://\S+', '[URL REDACTED]', text, flags=re.IGNORECASE)
    return ' '.join(text.split())[:200]


def fallback_request(source, code, topic):
    global fallback_last_request
    config = fallback_sources[source]
    category = FALLBACK_CATEGORIES[source].get(topic)
    if not config['key'] or config['stopped'] or config['used'] >= config['limit'] or not category:
        return []
    params = {'language': 'en', 'category': category}
    if code != 'world':
        params['country'] = FALLBACK_COUNTRIES[code]
    if source == 'currents':
        params['page_size'] = 15
    # NewsData defaults to ten articles/one credit on Free; never paginate.
    # At most 30 one-credit calls in this run, below its 30-credit/15-minute cap.
    # Other runs/clients can consume the same quota: stop immediately on 429.
    time.sleep(max(0, 1.5 - (time.monotonic() - fallback_last_request)))
    fallback_last_request = time.monotonic()
    config['used'] += 1
    url = config['endpoint'] + '?' + urllib.parse.urlencode(params)
    headers = {'User-Agent': 'GlobalPulseNews/1.0', config['header']: config['key']}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as response:
            status = response.status
            text = response.read().decode('utf-8')
            # Remaining quota zero still permits consuming this last response.
            for header in ('X-RateLimit-Remaining', 'X-API-Limit-Remaining'):
                remaining = response.headers.get(header)
                if remaining is not None and remaining.strip() == '0':
                    config['stopped'] = True
    except urllib.error.HTTPError as error:
        if error.code in (401, 403, 429):
            config['stopped'] = True
        try:
            detail = error.read().decode('utf-8', errors='replace')
        except Exception:
            detail = '[response body unavailable]'
        print(stamp(), source, 'http_' + str(error.code), fallback_error_detail(detail), flush=True)
        return []
    except Exception as error:
        # Never print exception text or request URLs.
        print(stamp(), source, 'request_error_' + type(error).__name__, flush=True)
        return []
    try:
        payload = json.loads(text)
    except ValueError:
        print(stamp(), source, 'http_' + str(status), 'invalid_json', fallback_error_detail(text), flush=True)
        return []
    if not isinstance(payload, dict):
        print(stamp(), source, 'http_' + str(status), 'invalid_response', fallback_error_detail(text), flush=True)
        return []
    if payload.get('status') != ('ok' if source == 'currents' else 'success'):
        # Providers may report quota errors in JSON rather than HTTP status.
        message = json.dumps(payload).lower()
        if any(term in message for term in ('quota', 'credit', 'rate_limit', 'ratelimit', 'rate limit', 'too many')):
            config['stopped'] = True
        print(stamp(), source, 'http_' + str(status), 'api_error', fallback_error_detail(text), flush=True)
        return []
    articles = payload.get('news' if source == 'currents' else 'results', [])
    return fallback_records(source, articles) if isinstance(articles, list) else []


for code in COUNTRIES:
    target = out['world'] if code == 'world' else out['countries'][code]
    for topic in TOPICS:
        status = out['fetchStatus'][code][topic]
        if recent_records(target.get(topic, [])) and status.split(';', 1)[0] != 'rate_limited_after_retry':
            continue
        for source in ('currents', 'newsdata'):
            records = fallback_request(source, code, topic)
            if not records:
                continue
            target[topic] = records
            out['fetchStatus'][code][topic] = status + '; fallback_' + source
            print(stamp(), code, topic, 'fallback_' + source, len(records), flush=True)
            out['fetchedAt'] = stamp()
            prune_records(out)
            path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
            break
out['fetchedAt'] = stamp()
prune_records(out)
path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
