from __future__ import annotations
import argparse, json, sys
from .engine import Engine

def main(argv=None):
    p=argparse.ArgumentParser(prog='mslt',description='Ontology-grounded typed multistate life-table pipeline')
    sub=p.add_subparsers(dest='cmd',required=True)
    for cmd in ['check','run','explain']:
        q=sub.add_parser(cmd); q.add_argument('program'); q.add_argument('--data-root',default='.'); q.add_argument('--out',default='outputs')
    a=p.parse_args(argv)
    try:
        e=Engine(a.program,a.data_root)
        if a.cmd=='check':
            # Type-level evaluation only: no CSV is opened, so this reports
            # ill-typed programs even where the data is not available.
            tenv=e.typecheck()
            width=max((len(k) for k in tenv),default=0)
            for name,t in tenv.items():
                print(f'  {name.ljust(width)} : {t.short()}')
            print(f'OK: {e.program.name}; {len(tenv)} typed nodes')
            return 0
        env=e.run()
        if a.cmd=='explain': print('\n\n'.join(e.trace))
        else:
            out=e.write_outputs(a.out); print(f'Wrote {out}')
            if 'indicators' in env:
                print(json.dumps(env['indicators'].rows,ensure_ascii=False,indent=2))
    except Exception as ex:
        print(f'ERROR: {ex}',file=sys.stderr); return 2
    return 0

if __name__=='__main__': raise SystemExit(main())
