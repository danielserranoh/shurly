"""
Sincroniza reglas manuales del ALB con los weights de Express Mode.

Express Mode gestiona las reglas de prioridad baja (1-5) con blue/green TGs.
Las reglas manuales para custom domains (prioridad 10+) deben reflejar los
mismos weights para que el tráfico llegue al TG activo.

Mapeo de reglas:
  - Prioridad 1 (Express Mode, shlink-api) → Prioridad 10 (go.griddo.io)
  - Prioridad 3 (Express Mode, shlink-web) → Prioridad 11 (links.griddo.io)
  - Prioridad 4 (Express Mode, shurly-api) → Prioridad 12 (s.griddo.io)

Cuándo se ejecuta (EventBridge "ECS Deployment State Change"):
  - SERVICE_DEPLOYMENT_IN_PROGRESS → sigue el despliegue: sincroniza cada
    POLL_SECONDS hasta que ECS lo da por COMPLETED/FAILED (o se acaba el
    tiempo de la Lambda). Así los custom domains siguen el canary de Express
    en vez de quedarse en el TG viejo.
  - SERVICE_DEPLOYMENT_COMPLETED / _FAILED → una pasada final.
  - Invocación manual (payload {}) → una pasada, como siempre.

Por qué hace falta seguir el despliegue: antes solo reaccionaba a COMPLETED,
y ECS para la task vieja ~1 min antes de emitir ese evento. En ese hueco la
regla del custom domain apuntaba a un TG vacío y el ALB respondía 503
(s.griddo.io, 27 sep 2026: 00:16:20 → 00:17:16). Y durante todo el canary el
custom domain seguía al 100% en la versión vieja.
"""

import json
import time

import boto3

elbv2 = boto3.client("elbv2", region_name="eu-south-2")
ecs = boto3.client("ecs", region_name="eu-south-2")

# Express Mode priority → custom rule priority
RULE_SYNC_MAP = {
    "1": "10",   # shlink-api → go.griddo.io
    "3": "11",   # shlink-web → links.griddo.io
    "4": "12",   # shurly-api → s.griddo.io
}

LISTENER_ARN = "arn:aws:elasticloadbalancing:eu-south-2:686255983646:listener/app/ecs-express-gateway-alb-d37ca364/8d6cb22fed5c0e8b/f182b836d7cff456"

POLL_SECONDS = 5
# Margen para la pasada final antes de que la Lambda agote su timeout.
SAFETY_MARGIN_MS = 15_000


def sync_once():
    """Una pasada: copia los weights de cada regla Express a su custom rule."""
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

        source_weights = {tg["TargetGroupArn"]: tg["Weight"] for tg in source_tgs}
        target_weights = {tg["TargetGroupArn"]: tg["Weight"] for tg in target_tgs}

        if source_weights == target_weights:
            continue

        elbv2.modify_rule(
            RuleArn=target_rule["RuleArn"],
            Actions=[{
                "Type": "forward",
                "ForwardConfig": {
                    "TargetGroups": source_tgs
                }
            }]
        )
        weights = ", ".join(f"{w}%" for w in source_weights.values())
        changes.append(f"Synced priority {target_pri} with {source_pri} ({weights})")

    return changes


def deployment_in_progress(service_arn, deployment_id):
    """True mientras ECS tenga ese despliegue en IN_PROGRESS."""
    cluster = service_arn.split("/")[-2]
    services = ecs.describe_services(cluster=cluster, services=[service_arn])["services"]
    if not services:
        return False
    for d in services[0].get("deployments", []):
        if d.get("id") == deployment_id:
            return d.get("rolloutState") == "IN_PROGRESS"
    # El despliegue ya no aparece: ha terminado (o lo ha sustituido otro).
    return False


def lambda_handler(event, context):
    event = event or {}
    detail = event.get("detail") or {}
    event_name = detail.get("eventName")
    deployment_id = detail.get("deploymentId")
    resources = event.get("resources") or []
    service_arn = resources[0] if resources else None

    changes = sync_once()

    follow = (
        event_name == "SERVICE_DEPLOYMENT_IN_PROGRESS"
        and service_arn
        and deployment_id
        and context is not None
    )
    if follow:
        print(json.dumps({"following": deployment_id, "service": service_arn}))
        while context.get_remaining_time_in_millis() > SAFETY_MARGIN_MS + POLL_SECONDS * 1000:
            time.sleep(POLL_SECONDS)
            step = sync_once()
            if step:
                print(json.dumps(step))
                changes.extend(step)
            if not deployment_in_progress(service_arn, deployment_id):
                break
        # Pasada final: recoge el último cambio de weights, si lo hubo.
        changes.extend(sync_once())

    result = changes if changes else ["No changes needed"]
    print(json.dumps(result))
    return result
