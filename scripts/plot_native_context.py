"""Plot matched C1 deep-context results with median and observed run range.

Input is compare_native.py's aggregate JSON, never raw prompts or service logs.
Requires Matplotlib (available in the pinned recipe container); serving does not
depend on this plotting tool. Preserve the JSON alongside generated figures.
"""
import argparse
import json
import math
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('comparison', type=Path)
    parser.add_argument('--output-prefix', type=Path, required=True)
    args = parser.parse_args()
    record = json.loads(args.comparison.read_text())
    if record.get('status') != 'workloads-matched':
        raise ValueError('Require a successful matched-workload comparison')
    rows = [row for row in record['rows'] if row['case']['streams'] == 1
            and row['case']['prompt_tokens'] > 0]
    rows.sort(key=lambda row: row['case']['prompt_tokens'] + row['case']['reply_tokens'])
    contexts = [row['case']['prompt_tokens'] + row['case']['reply_tokens'] for row in rows]
    if len(rows) < 2 or len(set(contexts)) != len(contexts):
        raise ValueError('Require one comparable C1 case at each of at least two context lengths')
    for field in ('reply_tokens', 'temperature', 'cache', 'mode', 'prompt_class'):
        if len({row['case'].get(field) for row in rows}) != 1:
            raise ValueError('Context cases differ in ' + field)
    if rows[0]['case']['cache'] != 'cold':
        raise ValueError('This figure describes cold requests')
    counts = {len(row[label]) for row in rows for label in ('reference', 'candidate')}
    if len(counts) != 1 or next(iter(counts)) < 2:
        raise ValueError('Require the same number of at least two repetitions at every point')
    outputs = [args.output_prefix.with_suffix(suffix) for suffix in ('.svg', '.png')]
    if any(path.exists() for path in outputs):
        raise ValueError('Preserve earlier figures; choose a new output prefix')

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'svg.fonttype': 'none'})
    figure, axes = plt.subplots(1, 2, figsize=(12, 4.7), sharex=True)
    panels = [('sampled_steady_decode_tps', 'Steady decode', 'Output tokens / second'),
              ('ttft_s_p50', 'Time to first token', 'Seconds (log scale)')]
    for axis, (metric, title, ylabel) in zip(axes, panels):
        for label, title_label, color in [('reference', 'Python reference', '#3268b2'),
                                          ('candidate', 'Native candidate', '#d46a25')]:
            medians, low, high = [], [], []
            for row in rows:
                values = [item['metrics'][metric] for item in row[label]]
                if any(value is None or not math.isfinite(value) or value <= 0 for value in values):
                    raise ValueError('Missing or invalid ' + metric + '; do not invent a plotted point')
                median = row['median_comparison'][metric][label]
                medians.append(median)
                low.append(median - min(values))
                high.append(max(values) - median)
            axis.errorbar(contexts, medians, yerr=[low, high], color=color, marker='o',
                          linewidth=1.8, capsize=4, label=title_label)
        axis.set_xscale('log', base=2)
        axis.set_xticks(contexts, [f'{x:,}' for x in contexts], rotation=25, ha='right')
        axis.set_xlabel('Prompt + output tokens')
        axis.set_ylabel(ylabel)
        axis.set_title(title, loc='left', fontweight='bold')
        axis.grid(True, alpha=.2)
        axis.spines[['top', 'right']].set_visible(False)
    axes[0].set_ylim(bottom=0)
    axes[1].set_yscale('log')
    axes[0].legend(frameon=False)
    budget = rows[0]['case']['reply_tokens']
    temperature = rows[0]['case']['temperature']
    figure.suptitle('One session across increasing context lengths', x=.08, ha='left', fontweight='bold')
    figure.text(.08, .025,
        f'Cold synthetic prompts · {budget:,} output tokens · temperature {temperature:g} · '
        f'{next(iter(counts))} runs per point\n'
        'Lines: median. Whiskers: observed min–max, not a confidence interval. Graph capture remains in measured time.',
        fontsize=9, color='#555555')
    figure.tight_layout(rect=(.03, .13, .99, .93))
    figure.savefig(outputs[0], metadata={'Date': None, 'Creator': 'TensorFold matched comparison'})
    figure.savefig(outputs[1], dpi=160, metadata={'Software': 'TensorFold matched comparison'})
    plt.close(figure)
    print('Wrote', ', '.join(str(path) for path in outputs))


if __name__ == '__main__':
    main()
