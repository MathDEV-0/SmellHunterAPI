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