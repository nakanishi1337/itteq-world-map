import re
from functools import lru_cache
from .common import digest
from .geography import PLACES, CITIES_HASH, heading_places
from .openai import MODEL, PROMPT, SCHEMA, OpenAIUnavailable


@lru_cache(maxsize=1)
def policy_hash():
    # Change this version when extraction rules change. API cache also includes the exact prompt.
    return digest([2, MODEL, PROMPT, SCHEMA, PLACES, CITIES_HASH])


def recap(title):
    return bool(re.search(r'アワード|総集編|名場面集|傑作選', title))


def documents(row, all_docs):
    preview = {'kind': 'preview', 'title': row['project'],
               'text': row['project'] + '\n' + row['body'], 'url': row['source']}
    candidates = [doc for doc in all_docs if doc['date'] == row['date']
                  and (not doc.get('projectId') or doc['projectId'] == row['id'])]
    # Supplement titles can differ; the single country call selects the relevant project.
    references = {(d['url'], d['text']): {k: d[k] for k in ('kind', 'title', 'text', 'url', 'date', 'dateBasis') if k in d}
                  for d in candidates}
    return [preview] + sorted(references.values(), key=lambda d: (d['kind'], d['url'], d['text']))


def decide(row, all_docs, client, manual=None, previous=None):
    places = heading_places(row['project'])
    docs = documents(row, [] if places or recap(row['project']) else all_docs)
    fingerprint = digest([row['date'], row['project'], row['performers'], docs, manual, policy_hash()])
    if previous and previous.get('inputHash') == fingerprint and previous['status'] in ('accepted', 'excluded'):
        return dict(previous)
    result = {'id': row['id'], 'date': row['date'], 'project': row['project'], 'performers': row['performers'],
              'source': row['source'], 'policyHash': policy_hash(), 'status': 'pending', 'reason': '',
              'countries': [], 'method': 'none', 'documents': docs, 'inputHash': fingerprint}
    if not row['date'] or not row['performers']:
        result['reason'] = 'missing_date_or_performers'
    elif manual:
        if manual['status'] == 'accepted':
            codes = manual.get('countries')
            if not isinstance(codes, list) or any(c not in PLACES['names'] for c in codes) or not manual.get('evidence'):
                raise ValueError('手動確定には有効な国コードと根拠が必要です')
            result.update(status='accepted', method='manual', reason='manual_override', countries=[
                {'countryCode': c, 'places': [], 'evidence': manual['evidence']} for c in sorted(set(codes))])
        elif manual['status'] in ('pending', 'excluded'):
            result.update(status=manual['status'], method='manual', reason=manual.get('reason', 'manual_override'))
        else:
            raise ValueError('不正な手動設定状態')
    elif recap(row['project']):
        result.update(status='excluded', reason='recap', method='rule')
    elif places:
        result.update(status='accepted', reason='explicit_heading', method='heading', countries=[
            {'countryCode': code, 'places': [p['place'] for p in places if p['countryCode'] == code],
             'evidence': {'text': row['project'], 'url': row['source']}}
            for code in sorted({p['countryCode'] for p in places})])
    else:
        result.update(method='openai', model=MODEL)
        try:
            codes = client.countries(row, docs)
            result.update(status='accepted', reason='openai_countries' if codes else 'openai_empty', countries=[
                {'countryCode': code, 'places': [], 'evidence': {'text': 'OpenAIによる資料の国抽出', 'url': row['source']}}
                for code in codes])
        except OpenAIUnavailable as error:
            result['reason'] = str(error)
    return result


def make_episodes(decisions, previous, overrides):
    """Replace full country sets after success; preserve previous data on failure."""
    by_id = {}
    for episode in previous:
        by_id.setdefault(episode['projectId'], []).append(episode)
    for d in decisions:
        key = d['id']
        if d['status'] == 'accepted':
            by_id[key] = [{'projectId': key, 'date': d['date'], 'countryCode': c['countryCode'],
                           'countryName': PLACES['names'][c['countryCode']], 'project': d['project'],
                           'performers': d['performers'], 'source': d['source'],
                           'sources': sorted({d['source'], c['evidence']['url']} |
                                             {doc['url'] for doc in d.get('documents', [])})}
                          for c in d['countries']]
        elif d['status'] == 'excluded' or overrides.get(key, {}).get('status') == 'excluded':
            by_id.pop(key, None)
    return sorted([e for group in by_id.values() for e in group], key=lambda e: (e['date'], e['projectId'], e['countryCode']))
