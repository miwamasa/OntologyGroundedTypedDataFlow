from __future__ import annotations
import ast, re
from dataclasses import dataclass
from pathlib import Path

@dataclass
class SourceStmt:
    name: str; declared: str; fn: str; args: list; kwargs: dict
@dataclass
class LetStmt:
    name: str; fn: str; args: list; kwargs: dict; emit: bool=False
@dataclass
class Program:
    name: str; settings: dict; sources: list[SourceStmt]; lets: list[LetStmt]

def _call(expr: str):
    node=ast.parse(expr.strip(),mode='eval').body
    if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Name):
        raise SyntaxError(f"expected function call: {expr}")
    args=[]; kwargs={}
    def conv(v):
        if isinstance(v, ast.Name): return ("$ref", v.id)
        if isinstance(v, ast.List): return [conv(z) for z in v.elts]
        return ast.literal_eval(v)
    for a in node.args:
        args.append(conv(a))
    for kw in node.keywords:
        v=kw.value
        kwargs[kw.arg]=conv(v)
    return node.func.id,args,kwargs

def parse(path: str|Path) -> Program:
    name="pipeline"; settings={}; sources=[]; lets=[]
    for raw in Path(path).read_text(encoding='utf-8').splitlines():
        line=raw.strip()
        if not line or line.startswith('#'): continue
        if line.startswith('pipeline '): name=line.split(None,1)[1].strip(); continue
        if line.startswith('set '):
            k,v=line[4:].split('=',1); settings[k.strip()]=ast.literal_eval(v.strip()); continue
        m=re.match(r'source\s+(\w+)\s*::\s*([^=]+?)\s*=\s*(.+)$',line)
        if m:
            fn,args,kwargs=_call(m.group(3)); sources.append(SourceStmt(m.group(1),m.group(2).strip(),fn,args,kwargs)); continue
        m=re.match(r'(let|emit)\s+(\w+)\s*=\s*(.+)$',line)
        if m:
            fn,args,kwargs=_call(m.group(3)); lets.append(LetStmt(m.group(2),fn,args,kwargs,m.group(1)=='emit')); continue
        raise SyntaxError(f"cannot parse line: {line}")
    return Program(name,settings,sources,lets)
