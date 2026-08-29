from __future__ import annotations
import csv, inspect, json
from pathlib import Path
from .dsl import parse
from .adapters import ADAPTERS, ADAPTER_TYPES
from .transforms import OPS, TYPE_OPS
from .ontology import Ontology
from .types import SemanticType, SemanticTypeError

class Engine:
    def __init__(self, program_path: str, data_root: str='.', ontology_path: str|None=None,
                 overrides: dict[str,dict]|None=None, source_cache: dict|None=None):
        """
        ``overrides`` replaces named keyword arguments of every statement that
        calls a given operation, which is how a sensitivity sweep re-runs the
        same program under a different assumption. ``source_cache``, when
        supplied, memoizes adapter results across engines so a sweep parses
        each CSV once rather than once per combination.
        """
        self.program=parse(program_path); self.data_root=Path(data_root); self.env={}; self.trace=[]
        self.overrides=overrides or {}
        self.source_cache=source_cache
        self.ontology=Ontology.load(self._ontology_path(program_path,ontology_path))

    def _apply_overrides(self, fn_name: str, kwargs: dict) -> dict:
        override=self.overrides.get(fn_name)
        return {**kwargs, **override} if override else kwargs

    def _ontology_path(self, program_path: str, override: str|None) -> Path:
        """Resolve which ontology this program is modelled against.

        An explicit argument wins, then a `set ontology = "..."` line in the
        program (resolved relative to the program), then the default. Choosing
        the ontology chooses the state space and the shape of G(x), so the same
        program can be run as a different model.
        """
        if override: return Path(override)
        declared=self.program.settings.get('ontology')
        if declared: return Path(program_path).parent / declared
        return Path(program_path).parent.parent/'ontology'/'marital.yaml'

    def _resolve(self,x,env=None):
        env=self.env if env is None else env
        if isinstance(x,tuple) and len(x)==2 and x[0]=='$ref': return env[x[1]]
        if isinstance(x,list): return [self._resolve(v,env) for v in x]
        return x

    def _with_ontology(self, fn, kwargs: dict) -> dict:
        """Supply the ontology to operations that declare they depend on it."""
        if 'ontology' in inspect.signature(fn).parameters:
            return {**kwargs, 'ontology': self.ontology}
        return kwargs

    def _check_declared(self, stmt, t: SemanticType) -> None:
        if stmt.declared.split('<',1)[0].strip() not in {t.kind,'Estimated'}:
            raise SemanticTypeError(f"source {stmt.name}: declared {stmt.declared}, adapter produced {t.short()}")

    def _check_ontology(self, name: str, t: SemanticType) -> None:
        if not (t.source_state and t.target_state): return
        src,dst=t.source_state,t.target_state
        unknown=[s for s in (src,dst) if s not in self.ontology.states]
        if unknown:
            raise SemanticTypeError(
                f"source {name}: transition {src}->{dst} names states {unknown} "
                f"absent from ontology {self.ontology.name!r}")
        if not self.ontology.is_licensed(src,dst):
            raise SemanticTypeError(
                f"source {name}: transition {src}->{dst} is not licensed by "
                f"ontology {self.ontology.name!r}")

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
            kwargs=self._apply_overrides(s.fn,{k:self._resolve(v,tenv) for k,v in s.kwargs.items()})
            t=ADAPTER_TYPES[s.fn](**kwargs)
            self._check_declared(s,t)
            self._check_ontology(s.name,t)
            tenv[s.name]=t
        for st in self.program.lets:
            if st.fn not in TYPE_OPS: raise KeyError(f"unknown operation {st.fn}")
            fn=TYPE_OPS[st.fn]
            args=[self._resolve(x,tenv) for x in st.args]
            kwargs=self._apply_overrides(st.fn,{k:self._resolve(v,tenv) for k,v in st.kwargs.items()})
            tenv[st.name]=fn(*args,**self._with_ontology(fn,kwargs))
        return tenv

    # -- evaluation ------------------------------------------------------
    def _adapt(self, fn_name, args, kwargs):
        """Call an adapter, reusing a cached frame when a sweep has one."""
        if self.source_cache is None:
            return ADAPTERS[fn_name](*args,**kwargs)
        key=(fn_name,tuple(args),tuple(sorted(kwargs.items())))
        if key not in self.source_cache:
            self.source_cache[key]=ADAPTERS[fn_name](*args,**kwargs)
        cached=self.source_cache[key]
        # Hand out a copy: the engine renames frames and callers may mutate.
        return cached.copy()

    def load_sources(self):
        for s in self.program.sources:
            if s.fn not in ADAPTERS: raise KeyError(f"unknown adapter {s.fn}")
            args=[self._resolve(x) for x in s.args]
            kwargs=self._apply_overrides(s.fn,{k:self._resolve(v) for k,v in s.kwargs.items()})
            if args and isinstance(args[0],str): args[0]=str((self.data_root/args[0]).resolve())
            f=self._adapt(s.fn,args,kwargs); f.name=s.name
            self._check_declared(s,f.type)
            self._check_ontology(s.name,f.type)
            self.env[s.name]=f; self.trace.append(f.explain())

    def run(self):
        self.load_sources()
        for st in self.program.lets:
            if st.fn not in OPS: raise KeyError(f"unknown operation {st.fn}")
            fn=OPS[st.fn]
            args=[self._resolve(x) for x in st.args]
            kwargs=self._apply_overrides(st.fn,{k:self._resolve(v) for k,v in st.kwargs.items()})
            f=fn(*args,**self._with_ontology(fn,kwargs)); f.name=st.name
            self.env[st.name]=f; self.trace.append(f.explain())
        return self.env

    def write_outputs(self,outdir: str):
        out=Path(outdir); out.mkdir(parents=True,exist_ok=True)
        (out/'type_trace.txt').write_text('\n\n'.join(self.trace),encoding='utf-8')
        manifest={k:{"type":v.type.short(),"rows":len(v.rows),
                     "depends_on":sorted(v.type.depends_on),
                     "provenance":v.provenance,"assumptions":v.assumptions} for k,v in self.env.items()}
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
