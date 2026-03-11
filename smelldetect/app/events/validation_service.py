from app.parser.metric_extractor import MetricExtractor

class ValidationService:
    def __init__(self):
        self.extractor = MetricExtractor()

    def validate(self, smell_dsl: str, env_raw: dict) -> dict:
        errors = []
        suggestions = []

        # -------- DSL vazio --------
        if not smell_dsl.strip():
            errors.append("DSL file is empty")
            suggestions.append("Provide a valid .smelldsl file")

        # -------- Env vazio --------
        if not env_raw:
            errors.append("Metrics file is empty")
            suggestions.append("Provide metrics JSON with required features")

        # -------- Verifica formato chave --------
        for key in env_raw.keys():
            if "." not in key:
                suggestions.append(
                    f"Metric '{key}' should follow format Smell.Feature"
                )
                
        declared_metrics, used_metrics = self.extractor.extract(smell_dsl)

        env = self._normalize_metrics(env_raw, used_metrics)

        missing = []

        for metric in used_metrics:
            if metric not in env:
                missing.append(metric)

        if missing:
            for m in missing:
                errors.append(f"Missing metric: {m}")
                suggestions.append(f"Add '{m}' to metrics JSON")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "suggestions": suggestions
        }
    
    def _normalize_metrics(self, env_raw: dict, used_metrics: set):

        normalized = {}

        for key, value in env_raw.items():

            key = key.strip()

            # caso já venha no formato correto
            if "." in key:
                normalized[key] = value
                continue

            # tenta casar com métricas usadas no DSL
            matched = False

            for used in used_metrics:
                if used.endswith("." + key):
                    normalized[used] = value
                    matched = True
                    break

            if not matched:
                normalized[key] = value

        return normalized