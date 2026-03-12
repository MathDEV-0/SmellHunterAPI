from app.parser.metric_extractor import MetricExtractor

class ValidationService:
    def __init__(self):
        self.extractor = MetricExtractor()

    # def validate(self, smell_dsl: str, env_raw: dict) -> dict:
    #     errors = []
    #     suggestions = []

    #     # -------- DSL empty --------
    #     if not smell_dsl.strip():
    #         errors.append("DSL file is empty")
    #         suggestions.append("Provide a valid .smelldsl file")

    #     # -------- Env empty --------
    #     if not env_raw:
    #         errors.append("Metrics file is empty")
    #         suggestions.append("Provide metrics JSON with required features")

    #     # -------- Verify key format --------
    #     for key in env_raw.keys():
    #         if "." not in key:
    #             suggestions.append(
    #                 f"Metric '{key}' should follow format Smell.Feature"
    #             )
                
    #     declared_metrics, used_metrics = self.extractor.extract(smell_dsl)

    #     env = self._normalize_metrics(env_raw, used_metrics)

    #     missing = []

    #     for metric in used_metrics:
    #         if metric not in env:
    #             missing.append(metric)

    #     if missing:
    #         for m in missing:
    #             errors.append(f"Missing metric: {m}")
    #             suggestions.append(f"Add '{m}' to metrics JSON")

    #     return {
    #         "valid": len(errors) == 0,
    #         "errors": errors,
    #         "suggestions": suggestions
    #     }

    def validate(self, smell_dsl: str, env_raw: dict) -> dict:
        errors = []
        suggestions = []

        # -------- DSL empty --------
        if not smell_dsl.strip():
            errors.append("DSL file is empty")
            suggestions.append("Provide a valid .smelldsl file")

        # -------- Env empty --------
        if not env_raw:
            errors.append("Metrics file is empty")
            suggestions.append("Provide metrics JSON with required features")

        # -------- Verify key format --------
        for key in env_raw.keys():
            if "." not in key:
                suggestions.append(
                    f"Metric '{key}' should follow format Smell.Feature"
                )
        
        # Extrai as métricas usadas no DSL
        declared_metrics, used_metrics = self.extractor.extract(smell_dsl)
        
        print(f"[DEBUG] used_metrics: {used_metrics}")
        print(f"[DEBUG] env_raw keys: {list(env_raw.keys())}")
        
        # SEPARA métricas normais de thresholds (que terminam com -LIMIT)
        normal_metrics = {m for m in used_metrics if not m.endswith("-LIMIT")}
        threshold_metrics = {m for m in used_metrics if m.endswith("-LIMIT")}
        
        print(f"[DEBUG] normal_metrics: {normal_metrics}")
        print(f"[DEBUG] threshold_metrics: {threshold_metrics}")
        
        # Verifica apenas as métricas normais
        missing = []
        for metric in normal_metrics:
            if metric not in env_raw:
                missing.append(metric)
                suggestions.append(f"Add '{metric}' to metrics JSON")
        
        # Para thresholds, verifica se a métrica base existe (sem o -LIMIT)
        for threshold in threshold_metrics:
            base_metric = threshold.replace("-LIMIT", "")
            if base_metric not in env_raw:
                # A métrica base também não existe? Avisa
                if base_metric not in normal_metrics:
                    missing.append(f"{base_metric} (required for {threshold})")
                    suggestions.append(f"Add '{base_metric}' to calculate {threshold}")
            # Se a base existe, o threshold pode vir de outro lugar (não falha)
        
        if missing:
            for m in missing:
                errors.append(f"Missing metric: {m}")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "suggestions": suggestions
        }
    
    def _normalize_metrics(self, env_raw: dict, used_metrics: set):

        normalized = {}

        for key, value in env_raw.items():

            key = key.strip()
            if "." in key:
                normalized[key] = value
                continue

            matched = False

            for used in used_metrics:
                if used.endswith("." + key):
                    normalized[used] = value
                    matched = True
                    break

            if not matched:
                normalized[key] = value

        return normalized