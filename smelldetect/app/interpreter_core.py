#!/usr/bin/env python
# coding: utf-8

#!/usr/bin/env python
# coding: utf-8

from __future__ import annotations

import os
import sys
import lark
from dataclasses import dataclass, field
from typing import Dict, Tuple, List, Optional, Union
from lark import Lark, Transformer, v_args, Token


# ==========================================================
# GRAMMAR
# ==========================================================
GRAMMAR = r"""
%import common.WS
%import common.CNAME
%import common.SIGNED_NUMBER
%import common.ESCAPED_STRING
%ignore WS
%ignore /\/\/[^\n]*/

NAME: /[A-Za-z_][A-Za-z0-9_-]*/

SEMI: ";"
LBRACE: "{"
RBRACE: "}"
DOT: "."
COMMA: ","

AND: "AND"
OR: "OR"
COMP: "==" | "!=" | ">=" | "<=" | ">" | "<"

SCALETYPE: "Nominal" | "Ordinal" | "Interval" | "Ratio" | "Others"

start         : (domain_type | rule_stmt)*
domain_type   : smelltype_decl | smell_decl
smelltype_decl: "smelltype" NAME SEMI? -> smelltype_core
smell_decl    : "smell" NAME opt_extends LBRACE smell_content RBRACE -> smell_decl_core
opt_extends   : "extends" NAME   -> with_extends | -> no_extends
smell_content : feature_decl+ symptom_opt treatment_opt
feature_decl  : "feature" NAME opt_scale "with" "threshold" measure_list SEMI?
opt_scale     : "is" SCALETYPE   -> with_scale | -> no_scale
measure_list  : measure (COMMA measure)*
measure       : NAME | ESCAPED_STRING | SIGNED_NUMBER
symptom_opt   : symptom?
treatment_opt : treatment?
symptom       : "symptom" simple_text SEMI?
treatment     : "treatment" simple_text SEMI?
simple_text   : ESCAPED_STRING | NAME
rule_stmt     : "rule" NAME "when" logic_expr "then" literal SEMI?
logic_expr    : logic_term (OR logic_term)*
logic_term    : logic_factor (AND logic_factor)*
logic_factor  : comparison -> factor_comp | "(" logic_expr ")" -> factor_group
comparison    : ref COMP ref
ref           : NAME DOT NAME
literal       : ESCAPED_STRING | SIGNED_NUMBER | NAME
"""

# ==========================================================
# MODEL
# ==========================================================
@dataclass
class Feature:
    name: str
    scale: Optional[str]
    threshold: List[Union[str, float]]

@dataclass
class Smell:
    name: str
    extends: Optional[str]
    features: Dict[str, Feature] = field(default_factory=dict)
    symptom: Optional[str] = None
    treatment: Optional[str] = None

@dataclass
class Rule:
    name: str
    dnf: List[List[Tuple[Tuple[str, str], str, Tuple[str, str]]]]
    then_literal: Union[str, float]

@dataclass
class DomainModel:
    smelltypes: List[str] = field(default_factory=list)
    smells: Dict[str, Smell] = field(default_factory=dict)
    rules: Dict[str, Rule] = field(default_factory=dict)

# ==========================================================
# TRANSFORMER
# ==========================================================
@v_args(inline=True)
class Builder(Transformer):
    def __init__(self):
        super().__init__()
        self.model = DomainModel()

    def NAME(self, t: Token): return str(t)
    def SCALETYPE(self, t: Token): return str(t)
    def ESCAPED_STRING(self, t: Token): return t[1:-1]
    def SIGNED_NUMBER(self, t: Token): return float(t)

    def smelltype_decl(self, *children):
        for ch in children:
            if isinstance(ch, str):
                self.model.smelltypes.append(ch)
                return
        raise ValueError(f"smelltype_decl: NAME not found in {children!r}")

    def smelltype_core(self, name, *maybe_semi):
        self.model.smelltypes.append(name)

    def opt_extends(self, *xs):
        if not xs: return None
        if len(xs) == 2: return xs[1]
        if len(xs) == 1: return xs[0]
        raise ValueError(f"opt_extends unexpected children: {xs!r}")

    def with_extends(self, name): return name
    def no_extends(self): return None

    def smell_content(self, *parts):
        feats: Dict[str, Feature] = {}
        sym = None
        trt = None
        for p in parts:
            if isinstance(p, Feature):
                feats[p.name] = p
            elif isinstance(p, tuple) and p[0] == "__symptom__":
                sym = p[1]
            elif isinstance(p, tuple) and p[0] == "__treatment__":
                trt = p[1]
        return Smell(name="", extends=None, features=feats, symptom=sym, treatment=trt)

    def feature_decl(self, *children):
        name, scale, measures = None, None, None
        for ch in children:
            if isinstance(ch, list):
                measures = ch
            elif isinstance(ch, str) and ch in ("Nominal", "Ordinal", "Interval", "Ratio", "Others"):
                scale = ch
            elif isinstance(ch, str) and name is None:
                name = ch
        if name is None or measures is None:
            raise ValueError(f"feature_decl inválido: {children!r}")
        return Feature(name=name, scale=scale, threshold=measures)

    def smell_decl_core(self, *children):
        name, ext, content = None, None, None
        for ch in children:
            if isinstance(ch, Smell):
                content = ch
            elif isinstance(ch, str):
                if name is None:
                    name = ch
                elif ext is None and ch != name:
                    ext = ch
        if name is None or content is None:
            raise ValueError(f"smell_decl_core inválido: {children!r}")
        content.name = name
        content.extends = ext
        self.model.smells[name] = content

    def opt_scale(self, *xs): return xs[1] if xs else None
    def with_scale(self, scaletype): return scaletype
    def no_scale(self): return None

    def measure_list(self, first, *rest):
        vals = [first]
        it = iter(rest)
        for elem in it:
            if isinstance(elem, Token) and getattr(elem, "type", "") == "COMMA":
                vals.append(next(it, None))
            else:
                vals.append(elem)
        return vals

    def measure(self, v): return v
    def symptom_opt(self, *xs): return xs[0] if xs else None
    def treatment_opt(self, *xs): return xs[0] if xs else None
    def symptom(self, _kw, text, *maybe_semi): return ("__symptom__", text)
    def treatment(self, text, *maybe_semi):return ("__treatment__", text)
    def simple_text(self, x): return x

    def rule_stmt(self, *children):
        name, logic, lit = None, None, None
        for ch in children:
            if isinstance(ch, Token): continue
            if isinstance(ch, list) and logic is None:
                logic = ch
            elif isinstance(ch, str) and name is None and logic is None:
                name = ch
            elif logic is not None and lit is None and not isinstance(ch, list):
                lit = ch
        if name is None or logic is None or lit is None:
            raise ValueError(f"rule_stmt inválido: {children!r}")
        self.model.rules[name] = Rule(name=name, dnf=logic, then_literal=lit)

    def logic_expr(self, first, *rest):
        dnf = [first]
        it = iter(rest)
        for elem in it:
            if isinstance(elem, Token) and getattr(elem, "type", "") == "OR":
                dnf.append(next(it, None))
            else:
                dnf.append(elem)
        return dnf

    def logic_term(self, first, *rest):
        factors = [first]
        it = iter(rest)
        for elem in it:
            if isinstance(elem, Token) and getattr(elem, "type", "") == "AND":
                factors.append(next(it, None))
            else:
                factors.append(elem)
        return factors

    def logic_factor(self, x): return x
    def factor_comp(self, comp): return comp
    def factor_group(self, expr): return expr
    def comparison(self, left, op, right):
        if hasattr(op, "value"): op = op.value
        return (left, op, right)
    def ref(self, smell, _dot, feature): return (str(smell), str(feature))
    def literal(self, x): return x

# ==========================================================
# INTERPRETER
# ==========================================================
def _flatten_to_comparisons(x):
    out = []
    stack = [x]
    while stack:
        item = stack.pop()
        if isinstance(item, tuple) and len(item) == 3:
            out.append(item)
        elif isinstance(item, list):
            stack.extend(item)
    out.reverse()
    return out

class Interpreter:
    def __init__(self, model):
        self.model = model

    def evaluate_rule(self, rule_name, env):
        rule = self.model.rules[rule_name]
        for term in rule.dnf:
            comps = _flatten_to_comparisons(term)
            if all(self._eval_comparison(c, env) for c in comps):
                return True
        return False

    def _eval_comparison(self, comp, env):
        if isinstance(comp, list) and len(comp) == 1:
            comp = comp[0]
        (lref, op, rref) = comp
        lv = env.get(lref)
        rv = env.get(rref)
        if lv is None or rv is None:
            raise KeyError(f"Missing env values for {lref} or {rref}")
        if op in ("==", "!="):
            return (lv == rv) if op == "==" else (lv != rv)
        lf, rf = float(lv), float(rv)
        return {">=": lf >= rf, "<=": lf <= rf, ">": lf > rf, "<": lf < rf}[op]

# ==========================================================
# DIRECT USE API
# ==========================================================
def parse(code: str) -> DomainModel:
    parser = Lark(GRAMMAR, start="start", parser="lalr")
    tree = parser.parse(code)
    builder = Builder()
    builder.transform(tree)
    return builder.model

def run_interpretation(env: dict, code: str) -> dict:
    """
    Executa o interpretador completo sobre o código DSL fornecido.
    Retorna um log estruturado.
    """
    model = parse(code)
    interp = Interpreter(model)
    results = {}
    for rn in model.rules.keys():
        results[rn] = interp.evaluate_rule(rn, env)
    return {
        "smells": list(model.smells.keys()),
        "rules": results,
        "interpreted": True,
        "treatments": {s.name: s.treatment for s in model.smells.values() if s.treatment},
        "model": model
    }

# ==========================================================
# MANUAL EXECUTION FOR TESTING
# ==========================================================
if __name__ == "__main__":
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        if not os.path.exists(file_path):
            print(f"❌ Arquivo não encontrado: {file_path}")
            sys.exit(1)

        with open(file_path, "r", encoding="utf-8") as f:
            code = f.read()

        model = parse(code)

        print("\n=== ✅ PARSE CONCLUÍDO ===")
        print("Smelltypes:", model.smelltypes)
        print("Smells:", list(model.smells.keys()))
        print("Rules:", list(model.rules.keys()))

        print("\n=== 🎯 Detalhes ===")
        for s_name, s in model.smells.items():
            print(f"\nSmell: {s_name}")
            for f_name, feat in s.features.items():
                print(f"  - Feature: {f_name}, Escala: {feat.scale}, Thresholds: {feat.threshold}")
            if s.symptom:
                print(f"  Symptom: {s.symptom}")
            if s.treatment:
                print(f"  Treatment: {s.treatment}")

        sys.exit(0)

    # Caso não passe arquivo, roda o exemplo interno
    sample = r"""
        smelltype DesignSmell;
        smelltype ImplementationSmell;

        smell GodClass extends DesignSmell {
            feature ATFD with threshold 4, 10;
            feature TCC with threshold 3, 5;
        }

        rule GodClassRule when (GodClass.ATFD > GodClass.TCC) then "Flag";
    """

    model = parse(sample)
    print("Smelltypes:", model.smelltypes)
    print("Smells:", list(model.smells.keys()))
    print("Rules:", list(model.rules.keys()))
