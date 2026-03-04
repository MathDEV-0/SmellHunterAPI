from lark import Lark, Visitor
from app.parser.grammar import GRAMMAR


class MetricVisitor(Visitor):
    def __init__(self):
        self.smells = {}
        self.rule_refs = set()
        self.current_smell = None

    def smell_decl_core(self, tree):
        smell_name = tree.children[0].value
        self.current_smell = smell_name
        self.smells[smell_name] = []

    def feature_decl(self, tree):
        feature_name = tree.children[0].value
        if self.current_smell:
            self.smells[self.current_smell].append(feature_name)

    def ref(self, tree):
        smell = tree.children[0].value
        feature = tree.children[2].value
        self.rule_refs.add(f"{smell}.{feature}")


class MetricExtractor:

    def __init__(self):
        self.parser = Lark(GRAMMAR, start="start")

    def extract(self, dsl_text: str):
        tree = self.parser.parse(dsl_text)
        visitor = MetricVisitor()
        visitor.visit(tree)

        declared_metrics = {
            f"{smell}.{feature}"
            for smell, features in visitor.smells.items()
            for feature in features
        }

        used_metrics = visitor.rule_refs

        return declared_metrics, used_metrics