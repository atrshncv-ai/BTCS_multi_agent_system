"""
Avito Parser Webhook Server.

Flask app that receives parsed Avito data and routes it to the agent system.
Integrates with parser_avito from https://github.com/Duff89/parser_avito
"""

import json
import logging
import sys
from pathlib import Path

from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent))


app = Flask(__name__)

WEBHOOK_SECRET = "avito_secret_key_change_me"
AGENT_CONTEXT = None
ORCHESTRATOR = None


def init_webhook(orchestrator):
    global ORCHESTRATOR, AGENT_CONTEXT
    from agents import AgentContext
    ORCHESTRATOR = orchestrator
    AGENT_CONTEXT = AgentContext(
        session_id="avito-webhook",
        user_id=0,
        session_key="avito_webhook",
    )
    AGENT_CONTEXT.ensure_session()


@app.route("/webhook/avito", methods=["POST"])
def avito_webhook():
    if not request.is_json:
        return jsonify({"error": "JSON expected"}), 400

    payload = request.get_json()
    logger.info(f"Avito webhook: {len(payload.get('items', []))} items")

    try:
        items = payload.get("items", [])
        parsed_count = payload.get("parsed_count", len(items))

        if not items:
            return jsonify({"status": "ok", "items_processed": 0})

        if ORCHESTRATOR:
            items_result = ORCHESTRATOR.process_sync(
                "import parsed items",
                params={
                    "source_type": "avito",
                    "items": items,
                    "parsed_count": parsed_count,
                },
            )

        if AGENT_CONTEXT:
            import asyncio
            from agents import AgentContext as AC
            ctx = AGENT_CONTEXT

            sellers_to_import = []
            for item in items[:200]:
                sellers_to_import.append({
                    "source_platform": "avito",
                    "source_url": item.get("url", ""),
                    "seller_name": item.get("seller_name", item.get("title", "Unknown")),
                    "seller_id": str(item.get("id", "")),
                    "region": item.get("region", ""),
                    "category": item.get("category", ""),
                    "relevance_score": item.get("relevance_score", 0.5),
                    "priority": _calc_priority(item.get("relevance_score", 0.5)),
                    "contact_data": json.dumps({
                        "phone": item.get("phone", ""),
                        "price": item.get("price", ""),
                    }),
                    "notes": item.get("description", "")[:500],
                })

            if sellers_to_import and ORCHESTRATOR:
                intake_result = ORCHESTRATOR.process_sync(
                    "qualify sellers",
                    params={
                        "source_type": "avito",
                        "records": sellers_to_import,
                    },
                )

        return jsonify({
            "status": "ok",
            "items_received": len(items),
            "items_processed": len(sellers_to_import),
        })

    except Exception as e:
        logger.exception(f"Avito webhook error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/webhook/avito/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok", "service": "avito-webhook"})


def _calc_priority(score: float) -> str:
    if score >= 0.7:
        return "high"
    elif score >= 0.4:
        return "medium"
    return "low"


if __name__ == "__main__":
    print("Starting Avito webhook server on :8081")
    app.run(host="0.0.0.0", port=8081, debug=False)