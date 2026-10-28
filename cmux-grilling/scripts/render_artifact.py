"""Render the human protocol from a grilling artifact and round metadata."""
from __future__ import annotations

import html
from pathlib import Path

from artifact_pair import REVIEW_LISTS, single_line, timestamp
from orchestrator_lib import LANES, read_json
from transcribe_artifact import transcribe


def quote(value: str) -> str:
    """Keep every free-text line out of the protocol's heading and entry grammar."""
    if not isinstance(value, str):
        raise ValueError('protocol text must be a string')
    return '\n'.join('> ' + html.escape(line, quote=False) for line in value.splitlines() or [''])


def quote_all(values: object) -> list[str]:
    if not isinstance(values, list):
        raise ValueError('protocol sources must be a list of strings')
    return [quote(value) for value in values]


def round_deferrals(run_dir: Path, rounds: int) -> dict[int, list[dict]]:
    deferred = {}
    for number in range(1, rounds + 1):
        source = run_dir / 'synthesis' / f'round-{number}.json'
        data = read_json(source)
        if not isinstance(data, dict) or data.get('round') != number or not isinstance(data.get('questions'), list):
            raise ValueError(f'invalid synthesis metadata: {source}')
        entries = data.get('deferred', [])
        if not isinstance(entries, list) or any(
                not isinstance(item, dict) or any(not isinstance(item.get(key), str) or not item[key].strip()
                                                 for key in ('id', 'question', 'reason')) for item in entries):
            raise ValueError(f'invalid deferred questions: {source}')
        deferred[number] = entries
    return deferred


def render_protocol(data: dict, run_dir: Path, title: str | None = None) -> str:
    state = read_json(run_dir / 'state.json')
    if not isinstance(state, dict) or state.get('run_id') != data.get('run_id'):
        raise ValueError('run directory belongs to a different run_id than the artifact')
    generated = state.get('created_at')
    if not timestamp(generated):
        raise ValueError('run created_at must be an ISO timestamp with timezone')
    rounds = data['roundsRun']
    if (type(rounds) is not int or rounds < 0 or type(data['maxRounds']) is not int
            or not rounds <= data['maxRounds']):
        raise ValueError('roundsRun must be a non-negative integer within maxRounds')
    deferred = round_deferrals(run_dir, rounds)
    title = title if title is not None else data['task']
    if not isinstance(title, str) or not title.strip():
        raise ValueError('protocol title must be non-empty text')
    qa = data['qa']
    if (type(data['questionsAsked']) is not int or not isinstance(qa, list)
            or len(qa) != data['questionsAsked']):
        raise ValueError('qa must contain exactly questionsAsked entries')
    by_round = {number: {} for number in range(1, rounds + 1)}
    for item in qa:
        if (not isinstance(item, dict) or type(item.get('round')) is not int
                or not 1 <= item['round'] <= rounds or not single_line(item.get('id'))):
            raise ValueError('qa entries need a round within roundsRun and a question id')
        if item['id'] in by_round[item['round']]:
            raise ValueError(f"duplicate qa entry: {(item['round'], item['id'])}")
        by_round[item['round']][item['id']] = item
    lines = ['# ' + html.escape(' '.join(title.splitlines()), quote=False), '',
             'Generiert:', quote(generated), '', 'Fragen:', quote(str(data['questionsAsked'])), '',
             'Stop-Grund:', quote(data['stopReason']), '', '## Aufgabe', '', quote(data['task']), '', '## Q&A', '']
    for number, questions in by_round.items():
        lines += [f'### Runde {number}', '']
        for item in questions.values():
            lines += ['Frage:', quote(item['id'] + ': ' + item['question']), '']
            for label, field in (('Antwort', 'answer'), ('Confidence', 'confidence')):
                lines += [label + ':', quote(item[field]), '']
            lines += ['Quellen:']
            lines += quote_all(item['sources'])
            lines += ['', 'Reasoning:', quote(item['reasoning']), '', '<details>',
                      '<summary>Lane Findings</summary>', '']
            for lane in LANES:
                finding = item['findings'][lane]
                lines += [lane + ':', quote(finding['result']), quote(finding['answer'])]
                lines += quote_all(finding['sources'])
                lines += ['']
            lines += ['</details>', '']
        for item in deferred[number]:
            lines += ['Zurückgestellte Frage:', quote(item['id'] + ': ' + item['question']),
                      '', 'Grund:', quote(item['reason']), '']
    for review_list in REVIEW_LISTS:
        lines += ['## ' + review_list.heading, '']
        # Transcription supplies markers with the same renderer used by later reviews.
        if review_list.name not in data:
            for index, text in enumerate(data.get(review_list.texts_name, []), 1):
                if not single_line(text):
                    raise ValueError(f'{review_list.texts_name} entries must be single-line strings')
                lines += [review_list.entry_marker.format(index=index) + text]
        lines += ['']
    lines += ['## Offene Fakten', '', '## Entscheidungen', '']
    for entry in data['open_decisions']:
        if not single_line(entry['id']):
            raise ValueError('decision id must be a single line')
        lines += ['### ' + entry['id'], '']
        for label, key in (('Frage', 'question'), ('Offen wegen', 'why_open'), ('Kontext', 'context')):
            lines += [label + ':', quote(entry[key]), '']
        lines += ['Belege:'] + [quote(value) for value in entry['evidence']] + ['', 'Optionen mit Implikation:']
        for option in entry['options']:
            lines += [quote(option['label'] + ': ' + option['implication'])]
        lines += ['', 'Empfehlung:', quote(entry['recommendation']), '', 'Begründung:', quote(entry['rationale']), '']
    return transcribe(data, '\n'.join(lines).rstrip() + '\n')
