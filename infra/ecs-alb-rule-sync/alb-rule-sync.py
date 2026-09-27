"""
Sincroniza reglas manuales del ALB con los weights de Express Mode
tras cada deploy de ECS.

Express Mode gestiona las reglas de prioridad baja (1-5) con blue/green TGs.
Las reglas manuales para custom domains (prioridad 10+) deben reflejar los
mismos weights para que el tráfico llegue al TG activo.

Mapeo de reglas:
  - Prioridad 1 (Express Mode, shlink-api) → Prioridad 10 (go.griddo.io)
  - Prioridad 3 (Express Mode, shlink-web) → Prioridad 11 (links.griddo.io)
  - Prioridad 4 (Express Mode, shurly-api) → Prioridad 12 (s.griddo.io)
"""

import json
import boto3

elbv2 = boto3.client("elbv2", region_name="eu-south-2")

# Express Mode priority → custom rule priority
RULE_SYNC_MAP = {
    "1": "10",   # shlink-api → go.griddo.io
    "3": "11",   # shlink-web → links.griddo.io
    "4": "12",   # shurly-api → s.griddo.io
}

LISTENER_ARN = "arn:aws:elasticloadbalancing:eu-south-2:686255983646:listener/app/ecs-express-gateway-alb-d37ca364/8d6cb22fed5c0e8b/f182b836d7cff456"


def lambda_handler(event, context):
    rules = elbv2.describe_rules(ListenerArn=LISTENER_ARN)["Rules"]

    rules_by_priority = {r["Priority"]: r for r in rules}

    changes = []
    for source_pri, target_pri in RULE_SYNC_MAP.items():
        source_rule = rules_by_priority.get(source_pri)
        target_rule = rules_by_priority.get(target_pri)
        if not source_rule or not target_rule:
            continue

        source_tgs = source_rule["Actions"][0]["ForwardConfig"]["TargetGroups"]
        target_tgs = target_rule["Actions"][0]["ForwardConfig"]["TargetGroups"]

        # Comparar weights actuales
        source_weights = {tg["TargetGroupArn"]: tg["Weight"] for tg in source_tgs}
        target_weights = {tg["TargetGroupArn"]: tg["Weight"] for tg in target_tgs}

        if source_weights == target_weights:
            continue

        # Sincronizar
        elbv2.modify_rule(
            RuleArn=target_rule["RuleArn"],
            Actions=[{
                "Type": "forward",
                "ForwardConfig": {
                    "TargetGroups": source_tgs
                }
            }]
        )
        changes.append(f"Synced priority {target_pri} with {source_pri}")

    result = changes if changes else ["No changes needed"]
    print(json.dumps(result))
    return result
