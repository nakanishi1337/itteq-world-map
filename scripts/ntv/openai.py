"""JSON extraction with Responses Structured Outputs; successful answers only are cached."""
import json
import os
import urllib.error
from .common import digest, read_json, request, write_json

MODEL = 'gpt-6-sol'

class OpenAIUnavailable(Exception):
    pass


def output(response, validator):
    if not isinstance(response, dict) or response.get('status') != 'completed':
        raise OpenAIUnavailable('incomplete_response')
    texts = []
    for item in response.get('output', []):
        for content in item.get('content', []):
            if content.get('type') == 'refusal':
                raise OpenAIUnavailable('model_refusal')
            if content.get('type') == 'output_text':
                texts.append(content['text'])
    return validator(json.loads(''.join(texts)))


class OpenAI:
    def __init__(self, cache, offline=False):
        self.cache = cache
        self.offline = offline
        self.calls = self.hits = 0
        self.usage = {}

    def extract(self, material, prompt, schema, validator, name):
        key = digest([MODEL, prompt, schema, material])
        path = self.cache / (key + '.json')
        cached = read_json(path)
        if cached is not None:
            codes = validator(cached)
            self.hits += 1
            return codes
        if self.offline:
            raise OpenAIUnavailable('offline_cache_miss')
        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            raise OpenAIUnavailable('openai_api_key_missing')
        payload = {'model': MODEL, 'store': False,
                   'input': [{'role': 'system', 'content': prompt},
                             {'role': 'user', 'content': json.dumps(material, ensure_ascii=False)}],
                   'text': {'format': {'type': 'json_schema', 'name': name,
                                       'strict': True, 'schema': schema}}}
        self.calls += 1
        try:
            response = json.loads(request('https://api.openai.com/v1/responses', payload, api_key, timeout=90))
            codes = output(response, validator)
        except urllib.error.HTTPError as error:
            raise OpenAIUnavailable(f'openai_http_{error.code}') from None
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise OpenAIUnavailable('openai_' + type(error).__name__) from None
        for metric, value in response.get('usage', {}).items():
            if isinstance(value, int):
                self.usage[metric] = self.usage.get(metric, 0) + value
        write_json(path, codes)
        return codes
