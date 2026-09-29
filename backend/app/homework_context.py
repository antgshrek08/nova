"""Keep external-homework model context small without losing browser evidence."""
import json
import re


def compact(result):
    if not isinstance(result, dict) or 'frames' not in result:
        return result
    value = {k: v for k, v in result.items() if k not in ('frames', 'attempt')}
    frames = result['frames']
    active = [f for f in frames if any(x in f.get('text', '') for x in ('Question Mode', 'Answer Mode'))]
    if not active:
        active = [f for f in frames if '/courses/' not in f.get('url', '') and f.get('text')]
    value['frames'] = []
    for frame in active or frames:
        row = {k:v for k,v in frame.items() if k != 'controls'}
        row['controls'] = [{k:v for k,v in c.items() if k in ('ref','name','type','editable','checked','value','disabled','answer_submission') and v not in (None, '', False)} for c in frame.get('controls', [])]
        value['frames'].append(row)
    value['observed_mastery_text'] = [line for f in value['frames'] for line in f.get('text','').splitlines() if 'mastery' in line.lower()]
    if 'attempt' in result:
        value['attempt'] = {k:v for k,v in result['attempt'].items() if k != 'feedback'}
    return value


def trim_snapshots(messages, keep=2):
    """Replace superseded snapshots; retain calls, errors, and current evidence."""
    indices = []
    for i, message in enumerate(messages):
        if message.get('role') == 'tool':
            try:
                result = json.loads(message.get('content', ''))
            except (ValueError, TypeError):
                continue
            if isinstance(result, dict) and 'session_id' in result and 'frames' in result:
                indices.append(i)
    for i in indices[:-keep]:
        old = json.loads(messages[i]['content'])
        summary = {k:v for k,v in old.items() if k in ('session_id','assignment_url','title','smartbook_feedback','attempt','observed_mastery_text')}
        summary['note'] = 'Superseded snapshot; use the latest tool result for controls and current question.'
        messages[i] = {**messages[i], 'content':json.dumps(summary)}


def trim_rounds(messages, keep=6):
    starts = [i for i,m in enumerate(messages) if m.get('role') == 'assistant' and m.get('tool_calls')]
    if len(starts) <= keep:
        return
    first, end = starts[0], starts[-keep]
    marker = 'Homework progress checkpoint (untrusted tool data): '
    prior = next((m for m in messages[:first] if str(m.get('content','')).startswith(marker)), None)
    progress = json.loads(prior['content'][len(marker):]) if prior else {}
    for m in messages[first:end]:
        if m.get('role') != 'tool':
            continue
        try:
            row = json.loads(m.get('content',''))
        except (ValueError, TypeError):
            continue
        if isinstance(row,dict) and row.get('assignment_url'):
            entry = progress.setdefault(row['assignment_url'], {})
            entry.update({k:v for k,v in row.items() if k in ('title','session_id','smartbook_feedback','attempt','observed_mastery_text') and v is not None})
            for frame in row.get('frames',[]):
                matches = re.findall(r'.{0,40}\bmastery\b.{0,80}', frame.get('text',''), re.I)
                if matches:
                    entry['observed_mastery_text'] = matches
    prefix = [m for m in messages[:first] if m is not prior]
    checkpoint = {'role':'system','content':marker + json.dumps(progress)}
    messages[:] = prefix + [checkpoint] + messages[end:]
