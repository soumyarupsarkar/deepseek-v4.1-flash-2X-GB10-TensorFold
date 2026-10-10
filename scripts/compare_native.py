"""Compare matched benchmark receipts and emit only reviewed aggregate fields.

This validates workload matching. It does not decide feature/stability gates or
automatically approve a cutover. Different engines may produce different token
hashes; that count is reported, never silently treated as correctness proof.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics

METRICS = ('aggregate_e2e_tps', 'sampled_steady_decode_tps', 'ttft_s_p50',
           'ttft_s_p95', 'effective_prefill_tps', 'engine_prefill_tps', 'latency_s_p95')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def compare(reference, candidate):
    for receipt in (reference, candidate):
        if receipt.get('status') != 'passed' or not receipt.get('rows'):
            raise ValueError('Require two complete, passing benchmark receipts')
    def indexed(receipt):
        result = {canonical(row['case']): row for row in receipt['rows']}
        if len(result) != len(receipt['rows']):
            raise ValueError('Duplicate cases; use explicit repetition numbers')
        return result
    left, right = indexed(reference), indexed(candidate)
    if left.keys() != right.keys():
        raise ValueError('Cases differ; compare exact concurrency, prompt/output budgets and sampling')
    groups = {}
    matched_requests = 0
    matching_output_hashes = 0
    for key in left:
        before, after = left[key], right[key]
        case = before['case']
        lrows, rrows = (sorted(row['results'], key=lambda x: x['index']) for row in (before, after))
        if len(lrows) != case['streams'] or len(rrows) != case['streams']:
            raise ValueError('Incomplete wave')
        for x, y in zip(lrows, rrows):
            if (x['index'] != y['index'] or x['prompt_sha256'] != y['prompt_sha256']
                    or x['usage']['prompt_tokens'] != y['usage']['prompt_tokens']
                    or x['usage']['completion_tokens'] != case['reply_tokens']
                    or y['usage']['completion_tokens'] != case['reply_tokens']):
                raise ValueError('Actual prompt hashes or completed token budgets differ')
            if case.get('cache', 'cold') == 'cold' and (x['tensorfold']['cached'] or y['tensorfold']['cached']):
                raise ValueError('A cold wave reused cached tokens')
            matched_requests += 1
            lhash, rhash = (r['tensorfold'].get('token_sha') for r in (x, y))
            matching_output_hashes += bool(lhash and lhash == rhash)
        group_case = {k: v for k, v in case.items() if k != 'rep'}
        group = groups.setdefault(canonical(group_case), dict(case=group_case, reference=[], candidate=[]))
        for label, row in (('reference', before), ('candidate', after)):
            group[label].append(dict(repetition=case.get('rep'),
                metrics={name: row['summary'].get(name) for name in METRICS},
                peak_decoding=row['summary']['peak_decoding'],
                native_graph_captures_during_wave=row.get('native_graph_captures_during_wave')))
    output = []
    for group in groups.values():
        comparison = {}
        for metric in METRICS:
            values = {label: [row['metrics'][metric] for row in group[label]]
                      for label in ('reference', 'candidate')}
            # Missing steady intervals stay missing. Do not select only a
            # convenient repetition or substitute end-to-end rates.
            medians = {label: statistics.median(rows) if rows and all(x is not None for x in rows) else None
                       for label, rows in values.items()}
            a, b = medians['reference'], medians['candidate']
            comparison[metric] = dict(**medians, candidate_change_percent=(b / a - 1) * 100
                                     if a is not None and a > 0 and b is not None else None)
        output.append(dict(group, median_comparison=comparison))
    return dict(status='workloads-matched', matched_waves=len(left), matched_requests=matched_requests,
        matching_output_hashes=matching_output_hashes,
        reference_image=reference['launch']['image'], candidate_image=candidate['launch']['image'],
        rows=output,
        notes=['Synthetic fixtures; output-token hash equality is reported separately from workload matching.',
               'Positive throughput changes are faster; positive latency changes are slower.',
               'Native graph captures remain included in elapsed measurements.',
               'This comparison does not establish feature, capacity, recovery or endurance qualification.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    before, after = args.reference.read_bytes(), args.candidate.read_bytes()
    result = compare(json.loads(before), json.loads(after))
    result['reference_receipt_sha256'] = hashlib.sha256(before).hexdigest()
    result['candidate_receipt_sha256'] = hashlib.sha256(after).hexdigest()
    with args.output.open('x') as stream:
        stream.write(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print('Matched', result['matched_waves'], 'waves and', result['matched_requests'], 'requests')


if __name__ == '__main__':
    main()
