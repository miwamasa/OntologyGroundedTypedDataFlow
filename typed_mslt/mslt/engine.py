from __future__ import annotations
import csv, json
from pathlib import Path
from .dsl import parse
from .adapters import ADAPTERS, ADAPTER_TYPES
from .transforms import OPS, TYPE_OPS
from .ontology import Ontology
from .types import SemanticType, SemanticTypeError

class Engine:
    def __init__(self, program_path: str, data_root: str='.', ontology_path: str|None=None):
        self.program=parse(program_path); self.data_root=Path(data_root); self.env={}; self.trace=[]
        opath=ontology_path or (Path(program_path).parent.parent/'ontology'/'marital.yaml')
        self.ontology=Ontology.load(opath)

    def _resolve(self,x,env=None):
        env=self.env if env is None else env
        if isinstance(x,tuple) and len(x)==2 and x[0]=='$ref': return env[x[1]]
        if isinstance(x,list): return [self._resolve(v,env) for v in x]
        return x

    def _check_declared(self, stmt, t: SemanticType) -> None:
        if stmt.declared.split('<',1)[0].strip() not in {t.kind,'Estimated'}:
            raise SemanticTypeError(f"source {stmt.name}: declared {stmt.declared}, adapter produced {t.short()}")

    def _check_ontology(self, t: SemanticType) -> None:
        if t.source_state and t.target_state:
            self.ontology.validate_transition(t.source_state,t.target_state)

    # -- static type checking -------------------------------------------
    def typecheck(self) -> dict[str, SemanticType]:
        """Derive every node's semantic type without reading any data file.

        The pipeline is evaluated in the type interpretation alone: adapters
        contribute the type their table yields, and each transformation's
        signature maps input types to an output type. A program that is
        ill-typed therefore fails here, in milliseconds, whether or not the
        CSVs it names are present.
        """
        tenv: dict[str, SemanticType] = {}
        for s in self.program.sources:
            if s.fn not in ADAPTER_TYPES: raise KeyError(f"unknown adapter {s.fn}")
            kwargs={k:self._resolve(v,tenv) for k,v in s.kwargs.items()}
            t=ADAPTER_TYPES[s.fn](**kwargs)
            self._check_declared(s,t)
            self._check_ontology(t)
            tenv[s.name]=t
        for st in self.program.lets:
            if st.fn not in TYPE_OPS: raise KeyError(f"unknown operation {st.fn}")
            args=[self._resolve(x,tenv) for x in st.args]
            kwargs={k:self._resolve(v,tenv) for k,v in st.kwargs.items()}
            tenv[st.name]=TYPE_OPS[st.fn](*args,**kwargs)
        return tenv

    # -- evaluation ------------------------------------------------------
    def load_sources(self):
        for s in self.program.sources:
            if s.fn not in ADAPTERS: raise KeyError(f"unknown adapter {s.fn}")
            args=[self._resolve(x) for x in s.args]; kwargs={k:self._resolve(v) for k,v in s.kwargs.items()}
            if args and isinstance(args[0],str): args[0]=str((self.data_root/args[0]).resolve())
            f=ADAPTERS[s.fn](*args,**kwargs); f.name=s.name
            self._check_declared(s,f.type)
            self._check_ontology(f.type)
            self.env[s.name]=f; self.trace.append(f.explain())

    def run(self):
        self.load_sources()
        for st in self.program.lets:
            if st.fn not in OPS: raise KeyError(f"unknown operation {st.fn}")
            args=[self._resolve(x) for x in st.args]; kwargs={k:self._resolve(v) for k,v in st.kwargs.items()}
            f=OPS[st.fn](*args,**kwargs); f.name=st.name; self.env[st.name]=f; self.trace.append(f.explain())
        return self.env

    def write_outputs(self,outdir: str):
        out=Path(outdir); out.mkdir(parents=True,exist_ok=True)
        (out/'type_trace.txt').write_text('\n\n'.join(self.trace),encoding='utf-8')
        manifest={k:{"type":v.type.short(),"rows":len(v.rows),"provenance":v.provenance,"assumptions":v.assumptions} for k,v in self.env.items()}
        (out/'semantic_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        for k,v in self.env.items():
            if not v.rows: continue
            if any('matrix' in r for r in v.rows): continue
            keys=[]
            for r in v.rows:
                for x in r:
                    if x not in keys: keys.append(x)
            with open(out/f'{k}.csv','w',encoding='utf-8-sig',newline='') as f:
                w=csv.DictWriter(f,fieldnames=keys); w.writeheader(); w.writerows(v.rows)
        return out
