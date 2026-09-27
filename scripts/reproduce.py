"""Offline recalculation from public raw, using the unchanged frozen statistics."""
from pathlib import Path
import argparse
import collections
import json
import math
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
import numpy as np
import pandas as pd
from analysis.statistics import independent_observations, paired_table, summary_table
from context_bench.manifest import verify_manifest
from verify_release import verify

EXPERIMENT = 'gpt6-sol-vs-luna-swbench-v1'
MODELS = ['sol', 'luna']

def require(ok, message):
    if not ok:
        raise ValueError(message)

def calculate():
    rows = [json.loads(x) for x in (ROOT / f'results/experiments/{EXPERIMENT}/full/raw.jsonl').read_text().splitlines()]
    freeze = json.loads((ROOT / f'experiments/{EXPERIMENT}/EXPERIMENT_FREEZE.json').read_text())
    manifest = [json.loads(x) for x in (ROOT / f'experiments/{EXPERIMENT}/manifest.jsonl').read_text().splitlines()]
    errors = verify_manifest(manifest, freeze['tasks'], MODELS, 2, freeze['seed'],
                             experiment_id=EXPERIMENT, model_ids={m:f'openai/gpt-6-{m}' for m in MODELS})
    require(not errors, str(errors))
    ids = set()
    by_id = {}
    roots = {r['run_id'] for r in manifest}
    children = collections.Counter()
    key = lambda r: (r['task_id'], r['model'], r['replicate'])
    for r in rows:
        require(r['schema_version'] == 2 and r['experiment_id'] == EXPERIMENT and r['phase'] == 'full', 'Mixed experiment or phase')
        require(r['opencode_model_id'] == f"openai/gpt-6-{r['model']}", 'Wrong model ID')
        require(r['run_id'] not in ids, 'Duplicate run ID')
        parent = r['retry_of']
        if parent:
            require(parent in ids and key(by_id[parent]) == key(r), 'Broken retry lineage')
            children[parent] += 1
            require(children[parent] == 1, 'Branched retry chain')
        else:
            require(r['run_id'] in roots, 'Unplanned root observation')
        ids.add(r['run_id'])
        by_id[r['run_id']] = r
    require(roots == {r['run_id'] for r in rows if not r['retry_of']}, 'Missing manifest roots')
    raw = pd.DataFrame(rows)
    terminal = independent_observations(raw)
    require(len(terminal) == len(manifest) == 120 and len(rows) == 136, 'Incorrect record count')
    require(collections.Counter(key(r) for r in terminal.to_dict('records')) == collections.Counter(key(r) for r in manifest), 'Incomplete canonical coverage')
    paired = paired_table(raw)
    frozen = summary_table(raw)
    outcomes = []
    for model in MODELS:
        d = terminal[terminal.model == model]
        solved = int(d.resolved.eq(True).sum())
        no_verdict = int(d.resolved.isna().sum())
        require(all(d.loc[d.resolved.isna(), 'patch_size'] == 0), 'Unexpected missing verdict')
        outcomes.append(dict(model=model, resolved=solved, unresolved=int(d.resolved.eq(False).sum()),
                             no_verdict_empty_patch=no_verdict, n_canonical=len(d), resolved_rate_of_60=solved/len(d)))
    metrics = []
    for variable, column in [('runtime_s','duration_s'),('input_tokens','input_tokens'),('output_tokens','output_tokens'),
                             ('reasoning_tokens','reasoning_tokens'),('total_tokens','total_tokens'),('tool_calls','tool_calls'),
                             ('patch_bytes','patch_size'),('lines_added','lines_added'),('lines_deleted','lines_deleted')]:
        for model in MODELS:
            v = terminal.loc[terminal.model == model, column].dropna()
            metrics.append(dict(model=model, variable=variable, mean=float(v.mean()), median=float(v.median()),
                                q1=float(v.quantile(.25)), q3=float(v.quantile(.75)), total=float(v.sum()), n=len(v)))
    task_rows = []
    for task in sorted(terminal.task_id.unique()):
        d = terminal[terminal.task_id == task].set_index(['model','replicate'])
        row = {'repo':task.split('__')[0], 'task_id':task}
        for model in MODELS:
            for rep in [1,2]:
                v = d.loc[(model,rep),'resolved']
                row[f'{model}_r{rep}'] = 'NONE' if pd.isna(v) else ('PASS' if v else 'FAIL')
        task_rows.append(row)
    b = int((paired.category == 'only Sol').sum())
    c = int((paired.category == 'only Luna').sum())
    one_sided = sum(math.comb(b+c,k) for k in range(min(b,c)+1)) / 2**(b+c)
    stats = {'paired_effect_luna_minus_sol_pp':frozen.attrs['paired_diff_pp'],
             'paired_diff_ci_95_pp':list(frozen.attrs['paired_diff_ci']),
             'mcnemar_exact_two_sided_p':min(1.0,2*one_sided),
             'mcnemar_exact_one_sided_p':one_sided,
             'complete_replicate_pairs':len(paired), 'discordant_sol_only_pairs':b,'discordant_luna_only_pairs':c}
    for _, r in frozen.iterrows():
        stats['task_rate_'+r.model] = float(r.resolved_rate)
        stats['task_rate_ci_'+r.model] = [float(r.ci_low),float(r.ci_high)]
    reliability = {'physical_raw_records':len(raw),'canonical_terminal_observations':len(terminal),
                   'infrastructure_retries':int(raw.retry_of.notna().sum()),
                   'terminal_provider_errors':int(terminal.provider_errors.apply(bool).sum()),
                   'terminal_timeouts':int(terminal.timeout.sum()),
                   'terminal_exit_nonzero':int(terminal.exit_status.ne(0).sum()),
                   'model_empty_patch_no_verdict':int(terminal.resolved.isna().sum())}
    return terminal, paired, frozen, pd.DataFrame(outcomes), pd.DataFrame(metrics), pd.DataFrame(task_rows), stats, reliability

def compare_article(outcomes, paired, metrics, tasks, stats, reliability):
    tables = ROOT / 'article_analysis/tables'
    old = pd.read_csv(tables/'table01_outcomes_by_model.csv').set_index('model')
    new = outcomes.set_index('model')
    for model in MODELS:
        for col in old.columns:
            require(abs(old.loc[model,col]-new.loc[model,col]) <= .00051, f'Article outcome mismatch: {model}/{col}')
    old = pd.read_csv(tables/'table02_paired_outcomes.csv').set_index('category')
    for cat in ['both solved','only Sol','only Luna','neither']:
        require(int(old.loc[cat,'complete_replicate_pairs']) == int((paired.category == cat).sum()), f'Pair mismatch: {cat}')
    old = pd.read_csv(tables/'table03_task_level.csv').set_index('task_id')
    new = tasks.set_index('task_id')
    for col in ['sol_r1','sol_r2','luna_r1','luna_r2']:
        require(old[col].equals(new[col]), f'Task outcome mismatch: {col}')
    new = metrics.set_index(['model','variable'])
    for file in ['table04_runtime_tokens.csv','table05_patch_metrics.csv']:
        old = pd.read_csv(tables/file, dtype=str).fillna('')
        for _, r in old.iterrows():
            for col in ['mean','median','q1','q3','total','n']:
                if col not in r or r[col] == '': continue
                digits = len(r[col].split('.')[1]) if '.' in r[col] else 0
                tolerance = .5 * 10**(-digits) + 1e-8
                require(abs(float(r[col])-new.loc[(r.model,r.variable),col]) <= tolerance, f'Article metric mismatch: {r.model}/{r.variable}/{col}')
    for _,r in pd.read_csv(tables/'table06_reliability.csv').iterrows():
        if r.metric in {'terminal_patch_application_failures', 'terminal_malformed_patches'}:
            continue  # These historical log-derived claims have no dedicated raw fields.
        require(reliability[r.metric] == r.value, f'Reliability mismatch: {r.metric}')
    for _,r in pd.read_csv(tables/'table07_frozen_statistics.csv').iterrows():
        if r.statistic not in stats: continue
        target=json.loads(r.value)
        require(np.allclose(stats[r.statistic], target, rtol=0, atol=.0051 if 'pp' in r.statistic else .00051), f'Frozen statistic mismatch: {r.statistic}')
    print('PASS: article outcomes, pairs, all task verdicts, descriptive metrics, raw-backed reliability and frozen statistics (published rounding)')
    print('NOT CHECKED: malformed/application-failure log claims; original evaluator logs are not distributed.')

def figures(out, terminal, paired, outcomes, tasks):
    figdir=out/'figures'; figdir.mkdir(parents=True,exist_ok=True)
    colors=['#325ea8','#e59a35']
    def save(fig,name):
        fig.tight_layout(); fig.savefig(figdir/f'{name}.png',dpi=160); plt.close(fig)
    fig,ax=plt.subplots(figsize=(7,4))
    ax.bar(['Sol','Luna'],outcomes.resolved_rate_of_60*100,color=colors)
    ax.set(ylabel='Resolved runs (%)',ylim=(0,100),title='All 60 terminal observations per model')
    for i,r in outcomes.iterrows(): ax.text(i,r.resolved_rate_of_60*100+2,f'{r.resolved}/60',ha='center')
    save(fig,'fig01_resolved_rate')
    fig,ax=plt.subplots(figsize=(7,4))
    cats=['both solved','only Sol','only Luna','neither']
    ax.bar(cats,[int((paired.category==c).sum()) for c in cats],color=['#5c9473',*colors,'#999999'])
    ax.set(ylabel='Complete replicate pairs',title='55 complete pairs; 5 excluded by frozen missing-verdict rule')
    save(fig,'fig02_paired_composition')
    for column,name,label in [('duration_s','fig03_runtime','Agent runtime (seconds)'),('total_tokens','fig04_total_tokens','Total tokens'),('reasoning_tokens','fig05_reasoning_tokens','Reasoning tokens'),('patch_size','fig07_patch_size','Patch size (bytes)')]:
        fig,ax=plt.subplots(figsize=(7,4)); ax.boxplot([terminal.loc[terminal.model==m,column].dropna() for m in MODELS],tick_labels=['Sol','Luna'])
        ax.set(ylabel=label,title='60 terminal observations per model'); save(fig,name)
    cols=['sol_r1','sol_r2','luna_r1','luna_r2']
    arr=tasks[cols].replace({'NONE':0,'FAIL':1,'PASS':2}).to_numpy(dtype=float)
    fig,ax=plt.subplots(figsize=(9,11)); ax.imshow(arr,cmap=ListedColormap(['#dddddd','#e4a19b','#74bfa5']),vmin=0,vmax=2,aspect='auto')
    ax.set_xticks(range(4),cols);ax.set_yticks(range(len(tasks)),tasks.task_id,fontsize=8)
    ax.set_title('Task verdicts: green PASS, red FAIL, gray NONE');save(fig,'fig06_task_heatmap')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'reproduced')
    args=parser.parse_args()
    out=args.output.resolve()
    require(out != ROOT and ROOT/'article_analysis' not in (out,*out.parents), 'Use a separate output directory')
    verify()
    terminal,paired,frozen,outcomes,metrics,tasks,stats,reliability=calculate()
    compare_article(outcomes,paired,metrics,tasks,stats,reliability)
    out.mkdir(parents=True,exist_ok=True)
    for name,table in [('outcomes',outcomes),('pairs',paired),('task_verdicts',tasks),('descriptive_metrics',metrics),('frozen_task_rates',frozen),('canonical_observations',terminal)]:
        table.to_csv(out/f'{name}.csv',index=False)
    (out/'statistics.json').write_text(json.dumps(stats,indent=2)+'\n',encoding='utf-8')
    (out/'reliability.json').write_text(json.dumps(reliability,indent=2)+'\n',encoding='utf-8')
    figures(out,terminal,paired,outcomes,tasks)
    print('PASS: 136 physical records -> 120 terminal observations; Sol 33/60, Luna 23/60')
    print(json.dumps(stats,indent=2))
    print('Saved recalculated tables and seven figures. No model, network or Docker calls were made.')

if __name__ == '__main__':
    main()
