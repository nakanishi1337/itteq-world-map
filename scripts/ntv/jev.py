import json
import os
from .common import digest, request, read_json, write_json

MODEL = 'jev-1.13.0'
PROMPT_VERSION = 1
THRESHOLD = .90


class JevUnavailable(Exception):
    pass


class Jev:
    def __init__(self, cache, limit=200):
        self.cache = cache
        self.limit = limit
        self.calls = 0
        self.hits = 0
        self.usage = []

    def ask(self, state, questions):
        payload = {'model': MODEL, 'state': state, 'questions': questions}
        cache_file = self.cache / (digest([PROMPT_VERSION, payload]) + '.json')
        stored = read_json(cache_file)
        if stored is not None:
            self.hits += 1
            response = stored
        else:
            if not os.environ.get('TYPESAFE_API_KEY'):
                raise JevUnavailable('api_key_missing')
            if self.calls >= self.limit:
                raise JevUnavailable('request_limit')
            self.calls += 1
            try:
                response = json.loads(request('https://api.typesafe.ai/v1/systemone', payload, os.environ['TYPESAFE_API_KEY']))
            except (OSError, ValueError) as error:
                # Do not log headers or the API key.
                raise JevUnavailable('api_error:' + type(error).__name__) from error
            self.validate(response, questions)
            write_json(cache_file, response)
            self.usage.append(response.get('usage', {}))
        self.validate(response, questions)
        return response['answers']

    @staticmethod
    def validate(response, questions):
        if response.get('model') != MODEL:
            raise JevUnavailable('unexpected_model')
        answers = response.get('answers')
        if not isinstance(answers, dict) or set(answers) != set(questions):
            raise JevUnavailable('invalid_answers')
        for name, question in questions.items():
            a = answers[name]
            if a.get('choice') not in question['criteria'] or not isinstance(a.get('confidence'), (float, int)) or not 0 <= a['confidence'] <= 1:
                raise JevUnavailable('invalid_choice')
            probs = a.get('probabilities')
            if not isinstance(probs, dict) or set(probs) != set(question['criteria']) or any(not isinstance(p, (int, float)) or not 0 <= p <= 1 for p in probs.values()):
                raise JevUnavailable('invalid_probabilities')


def choice(instructions, criteria):
    return {'type': 'choice', 'instructions': instructions, 'criteria': criteria}


def confident(answer, selected):
    return answer['choice'] == selected and answer['confidence'] >= THRESHOLD
